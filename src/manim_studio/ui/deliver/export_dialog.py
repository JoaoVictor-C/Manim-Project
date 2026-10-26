"""File > Export Video... (S4, ADR 0017): a non-modal dialog around one ``ExportJob``.

Export renders the scene as it is when the button is pressed (saved or not);
editing continues while it runs. The dialog shows "Starting..." while the
renderer process starts (~4 s), then frames, a progress bar and an estimate of
the time left; Cancel stops it without touching an existing video; when done it
offers to open the folder.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.model.schema import Project
from .export_job import ExportJob


class ExportDialog(QDialog):
    stateChanged = Signal(str)  # a short status for the main window ("" when idle)

    def __init__(
        self,
        snapshot: Callable[[], Project],
        default_output: Path,
        cache_dir: Path,
        parent: QWidget | None = None,
        trusted: Callable[[Project], bool] = lambda project: False,
    ) -> None:
        super().__init__(parent)
        self.trusted = trusted  # may code layers run? (ADR 0019)
        self.setWindowTitle("Export video")
        self.setModal(False)
        self.snapshot, self.cache_dir = snapshot, cache_dir
        self.job: ExportJob | None = None
        self.result_path: Path | None = None
        self._first_progress: tuple[float, int] | None = None

        self.path = QLineEdit(str(default_output))
        browse = QToolButton(text="...")
        browse.clicked.connect(self._browse)
        self.status = QLabel("Choose where to save the video.")
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.export_button = QPushButton("Export")
        self.export_button.setDefault(True)
        self.export_button.clicked.connect(self.start)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        self.open_button = QPushButton("Open folder")
        self.open_button.clicked.connect(self.open_folder)
        self.open_button.setEnabled(False)
        close = QPushButton("Close")
        close.clicked.connect(self.close)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Save as"))
        path_row.addWidget(self.path, 1)
        path_row.addWidget(browse)
        buttons = QHBoxLayout()
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)
        for button in (self.export_button, self.cancel_button, close):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addLayout(path_row)
        layout.addWidget(self.bar)
        layout.addWidget(self.status)
        layout.addLayout(buttons)
        self.resize(520, 160)

    @property
    def running(self) -> bool:
        return self.job is not None and self.job.running

    # -- actions --------------------------------------------------------------------

    def start(self) -> None:
        if self.running:
            return
        text = self.path.text().strip()
        if not text:
            self._set_status("Choose where to save the video.")
            return
        output = Path(text)
        if output.suffix.lower() != ".mp4":
            output = output.with_suffix(".mp4")
            self.path.setText(str(output))
        self.result_path = None
        self._first_progress = None
        project = self.snapshot()
        self.job = ExportJob(project, output, self.cache_dir, trust_code=self.trusted(project), parent=self)
        self.job.progress.connect(self._on_progress)
        self.job.finished.connect(self._on_finished)
        self.job.failed.connect(self._on_failed)
        self.bar.setRange(0, 0)  # busy until the first frame
        self._set_status("Starting the renderer...")
        self._set_running(True)
        self.job.start()

    def cancel(self) -> None:
        if not self.running:
            return
        self.job.cancel()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self._set_status("Cancelled. Any previous video at that path was left as it was.")
        self._set_running(False)

    def open_folder(self) -> None:
        if self.result_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result_path.parent)))

    # -- job signals ----------------------------------------------------------------

    def _on_progress(self, frame: int, total: int) -> None:
        now = time.monotonic()
        if self._first_progress is None:
            self._first_progress = (now, frame)
        self.bar.setRange(0, total)
        self.bar.setValue(frame)
        text = f"Rendering frame {frame} of {total}"
        started, first = self._first_progress
        if frame > first and now > started:
            rate = (frame - first) / (now - started)
            text += f" - about {max(0.0, (total - frame) / rate):.0f} s left"
        self._set_status(text)

    def _on_finished(self, path: str, warning: str) -> None:
        self.result_path = Path(path)
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        text = f"Exported to {path}"
        if warning:
            text += f"\n{warning}"
        self._set_status(text)
        self._set_running(False)
        self.open_button.setEnabled(True)

    def _on_failed(self, message: str) -> None:
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self._set_status(f"Export failed: {message}")
        self._set_running(False)

    # -- internals ------------------------------------------------------------------

    def _browse(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, "Export video", self.path.text(), "MP4 video (*.mp4)")
        if name:
            self.path.setText(name)

    def _set_running(self, running: bool) -> None:
        self.export_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.path.setEnabled(not running)
        if running:
            self.open_button.setEnabled(False)
        if not running:
            self.stateChanged.emit("")

    def _set_status(self, text: str) -> None:
        self.status.setText(text)
        if self.running:
            self.stateChanged.emit(text.splitlines()[0])
