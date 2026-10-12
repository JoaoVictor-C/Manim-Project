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

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..core import adapter, audio, edits, library, parts, recovery, subtitles
from ..core.edits import Edit, EditKind
from ..core.evaluator import Evaluator
from ..core.frame_cache import frame_index, frame_time
from ..core.python_export import PythonExport, class_name, to_python
from ..core.schema import MEDIA_TYPES, TEXT_TYPES, Project
from ..core.trust import TrustStore
from ..logging_config import LOGGER_NAME, get_logger, setup_logging
from . import icons, theme
from .audio_player import make_audio_player
from .autosave import Autosave
from .build_service import BuildService
from .canvas import CanvasWidget
from .canvas_tools import MoveTool
from .clipboard_actions import ClipboardActions
from .code_render import make_code_renderer
from .document import Document
from .export_dialog import ExportDialog
from .layers_panel import LayersPanel
from .pages import PageHost, Shared
from .pages.audio import AudioPage
from .pages.code import CodePage
from .pages.compose import ComposePage
from .plugins_dialog import PluginsDialog, startup_message
from .preview_client import make_preview
from .properties_panel import PropertiesPanel
from .render_ahead import RenderAhead
from .selection import Selection
from .timeline.view import TimelineView
from .viewport import ZOOM_STEP
from .worker_process import make_worker

log = get_logger(__name__)


