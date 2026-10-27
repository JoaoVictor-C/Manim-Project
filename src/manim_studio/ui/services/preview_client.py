"""The preview render process as seen from the editor (ADR 0028).

``PreviewProcess`` runs ``python -m manim_studio.processes.preview`` in a ``QProcess`` and
keeps the latest project, view and wanted frames, so a process that starts
late or restarts after a crash is brought up to date. It emits ``frame(view_id,
generation, index, data, width, height)`` with zlib-compressed RGBA ``data``
and ``failed(index)``; after ``MAX_FAILED_STARTS`` starts that never become
ready it gives up (``available`` is False) and the editor renders live.

With ``idle_s`` the process is released once nothing has been sent to it and no frame has come from it for
that long (it is a Python process with Manim loaded, over 100 MB). The next message starts it again and it
is brought up to date from the latest ones, as after a crash; the editor renders live until its frames come.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from ...core.model.schema import Project
from ...logging_config import get_logger
from ...render.preview import PreviewView
from . import children
from .worker_process import IDLE_SECONDS, idle_seconds

log = get_logger(__name__)

MAX_FAILED_STARTS = 3


class PreviewProcess(QObject):
    frame = Signal(int, int, int, bytes, int, int)  # view id, generation, index, data, width, height
    failed = Signal(int)  # index
    availableChanged = Signal(bool)

    def __init__(
        self,
        cache_dir: Path,
        *,
        program: str = sys.executable,
        args: list[str] | None = None,
        idle_s: float | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._program = program
        self._args = (
            args
            if args is not None
            else ["-m", "manim_studio.processes.preview", "--cache-dir", str(cache_dir)]
        )
        self._process: QProcess | None = None
        self._ready = False
        self._available = True
        self._stopping = False
        self._failed_starts = 0
        self._crashes = 0  # in a row without a frame: a frame that kills it every time
        self._buffer = b""
        self._project: str | None = None  # the latest messages, re-sent after a (re)start
        self._view: str | None = None
        self._want: str | None = None
        self._asleep = False  # released after ``idle_s`` unused; the next message starts it again
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        if idle_s:
            self._idle.setInterval(round(idle_s * 1000))
            self._idle.timeout.connect(self._fall_asleep)
        self.start()

    @property
    def available(self) -> bool:
        return self._available

    @property
    def asleep(self) -> bool:
        """Released after being idle: no process now, one starts with the next message."""
        return self._asleep

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def pid(self) -> int | None:
        return int(self._process.processId()) if self._process is not None else None

    # -- messages ---------------------------------------------------------------

    def send_project(self, project: Project, generation: int) -> None:
        payload = {"project": json.loads(project.model_dump_json(by_alias=True)), "generation": generation}
        self._project = json.dumps(payload) + "\n"
        self._write(self._project)

    def send_view(self, view_id: int, view: PreviewView) -> None:
        self._view = json.dumps({"view": view.to_json(), "view_id": view_id}) + "\n"
        self._write(self._view)

    def want(self, indices: list[int]) -> None:
        self._want = json.dumps({"want": indices}) + "\n"
        self._write(self._want, wake=bool(indices))  # nothing wanted is no reason to start a released process

    def media(self) -> None:
        self._write(json.dumps({"media": True}) + "\n", wake=False)  # a fresh process reads the media itself

    # -- lifecycle ----------------------------------------------------------------

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
        log.info("starting preview process: %s %s", self._program, " ".join(self._args))
        children.start(process)

    def stop(self) -> None:
        self._stopping = True
        self._idle.stop()
        if self._process is None:
            return
        process, self._process = self._process, None
        process.closeWriteChannel()  # the process ends when its input does
        if not process.waitForFinished(2000):
            process.kill()
            process.waitForFinished(1000)

    def _touch(self) -> None:
        """Something was sent or came back: the idle countdown starts again."""
        if self._idle.interval() > 0 and not self._stopping:
            self._idle.start()

    def _fall_asleep(self) -> None:
        """Release the process (and its memory) when it has been left alone."""
        if self._process is None or not self._ready:
            self._touch()  # still starting: look again later
            return
        log.info("preview process idle for %.0f s: released", self._idle.interval() / 1000)
        process, self._process = self._process, None
        self._asleep, self._ready = True, False
        process.finished.connect(process.deleteLater)
        process.closeWriteChannel()  # the process ends when its input does

    def _wake(self) -> None:
        self._asleep = False
        self._failed_starts = 0
        self._crashes = 0
        self.start()

    def _on_ready(self) -> None:
        self._ready = True
        self._failed_starts = 0
        log.info("preview process ready (pid %s)", self.pid)
        self._touch()
        for line in (self._project, self._view, self._want):
            if line is not None:
                self._write(line)

    def _on_exit(self, process: QProcess) -> None:
        if process is not self._process or self._stopping:
            return
        if not self._ready:
            self._failed_starts += 1
        else:
            self._crashes += 1
        if self._failed_starts >= MAX_FAILED_STARTS or self._crashes >= MAX_FAILED_STARTS:
            self._give_up()
            return
        log.warning("preview process exited; restarting")
        process.deleteLater()
        self.start()

    def _on_error(self, process: QProcess, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart and process is self._process:
            log.error("preview process failed to start: %s", process.errorString())
            self._give_up()

    def _give_up(self) -> None:
        log.error("preview process unavailable; frames are rendered live")
        self._available = False
        self._ready = False
        self._process = None
        self.availableChanged.emit(False)

    # -- I/O ------------------------------------------------------------------------

    def _write(self, line: str, wake: bool = True) -> None:
        if self._asleep:
            if wake and self._available:
                self._touch()
                self._wake()  # ``_on_ready`` sends the latest project, view and frames wanted
            return
        self._touch()
        if self._process is not None and self._ready:
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
        elif "frame" in message:
            self._crashes = 0
            self._touch()
            data = base64.b64decode(message["data"])
            self.frame.emit(
                message["view_id"],
                message["generation"],
                message["frame"],
                data,
                message["width"],
                message["height"],
            )
        elif "failed" in message:
            log.warning("preview frame %s failed: %s", message["failed"], message.get("error"))
            self.failed.emit(message["failed"])

    def _log_stderr(self, process: QProcess) -> None:
        text = bytes(process.readAllStandardError().data()).decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                log.debug("preview: %s", line)


def make_preview(cache_dir: Path, parent: QObject | None = None) -> PreviewProcess | None:
    """The preview process, or none when ``MANIM_STUDIO_PREVIEW=0`` (tests, debugging). It is released after
    ``IDLE_SECONDS`` unused (``MANIM_STUDIO_IDLE_SECONDS``, as for the build worker)."""
    if os.environ.get("MANIM_STUDIO_PREVIEW") == "0":
        return None
    return PreviewProcess(cache_dir, idle_s=idle_seconds(IDLE_SECONDS), parent=parent)
