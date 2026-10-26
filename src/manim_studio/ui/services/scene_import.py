"""Recording a Manim scene from the editor (P10.3, ADR 0053).

``SceneImporter`` runs ``python -m manim_studio.processes.scene_recorder`` - the user's code never runs in
the editor (ADR 0019). A process is started as soon as an import begins (``warm``): it imports
Manim (6-8 s cold, B30) while the user picks the file and the scene, then takes ONE job and exits.
A job that runs longer than ``timeout_s`` is killed and reported. ``finished`` carries the
recording, ``failed`` the reason (with the line of the user's code when known).

``ImportReport`` is the non-modal window that lists what the import made of the scene.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout, QWidget

from ...logging_config import get_logger
from ...processes.scene_recorder import TIME_LIMIT
from ..style import theme

log = get_logger(__name__)


class SceneImporter(QObject):
    finished = Signal(dict)  # the recording
    failed = Signal(str)  # why, for the status bar

    def __init__(
        self,
        cache_dir: Path,
        *,
        timeout_s: float = TIME_LIMIT,
        program: str = sys.executable,
        args: list[str] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.timeout_s = timeout_s
        self._program = program
        self._args = (
            args
            if args is not None
            else ["-m", "manim_studio.processes.scene_recorder", "--cache-dir", str(cache_dir)]
        )
        self._process: QProcess | None = None
        self._ready = False
        self._job: dict | None = None
        self._sent = 0.0
        self._buffer = b""
        self._folder: str | None = None
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(250)
        self._watchdog.timeout.connect(self._check_time)

    @property
    def busy(self) -> bool:
        return self._job is not None

    def warm(self) -> None:
        """Start the process now, so Manim is imported by the time the job comes."""
        if self._process is None:
            process = QProcess()
            process.setProgram(self._program)
            process.setArguments(self._args)
            env = QProcessEnvironment.systemEnvironment()
            env.insert("PYTHONUTF8", "1")
            env.insert("PYTHONUNBUFFERED", "1")
            process.setProcessEnvironment(env)
            process.readyReadStandardOutput.connect(self._read)
            process.readyReadStandardError.connect(self._log_stderr)
            process.finished.connect(self._on_exit)
            self._process, self._ready, self._buffer = process, False, b""
            process.start()

    def start(self, path: Path, scene: str | None, prelude: bool = False) -> None:
        """Record ``path``'s scene (``prelude``: a code layer's code, ADR 0019)."""
        self.cancel()
        self._folder = tempfile.mkdtemp(prefix="manim-studio-import-")
        output = str(Path(self._folder) / "recording.json")
        self._job = {"file": str(path), "scene": scene, "prelude": prelude, "output": output}
        self.warm()
        self._send()

    def cancel(self) -> None:
        """Drop the job running now (its process is killed; the next import starts another)."""
        if self._job is not None:
            self._job = None
            self._kill()
        self._clean()

    def stop(self) -> None:
        self._job = None
        self._kill()
        self._clean()

    # -- the process -------------------------------------------------------------------------------------

    def _send(self) -> None:
        if self._job is None or not self._ready or self._process is None or self._sent:
            return
        self._process.write((json.dumps(self._job) + "\n").encode("utf-8"))
        self._process.closeWriteChannel()
        self._sent = time.monotonic()
        self._watchdog.start()

    def _read(self) -> None:
        if self._process is None:
            return
        self._buffer += bytes(self._process.readAllStandardOutput().data())
        *lines, self._buffer = self._buffer.split(b"\n")
        for raw in lines:
            text = raw.strip()
            if text.startswith(b"{"):  # anything else is not the protocol
                self._handle(json.loads(text))

    def _handle(self, message: dict) -> None:
        if message.get("ready"):
            self._ready = True
            self._send()
            return
        job, self._job = self._job, None
        if job is None:
            return
        self._watchdog.stop()
        if "error" in message:
            line = message.get("line")
            self.failed.emit(f"line {line}: {message['error']}" if line else str(message["error"]))
        elif message.get("done"):
            try:
                recording = json.loads(Path(job["output"]).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                self.failed.emit(f"the recording could not be read: {exc}")
            else:
                self.finished.emit(recording)
        self._clean()

    def _on_exit(self, *_args) -> None:
        self._read()
        process, self._process, self._sent, self._ready = self._process, None, 0.0, False
        if process is not None:
            _release(process)
        if self._job is not None:
            self._job = None
            self._watchdog.stop()
            self.failed.emit("the recording process stopped unexpectedly")
            self._clean()

    def _check_time(self) -> None:
        if self._job is None or not self._sent:
            self._watchdog.stop()
            return
        if time.monotonic() - self._sent > self.timeout_s:
            self._job = None
            self._watchdog.stop()
            self._kill()
            self.failed.emit(f"the scene took longer than {self.timeout_s:g} s to play, so it was stopped")
            self._clean()

    def _kill(self) -> None:
        process, self._process, self._sent, self._ready = self._process, None, 0.0, False
        if process is not None:
            _release(process)  # its signals: nothing it says now is about a job
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(2000)

    def _clean(self) -> None:
        if self._folder is not None and self._job is None:
            shutil.rmtree(self._folder, ignore_errors=True)
            self._folder = None

    def _log_stderr(self) -> None:
        if self._process is None:
            return
        text = bytes(self._process.readAllStandardError().data()).decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                log.debug("scene recorder: %s", line)


def _release(process: QProcess) -> None:
    for signal in (process.readyReadStandardOutput, process.readyReadStandardError, process.finished):
        with contextlib.suppress(RuntimeError, TypeError):
            signal.disconnect()
    process.deleteLater()


class ImportReport(QDialog):
    """What an import made of a scene: one line per layer, and what could not be converted."""

    def __init__(self, title: str, lines: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        self.resize(640, 360)
        self.text = QPlainTextEdit("\n".join(lines))
        self.text.setReadOnly(True)
        self.text.setFont(theme.mono_font())
        self.text.setObjectName("importReport")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setToolTip("Close this report")
        layout = QVBoxLayout(self)
        layout.addWidget(self.text, 1)
        layout.addWidget(buttons)