class MainWindow(QMainWindow):
    SLIDER_STEPS_PER_SECOND = 1000
    playheadChanged = Signal(float)  # the playhead moved (seek, every playback tick): the level meter

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
        self._media_errors: dict[str, str] = {}  # layers drawn as placeholders (ADR 0027, 0032)
        self.render_ahead: RenderAhead | None = None  # started with the first project (ADR 0028)
        self.t = 0.0
        self._play_origin: tuple[float, float] | None = None  # (wall clock, t) at play start
        # The project's sound plays through this; its played time is the clock (ADR 0034).
        self.audio_player = make_audio_player(self)
        self._audio_signature: str | None = None  # the mix playing, None: the wall clock drives
        # Every panel edit goes through the build service (ADR 0015).
        self.builds = BuildService(self.document, make_worker(adapter.cache_dir(), self), self)
        self.builds.failed.connect(self._on_build_failed)
        self.builds.prewarm([adapter.default_spec(t) for t in sorted(TEXT_TYPES)])  # library defaults
        # Code layers render in separate processes, only if trusted (ADR 0019).
        self.trust = TrustStore()
        self.code = make_code_renderer(adapter.cache_dir(), self.trust, self)

        self.canvas = CanvasWidget()
        self.canvas.resized.connect(self.refresh)
        self.canvas.view_changed.connect(self.refresh)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(self._on_slider)
        self.play_button = QPushButton(icons.icon("play"), "Play")
        self.play_button.clicked.connect(self.toggle_play)
        self.time_label = QLabel("0.00 s")
        self.time_label.setMinimumWidth(170)

        controls = QHBoxLayout()
        controls.addWidget(self.play_button)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)
        self.viewer = QWidget()  # the canvas with its transport, shown by the pages (ADR 0041)
        layout = QVBoxLayout(self.viewer)
        layout.addWidget(self.canvas, 1)
        layout.addLayout(controls)

        self.timeline = TimelineView()
        self.timeline.set_document(self.document)
        self.timeline.seekRequested.connect(self._on_timeline_seek)

        self.play_timer = QTimer(self)
        self.play_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.play_timer.timeout.connect(self._on_play_tick)
        self.idle_timer = QTimer(self)
        self.idle_timer.setInterval(0)
        self.idle_timer.timeout.connect(self._on_idle)

        self.layers = LayersPanel(self.builds)
        self.layers.message.connect(lambda text: self.statusBar().showMessage(text, 10000))
        self.layers.trust_code = lambda code: self.trust.trust([code])
        self.layers.setEnabled(False)
        self.properties = PropertiesPanel(self.builds)
        self.properties.message.connect(lambda text: self.statusBar().showMessage(text, 10000))
        self.properties.playhead = lambda: self.t
        self.properties.trust_code = lambda code: self.trust.trust([code])
        self.properties.code_status = lambda i: s.text if (s := self.code.status(i)) else None
        self.properties.code_failed = lambda i: (s := self.code.status(i)) is not None and s.state == "error"
        self.properties.retry_code = self.code.retry
        self.code.statusChanged.connect(self.properties.refresh_code_status)
        self.code.rendered.connect(self._on_code_rendered)
        # The workspace pages share the views above (ADR 0041); Compose is the first.
        self.pages = PageHost(Shared(self.viewer, self.timeline, self.layers, self.properties), self)
        for page in (ComposePage, CodePage, AudioPage):  # final order: Compose, Animate, Code, Audio, Deliver
            self.pages.add(page(self))
        self.setCentralWidget(self.pages)
        # One selection for every view (ADR 0016): views report, then follow it.
        self.selection = Selection(self.document, self)
        self.layers.layerSelected.connect(self.selection.select_layer)
        self.timeline.clipSelected.connect(self.selection.set)
        self.timeline.keySelected.connect(self.selection.set_key)
        self.timeline.audioSelected.connect(self.selection.set_audio)
        self.timeline.subtitleSelected.connect(self.selection.set_subtitle)
        self.timeline.markerSelected.connect(self.selection.set_marker)
        self.properties.keyMoved.connect(self.selection.set_key)
        self.selection.changed.connect(self._on_selection_changed)
        self.move_tool = MoveTool(self.canvas, self.document, self.selection, lambda: self.t, self.seek, self)
        self.move_tool.message.connect(lambda text: self.statusBar().showMessage(text, 10000))
        self.timeline.message.connect(lambda text: self.statusBar().showMessage(text, 10000))
        self.builds.pendingChanged.connect(self._on_pending_changed)
        # Cut, copy, paste, duplicate; a recovery copy of unsaved work (ADR 0038).
        has_project = lambda: self._has_project  # noqa: E731
        self.clipboard = ClipboardActions(self.builds, self.selection, lambda: self.t, has_project, self)
        self.clipboard.message.connect(lambda text: self.statusBar().showMessage(text, 10000))
        self.autosave = Autosave(self.document, lambda: self.path, has_project, self)
        self.autosave.timer.start()

        self.library = library.load_library()  # presets, themes, templates (ADR 0039)
        self.timeline.preset_menu = self._preset_menu
        self._build_menu()
        app = QApplication.instance()
        if app is not None:  # coming back from another program: files may have changed (ADR 0027)
            app.applicationStateChanged.connect(self._on_application_state)
        self.statusBar().showMessage(
            startup_message()
            or self._library_message()
            or "Create a project (File > New) or open one (File > Open)."
        )

    # -- menu ------------------------------------------------------------------

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        for text, shortcut, slot in (
            ("&New", QKeySequence.StandardKey.New, self.new_project),
            ("&Open...", QKeySequence.StandardKey.Open, self.open_dialog),
            ("&Save", QKeySequence.StandardKey.Save, self.save),
            ("Save &As...", QKeySequence.StandardKey.SaveAs, self.save_as),
            ("&Export Video...", QKeySequence("Ctrl+E"), self.show_export_dialog),
            ("Export &Python...", QKeySequence(), self.export_python),
            ("Import &Audio...", QKeySequence(), self.import_audio),
            ("Import &Subtitles...", QKeySequence(), self.import_subtitles),
            ("Export Su&btitles...", QKeySequence(), self.export_subtitles),
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
        self.clipboard.add_to(edit_menu)
        add_subtitle = QAction("Add &Subtitle", self)
        add_subtitle.setShortcut(QKeySequence("Ctrl+T"))
        add_subtitle.setToolTip("A subtitle at the playhead (ADR 0035)")
        add_subtitle.triggered.connect(self.add_subtitle)
        edit_menu.addAction(add_subtitle)
        edit_menu.addSeparator()  # markers (ADR 0037)
        for text, key, slot in (
            ("Add &Marker", "M", self.add_marker),
            ("Previous Marker", "[", lambda: self.jump_to_marker(-1)),
            ("Next Marker", "]", lambda: self.jump_to_marker(+1)),
        ):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(slot)
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        self.auto_key_action = QAction("&Auto-key", self, checkable=True)
        self.auto_key_action.setToolTip("Changing an object's transform sets keyframes at the playhead")
        edit_menu.addAction(self.auto_key_action)
        self.move_tool.auto_key = self.auto_key_action.isChecked
        self.properties.auto_key = self.auto_key_action.isChecked
        animate_menu = self.menuBar().addMenu("&Animate")  # presets (ADR 0039)
        self.apply_preset_menu = animate_menu.addMenu("Apply &Preset")
        self._preset_menu(self.apply_preset_menu, None, None)
        save_preset = QAction("Save Animation as Preset...", self)
        save_preset.setToolTip("The selected layer's clips and keys, as a preset of your own")
        save_preset.triggered.connect(self.save_preset)
        animate_menu.addAction(save_preset)
        save_template = QAction("Save Object as Template...", self)
        save_template.setToolTip("The selected object with everything under it, as a template of your own")
        save_template.triggered.connect(self.save_template)
        animate_menu.addAction(save_template)
        self._fill_templates_menu()
        view_menu = self.menuBar().addMenu("&View")
        pages_menu = view_menu.addMenu("&Pages")  # the workspace pages (ADR 0041)
        for number, (name, page) in enumerate(self.pages.pages.items(), start=1):
            action = QAction(page.title, self)
            action.setShortcut(QKeySequence(f"Shift+{number}"))
            action.setToolTip(page.tooltip)
            action.triggered.connect(lambda _=False, n=name: self.show_page(n))
            pages_menu.addAction(action)
        for title, panel in (("&Layers", self.layers), ("P&roperties", self.properties)):
            toggle = QAction(title, self, checkable=True, checked=True)
            toggle.toggled.connect(lambda on, p=panel: self.pages.set_visible(p, on))
            view_menu.addAction(toggle)
        half = QAction("Half-resolution playback", self, checkable=True)
        half.toggled.connect(self._set_half_resolution)
        view_menu.addAction(half)
        self.render_ahead_action = QAction("Render Ahead", self, checkable=True, checked=True)
        self.render_ahead_action.setToolTip("Render frames ahead of the playhead in another process")
        self.render_ahead_action.toggled.connect(self._set_render_ahead)
        view_menu.addAction(self.render_ahead_action)
        view_menu.addSeparator()  # the canvas view (ADR 0023)
        for text, keys, slot in (
            ("Zoom &In", ("Ctrl+=", "Ctrl++"), lambda: self.canvas.zoom(ZOOM_STEP)),
            ("Zoom &Out", ("Ctrl+-",), lambda: self.canvas.zoom(1 / ZOOM_STEP)),
            ("&Fit", ("Ctrl+0",), self.canvas.fit),
            ("&Actual Size (100 %)", ("Ctrl+1",), self.canvas.actual_size),
        ):
            action = QAction(text, self)
            action.setShortcuts([QKeySequence(k) for k in keys])
            action.triggered.connect(slot)
            view_menu.addAction(action)
        self.snap_action = QAction("&Snap to Objects", self, checkable=True, checked=True)
        self.snap_action.setShortcut(QKeySequence("Ctrl+;"))
        self.snap_action.setToolTip(
            "Moved objects and dragged handles line up with other objects and the frame (hold Alt: off)"
        )
        self.snap_action.toggled.connect(lambda on: setattr(self.move_tool, "snapping", on))
        view_menu.addAction(self.snap_action)
        view_menu.addSeparator()
        self.themes_menu = view_menu.addMenu("&Themes")
        self.themes_menu.setToolTipsVisible(True)
        self._fill_themes_menu()
        view_menu.addSeparator()
        reload_media = QAction("Reload &Media", self)
        reload_media.setShortcut(QKeySequence("F5"))
        reload_media.setToolTip("Read images and SVG files again after they changed on disk")
        reload_media.triggered.connect(lambda: self.reload_media(report=True))
        view_menu.addAction(reload_media)
        help_menu = self.menuBar().addMenu("&Help")
        plugins_action = QAction("&Plugins...", self)
        plugins_action.triggered.connect(self.show_plugins)
        help_menu.addAction(plugins_action)
        play = QAction("Play / Pause", self)
        play.setShortcut(Qt.Key.Key_Space)
        play.triggered.connect(self.toggle_play)
        self.addAction(play)
        for key, frames in ((Qt.Key.Key_Right, 1), (Qt.Key.Key_Left, -1)):
            step = QAction(self)
            step.setShortcut(key)
            step.triggered.connect(lambda _=False, f=frames: self.step(f))
            self.addAction(step)

    def _library_message(self) -> str | None:
        """A status-bar line when library files were skipped (ADR 0039), else None."""
        for problem in self.library.problems:
            log.warning("library file skipped: %s", problem)
        count = len(self.library.problems)
        if not count:
            return None
        return f"{count} preset or theme file{'s' if count > 1 else ''} skipped: {self.library.problems[0]}"

    @property
    def page(self) -> str:
        """The workspace page shown (ADR 0041)."""
        return self.pages.current

    def show_page(self, name: str) -> None:
        """Show the workspace page ``name`` (compose, animate, code, audio, deliver)."""
        self.pages.show_page(name)

    def show_plugins(self) -> PluginsDialog:
        """Help > Plugins...: what loaded and what failed (ADR 0032)."""
        dialog = PluginsDialog(self)
        dialog.show()
        return dialog

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
        if self._offer_recovery(self.autosave.offered(path)):  # a crash left newer work (ADR 0038)
            return
        log.info("opened %s (%d layers)", path, len(project.layers))
        self.path = path
        self.document.replace(project)

    # -- crash recovery (ADR 0038) ---------------------------------------------------

    def check_recovery(self) -> bool:
        """At start-up: offer work a crashed instance left behind; True if it was restored."""
        recovery.prune(self.autosave.folder)
        return self._offer_recovery(self.autosave.offered())

    def _offer_recovery(self, entries: list[recovery.Entry]) -> bool:
        if not entries:
            return False
        answer = self.ask_recover(entries)
        if answer == "restore":
            return self.restore(entries[0])
        if answer == "discard":
            for entry in entries:
                recovery.remove(entry.folder, entry.stem)
            log.info("recovery copies discarded: %s", [e.stem for e in entries])
        return False

    def ask_recover(self, entries: list[recovery.Entry]) -> str:
        """``"restore"`` the newest copy, ``"discard"`` them all, or decide ``"later"``."""
        lines = [
            f"  - {e.name} ({time.strftime('%Y-%m-%d %H:%M', time.localtime(e.saved_at))})" for e in entries
        ]
        box = QMessageBox(self)
        box.setWindowTitle("Recover unsaved work?")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(
            "Manim Studio closed without saving this work:\n\n"
            + "\n".join(lines)
            + "\n\nRestore the most recent one? Discard deletes "
            + ("it." if len(entries) == 1 else "all of them.")
        )
        restore = box.addButton("Restore", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return {restore: "restore", discard: "discard"}.get(box.clickedButton(), "later")

    def restore(self, entry: recovery.Entry) -> bool:
        """Open a recovery copy as unsaved changes to its original file."""
        try:
            project = recovery.read_project(entry)
        except Exception as exc:  # a damaged copy: say so and keep it for the user
            log.exception("could not restore %s", entry.project_file)
            QMessageBox.critical(self, "Could not restore", f"{entry.project_file}:\n{exc}")
            return False
        self.path = entry.path
        self.document.replace(project)
        self.document.undo_stack.resetClean()  # unsaved: Save writes it to the original file
        self.autosave.write_now()  # this instance's copy first, then the old one goes
        recovery.remove(entry.folder, entry.stem)
        log.info("restored %s from %s", entry.path or "an untitled project", entry.project_file)
        self.statusBar().showMessage(f"Restored unsaved work on {entry.name}", 10000)
        return True

    @property
    def project(self) -> Project | None:
        return self.document.project if self._has_project else None

    def _on_reset(self, project: Project) -> None:
        """A project was opened: rebuild everything that depends on it."""
        self._has_project = True
        self.layers.setEnabled(True)
        self.evaluator = Evaluator(project, self.code.cache)  # frames where the renderer writes them
        self.canvas.set_scene(project.canvas, self.evaluator)
        if self.render_ahead is None and self.render_ahead_action.isChecked():
            self._start_render_ahead()
        if self.render_ahead is not None:
            self.render_ahead.reset(project)
        self.slider.setRange(0, int(project.canvas.duration * self.SLIDER_STEPS_PER_SECOND))
        self._update_title()
        self.seek(0.0)
        gc.collect()
        gc.freeze()  # measured: removes the gen-2 GC hitches during playback
        self.idle_timer.start()
        self.code.sync(project)
        self._warm_subtitles(project)
        self._media_errors = {}
        self.report_media()
        untrusted = self.trust.untrusted(project)
        if untrusted:  # opening a file must never run its code silently (ADR 0019)
            names = [project.layer(i).name or i for i in untrusted]
            if self.ask_trust(names) == "run":
                self.code.trust_layers(project, untrusted)
            else:
                self.statusBar().showMessage(
                    "Code layers were not run: they show a placeholder. Edit their code to run it.", 15000
                )

    def ask_trust(self, names: list[str]) -> str:
        """``"run"`` or ``"skip"``: may this project's code run on this computer?"""
        answer = QMessageBox.question(
            self,
            "Run code from this project?",
            "This project contains Python code that will run on your computer:\n\n"
            + "\n".join(f"  - {name}" for name in names)
            + "\n\nOnly run it if you trust where the project came from. Run it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return "run" if answer == QMessageBox.StandardButton.Yes else "skip"

    def _on_changed(self, project: Project, layer_ids: frozenset[str], kind: EditKind) -> None:
        """An edit, undo or redo changed the snapshot (ADR 0013, 0014)."""
        assert self.evaluator is not None
        before = self.evaluator.project
        self.evaluator.apply(Edit(project, kind, layer_ids))
        if self.render_ahead is not None:
            self.render_ahead.changed(project)
        self.refresh()
        if kind in ("clip", "spec"):
            self.idle_timer.start()  # recompute dropped checkpoints while idle (ADR 0009)
        if kind == "spec":
            self._warn_retargeted(before, project)
            self.report_media()  # a re-picked file may not be drawable
        if (project.subtitles, project.subtitle_style) != (before.subtitles, before.subtitle_style):
            self._warm_subtitles(project)
        if project.audio != before.audio:
            self.report_media()  # a sound's file may be missing (ADR 0034)
            if self.play_timer.isActive() and self._audio_signature != audio.mix_signature(project):
                self._start_sound()  # hear the edit from where the playhead is
        self.code.sync(project)

    # -- media files (ADR 0027) ------------------------------------------------

    def _on_application_state(self, state: Qt.ApplicationState) -> None:
        if state == Qt.ApplicationState.ApplicationActive and self.isVisible():
            self.reload_media()

    def reload_media(self, report: bool = False) -> set[str]:
        """Read media files changed on disk again and redraw; returns the layers rebuilt.
        ``report`` always says what happened (the menu action); otherwise only new problems."""
        if self.evaluator is None or self.project is None:
            return set()
        changed = self.evaluator.check_media()
        if changed:
            log.info("media reloaded: %s", sorted(changed))
            if self.render_ahead is not None:
                self.render_ahead.layers_changed(changed, media=True)
            self.refresh()
            self.idle_timer.start()  # their checkpoints were dropped (ADR 0009)
        if not self.report_media(force=report) and report:
            self.statusBar().showMessage(f"Media reloaded ({len(changed)} changed)", 3000)
        return changed

    def report_media(self, force: bool = False) -> bool:
        """Say which layers show a placeholder (media, plugins) when that changed (or ``force``)."""
        assert self.evaluator is not None and self.project is not None
        errors = self.evaluator.build_errors()
        sounds = audio.problems(self.project)  # silent sounds (ADR 0034)
        shown = bool(errors or sounds) and (force or {**errors, **sounds} != self._media_errors)
        if shown:
            names = []
            for layer_id, problem in errors.items():
                layer = self.project.layer(layer_id)
                file = (
                    Path(str(layer.spec.params.get("path") or "")).name
                    if layer.spec.type in MEDIA_TYPES
                    else ""
                )
                names.append(f"{layer.name or layer_id} ({file + ' - ' if file else ''}{problem})")
            for clip in self.project.audio:
                if clip.id in sounds:
                    names.append(f"{clip.name or clip.id} ({Path(clip.path).name} - {sounds[clip.id]})")
            media = all(self.project.layer(i).spec.type in MEDIA_TYPES for i in errors)
            self.statusBar().showMessage(
                f"{'Missing media' if media else 'Cannot draw'}: {', '.join(names)}", 15000
            )
        self._media_errors = {**errors, **sounds}
        return shown

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
        self.timeline.set_selected_audio(self.selection.audio_id)
        self.timeline.set_selected_subtitle(self.selection.subtitle_id)
        self.timeline.set_selected_marker(self.selection.marker_id)
        if self.selection.audio_id is not None:
            self.properties.show_audio(self.selection.audio_id)
        elif self.selection.subtitle_id is not None:
            self.properties.show_subtitle(self.selection.subtitle_id)
        elif self.selection.marker_id is not None:
            self.properties.show_marker(self.selection.marker_id)
        elif key_time is not None:
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
        self.autosave.timer.stop()
        self.autosave.discard()  # saved, or thrown away on purpose (ADR 0038)
        if exporting:
            self.export_dialog.cancel()
        if self.export_dialog is not None:
            self.export_dialog.close()
        self.builds.client.stop()
        self.code.stop()
        if self.render_ahead is not None:
            self.render_ahead.stop()
        super().closeEvent(event)

    # -- render ahead (ADR 0028) ---------------------------------------------------------

    def _start_render_ahead(self) -> None:
        self.render_ahead = RenderAhead(make_preview(adapter.cache_dir(), self), self)
        self.render_ahead.progress.connect(self._update_readout)
        self.canvas.render_ahead = self.render_ahead

    def _set_render_ahead(self, enabled: bool) -> None:
        if not enabled and self.render_ahead is not None:
            self.render_ahead.stop()
            self.render_ahead = self.canvas.render_ahead = None
        elif enabled and self.render_ahead is None and self.project is not None:
            self._start_render_ahead()
            self.render_ahead.reset(self.project)
        self.refresh()

    def _on_code_rendered(self, layer_id: str) -> None:
        if self.render_ahead is not None:
            self.render_ahead.layers_changed({layer_id})
        self.refresh()

    # -- Python export (ADR 0031) ------------------------------------------------------

    def export_python(self) -> None:
        if self.project is None:
            self.statusBar().showMessage("Create or open a project first.", 5000)
            return
        start = self.path.with_suffix(".py") if self.path else Path.cwd() / "scene.py"
        name = self.ask_python_path(start)
        if name:
            self.write_python(Path(name))

    # -- subtitles (ADR 0035) ---------------------------------------------------

    def _warm_subtitles(self, project: Project) -> None:
        """Build the subtitles' text in the worker ahead of time; edits never wait for it."""
        style = project.subtitle_style
        self.builds.prewarm(
            [spec for cue in project.subtitles for spec in subtitles.line_specs(cue.text, style)]
        )

    def add_subtitle(self) -> None:
        """Edit > Add Subtitle: a cue at the playhead (or after the cue under it), selected for typing."""
        if self.project is None:
            return
        place = subtitles.place_cue(self.project, self.t)
        if place is None:
            self.statusBar().showMessage("No room for a subtitle here", 5000)
            return
        edit = edits.add_cue(self.project, *place, text="New subtitle")
        self.document.apply(edit, "Add subtitle")
        cue = next(c for c in edit.project.subtitles if c.start == place[0])
        self.selection.set_subtitle(cue.id)

    def add_marker(self) -> None:
        """Edit > Add Marker (M): a marker at the playhead, or the one already there selected."""
        if self.project is not None:
            self.timeline.add_marker_at(self.t)

    def jump_to_marker(self, direction: int) -> None:
        """Edit > Previous / Next Marker ([ and ]): the playhead to the nearest marker that way."""
        if self.project is None:
            return
        half = 0.5 / self.project.canvas.fps
        times = [m.t for m in self.project.markers]
        ahead = (
            [t for t in times if t > self.t + half]
            if direction > 0
            else [t for t in times if t < self.t - half]
        )
        if ahead:
            self.seek(min(ahead) if direction > 0 else max(ahead))

    # -- presets and themes (P5e, ADR 0039) ----------------------------------------------

    def _preset_menu(self, menu, layer_id: str | None, t: float | None) -> None:
        """Fill ``menu`` with the presets by category; the Animate menu's apply to the selected
        layer at the playhead (``layer_id`` and ``t`` None), the timeline's to its row and time."""
        menu.clear()
        menu.setToolTipsVisible(True)
        titles = {"entrance": "Entrance", "emphasis": "Emphasis", "exit": "Exit", "motion": "Motion"}
        for category in library.CATEGORIES:
            sub = menu.addMenu(titles[category])
            sub.setToolTipsVisible(True)
            for preset in self.library.presets_in(category):
                action = sub.addAction(preset.name, lambda p=preset: self.apply_preset(p, layer_id, t))
                action.setToolTip(preset.description)
            sub.setEnabled(bool(sub.actions()))

    def apply_preset(
        self, preset: library.Preset, layer_id: str | None = None, t: float | None = None
    ) -> bool:
        """Apply ``preset`` to the layer (default: the selected one) at ``t`` (default: the playhead);
        a refusal is shown in the status bar. True when it was applied."""
        layer_id = layer_id or self.selection.layer_id
        if self.project is None or layer_id is None:
            self.statusBar().showMessage("Select a layer to animate first", 6000)
            return False
        try:
            edit = library.apply_preset(self.project, layer_id, preset, self.t if t is None else t)
        except edits.EditError as exc:
            self.statusBar().showMessage(str(exc), 10000)
            return False
        self.document.apply(edit, f"Apply {preset.name}")
        self.statusBar().showMessage(f"{preset.name} at {self.t if t is None else t:.2f} s", 4000)
        return True

    def save_preset(self) -> None:
        """Animate > Save Animation as Preset...: the selected layer's clips and keys."""
        layer_id = self.selection.layer_id
        if self.project is None or layer_id is None:
            self.statusBar().showMessage("Select the layer whose animation to save", 6000)
            return
        answer = self.ask_preset_name()
        if answer is None:
            return
        name, category = answer
        try:
            preset = library.preset_from_layer(self.project.layer(layer_id), name, category)
        except edits.EditError as exc:
            self.statusBar().showMessage(str(exc), 8000)
            return
        path = library.save_item(preset)
        self.library.add(preset)
        self._preset_menu(self.apply_preset_menu, None, None)
        self.statusBar().showMessage(f"Saved the preset {name} ({path.name})", 6000)

    def ask_preset_name(self) -> tuple[str, library.Category] | None:
        """A name and a category for a new preset, or None (cancelled). Tests replace it."""
        name, ok = QInputDialog.getText(self, "Save Preset", "Name:")
        if not ok or not name.strip():
            return None
        titles = ["Entrance", "Emphasis", "Exit", "Motion"]
        category, ok = QInputDialog.getItem(self, "Save Preset", "Category:", titles, 0, False)
        return (name.strip(), category.lower()) if ok else None

    def _fill_templates_menu(self) -> None:
        """The Templates section of the Layers panel's Add menu (ADR 0039)."""
        menu = self.layers.library_menu
        for action in getattr(self, "_template_actions", []):
            menu.removeAction(action)
        self._template_actions = [menu.addSection("Templates")]
        menu.setToolTipsVisible(True)
        for template in self.library.templates:
            action = menu.addAction(template.name, lambda tp=template: self.insert_template(tp))
            action.setToolTip(template.description)
            self._template_actions.append(action)

    def insert_template(self, template: library.Template) -> bool:
        """Add > Templates: the template's layers at the playhead, above the selected object."""
        if self.project is None:
            return False
        try:
            pasted = library.insert_template(self.project, template, self.t, above=self.selection.layer_id)
        except edits.EditError as exc:
            self.statusBar().showMessage(str(exc), 10000)
            return False
        self.document.apply(pasted.edit, f"Insert {template.name}")
        self.selection.set(pasted.selected)
        note = f" ({'; '.join(pasted.notes)})" if pasted.notes else ""
        self.statusBar().showMessage(f"{template.name} at {self.t:.2f} s{note}", 6000)
        return True

    def save_template(self) -> None:
        """Animate > Save Object as Template...: the selected object with everything under it."""
        layer_id = self.selection.layer_id
        if self.project is None or layer_id is None:
            self.statusBar().showMessage("Select the object to save as a template", 6000)
            return
        name = self.ask_template_name()
        if not name:
            return
        try:
            template = library.template_from(self.project, layer_id, name)
        except edits.EditError as exc:
            self.statusBar().showMessage(str(exc), 8000)
            return
        path = library.save_item(template)
        self.library.add(template)
        self._fill_templates_menu()
        self.statusBar().showMessage(f"Saved the template {name} ({path.name})", 6000)

    def ask_template_name(self) -> str | None:
        """A name for a new template, or None (cancelled). Tests replace it."""
        name, ok = QInputDialog.getText(self, "Save Template", "Name:")
        return name.strip() if ok and name.strip() else None

    def _fill_themes_menu(self) -> None:
        self.themes_menu.clear()
        for item in self.library.themes:
            action = self.themes_menu.addAction(item.name, lambda th=item: self.apply_theme(th))
            action.setToolTip(f"{item.description} The selected object, or everything with nothing selected.")

    def apply_theme(self, chosen: library.Theme) -> None:
        """View > Themes: recolour the selected object, or every layer and the background."""
        if self.project is None:
            return
        selected = self.selection.layer_id
        edit = library.apply_theme(self.project, chosen, {selected} if selected else None)
        self.document.apply(edit, f"Apply the {chosen.name} theme")
        where = "the selection" if selected else "the scene"
        self.statusBar().showMessage(f"{chosen.name} theme applied to {where}", 4000)

    def import_subtitles(self) -> None:
        """File > Import Subtitles...: an .srt replaces the subtitles (one undo step)."""
        if self.project is None:
            return
        name = self.ask_subtitles_path()
        if not name:
            return
        try:
            cues = subtitles.read_srt(Path(name).read_text(encoding="utf-8-sig", errors="replace"))
        except OSError as exc:
            self.statusBar().showMessage(f"Cannot read {Path(name).name}: {exc}", 10000)
            return
        if not cues:
            self.statusBar().showMessage(f"No subtitles found in {Path(name).name}", 10000)
            return
        self.document.apply(edits.set_subtitles(self.project, cues), "Import subtitles")
        late = sum(1 for cue in cues if cue.end > self.project.canvas.duration)
        note = f" ({late} after the end of the video)" if late else ""
        self.statusBar().showMessage(f"Imported {len(cues)} subtitles from {Path(name).name}{note}", 10000)

    def export_subtitles(self) -> None:
        if self.project is None or not self.project.subtitles:
            self.statusBar().showMessage("There are no subtitles to export", 5000)
            return
        name = self.ask_subtitles_save_path()
        if not name:
            return
        Path(name).write_text(subtitles.write_srt(self.project.subtitles), encoding="utf-8")
        self.statusBar().showMessage(
            f"Wrote {len(self.project.subtitles)} subtitles to {Path(name).name}", 10000
        )

    def ask_subtitles_path(self) -> str:
        name, _ = QFileDialog.getOpenFileName(
            self, "Import Subtitles", "", "Subtitles (*.srt);;All files (*)"
        )
        return name

    def ask_subtitles_save_path(self) -> str:
        start = str(self.path.with_suffix(".srt")) if self.path is not None else ""
        name, _ = QFileDialog.getSaveFileName(self, "Export Subtitles", start, "Subtitles (*.srt)")
        return name

    # -- sounds (ADR 0034) -------------------------------------------------------

    def import_audio(self) -> None:
        """File > Import Audio...: a sound at the playhead, playing the whole file (ADR 0034)."""
        if self.project is None:
            return
        name = self.ask_audio_path()
        if not name:
            return
        length = audio.probe(name)
        if length is None or length <= 0:
            self.statusBar().showMessage(f"Cannot read {Path(name).name} as a sound", 10000)
            return
        edit = edits.add_audio(self.project, name, start=self.t, duration=length, name=Path(name).stem)
        self.document.apply(edit, "Import sound")
        self.selection.set_audio(edit.project.audio[-1].id)
        self.statusBar().showMessage(f"Imported {Path(name).name} ({length:.1f} s) at {self.t:.2f} s", 10000)

    def ask_audio_path(self) -> str:
        name, _ = QFileDialog.getOpenFileName(
            self, "Import Audio", "", "Sounds (*.wav *.mp3 *.ogg *.flac *.m4a *.aac);;All files (*)"
        )
        return name

    def ask_python_path(self, start: Path) -> str:
        name, _ = QFileDialog.getSaveFileName(self, "Export Python", str(start), "Python (*.py)")
        return name

    def write_python(self, path: Path) -> PythonExport:
        """Write the project as a Manim scene: readable when it can be, exact otherwise."""
        export = to_python(self.project, class_name(path.stem), str(adapter.cache_dir() / "code"))
        path.write_text(export.code, encoding="utf-8")
        log.info("python export %s (%s)", path, "readable" if export.readable else "exact")
        if export.readable:
            self.statusBar().showMessage(f"Wrote {path.name}: readable Manim code", 10000)
        else:
            reasons = "; ".join(export.problems[:3]) + (" ..." if len(export.problems) > 3 else "")
            self.statusBar().showMessage(
                f"Wrote {path.name}: exact scene (needs Manim Studio) - {reasons}", 15000
            )
        return export

    # -- export (S4, ADR 0017) -------------------------------------------------------

    def show_export_dialog(self) -> None:
        if self.project is None:
            self.statusBar().showMessage("Create or open a project first.", 5000)
            return
        if self.export_dialog is None:
            name = self.path.stem if self.path else "untitled"
            folder = self.path.parent if self.path else Path.cwd()
            self.export_dialog = ExportDialog(
                lambda: self.document.project,
                folder / "out" / f"{name}.mp4",
                adapter.cache_dir(),
                self,
                trusted=lambda project: not self.trust.untrusted(project),
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
        self.playheadChanged.emit(self.t)

    def refresh(self) -> None:
        if self.project is None:
            return
        if self.render_ahead is not None:
            self.render_ahead.set_playhead(self.t)
        self.canvas.render_at(self.t)
        self._update_readout()

    def _update_readout(self) -> None:
        if self.project is None:
            return
        fps = self.project.canvas.fps
        ahead = ""
        if self.render_ahead is not None and self.render_ahead.active:
            ahead = f"   ahead {len(self.render_ahead.store)}/{self.render_ahead.store.total}"
        source = "cached" if self.canvas.from_cache else f"{self.canvas.last_render_ms:4.1f} ms"
        self.time_label.setText(
            f"{self.t:5.2f} s  frame {frame_index(self.t, fps):4d}  ({source})"
            f"   {self.canvas.zoom_label()}{ahead}"
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
        self._start_sound()
        self.play_timer.start(int(1000 / self.project.canvas.fps))
        self.play_button.setText("Pause")
        self.play_button.setIcon(icons.icon("pause"))
        self.canvas.playing = True

    def _start_sound(self) -> None:
        """Play the project's mix from the playhead and follow its clock, or the wall clock
        when there is nothing to hear or no player (ADR 0034)."""
        project = self.project
        if self.audio_player is not None:
            self.audio_player.stop()
        self._audio_signature = None
        if project is not None and project.audio and self.audio_player is not None:
            self.audio_player.play(audio.mix(project), self.t)
            self._audio_signature = audio.mix_signature(project)
        self._play_origin = (time.perf_counter(), self.t)

    def pause(self) -> None:
        self.play_timer.stop()
        if self._audio_signature is not None:
            self.audio_player.stop()
            self._audio_signature = None
        self.play_button.setText("Play")
        self.play_button.setIcon(icons.icon("play"))
        if self.canvas.playing:
            self.canvas.playing = False
            self.refresh()  # the motion path comes back

    def _on_play_tick(self) -> None:
        assert self.project is not None and self._play_origin is not None
        wall0, t0 = self._play_origin
        if self._audio_signature is not None:  # the sound's clock (ADR 0034)
            t = self.audio_player.position()
        else:
            t = t0 + (time.perf_counter() - wall0)  # wall clock: slow frames are dropped, never queued
        fps = self.project.canvas.fps
        t = frame_time(frame_index(t, fps), fps)  # the frames the export has (ADR 0028)
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
            if self.statusBar().currentMessage().startswith("Preparing timeline"):
                self.statusBar().showMessage("Ready", 2000)  # never over another message
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
    theme.apply(app)  # the studio look (ADR 0040)
    adapter.configure(Path.cwd() / ".cache" / "manim")
    window = MainWindow()
    window.show()
    if len(argv) > 1:
        window.load(Path(argv[1]))  # offers that file's recovery copies (ADR 0038)
    else:
        window.check_recovery()
    return app.exec()
