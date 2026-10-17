"""The build worker as seen from the editor (ADR 0015).

``WorkerClient`` is the interface the ``BuildService`` talks to: ``request(id,
spec_json)`` and a ``replied(id, ok, error)`` signal. ``WorkerProcess`` runs
``python -m manim_studio.worker`` in a ``QProcess`` and owns its lifecycle:

* requests queue while the worker starts (importing Manim takes 3-4 s, B18);
* the worker builds one request at a time; if the one it is on takes longer
  than ``timeout_s`` the worker is killed, that request fails, and the worker
  restarts with the rest;
* if the worker dies on its own it restarts and the requests are re-sent once —
  a request that kills it twice fails;
* after ``MAX_FAILED_STARTS`` starts in a row that never become ready, the
  client becomes unavailable and the service builds synchronously instead.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import shiboken6
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from ..logging_config import get_logger

log = get_logger(__name__)

MAX_FAILED_STARTS = 3


class WorkerClient(QObject):
    """No worker: ``available`` is False, so every edit is applied synchronously."""

    replied = Signal(int, bool, str)  # request id, ok, error message
    availableChanged = Signal(bool)

    @property
    def available(self) -> bool:
        return False

    def request(self, request_id: int, spec_json: str) -> None:
        raise RuntimeError("no build worker")

    def stop(self) -> None:
        pass


@dataclass
class _Request:
    id: int
    line: str
    retried: bool = False


class WorkerProcess(WorkerClient):
    def __init__(
        self,
        cache_dir: Path,
        *,
        timeout_s: float = 20.0,
        program: str = sys.executable,
        args: list[str] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._program = program
        self._args = (
            args if args is not None else ["-m", "manim_studio.worker", "--cache-dir", str(cache_dir)]
        )
        self._timeout_s = timeout_s
        self._process: QProcess | None = None
        self._ready = False
        self._available = True
        self._stopping = False
        self._failed_starts = 0
        self._requests: list[_Request] = []  # in the order the worker will build them
        self._head_since = 0.0  # when the worker started on the first request
        self._buffer = b""
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(250)
        self._watchdog.timeout.connect(self._check_timeout)
        self.start()

    # -- WorkerClient ---------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._available

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def pid(self) -> int | None:
        return int(self._process.processId()) if self._process is not None else None

    def request(self, request_id: int, spec_json: str) -> None:
        if not self._available:
            raise RuntimeError("build worker unavailable")
        line = json.dumps({"id": request_id, "spec": json.loads(spec_json)}) + "\n"
        self._requests.append(_Request(request_id, line))
        if self._ready:
            if len(self._requests) == 1:
                self._head_since = time.monotonic()
            self._write(line)

    def stop(self) -> None:
        self._stopping = True
        self._watchdog.stop()
        if self._process is None:
            return
        process, self._process = self._process, None
        process.closeWriteChannel()
        if not process.waitForFinished(2000):
            process.kill()
            process.waitForFinished(1000)

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        self._ready = False
        self._buffer = b""
        process = QProcess(self)
        process.setProgram(self._program)
        process.setArguments(self._args)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUTF8", "1")
        process.setProcessEnvironment(env)
        process.readyReadStandardOutput.connect(lambda: self._read(process))
        process.readyReadStandardError.connect(lambda: self._log_stderr(process))
        process.finished.connect(lambda *_: self._on_exit(process))
        process.errorOccurred.connect(lambda error: self._on_error(process, error))
        self._process = process
        log.info("starting build worker: %s %s", self._program, " ".join(self._args))
        process.start()

    def _restart(self, reason: str) -> None:
        log.warning("restarting build worker: %s", reason)
        old, self._process = self._process, None
        if old is not None and shiboken6.isValid(old):
            old.blockSignals(True)
            old.kill()
            old.waitForFinished(1000)
            old.deleteLater()
        self.start()

    def _on_ready(self) -> None:
        self._ready = True
        self._failed_starts = 0
        log.info("build worker ready (pid %s)", self.pid)
        self._head_since = time.monotonic()
        for request in self._requests:
            self._write(request.line)
        self._watchdog.start()

    def _on_exit(self, process: QProcess) -> None:
        if process is not self._process or self._stopping:
            return
        if not shiboken6.isValid(self) or not shiboken6.isValid(process):
            return  # torn down with the application (no closeEvent): nothing to restart (GP)
        if not self._ready:
            self._failed_starts += 1
            if self._failed_starts >= MAX_FAILED_STARTS:
                self._give_up()
                return
        elif self._requests:
            head = self._requests[0]
            if head.retried:
                self._requests.pop(0)
                self.replied.emit(head.id, False, "the build worker crashed on this object")
            else:
                for request in self._requests:
                    request.retried = True
        self._restart("it exited")

    def _on_error(self, process: QProcess, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart and process is self._process:
            log.error("build worker failed to start: %s", process.errorString())
            self._give_up()

    def _give_up(self) -> None:
        log.error("build worker unavailable; text objects will be built synchronously")
        self._available = False
        self._watchdog.stop()
        self._process = None
        failed, self._requests = self._requests, []
        for request in failed:
            self.replied.emit(request.id, False, "build worker unavailable")
        self.availableChanged.emit(False)

    def _check_timeout(self) -> None:
        if not (self._ready and self._requests):
            return
        if time.monotonic() - self._head_since <= self._timeout_s:
            return
        head = self._requests.pop(0)
        self.replied.emit(head.id, False, f"building took longer than {self._timeout_s:g} s")
        self._restart("request timed out")

    # -- I/O ------------------------------------------------------------------

    def _write(self, line: str) -> None:
        if self._process is not None:
            self._process.write(line.encode("utf-8"))

    def _read(self, process: QProcess) -> None:
        if process is not self._process:
            return
        self._buffer += bytes(process.readAllStandardOutput().data())
        *lines, self._buffer = self._buffer.split(b"\n")
        for raw in lines:
            if raw.strip():
                self._handle(json.loads(raw))

    def _handle(self, message: dict) -> None:
        if message.get("ready"):
            self._on_ready()
            return
        request_id = message["id"]
        self._requests = [r for r in self._requests if r.id != request_id]
        self._head_since = time.monotonic()
        if message["ok"]:
            log.debug("warmed request %s in %s ms", request_id, message.get("ms"))
        self.replied.emit(request_id, bool(message["ok"]), message.get("error", ""))

    def _log_stderr(self, process: QProcess) -> None:
        text = bytes(process.readAllStandardError().data()).decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                log.debug("worker: %s", line)


def make_worker(cache_dir: Path, parent: QObject | None = None) -> WorkerClient:
    """The real worker, or none when ``MANIM_STUDIO_WORKER=0`` (tests, debugging)."""
    if os.environ.get("MANIM_STUDIO_WORKER") == "0":
        return WorkerClient(parent)
    return WorkerProcess(cache_dir, parent=parent)
