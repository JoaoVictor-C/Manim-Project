"""The preview render process as seen from the editor (ADR 0028).

``PreviewProcess`` runs ``python -m manim_studio.preview`` in a ``QProcess`` and
keeps the latest project, view and wanted frames, so a process that starts
late or restarts after a crash is brought up to date. It emits ``frame(view_id,
generation, index, data, width, height)`` with zlib-compressed RGBA ``data``
and ``failed(index)``; after ``MAX_FAILED_STARTS`` starts that never become
ready it gives up (``available`` is False) and the editor renders live.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from ..core.schema import Project
from ..logging_config import get_logger
from ..render.preview import PreviewView

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
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._program = program
        self._args = (
            args if args is not None else ["-m", "manim_studio.preview", "--cache-dir", str(cache_dir)]
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
        self.start()

    @property
    def available(self) -> bool:
        return self._available

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
        self._write(self._want)

    def media(self) -> None:
        self._write(json.dumps({"media": True}) + "\n")

    # -- lifecycle ----------------------------------------------------------------

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
        log.info("starting preview process: %s %s", self._program, " ".join(self._args))
        process.start()

    def stop(self) -> None:
        self._stopping = True
        if self._process is None:
            return
        process, self._process = self._process, None
        process.closeWriteChannel()  # the process ends when its input does
        if not process.waitForFinished(2000):
            process.kill()
            process.waitForFinished(1000)

    def _on_ready(self) -> None:
        self._ready = True
        self._failed_starts = 0
        log.info("preview process ready (pid %s)", self.pid)
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

    def _write(self, line: str) -> None:
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
    """The preview process, or none when ``MANIM_STUDIO_PREVIEW=0`` (tests, debugging)."""
    if os.environ.get("MANIM_STUDIO_PREVIEW") == "0":
        return None
    return PreviewProcess(cache_dir, parent=parent)
