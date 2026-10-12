"""The Deliver page (P6b.5, ADR 0041, ADR 0042): render settings, a queue of exports and the Python scene.

Left, the shared viewer. Right, top to bottom: the **render settings** (file, size, frame
rate, range, quality, subtitles) with *Add to queue*; the **queue** of exports, run one after
another through ``ExportJob`` (each from the project as it was when it was added); and the
**Python scene** with a readable/exact preview and *Save as...*. The settings are the
page's own state, not the project's; they start from the project's canvas.
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core import adapter
from ...core.python_export import PythonExport, class_name, to_python
from ...core.schema import Project
from ...logging_config import get_logger
from ...render.options import (
    DEFAULT_CRF,
    HEIGHT_PRESETS,
    QUALITIES,
    OptionsError,
    RenderOptions,
    apply_options,
    frame_window,
    size_for_height,
)
from .. import theme
from ..export_job import ExportJob
from ..render_queue import QueueJob, RenderQueue, Status
from . import Page, Shared

log = get_logger(__name__)

PYTHON_DELAY_MS = 400  # the preview follows edits this long after the last one
SUBTITLE_LABELS = (
    ("burn", "Burned into the video (and an .srt beside it)"),
    ("srt", "An .srt beside the video only"),
    ("none", "None"),
)
STATUS_TEXT = {
    Status.QUEUED: "Queued",
    Status.DONE: "Done",
    Status.CANCELLED: "Cancelled",
}


def open_folder(path: Path) -> None:
    """Show the folder holding ``path`` in the system's file manager."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))


def default_output(path: Path | None) -> Path:
    name = path.stem if path else "untitled"
    return (path.parent if path else Path.cwd()) / "out" / f"{name}.mp4"


