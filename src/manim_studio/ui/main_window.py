"""S0: the previewer slice of the editor.

Canvas that shows the exact Manim frame at the playhead, a time slider, play/pause
and open/save. Rules from DESIGN.md:

* the content is rendered by Manim's Cairo camera at device pixels (preview == export);
* playback samples wall-clock time and drops frames instead of queueing them;
* missing checkpoints are computed one per idle tick, and gc is frozen after load,
  which keeps the worst playback frame near the 33 ms budget.
"""

from __future__ import annotations

import gc
import logging
import sys
import time
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core import adapter, parts
from ..core.edits import Edit, EditKind
from ..core.evaluator import Evaluator
from ..core.schema import TEXT_TYPES, Project
from ..logging_config import LOGGER_NAME, get_logger, setup_logging
from .build_service import BuildService
from .canvas import CanvasWidget
from .canvas_tools import MoveTool
from .document import Document
from .export_dialog import ExportDialog
from .layers_panel import LayersPanel
from .properties_panel import PropertiesPanel
from .selection import Selection
from .timeline.view import TimelineView
from .worker_process import make_worker

log = get_logger(__name__)


class MainWindow(QMainWindow):
    SLIDER_STEPS_PER_SECOND = 1000

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Manim Studio")
        self.resize(1280, 820)
        # The document always exists (so the Edit menu can bind to its undo stack);
        # ``project`` is None until a file is opened.
        self.document = Document(Project(), self)
        self.document.reset.connect(self._on_reset)
        self.document.changed.connect(self._on_changed)
        self.document.undo_stack.cleanChanged.connect(self._update_title)
        self._has_project = False
        self.export_dialog: ExportDialog | None = None
        self.path: Path | None = None
        self.evaluator: Evaluator | None = None
        self.t = 0.0
        self._play_origin: tuple[float, float] | None = None  # (wall clock, t) at play start
        # Every panel edit goes through the build service (ADR 0015).
        self.builds = BuildService(self.document, make_worker(adapter.cache_dir(), self), self)
        self.builds.failed.connect(self._on_build_failed)
        self.builds.prewarm([adapter.default_spec(t) for t in sorted(TEXT_TYPES)])  # library defaults

        self.canvas = CanvasWidget()
        self.canvas.resized.connect(self.refresh)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(self._on_slider)
        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle_play)
        self.time_label = QLabel("0.00 s")
        self.time_label.setMinimumWidth(170)

        controls = QHBoxLayout()
        controls.addWidget(self.play_button)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)
        preview = QWidget()
        layout = QVBoxLayout(preview)
        layout.addWidget(self.canvas, 1)
        layout.addLayout(controls)

        self.timeline = TimelineView()
        self.timeline.set_document(self.document)
        self.timeline.seekRequested.connect(self._on_timeline_seek)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(preview)
        splitter.addWidget(self.timeline)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)  # the timeline keeps its height (about six rows)
        self.setCentralWidget(splitter)

        self.play_timer = QTimer(self)
        self.play_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.play_timer.timeout.connect(self._on_play_tick)
        self.idle_timer = QTimer(self)
        self.idle_timer.setInterval(0)
        self.idle_timer.timeout.connect(self._on_idle)

        self.layers = LayersPanel(self.builds)
        self.layers.message.connect(lambda text: self.statusBar().showMessage(text, 10000))
        self.layers.setEnabled(False)
        self.layers_dock = self._dock("Layers", self.layers, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.properties = PropertiesPanel(self.builds)
        self.properties.message.connect(lambda text: self.statusBar().showMessage(text, 10000))
        self.properties.playhead = lambda: self.t
        self.properties_dock = self._dock(
            "Properties", self.properties, Qt.DockWidgetArea.RightDockWidgetArea
        )
        # One selection for every view (ADR 0016): views report, then follow it.
        self.selection = Selection(self.document, self)
        self.layers.layerSelected.connect(self.selection.select_layer)
        self.timeline.clipSelected.connect(self.selection.set)
        self.timeline.keySelected.connect(self.selection.set_key)
        self.properties.keyMoved.connect(self.selection.set_key)
        self.selection.changed.connect(self._on_selection_changed)
        self.move_tool = MoveTool(self.canvas, self.document, self.selection, lambda: self.t, self.seek, self)
        self.move_tool.message.connect(lambda text: self.statusBar().showMessage(text, 10000))
        self.timeline.message.connect(lambda text: self.statusBar().showMessage(text, 10000))
        self.builds.pendingChanged.connect(self._on_pending_changed)

        self._build_menu()
        self.statusBar().showMessage("Create a project (File > New) or open one (File > Open).")

    def _dock(self, title: str, widget: QWidget, area: Qt.DockWidgetArea) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(f"{title.lower()}-dock")
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    # -- menu ------------------------------------------------------------------

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        for text, shortcut, slot in (
            ("&New", QKeySequence.StandardKey.New, self.new_project),
            ("&Open...", QKeySequence.StandardKey.Open, self.open_dialog),
            ("&Save", QKeySequence.StandardKey.Save, self.save),
            ("Save &As...", QKeySequence.StandardKey.SaveAs, self.save_as),
            ("&Export Video...", QKeySequence("Ctrl+E"), self.show_export_dialog),
        ):
            action = QAction(text, self)
            action.setShortcut(shortcut)
            action.triggered.connect(slot)
            file_menu.addAction(action)
        edit_menu = self.menuBar().addMenu("&Edit")
        undo = self.document.undo_stack.createUndoAction(self, "&Undo")
        undo.setShortcut(QKeySequence.StandardKey.Undo)
        redo = self.document.undo_stack.createRedoAction(self, "&Redo")
        redo.setShortcut(QKeySequence.StandardKey.Redo)
        edit_menu.addActions([undo, redo])
        edit_menu.addSeparator()
        self.auto_key_action = QAction("&Auto-key", self, checkable=True)
        self.auto_key_action.setToolTip("Changing an object's transform sets keyframes at the playhead")
        edit_menu.addAction(self.auto_key_action)
        self.move_tool.auto_key = self.auto_key_action.isChecked
        self.properties.auto_key = self.auto_key_action.isChecked
        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.layers_dock.toggleViewAction())
        view_menu.addAction(self.properties_dock.toggleViewAction())
        half = QAction("Half-resolution playback", self, checkable=True)
        half.toggled.connect(self._set_half_resolution)
        view_menu.addAction(half)
        play = QAction("Play / Pause", self)
        play.setShortcut(Qt.Key.Key_Space)
        play.triggered.connect(self.toggle_play)
        self.addAction(play)
        for key, frames in ((Qt.Key.Key_Right, 1), (Qt.Key.Key_Left, -1)):
            step = QAction(self)
            step.setShortcut(key)
            step.triggered.connect(lambda _=False, f=frames: self.step(f))
            self.addAction(step)

    # -- project ---------------------------------------------------------------

    def new_project(self) -> None:
        """An empty scene with the default canvas (1280x720, 30 fps, 5 s)."""
        if not self.confirm_discard():
            return
        self.path = None
        self.document.replace(Project())
        log.info("new project")

    def open_dialog(self) -> None:
        if not self.confirm_discard():
            return
        start = str(self.path.parent if self.path else Path.cwd())
        name, _ = QFileDialog.getOpenFileName(self, "Open project", start, "Manim Studio project (*.json)")
        if name:
            self.load(Path(name))

    def load(self, path: Path) -> None:
        try:
            project = Project.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # show validation errors to the user
            log.exception("could not open %s", path)
            QMessageBox.critical(self, "Could not open project", str(exc))
            return
        log.info("opened %s (%d layers)", path, len(project.layers))
        self.path = path
        self.document.replace(project)

    @property
    def project(self) -> Project | None:
        return self.document.project if self._has_project else None

    def _on_reset(self, project: Project) -> None:
        """A project was opened: rebuild everything that depends on it."""
        self._has_project = True
        self.layers.setEnabled(True)
        self.evaluator = Evaluator(project)
        self.canvas.set_scene(project.canvas, self.evaluator)
        self.slider.setRange(0, int(project.canvas.duration * self.SLIDER_STEPS_PER_SECOND))
        self._update_title()
        self.seek(0.0)
        gc.collect()
        gc.freeze()  # measured: removes the gen-2 GC hitches during playback
        self.idle_timer.start()

    def _on_changed(self, project: Project, layer_ids: frozenset[str], kind: EditKind) -> None:
        """An edit, undo or redo changed the snapshot (ADR 0013, 0014)."""
        assert self.evaluator is not None
        before = self.evaluator.project
        self.evaluator.apply(Edit(project, kind, layer_ids))
        self.refresh()
        if kind in ("clip", "spec"):
            self.idle_timer.start()  # recompute dropped checkpoints while idle (ADR 0009)
        if kind == "spec":
            self._warn_retargeted(before, project)

    def _warn_retargeted(self, before: Project, after: Project) -> None:
        """A text edit can move a part to another match (ADR 0012): say which parts to check."""
        moved = parts.retargeted(before, after)
        if moved:
            names = ", ".join(f"{after.layer(i).name or i} ({why})" for i, why in moved.items())
            self.statusBar().showMessage(f"Check parts: {names}", 15000)

    def _on_selection_changed(self) -> None:
        layer_id, clip_id = self.selection.layer_id, self.selection.clip_id
        key_time = self.selection.key_time
        with QSignalBlocker(self.layers.list):
            self.layers.select(layer_id)
        self.layers.update_buttons()
        self.timeline.set_selected(layer_id, clip_id, key_time)
        if key_time is not None:
            self.properties.show_key(layer_id, key_time)
        elif clip_id is not None:
            self.properties.show_clip(layer_id, clip_id)
        elif layer_id is not None:
            self.properties.show_layer(layer_id)
        else:
            self.properties.show_nothing()
        self.canvas.selected_layer = layer_id
        self.refresh()

    def _on_pending_changed(self) -> None:
        if self.builds.busy:
            self.statusBar().showMessage("Building text...")
        elif self.statusBar().currentMessage() == "Building text...":
            self.statusBar().clearMessage()

    def _on_build_failed(self, text: str, message: str) -> None:
        self.statusBar().showMessage(f"{text}: not applied - {message}", 10000)

    def closeEvent(self, event: QCloseEvent) -> None:
        exporting = self.export_dialog is not None and self.export_dialog.running
        if exporting and self.ask_stop_export() != "stop":
            event.ignore()
            return
        if not self.confirm_discard():
            event.ignore()
            return
        if exporting:
            self.export_dialog.cancel()
        if self.export_dialog is not None:
            self.export_dialog.close()
        self.builds.client.stop()
        super().closeEvent(event)

    # -- export (S4, ADR 0017) -------------------------------------------------------

    def show_export_dialog(self) -> None:
        if self.project is None:
            self.statusBar().showMessage("Create or open a project first.", 5000)
            return
        if self.export_dialog is None:
            name = self.path.stem if self.path else "untitled"
            folder = self.path.parent if self.path else Path.cwd()
            self.export_dialog = ExportDialog(
                lambda: self.document.project, folder / "out" / f"{name}.mp4", adapter.cache_dir(), self
            )
            self.export_dialog.stateChanged.connect(self._on_export_state)
        self.export_dialog.show()
        self.export_dialog.raise_()
        self.export_dialog.activateWindow()

    def _on_export_state(self, text: str) -> None:
        if text:
            self.statusBar().showMessage(f"Export: {text}")
        elif self.statusBar().currentMessage().startswith("Export: "):
            self.statusBar().clearMessage()

    def ask_stop_export(self) -> str:
        """An export is running: "stop" it and quit, or "cancel" quitting."""
        buttons = QMessageBox.StandardButton
        answer = QMessageBox.question(
            self,
            "Export running",
            "A video is being exported. Stop it and quit?",
            buttons.Yes | buttons.No,
            buttons.No,
        )
        return "stop" if answer == buttons.Yes else "cancel"

    # -- unsaved changes ----------------------------------------------------------

    def confirm_discard(self) -> bool:
        """True if the current project may be replaced or closed (saved, or the user agreed)."""
        if self.project is None or self.document.undo_stack.isClean():
            return True
        answer = self.ask_unsaved()
        if answer == "save":
            self.save()
            return self.document.undo_stack.isClean()  # False if Save As was cancelled
        return answer == "discard"

    def ask_unsaved(self) -> str:
        """Ask what to do with unsaved changes: "save", "discard" or "cancel"."""
        name = self.path.name if self.path else "untitled"
        buttons = QMessageBox.StandardButton
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            f"Save the changes to {name}?",
            buttons.Save | buttons.Discard | buttons.Cancel,
            buttons.Save,
        )
        return {buttons.Save: "save", buttons.Discard: "discard"}.get(answer, "cancel")

    def _update_title(self) -> None:
        name = self.path.name if self.path else "untitled"
        dirty = "" if self.document.undo_stack.isClean() else " *"
        self.setWindowTitle(f"Manim Studio - {name}{dirty}")

    def save(self) -> None:
        if self.project is None:
            return
        if self.path is None:
            self.save_as()
            return
        self.path.write_text(self.project.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
        self.document.undo_stack.setClean()
        self._update_title()
        log.info("saved %s", self.path)
        self.statusBar().showMessage(f"Saved {self.path}", 3000)

    def save_as(self) -> None:
        if self.project is None:
            return
        name, _ = QFileDialog.getSaveFileName(
            self, "Save project", str(self.path or "project.json"), "*.json"
        )
        if name:
            self.path = Path(name)
            self.save()

    # -- time ------------------------------------------------------------------

    def seek(self, t: float) -> None:
        if self.project is None:
            return
        duration = self.project.canvas.duration
        self.t = min(max(0.0, t), duration)
        self.slider.blockSignals(True)
        self.slider.setValue(int(self.t * self.SLIDER_STEPS_PER_SECOND))
        self.slider.blockSignals(False)
        self.timeline.set_playhead(self.t)
        self.refresh()
        if not self.play_timer.isActive():
            self.properties.refresh()  # keyed fields show their value at the playhead

    def refresh(self) -> None:
        if self.project is None:
            return
        self.canvas.render_at(self.t)
        fps = self.project.canvas.fps
        self.time_label.setText(
            f"{self.t:5.2f} s  frame {int(self.t * fps):4d}  ({self.canvas.last_render_ms:4.1f} ms)"
        )

    def step(self, frames: int) -> None:
        if self.project is not None:
            self.pause()
            self.seek(self.t + frames / self.project.canvas.fps)

    def _on_timeline_seek(self, t: float) -> None:
        self.pause()
        self.seek(t)

    def _on_slider(self, value: int) -> None:
        self.pause()
        self.seek(value / self.SLIDER_STEPS_PER_SECOND)

    def toggle_play(self) -> None:
        if self.play_timer.isActive():
            self.pause()
        else:
            self.play()

    def play(self) -> None:
        if self.project is None:
            return
        if self.t >= self.project.canvas.duration - 1e-6:
            self.seek(0.0)
        self._play_origin = (time.perf_counter(), self.t)
        self.play_timer.start(int(1000 / self.project.canvas.fps))
        self.play_button.setText("Pause")

    def pause(self) -> None:
        self.play_timer.stop()
        self.play_button.setText("Play")

    def _on_play_tick(self) -> None:
        assert self.project is not None and self._play_origin is not None
        wall0, t0 = self._play_origin
        t = t0 + (time.perf_counter() - wall0)  # wall clock: slow frames are dropped, never queued
        if t >= self.project.canvas.duration:
            self.seek(self.project.canvas.duration)
            self.pause()
            return
        self.seek(t)

    def _on_idle(self) -> None:
        """Compute one missing checkpoint per idle tick (<= ~25 ms each)."""
        if self.evaluator is None or self.play_timer.isActive():
            return
        missing = self.evaluator.missing_checkpoints()
        if not missing:
            self.idle_timer.stop()
            self.statusBar().showMessage("Ready", 2000)
            return
        self.statusBar().showMessage(f"Preparing timeline... {len(missing)} checkpoints left")
        self.evaluator.compute_checkpoint(*missing[0])

    def _set_half_resolution(self, enabled: bool) -> None:
        self.canvas.half_resolution = enabled
        self.refresh()


def run(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if not logging.getLogger(LOGGER_NAME).handlers:  # launched without the CLI
        setup_logging()
    app = QApplication(argv)
    app.setApplicationName("Manim Studio")
    adapter.configure(Path.cwd() / ".cache" / "manim")
    window = MainWindow()
    window.show()
    if len(argv) > 1:
        window.load(Path(argv[1]))
    return app.exec()
