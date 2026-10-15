"""One video export running in a separate process (S4, ADR 0017).

``ExportJob(project, output, cache_dir)`` writes the snapshot to
``<cache_dir>/exports/<uuid>.json`` and runs ``python -m manim_studio render``
with ``--cache-dir`` and ``--progress json`` in a ``QProcess``. It reports
``progress(frame, total)``, then ``finished(path, warning)`` or
``failed(message)``. ``options`` (size, fps, range, quality, subtitles) become flags of that
command (ADR 0042). ``cancel()`` kills the process and removes the partial video; the
snapshot file is always removed when the job ends.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from ..core.schema import Project
from ..logging_config import get_logger
from ..render.cairo_export import partial_path
from ..render.options import RenderOptions

log = get_logger(__name__)

STDERR_LINES = 8  # shown when the render fails without an "error:" line


class ExportJob(QObject):
    progress = Signal(int, int)  # frame, total
    finished = Signal(str, str)  # path, warning ("" if none)
    failed = Signal(str)  # message

    def __init__(
        self,
        project: Project,
        output: Path,
        cache_dir: Path,
        *,
        program: str = sys.executable,
        trust_code: bool = False,
        options: RenderOptions | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.trust_code = trust_code  # run code layers missing from the cache (ADR 0019)
        self.project, self.output, self.cache_dir = project, Path(output), Path(cache_dir)
        self.options = options or RenderOptions()  # size, fps, range, quality, subtitles (ADR 0042)
        self._program = program
        self._snapshot: Path | None = None
        self._process: QProcess | None = None
        self._stdout = b""
        self._stderr = b""
        self._done_path: str | None = None
        self._warning = ""
        self._cancelled = False

    @property
    def running(self) -> bool:
        return self._process is not None

    def start(self) -> None:
        exports = self.cache_dir / "exports"
        exports.mkdir(parents=True, exist_ok=True)
        self._snapshot = exports / f"{uuid.uuid4().hex}.json"
        self._snapshot.write_text(self.project.model_dump_json(by_alias=True), encoding="utf-8")
        process = QProcess(self)
        process.setProgram(self._program)
        process.setArguments(
            [
                "-m",
                "manim_studio",
                "render",
                str(self._snapshot),
                str(self.output),
                "--cache-dir",
                str(self.cache_dir),
                "--progress",
                "json",
                *(["--trust-code"] if self.trust_code else []),
                *self.options.to_args(),
            ]
        )
        process.setWorkingDirectory(os.getcwd())  # relative image paths resolve as in the editor
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("PYTHONUTF8", "1")
        process.setProcessEnvironment(env)
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        self._process = process
        log.info("export %s -> %s", self._snapshot.name, self.output)
        process.start()

    def cancel(self) -> None:
        if self._process is None:
            return
        self._cancelled = True
        process = self._process
        process.kill()
        process.waitForFinished(3000)
        self._cleanup(remove_partial=True)

    # -- process output ---------------------------------------------------------

    def _read_stdout(self) -> None:
        self._stdout += bytes(self._process.readAllStandardOutput().data())
        *lines, self._stdout = self._stdout.split(b"\n")
        for raw in lines:
            line = raw.strip()
            if not line.startswith(b"{"):
                continue
            message = json.loads(line)
            if "frame" in message:
                self.progress.emit(int(message["frame"]), int(message["total"]))
            elif "warning" in message:
                self._warning = message["warning"]
            elif "done" in message:
                self._done_path = message["done"]

    def _read_stderr(self) -> None:
        self._stderr += bytes(self._process.readAllStandardError().data())

    def _on_finished(self, exit_code: int, _status) -> None:
        if self._process is None:  # cancelled: already cleaned up
            return
        self._read_stdout()
        self._read_stderr()
        ok = exit_code == 0 and self._done_path is not None and not self._cancelled
        self._cleanup(remove_partial=not ok)
        if ok:
            log.info("export finished: %s", self._done_path)
            self.finished.emit(self._done_path, self._warning)
        elif not self._cancelled:
            message = self._error_message()
            log.warning("export failed (exit %s): %s", exit_code, message)
            self.failed.emit(message)

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart and self._process is not None:
            message = f"could not start the renderer: {self._process.errorString()}"
            self._cleanup(remove_partial=True)
            self.failed.emit(message)

    def _error_message(self) -> str:
        text = self._stderr.decode("utf-8", errors="replace")
        errors = [line.removeprefix("error: ") for line in text.splitlines() if line.startswith("error: ")]
        if errors:
            return "\n".join(errors)
        tail = [line for line in text.splitlines() if line.strip()][-STDERR_LINES:]
        return "\n".join(tail) or "the renderer stopped unexpectedly"

    def _cleanup(self, remove_partial: bool) -> None:
        process, self._process = self._process, None
        if process is not None:
            process.deleteLater()
        if self._snapshot is not None:
            self._snapshot.unlink(missing_ok=True)
        if remove_partial:
            partial_path(self.output).unlink(missing_ok=True)
