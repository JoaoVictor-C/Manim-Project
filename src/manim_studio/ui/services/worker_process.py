"""The build worker as seen from the editor (ADR 0015).

``WorkerClient`` is the interface the ``BuildService`` talks to: ``request(id,
spec_json)`` and a ``replied(id, ok, error)`` signal. ``WorkerProcess`` runs
``python -m manim_studio.processes.worker`` in a ``QProcess`` and owns its lifecycle:

* requests queue while the worker starts (importing Manim takes 3-4 s, B18);
* the worker builds one request at a time; if the one it is on takes longer
  than ``timeout_s`` the worker is killed, that request fails, and the worker
  restarts with the rest;
* if the worker dies on its own it restarts and the requests are re-sent once —
  a request that kills it twice fails;
* after ``MAX_FAILED_STARTS`` starts in a row that never become ready, the
  client becomes unavailable and the service builds synchronously instead;
* with ``idle_s`` the worker is *released* once it has had nothing to do for that long (a Python
  process with Manim loaded is about 120 MB) and starts again, with the requests it was sent
  meanwhile, when the next request comes: the first one then waits for Manim's import;
* with ``lazy`` it starts in that released state: the welcome page, which builds nothing, runs no process.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import shiboken6
from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from ... import lifeline
from ...core.code import limits
from ...logging_config import get_logger
from . import children

log = get_logger(__name__)

MAX_FAILED_STARTS = 3
IDLE_SECONDS = 600.0  # what the editor's worker may sit unused before it is released


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

    @property
    def asleep(self) -> bool:
        return False


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
        timeout_s: float = limits.BUILD_LIMIT,
        program: str = sys.executable,
        args: list[str] | None = None,
        idle_s: float | None = None,
        lazy: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._program = program
        self._args = (
            args
            if args is not None
            else ["-m", "manim_studio.processes.worker", "--cache-dir", str(cache_dir)]
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
        self._asleep = False  # released after ``idle_s`` without work; the next request starts it again
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        if idle_s:
            self._idle.setInterval(round(idle_s * 1000))
            self._idle.timeout.connect(self._fall_asleep)
        if lazy:
            self._asleep = True  # nothing to build yet: the first request starts it
        else:
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

    @property
    def asleep(self) -> bool:
        """Released after being idle: no process now, one starts with the next request."""
        return self._asleep

    def request(self, request_id: int, spec_json: str) -> None:
        if not self._available:
            raise RuntimeError("build worker unavailable")
        spec = json.loads(spec_json)
        # A Python object's helpers (ADR 0058) ride in its warm key: sent beside the spec.
        extra = {name: spec.pop(name) for name in ("helpers", "trusted_helpers") if name in spec}
        if limits.unlimited():  # the user lifted the time limits (ADR 0059): the worker obeys too
            extra["no_limit"] = True
        line = json.dumps({"id": request_id, "spec": spec, **extra}) + "\n"
        self._requests.append(_Request(request_id, line))
        self._touch()
        if self._asleep:
            self._wake()  # the request waits in the queue, and is sent when the worker is ready
        elif self._ready:
            if len(self._requests) == 1:
                self._head_since = time.monotonic()
            self._write(line)

    def stop(self) -> None:
        self._stopping = True
        self._watchdog.stop()
        self._idle.stop()
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
        process.setProcessEnvironment(children.environment())
        process.readyReadStandardOutput.connect(lambda: self._read(process))
        process.readyReadStandardError.connect(lambda: self._log_stderr(process))
        process.finished.connect(lambda *_: self._on_exit(process))
        process.errorOccurred.connect(lambda error: self._on_error(process, error))
        self._process = process
        log.info("starting build worker: %s %s", self._program, " ".join(self._args))
        children.start(process)

    def _restart(self, reason: str) -> None:
        log.warning("restarting build worker: %s", reason)
        old, self._process = self._process, None
        if old is not None and shiboken6.isValid(old):
            old.blockSignals(True)
            pid = int(old.processId())
            tree = [pid, *lifeline.descendants(pid)] if pid else []
            lifeline.kill_tree(
                pid
            )  # LaTeX too: the next worker must not meet a build still holding its files
            lifeline.wait_gone(tree, timeout=2.0)
            old.kill()
            old.waitForFinished(1000)
            old.deleteLater()
        self.start()

    def _touch(self) -> None:
        """Something happened: the idle countdown starts again."""
        if self._idle.interval() > 0 and not self._stopping:
            self._idle.start()

    def _fall_asleep(self) -> None:
        """Release the process (and its memory) when there is nothing to build, and nothing is starting."""
        if self._requests or not self._ready or self._process is None:
            self._touch()  # busy or still starting: look again later
            return
        log.info(
            "build worker idle for %.0f s: released (it starts again with the next request)",
            self._idle.interval() / 1000,
        )
        process, self._process = self._process, None
        self._asleep, self._ready = True, False
        self._watchdog.stop()
        process.finished.connect(process.deleteLater)
        process.closeWriteChannel()  # it ends when its input does

    def _wake(self) -> None:
        self._asleep = False
        self._failed_starts = 0
        self.start()

    def _on_ready(self) -> None:
        self._ready = True
        self._failed_starts = 0
        log.info("build worker ready (pid %s)", self.pid)
        self._touch()
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
        if not (self._ready and self._requests) or limits.unlimited():
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
        self._touch()
        if message["ok"]:
            log.debug("warmed request %s in %s ms", request_id, message.get("ms"))
        self.replied.emit(request_id, bool(message["ok"]), message.get("error", ""))

    def _log_stderr(self, process: QProcess) -> None:
        text = bytes(process.readAllStandardError().data()).decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                log.debug("worker: %s", line)


def make_worker(cache_dir: Path, parent: QObject | None = None) -> WorkerClient:
    """The real worker, or none when ``MANIM_STUDIO_WORKER=0`` (tests, debugging). It starts with the first
    request, and is released after ``IDLE_SECONDS`` without work (``MANIM_STUDIO_IDLE_SECONDS`` changes that;
    0 keeps it for good)."""
    if os.environ.get("MANIM_STUDIO_WORKER") == "0":
        return WorkerClient(parent)
    return WorkerProcess(cache_dir, idle_s=idle_seconds(IDLE_SECONDS), lazy=True, parent=parent)


def idle_seconds(default: float) -> float | None:
    """How long a helper may sit unused before it is released: ``MANIM_STUDIO_IDLE_SECONDS``, else
    ``default``; None (never) for 0."""
    try:
        seconds = float(os.environ.get("MANIM_STUDIO_IDLE_SECONDS", default))
    except ValueError:
        seconds = default
    return seconds if seconds > 0 else None