class DeliverPage(Page):
    name = "deliver"
    title = "Deliver"
    icon = "deliver"
    tooltip = "Export the video (size, range, quality, a queue of renders) and the Python scene (Shift+5)"

    # -- building ---------------------------------------------------------------------

    def build(self) -> QWidget:
        self.queue = RenderQueue()
        self._export: ExportJob | None = None  # the running export, for queue.current
        self._rows: dict[int, QTreeWidgetItem] = {}
        self._first_progress: tuple[float, int] | None = None
        self._default_output: str = ""
        self._fps_touched = False
        self._markers_chosen = False  # until the user picks, the range is first marker to last
        self._seen = None
        self._duration: float | None = None
        self._python_stale = True
        self._python_timer = QTimer(singleShot=True, interval=PYTHON_DELAY_MS)
        self._python_timer.timeout.connect(self.refresh_python)

        self.outer = QSplitter(Qt.Orientation.Horizontal)
        self.outer.setChildrenCollapsible(False)
        right = QSplitter(Qt.Orientation.Vertical)
        right.setChildrenCollapsible(False)
        right.addWidget(self._build_settings())
        right.addWidget(self._build_queue())
        right.addWidget(self._build_python())
        right.setStretchFactor(0, 0)
        right.setStretchFactor(1, 1)
        right.setStretchFactor(2, 1)
        self.right = right
        self.outer.addWidget(right)
        self.outer.setStretchFactor(0, 1)
        self.outer.setStretchFactor(1, 0)

        document = self.window.document
        document.reset.connect(self._on_reset)
        document.changed.connect(self._on_changed)
        self._on_reset(document.project)
        return self.outer

    def _build_settings(self) -> QGroupBox:
        box = QGroupBox("Render settings")
        form = QFormLayout(box)
        self.path = QLineEdit()
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path, 1)
        path_row.addWidget(browse)
        form.addRow("Save as", path_row)

        self.size = QComboBox()
        self.size.addItem("", "project")
        for label in HEIGHT_PRESETS:
            self.size.addItem("", label)
        self.size.addItem("Custom", "custom")
        self.width = QSpinBox(minimum=2, maximum=16384, singleStep=2)
        self.height = QSpinBox(minimum=2, maximum=16384, singleStep=2)
        size_row = QHBoxLayout()
        size_row.addWidget(self.size, 1)
        size_row.addWidget(self.width)
        size_row.addWidget(QLabel("x"))
        size_row.addWidget(self.height)
        form.addRow("Size", size_row)
        self.size.currentIndexChanged.connect(self._on_size_choice)
        self.width.valueChanged.connect(self._refresh_summary)
        self.height.valueChanged.connect(self._refresh_summary)

        self.fps = QSpinBox(minimum=1, maximum=240, suffix=" fps")
        self.fps.valueChanged.connect(self._on_fps_edited)
        form.addRow("Frame rate", self.fps)

        self.range = QComboBox()
        for label, key in (
            ("Whole scene", "whole"),
            ("From - to", "times"),
            ("Between two markers", "markers"),
        ):
            self.range.addItem(label, key)
        self.range.currentIndexChanged.connect(self._on_range_choice)
        self.start = QDoubleSpinBox(decimals=3, singleStep=0.1, suffix=" s")
        self.end = QDoubleSpinBox(decimals=3, singleStep=0.1, suffix=" s")
        times_row = QHBoxLayout()
        times_row.addWidget(self.start)
        times_row.addWidget(QLabel("to"))
        times_row.addWidget(self.end)
        self.marker_from, self.marker_to = QComboBox(), QComboBox()
        markers_row = QHBoxLayout()
        markers_row.addWidget(self.marker_from, 1)
        markers_row.addWidget(QLabel("to"))
        markers_row.addWidget(self.marker_to, 1)
        form.addRow("Range", self.range)
        form.addRow("", times_row)
        form.addRow("", markers_row)
        for widget in (self.start, self.end):
            widget.valueChanged.connect(self._refresh_summary)
        for combo in (self.marker_from, self.marker_to):
            combo.currentIndexChanged.connect(self._refresh_summary)
            combo.activated.connect(self._on_marker_chosen)

        self.quality = QComboBox()
        for label, crf in QUALITIES.items():
            self.quality.addItem(f"{label} (crf {crf})", crf)
        self.quality.setCurrentIndex(self.quality.findData(DEFAULT_CRF))
        self.quality.currentIndexChanged.connect(self._refresh_summary)
        form.addRow("Quality", self.quality)

        self.subtitles = QComboBox()
        for key, label in SUBTITLE_LABELS:
            self.subtitles.addItem(label, key)
        form.addRow("Subtitles", self.subtitles)

        self.summary = QLabel()
        self.summary.setProperty("role", "readout")
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet(f"color: {theme.THEME.danger};")
        self.add_button = QPushButton("Add to queue")
        self.add_button.setDefault(True)
        self.add_button.clicked.connect(self.add_to_queue)
        bottom = QHBoxLayout()
        bottom.addWidget(self.summary, 1)
        bottom.addWidget(self.add_button)
        form.addRow(bottom)
        form.addRow(self.error)
        return box

    def _build_queue(self) -> QGroupBox:
        box = QGroupBox("Render queue")
        layout = QVBoxLayout(box)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Video", "Render", "Status"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setMinimumHeight(90)
        self.tree.header().setStretchLastSection(True)
        self.tree.setColumnWidth(0, 150)
        self.tree.setColumnWidth(1, 170)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self.tree.itemDoubleClicked.connect(lambda item, _col: self.open_folder())
        layout.addWidget(self.tree, 1)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.queue_status = QLabel("Add an export, then start the queue.")
        self.queue_status.setWordWrap(True)
        layout.addWidget(self.bar)
        layout.addWidget(self.queue_status)

        self.start_button = QPushButton("Start queue")
        self.cancel_button = QPushButton("Cancel")
        self.remove_button = QPushButton("Remove")
        self.clear_button = QPushButton("Clear finished")
        self.open_button = QPushButton("Open folder")
        self.start_button.clicked.connect(self.start_queue)
        self.cancel_button.clicked.connect(self.cancel_selected)
        self.remove_button.clicked.connect(self.remove_selected)
        self.clear_button.clicked.connect(self.clear_finished)
        self.open_button.clicked.connect(self.open_folder)
        buttons = QHBoxLayout()
        for button in (self.start_button, self.cancel_button, self.remove_button, self.clear_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.open_button)
        layout.addLayout(buttons)
        self._update_buttons()
        return box

    def _build_python(self) -> QGroupBox:
        box = QGroupBox("Python scene")
        layout = QVBoxLayout(box)
        self.python_kind = QLabel()
        self.python_kind.setProperty("role", "section")
        self.python_reasons = QLabel()
        self.python_reasons.setWordWrap(True)
        self.python_code = QPlainTextEdit()
        self.python_code.setReadOnly(True)
        self.python_code.setFont(theme.mono_font())
        self.python_code.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.python_code.setMinimumHeight(90)
        self.python_save = QPushButton("Save as...")
        self.python_save.clicked.connect(self.save_python)
        row = QHBoxLayout()
        row.addWidget(self.python_kind, 1)
        row.addWidget(self.python_save)
        layout.addLayout(row)
        layout.addWidget(self.python_reasons)
        layout.addWidget(self.python_code, 1)
        return box

    # -- page lifecycle -----------------------------------------------------------------

    def place(self, shared: Shared) -> None:
        self.outer.insertWidget(0, shared.viewer)

    def on_show(self) -> None:
        if not getattr(self, "_sized", False):  # first show: the settings column at its natural width
            self._sized = True
            total = max(self.outer.width(), 1200)
            self.outer.setSizes([total - 520, 520])
        self._follow_default_output()
        if self._python_stale:
            self.refresh_python()

    def on_hide(self) -> None:
        self._python_timer.stop()

    @property
    def busy(self) -> bool:
        """An export of the queue is rendering (the window asks before closing)."""
        return self.queue.busy

    def cancel_all(self) -> None:
        """Stop the running export and the rest of the queue (the window is closing)."""
        if self.queue.cancel_all() and self._export is not None:
            self._export.cancel()
            self._export = None
        for job in self.queue.jobs:
            self._update_row(job)
        self._update_buttons()

    # -- the project ----------------------------------------------------------------------

    def _canvas(self):
        return self.window.document.project.canvas

    def _on_reset(self, project: Project) -> None:
        """A project was opened: the settings start from its canvas again."""
        self._fps_touched = False
        self._markers_chosen = False
        self._seen = None
        self.size.blockSignals(True)
        self.size.setCurrentIndex(0)
        self.size.blockSignals(False)
        self._refresh_sizes()
        self._set_fps(project.canvas.fps)
        self.range.setCurrentIndex(0)
        self.quality.setCurrentIndex(self.quality.findData(DEFAULT_CRF))
        self.subtitles.setCurrentIndex(
            self.subtitles.findData("burn" if project.subtitle_style.burn_in else "srt")
        )
        self._follow_default_output(force=True)
        self.start.setValue(0.0)
        self._duration = None
        self._refresh_project_fields(project)
        self.error.clear()
        self._python_changed()

    def _on_changed(self, project: Project, *_rest) -> None:
        self._refresh_sizes()
        if not self._fps_touched:
            self._set_fps(project.canvas.fps)
        self._refresh_project_fields(project)
        self._python_changed()

    def _refresh_project_fields(self, project: Project) -> None:
        """The range, markers and subtitle choice follow the project's duration, markers and cues."""
        duration, markers = project.canvas.duration, tuple(project.markers)
        seen = (duration, markers, bool(project.subtitles), project.canvas.width_px, project.canvas.height_px)
        if seen == self._seen:  # a drag changes the document often; most changes touch none of this
            return
        self._seen = seen
        for spin in (self.start, self.end):
            spin.blockSignals(True)
            spin.setRange(0.0, duration)
            spin.blockSignals(False)
        if self._duration is None or abs(self.end.value() - self._duration) < 1e-9:
            self.end.setValue(duration)  # the end follows the scene's end until it is set
        self._duration = duration
        for combo, last in ((self.marker_from, False), (self.marker_to, True)):
            before = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for marker in markers:
                combo.addItem(f"{marker.name or marker.id} ({marker.t:.2f} s)", marker.t)
            index = combo.findData(before) if before is not None and self._markers_chosen else -1
            combo.setCurrentIndex(index if index >= 0 else (combo.count() - 1 if last else 0))
            combo.blockSignals(False)
        self.subtitles.setEnabled(bool(project.subtitles))
        self.add_button.setEnabled(self.window.project is not None)
        self._on_range_choice()
        self._on_size_choice()

    def _refresh_sizes(self) -> None:
        canvas = self._canvas()
        self.size.setItemText(0, f"Project canvas ({canvas.width_px}x{canvas.height_px})")
        for index in range(1, self.size.count() - 1):
            width, height = size_for_height(canvas, HEIGHT_PRESETS[self.size.itemData(index)])
            self.size.setItemText(index, f"{self.size.itemData(index)} ({width}x{height})")

    def _set_fps(self, value: int) -> None:
        self.fps.blockSignals(True)
        self.fps.setValue(value)
        self.fps.blockSignals(False)
        self._refresh_summary()

    def _on_fps_edited(self, _value: int) -> None:
        self._fps_touched = True
        self._refresh_summary()

    def _follow_default_output(self, force: bool = False) -> None:
        """The path field offers ``out/<project>.mp4`` until the user types another."""
        new = str(default_output(self.window.path))
        if force or not self.path.text() or self.path.text() == self._default_output:
            self.path.setText(new)
        self._default_output = new

    # -- the settings -----------------------------------------------------------------------

    def _on_size_choice(self, *_args) -> None:
        key = self.size.currentData()
        canvas = self._canvas()
        if key == "project":
            width, height = canvas.width_px, canvas.height_px
        elif key == "custom":
            width, height = self.width.value(), self.height.value()
        else:
            width, height = size_for_height(canvas, HEIGHT_PRESETS[key])
        for spin, value in ((self.width, width), (self.height, height)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self.width.setEnabled(key == "custom")
        self.height.setEnabled(key == "custom")
        self._refresh_summary()

    def _on_range_choice(self, *_args) -> None:
        mode = self.range.currentData()
        self.start.setEnabled(mode == "times")
        self.end.setEnabled(mode == "times")
        self.marker_from.setEnabled(mode == "markers")
        self.marker_to.setEnabled(mode == "markers")
        self._refresh_summary()

    def _on_marker_chosen(self, _index: int) -> None:
        self._markers_chosen = True

    def options(self) -> RenderOptions:
        """The options the form describes (OptionsError when they cannot be rendered)."""
        canvas = self._canvas()
        key = self.size.currentData()
        if key == "project":
            width = height = None
        else:
            width, height = self.width.value(), self.height.value()
        fps = self.fps.value() if self.fps.value() != canvas.fps else None
        start, end = 0.0, None
        mode = self.range.currentData()
        if mode == "times":
            start, end = self.start.value(), self.end.value()
        elif mode == "markers":
            a, b = self.marker_from.currentData(), self.marker_to.currentData()
            if a is None or b is None or self.marker_from.count() < 2:
                raise OptionsError("Add two markers to the timeline (M) to export between them.")
            if abs(a - b) < 1e-9:
                raise OptionsError("Choose two different markers.")
            start, end = min(a, b), max(a, b)
        return RenderOptions(
            width=width,
            height=height,
            fps=fps,
            start=start,
            end=end,
            crf=self.quality.currentData(),
            subtitles=self.subtitles.currentData() if self.subtitles.isEnabled() else None,
        )

    def _refresh_summary(self, *_args) -> None:
        """What the current settings would render, or why they cannot."""
        if not hasattr(self, "summary"):
            return
        project = self.window.document.project
        try:
            options = self.options()
            canvas = apply_options(project, options).canvas
            first, last = frame_window(canvas, options)
        except OptionsError as error:
            self.summary.setText(str(error))
            return
        seconds = (last - first) / canvas.fps
        size = f"{canvas.width_px}x{canvas.height_px} at {canvas.fps} fps"
        self.summary.setText(f"{last - first} frames, {seconds:.2f} s - {size}")

    def _browse(self) -> None:
        name, _ = QFileDialog.getSaveFileName(
            self.widget, "Export video", self.path.text(), "MP4 video (*.mp4)"
        )
        if name:
            self.path.setText(name)

    # -- the queue ----------------------------------------------------------------------------

    def add_to_queue(self) -> QueueJob | None:
        """Queue an export of the project as it is now with the settings shown."""
        project = self.window.project
        if project is None:
            self.error.setText("Create or open a project first.")
            return None
        text = self.path.text().strip()
        if not text:
            self.error.setText("Choose where to save the video.")
            return None
        try:
            options = self.options()
            frame_window(apply_options(project, options).canvas, options)
        except OptionsError as error:
            self.error.setText(str(error))
            return None
        self.error.clear()
        trust = not self.window.trust.untrusted(project)  # fixed now, like the snapshot (ADR 0019)
        job = self.queue.add(project, options, Path(text), trust)
        self._add_row(job)
        self.queue_status.setText(f"Added {job.output.name}.")
        self._update_buttons()
        if self.queue.active:  # the queue is running: this one follows the others
            self._launch_next()
        return job

    def start_queue(self) -> None:
        if self.queue.start() is not None:
            self._launch(self.queue.current)

    def _launch_next(self) -> None:
        job = self.queue.advance()
        if job is not None:
            self._launch(job)
        elif not self.queue.busy:
            self._queue_idle()

    def _launch(self, job: QueueJob) -> None:
        self._first_progress = None
        export = ExportJob(
            job.project,
            job.output,
            adapter.cache_dir(),
            trust_code=job.trust,
            options=job.options,
            parent=self.widget,
        )
        export.progress.connect(lambda frame, total: self._on_progress(job, frame, total))
        export.finished.connect(lambda path, warning: self._on_finished(job, path, warning))
        export.failed.connect(lambda message: self._on_failed(job, message))
        self._export = export
        self.bar.setRange(0, 0)  # busy until the first frame
        self.queue_status.setText(f"Starting the renderer for {job.output.name}...")
        self._update_row(job)
        self._update_buttons()
        log.info("deliver: rendering %s (%s)", job.output, job.summary)
        export.start()

    def _on_progress(self, job: QueueJob, frame: int, total: int) -> None:
        if job.status is not Status.RENDERING:
            return
        now = time.monotonic()
        if self._first_progress is None:
            self._first_progress = (now, frame)
        self.queue.progress(job, frame, total)
        self.bar.setRange(0, total)
        self.bar.setValue(frame)
        text = f"Rendering {job.output.name}: frame {frame} of {total}"
        started, first = self._first_progress
        if frame > first and now > started:
            rate = (frame - first) / (now - started)
            text += f" - about {max(0.0, (total - frame) / rate):.0f} s left"
        self.queue_status.setText(text)
        self._update_row(job)
        self._status_message(text)

    def _on_finished(self, job: QueueJob, path: str, warning: str) -> None:
        self.queue.finish(job, Path(path), warning)
        self._after_job(job, f"Exported to {path}" + (f"\n{warning}" if warning else ""))

    def _on_failed(self, job: QueueJob, message: str) -> None:
        self.queue.fail(job, message)
        self._after_job(job, f"Export failed: {message}")

    def _after_job(self, job: QueueJob, text: str) -> None:
        if self._export is not None:
            self._export.deleteLater()
            self._export = None
        self.bar.setRange(0, 1)
        self.bar.setValue(1 if job.status is Status.DONE else 0)
        self.queue_status.setText(text)
        self._update_row(job)
        self._launch_next()
        self._update_buttons()

    def _queue_idle(self) -> None:
        self._status_message("")
        self._update_buttons()

    def cancel_selected(self) -> None:
        """Cancel the selected job, or the one rendering when none is selected."""
        job = self.selected() or self.queue.current
        if job is None or job.finished:
            return
        if self.queue.cancel(job) and self._export is not None:
            self._export.cancel()
            self._export = None
            self.bar.setRange(0, 1)
            self.bar.setValue(0)
            self.queue_status.setText("Cancelled. A video already at that path was left as it was.")
        self._update_row(job)
        self._launch_next()
        self._update_buttons()

    def remove_selected(self) -> None:
        job = self.selected()
        if job is not None and self.queue.remove(job):
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(self._rows.pop(job.id)))
            self._update_buttons()

    def clear_finished(self) -> None:
        for job in [j for j in self.queue.jobs if j.finished]:
            self.queue.remove(job)
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(self._rows.pop(job.id)))
        self._update_buttons()

    def open_folder(self) -> None:
        job = self.selected()
        if job is not None and job.result is not None:
            open_folder(job.result)

    def selected(self) -> QueueJob | None:
        items = self.tree.selectedItems()
        return self.queue.get(items[0].data(0, Qt.ItemDataRole.UserRole)) if items else None

    def select(self, job: QueueJob) -> None:
        self.tree.setCurrentItem(self._rows[job.id])

    # -- the queue's rows ---------------------------------------------------------------------

    def _add_row(self, job: QueueJob) -> None:
        item = QTreeWidgetItem(self.tree)
        item.setData(0, Qt.ItemDataRole.UserRole, job.id)
        self._rows[job.id] = item
        self._update_row(job)

    def status_text(self, job: QueueJob) -> str:
        if job.status is Status.RENDERING:
            return f"Rendering {job.percent} %" if job.total else "Starting..."
        if job.status is Status.FAILED:
            return "Failed: " + (job.message.splitlines()[0] if job.message else "unknown error")
        if job.status is Status.DONE and job.message:
            return f"Done - {job.message}"
        return STATUS_TEXT[job.status]

    def _update_row(self, job: QueueJob) -> None:
        item = self._rows.get(job.id)
        if item is None:
            return
        item.setText(0, job.output.name)
        item.setToolTip(0, str(job.output))
        item.setText(1, job.summary)
        item.setText(2, self.status_text(job))
        item.setToolTip(2, job.message or item.text(2))

    def _update_buttons(self) -> None:
        job = self.selected()
        target = job or self.queue.current
        self.start_button.setEnabled(bool(self.queue.queued) and not self.queue.active)
        self.cancel_button.setEnabled(target is not None and not target.finished)
        self.remove_button.setEnabled(job is not None and job.status is not Status.RENDERING)
        self.clear_button.setEnabled(any(j.finished for j in self.queue.jobs))
        self.open_button.setEnabled(job is not None and job.result is not None)

    def _status_message(self, text: str) -> None:
        bar = self.window.statusBar()
        if text:
            bar.showMessage(f"Deliver: {text}")
        elif bar.currentMessage().startswith("Deliver: "):
            bar.clearMessage()

    # -- the Python scene -----------------------------------------------------------------------

    def _python_changed(self) -> None:
        self._python_stale = True
        if self.window.page == self.name:
            self._python_timer.start()

    def refresh_python(self) -> None:
        """Show ``to_python`` of the project as it is: readable code, or the exact scene and why."""
        self._python_timer.stop()
        self._python_stale = False
        project = self.window.project
        if project is None:
            self._show_python(None, "Open a project to see its Python scene.")
            return
        stem = self.window.path.stem if self.window.path else "scene"
        try:
            export = to_python(project, class_name(stem), str(adapter.cache_dir() / "code"))
        except Exception as error:  # a preview must never take the editor down
            log.exception("python preview failed")
            self._show_python(None, f"The scene cannot be written yet: {error}")
            return
        self._show_python(export, "")

    def _show_python(self, export: PythonExport | None, message: str) -> None:
        self.python_save.setEnabled(export is not None)
        if export is None:
            self.python_kind.setText(message)
            self.python_reasons.clear()
            self.python_code.clear()
            return
        if export.readable:
            self.python_kind.setText("Readable Manim code - runs with plain Manim")
            self.python_reasons.setText("Nothing in the project needs Manim Studio to play it.")
        else:
            self.python_kind.setText("Exact scene - plays the project through Manim Studio")
            shown = "; ".join(export.problems[:4]) + (
                f"; and {len(export.problems) - 4} more" if len(export.problems) > 4 else ""
            )
            self.python_reasons.setText(f"Exact because: {shown}")
        self.python_code.setPlainText(export.code)

    def save_python(self) -> None:
        """Save the scene as a .py file (the same as File > Export Python...)."""
        self.window.export_python()
