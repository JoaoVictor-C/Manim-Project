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

import numpy as np
from PySide6.QtCore import QSignalBlocker, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ..core import adapter, audio, edits, library, parts, recovery, shift_timing, subtitles
from ..core.edits import Edit, EditKind
from ..core.evaluator import Evaluator
from ..core.frame_cache import frame_index, frame_time
from ..core.python_export import PythonExport, class_name, to_python
from ..core.schema import MEDIA_TYPES, TEXT_TYPES, Project
from ..core.trust import TrustStore
from ..logging_config import LOGGER_NAME, get_logger, log_dir, setup_logging
from . import arrange, icons, places, shortcuts_help, snap_guides, theme
from .audio_player import make_audio_player
from .autosave import Autosave
from .build_service import BuildService
from .canvas import CanvasWidget
from .canvas_tools import MoveTool
from .clipboard_actions import ClipboardActions
from .code_render import make_code_renderer
from .document import Document
from .elided_label import ElidedLabel
from .export_dialog import ExportDialog
from .layers_panel import LayersPanel
from .pages import PageHost, Shared
from .pages.animate import AnimatePage
from .pages.audio import AudioPage
from .pages.code import CodePage
from .pages.compose import ComposePage
from .pages.deliver import DeliverPage
from .plugins_dialog import PluginsDialog, startup_message
from .preferences import Preferences
from .presets_browser import PresetsBrowser
from .preview_client import make_preview
from .properties_panel import PropertiesPanel
from .render_ahead import RenderAhead
from .selection import Selection
from .shortcuts_help import ShortcutsDialog
from .timeline.view import TimelineView
from .viewport import ZOOM_STEP
from .welcome import EXAMPLE, WelcomePanel
from .worker_process import make_worker

log = get_logger(__name__)


START_HINT = "Create a project (File > New) or open one (File > Open)."


class MainWindow(QMainWindow):
    SLIDER_STEPS_PER_SECOND = 1000
    playheadMoved = Signal(float)  # every seek and playback tick: pages' own views follow it

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Manim Studio")
        self.resize(1280, 820)
        self.prefs = Preferences()  # how the editor was left (ADR 0044)
        self._page_restored = False  # the last page returns once, when the first project opens
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
        self.time_label = ElidedLabel("0.00 s", minimum=170)  # shortened, not cut, in a narrow window
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        controls = QHBoxLayout()
        controls.addWidget(self.play_button)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)
        self.stage = QWidget()  # the canvas with its transport
        layout = QVBoxLayout(self.stage)
        layout.addWidget(self.canvas, 1)
        layout.addLayout(controls)
        # What the pages show: the stage, or the welcome until a project is open (ADR 0041, 0044).
        self.viewer = QWidget()
        self.viewer_stack = QStackedLayout(self.viewer)
        self.welcome = WelcomePanel()
        self.viewer_stack.addWidget(self.stage)
        self.viewer_stack.addWidget(self.welcome)
        self.viewer_stack.setCurrentWidget(self.welcome)

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
        self.layers.playhead = lambda: self.t  # new objects are placed where they are free then (GP)
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
        self.properties.code_ends = lambda: self.evaluator.code_ends() if self.evaluator is not None else []
        self.code.statusChanged.connect(self.properties.refresh_code_status)
        self.code.rendered.connect(self._on_code_rendered)
        # The workspace pages share the views above (ADR 0041); Compose is the first.
        self.pages = PageHost(Shared(self.viewer, self.timeline, self.layers, self.properties), self)
        for page in (ComposePage, AnimatePage, CodePage, AudioPage, DeliverPage):  # Shift+1..5
            self.pages.add(page(self))
        self.setCentralWidget(self.pages)
        # One selection for every view (ADR 0016): views report, then follow it.
        self.selection = Selection(self.document, self)
        self.layers.layerSelected.connect(self.selection.select_layer)
        self.layers.layersPicked.connect(lambda ids, current: self.selection.set_layers(ids, current))
        self.timeline.clipSelected.connect(self.selection.set)
        self.timeline.layerPicked.connect(self._on_layer_picked)
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
        self.timeline.browse_presets = self.show_presets_browser
        self.presets_browser: PresetsBrowser | None = None  # made on the first Browse Presets
        self._build_menu()
        self._wire_welcome()
        self._restore_preferences()
        app = QApplication.instance()
        if app is not None:  # coming back from another program: files may have changed (ADR 0027)
            app.applicationStateChanged.connect(self._on_application_state)
        self.statusBar().showMessage(startup_message() or self._library_message() or START_HINT)

    # -- menu ------------------------------------------------------------------

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        for text, shortcut, slot, tip in (
            ("&New", QKeySequence.StandardKey.New, self.new_project, "Start an empty project"),
            ("&Open...", QKeySequence.StandardKey.Open, self.open_dialog, "Open a project file (.json)"),
            ("&Save", QKeySequence.StandardKey.Save, self.save, "Save the project to its file"),
            ("Save &As...", QKeySequence.StandardKey.SaveAs, self.save_as, "Save the project to a new file"),
            (
                "&Export Video...",
                QKeySequence("Ctrl+E"),
                self.show_export_dialog,
                "Render the whole video with Manim to an MP4 file",
            ),
            ("Export &Python...", QKeySequence(), self.export_python, "Write the scene as a Manim script"),
            ("Import &Audio...", QKeySequence(), self.import_audio, "Add a sound at the playhead"),
            (
                "Import &Subtitles...",
                QKeySequence(),
                self.import_subtitles,
                "Read subtitles from an .srt file",
            ),
            (
                "Export Su&btitles...",
                QKeySequence(),
                self.export_subtitles,
                "Write the subtitles as an .srt file",
            ),
        ):
            action = QAction(text, self)
            action.setShortcut(shortcut)
            action.setToolTip(tip)
            action.triggered.connect(slot)
            file_menu.addAction(action)
            if slot == self.open_dialog:  # then the ways to open something else (ADR 0044)
                self.open_recent_menu = file_menu.addMenu("Open &Recent")
                self.open_recent_menu.setToolTipsVisible(True)
                self.open_recent_menu.menuAction().setToolTip("The projects opened or saved lately")
                self.open_recent_menu.aboutToShow.connect(self._fill_recent_menu)
                example = QAction("Open Examp&le", self)
                example.setToolTip("The showcase scene, as an untitled copy you can change freely")
                example.triggered.connect(self.open_example)
                file_menu.addAction(example)
                self.open_example_action = example
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
        for text, key, slot, tip in (
            ("Add &Marker", "M", self.add_marker, "A marker at the playhead, to snap to and jump between"),
            (
                "Previous Marker",
                "[",
                lambda: self.jump_to_marker(-1),
                "Move the playhead to the marker before it",
            ),
            ("Next Marker", "]", lambda: self.jump_to_marker(+1), "Move the playhead to the marker after it"),
        ):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(key))
            action.setToolTip(tip)
            action.triggered.connect(slot)
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        self.auto_key_action = QAction("&Auto-key", self, checkable=True)
        self.auto_key_action.setToolTip("Changing an object's transform sets keyframes at the playhead")
        edit_menu.addAction(self.auto_key_action)
        self.move_tool.auto_key = self.auto_key_action.isChecked
        self.properties.auto_key = self.auto_key_action.isChecked
        edit_menu.addSeparator()  # the scene's settings (P7.1)
        scene_settings = QAction("&Scene Settings...", self)
        scene_settings.setToolTip("The video's length, size, frame rate and background, in Properties")
        scene_settings.triggered.connect(self.show_scene_settings)
        fit_length = QAction("&Fit Length to Content", self)
        fit_length.setToolTip("End the scene where its last clip, key, sound or subtitle ends")
        fit_length.triggered.connect(lambda: self._has_project and self.properties.fit_length())
        shift_action = QAction("Shift &Timing...", self)
        shift_action.setToolTip(
            "Move the selected layers, clip, keys, sound, subtitle or marker earlier or later"
        )
        shift_action.setShortcut(QKeySequence("Ctrl+Shift+T"))
        shift_action.triggered.connect(self.shift_selection)
        self.ask_shift = self._ask_shift_dialog  # tests and other front-ends answer here
        edit_menu.addActions([scene_settings, fit_length, shift_action])
        animate_menu = self.menuBar().addMenu("&Animate")  # presets (ADR 0039)
        self.apply_preset_menu = animate_menu.addMenu("Apply &Preset")
        self._preset_menu(self.apply_preset_menu, None, None)
        browse_presets = QAction("&Browse Presets...", self)  # moving previews (P6d.3, ADR 0044)
        browse_presets.setShortcut(QKeySequence("Ctrl+Shift+P"))
        browse_presets.setToolTip("Pick a preset by its moving preview and apply it to the selected layers")
        browse_presets.triggered.connect(lambda: self.show_presets_browser())
        animate_menu.addAction(browse_presets)
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
        self.panel_toggles: dict[QWidget, QAction] = {}
        for title, panel in (("&Layers", self.layers), ("P&roperties", self.properties)):
            toggle = QAction(title, self, checkable=True, checked=True)
            toggle.setToolTip(f"Show or hide the {title.replace('&', '')} panel on every page")
            toggle.toggled.connect(lambda on, p=panel: self.pages.set_visible(p, on))
            view_menu.addAction(toggle)
            self.panel_toggles[panel] = toggle
        self.half_action = QAction("Half-resolution playback", self, checkable=True)
        self.half_action.setToolTip("Draw the canvas at half resolution: smoother playback of heavy scenes")
        self.half_action.toggled.connect(self._set_half_resolution)
        view_menu.addAction(self.half_action)
        self.follow_action = QAction("&Follow Playhead", self, checkable=True, checked=True)
        self.follow_action.setToolTip(
            "The timeline scrolls to keep the playhead in view (also when you scrub or play)"
        )
        self.follow_action.toggled.connect(self._set_follow_playhead)
        view_menu.addAction(self.follow_action)
        self.render_ahead_action = QAction("Render Ahead", self, checkable=True, checked=True)
        self.render_ahead_action.setToolTip("Render frames ahead of the playhead in another process")
        self.render_ahead_action.toggled.connect(self._set_render_ahead)
        view_menu.addAction(self.render_ahead_action)
        view_menu.addSeparator()  # the canvas view (ADR 0023)
        for text, keys, slot, tip in (
            ("Zoom &In", ("Ctrl+=", "Ctrl++"), lambda: self.canvas.zoom(ZOOM_STEP), "Zoom in on the canvas"),
            (
                "Zoom &Out",
                ("Ctrl+-",),
                lambda: self.canvas.zoom(1 / ZOOM_STEP),
                "Zoom out (Ctrl+wheel zooms about the cursor)",
            ),
            ("&Fit", ("Ctrl+0",), self.canvas.fit, "Fit the whole video frame in the canvas"),
            (
                "Frame &Selection",
                (),
                self.canvas.frame_selection,
                "Zoom to the selected objects (F in the canvas; the whole frame when nothing is selected)",
            ),
            (
                "&Actual Size (100 %)",
                ("Ctrl+1",),
                self.canvas.actual_size,
                "One video pixel per screen pixel",
            ),
        ):
            action = QAction(text, self)
            action.setToolTip(tip)
            action.setShortcuts([QKeySequence(k) for k in keys])
            action.triggered.connect(slot)
            view_menu.addAction(action)
        fit_timeline = QAction("Fit &Timeline", self)
        fit_timeline.setShortcut(QKeySequence("Shift+F"))
        fit_timeline.setToolTip("Zoom the timeline so the whole scene fits its width")
        fit_timeline.triggered.connect(self.timeline.fit_to_width)
        view_menu.addAction(fit_timeline)
        self.snap_action = QAction("&Snap to Objects", self, checkable=True, checked=True)
        self.snap_action.setShortcut(QKeySequence("Ctrl+;"))
        self.snap_action.setToolTip(
            "Moved objects and dragged handles line up with other objects and the frame (hold Alt: off)"
        )
        self.snap_action.toggled.connect(lambda on: setattr(self.move_tool, "snapping", on))
        view_menu.addAction(self.snap_action)
        self.arrange_menu = self.menuBar().addMenu("A&rrange")  # align and distribute (ADR 0043)
        self.arrange_menu.setToolTipsVisible(True)
        for text, how, key in (
            ("Align &Left", "left", "Ctrl+Alt+Left"),
            ("Align &Centre", "centre", "Ctrl+Alt+H"),
            ("Align &Right", "right", "Ctrl+Alt+Right"),
            ("Align &Top", "top", "Ctrl+Alt+Up"),
            ("Align &Middle", "middle", "Ctrl+Alt+V"),
            ("Align &Bottom", "bottom", "Ctrl+Alt+Down"),
        ):
            action = self.arrange_menu.addAction(text, lambda h=how: self.align(h))
            action.setShortcut(QKeySequence(key))
            action.setToolTip("Line the selected objects up (one object: on the video frame)")
            if how == "right":
                self.arrange_menu.addSeparator()
        self.arrange_menu.addSeparator()
        for text, axis in (("Distribute &Horizontally", 0), ("Distribute &Vertically", 1)):
            action = self.arrange_menu.addAction(text, lambda a=axis: self.distribute(a))
            action.setToolTip("Equal gaps between three or more selected objects")
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
        help_menu.setToolTipsVisible(True)
        shortcuts_action = QAction("&Keyboard Shortcuts...", self)
        shortcuts_action.setShortcut(QKeySequence("F1"))
        shortcuts_action.setToolTip("Every shortcut and mouse gesture, searchable (ADR 0044)")
        shortcuts_action.triggered.connect(self.show_shortcuts)
        help_menu.addAction(shortcuts_action)
        plugins_action = QAction("&Plugins...", self)
        plugins_action.setToolTip("Which plugins loaded, the object types they add, and which failed")
        plugins_action.triggered.connect(self.show_plugins)
        help_menu.addAction(plugins_action)
        log_action = QAction("Open &Log Folder", self)
        log_action.setToolTip("The editor's log: what to attach when reporting a problem")
        log_action.triggered.connect(self.open_log_folder)
        help_menu.addAction(log_action)
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

    def show_shortcuts(self) -> ShortcutsDialog:
        """Help > Keyboard Shortcuts (F1): the window's shortcuts and the gestures (ADR 0044)."""
        rows = shortcuts_help.keyboard_rows(self.menuBar(), self) + list(shortcuts_help.GESTURES)
        self.shortcuts_dialog = ShortcutsDialog(rows, self)
        self.shortcuts_dialog.show()
        return self.shortcuts_dialog

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
        start = str(self.path.parent if self.path else self.default_folder())
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
        self._remember(path)
        if self._offer_recovery(self.autosave.offered(path)):  # a crash left newer work (ADR 0038)
            return
        log.info("opened %s (%d layers)", path, len(project.layers))
        self.path = path
        self.document.replace(project)

    # -- recent files, the example, the welcome (P6d.1, ADR 0044) -------------------------

    def recent_paths(self) -> list[Path]:
        """The recent files that still exist, newest first."""
        return self.prefs.recent()

    def _remember(self, path: Path) -> None:
        """A file was opened or saved: first in the recent list, in the menu and the welcome."""
        self.prefs.add_recent(path)
        self._refresh_recent()

    def _refresh_recent(self) -> None:
        recent = self.recent_paths()
        self.open_recent_menu.menuAction().setEnabled(bool(recent))
        self.welcome.set_recent(recent)

    def _fill_recent_menu(self) -> None:
        menu = self.open_recent_menu
        menu.clear()
        recent = self.recent_paths()
        for path in recent:
            action = menu.addAction(path.name, lambda p=path: self.open_recent(p))
            action.setData(str(path))
            action.setToolTip(str(path))
        if not recent:
            placeholder = menu.addAction("No recent files")
            placeholder.setEnabled(False)
            placeholder.setToolTip("Files you open or save appear here")
        menu.addSeparator()
        clear = menu.addAction("Clear Recent", self.clear_recent)
        clear.setEnabled(bool(recent))
        clear.setToolTip("Forget the list of recent files (the files stay where they are)")

    def clear_recent(self) -> None:
        self.prefs.clear_recent()
        self._refresh_recent()

    def open_recent(self, path: Path) -> None:
        """File > Open Recent, or a link on the welcome: open ``path``, if it is still there."""
        if not self.confirm_discard():
            return
        if not Path(path).is_file():
            self.statusBar().showMessage(f"{Path(path).name} no longer exists", 8000)
            self._refresh_recent()
            return
        self.load(Path(path))

    def open_example(self) -> None:
        """File > Open Example: the showcase scene as an untitled copy (Save asks where)."""
        if not self.confirm_discard():
            return
        try:
            project = Project.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))
        except Exception as exc:  # a missing or damaged example: say so
            log.exception("could not open the example %s", EXAMPLE)
            QMessageBox.critical(self, "Could not open the example", str(exc))
            return
        self.path = None
        self.document.replace(project)

    def _wire_welcome(self) -> None:
        self.welcome.newRequested.connect(self.new_project)
        self.welcome.openRequested.connect(self.open_dialog)
        self.welcome.exampleRequested.connect(self.open_example)
        self.welcome.recentRequested.connect(self.open_recent)
        self._refresh_recent()

    # -- preferences (P6d.1, ADR 0044) ----------------------------------------------------

    def _restore_preferences(self) -> None:
        """Window, view toggles and panel sizes as they were left; then follow the pages."""
        geometry, state = self.prefs.window()
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)
        for name, action, default in self._toggles():
            action.setChecked(self.prefs.toggle(name, default))
        self.pages.restore_states({name: self.prefs.page_sizes(name) for name in self.pages.pages})
        self.pages.pageChanged.connect(self._on_page_changed)

    def _toggles(self) -> tuple[tuple[str, QAction, bool], ...]:
        """The view toggles that are remembered: name in the file, action, default."""
        return (
            ("snap", self.snap_action, True),
            ("half_resolution", self.half_action, False),
            ("follow_playhead", self.follow_action, True),
            ("render_ahead", self.render_ahead_action, True),
        )

    def _on_page_changed(self, name: str) -> None:
        self.prefs.set_last_page(name)
        self._save_page_sizes()

    def _save_page_sizes(self) -> None:
        for name, sizes in self.pages.page_states().items():
            self.prefs.set_page_sizes(name, sizes)

    def _save_preferences(self) -> None:
        self.prefs.save_window(self.saveGeometry(), self.saveState())
        for name, action, _ in self._toggles():
            self.prefs.set_toggle(name, action.isChecked())
        self._save_page_sizes()

    def _restore_last_page(self) -> None:
        """The first project opened in this run brings back the page the editor was left on."""
        if self._page_restored:
            return
        self._page_restored = True
        name = self.prefs.last_page()
        if name in self.pages.pages:
            self.show_page(name)

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
        self.viewer_stack.setCurrentWidget(self.stage)  # the welcome is for an empty start
        if self.statusBar().currentMessage() == START_HINT:
            self.statusBar().clearMessage()  # done: a project is open (GP)
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
        self._restore_last_page()  # the first project of this run (ADR 0044)

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
        length_only = project.canvas.model_copy(
            update={"duration": before.canvas.duration, "grow_with_content": before.canvas.grow_with_content}
        )
        if length_only != before.canvas:
            self._scene_changed(before, project)  # size, fps, background: start again (P7.1)
        else:
            self.evaluator.apply(Edit(project, kind, layer_ids))
            if self.render_ahead is not None:
                self.render_ahead.changed(project)
            if project.canvas != before.canvas:
                self._length_changed(project)  # frames do not depend on the length (P7.1)
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

    def _scene_changed(self, before: Project, project: Project) -> None:
        """The picture's settings changed: everything drawn starts again; the view stays where it
        was when the frame's shape did not change."""
        self.evaluator = Evaluator(project, self.code.cache)
        shape = ("width_px", "height_px", "frame_height")
        same_shape = all(getattr(before.canvas, f) == getattr(project.canvas, f) for f in shape)
        view = self.canvas.view
        self.canvas.set_scene(project.canvas, self.evaluator)
        if same_shape:
            self.canvas.view = view
        if self.render_ahead is not None:
            self.render_ahead.reset(project)
        self._length_changed(project)
        self.idle_timer.start()

    def _length_changed(self, project: Project) -> None:
        """The scene's length changed: the slider and the playhead follow."""
        self.canvas.set_canvas(project.canvas)
        self.slider.setRange(0, int(project.canvas.duration * self.SLIDER_STEPS_PER_SECOND))
        if self.t > project.canvas.duration:
            self.seek(project.canvas.duration)

    def open_log_folder(self) -> None:
        folder = log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_layer_picked(self, layer_id: str, extend: bool) -> None:
        """A timeline row was clicked: select its object, as clicking it in the scene does (P7.1)."""
        if extend:
            self.selection.toggle_layer(layer_id)
        else:
            self.selection.set(layer_id)

    def _ask_shift_dialog(self) -> float | None:
        delta, ok = QInputDialog.getDouble(
            self, "Shift Timing", "Move by (seconds; negative is earlier):", 1.0, -3600.0, 3600.0, 3
        )
        return delta if ok else None

    def _selected_timing(self) -> shift_timing.Selection | None:
        """What is selected, as the timing edit wants it (None: nothing)."""
        sel = self.selection
        if sel.audio_id is not None:
            return shift_timing.Selection(audio=(sel.audio_id,))
        if sel.subtitle_id is not None:
            return shift_timing.Selection(cues=(sel.subtitle_id,))
        if sel.marker_id is not None:
            return shift_timing.Selection(markers=(sel.marker_id,))
        if sel.layer_id and sel.clip_id:
            return shift_timing.Selection(clips=((sel.layer_id, sel.clip_id),))
        if sel.layer_id and sel.key_time is not None:
            return shift_timing.Selection(keys=((sel.layer_id, sel.key_time, None),))
        if sel.layer_ids:
            return shift_timing.Selection(layers=sel.layer_ids)
        return None

    def shift_selection(self) -> None:
        """Edit > Shift Timing: move what is selected by a typed delta (U4), in one undo step."""
        if not self._has_project:
            return
        chosen = self._selected_timing()
        if chosen is None:
            self.statusBar().showMessage(
                "Shift timing: select a layer, a clip, keys, a sound, a subtitle or a marker", 6000
            )
            return
        delta = self.ask_shift()
        if delta is None or delta == 0:
            return
        before = self.project
        try:
            edit = shift_timing.shift_timing(before, chosen, delta)
        except edits.EditError as exc:
            self.statusBar().showMessage(f"Shift timing: {exc}", 10000)
            return
        if edit.project == before:
            self.statusBar().showMessage("Shift timing: nothing moved (it is at the start already)", 6000)
            return
        self.document.apply(edit, "Shift timing")
        old = set(shift_timing.timing_warnings(before))
        new = [w for w in shift_timing.timing_warnings(edit.project) if w not in old]
        if new:
            self.statusBar().showMessage(f"Shift timing: {new[0]}", 15000)

    def show_scene_settings(self) -> None:
        """Nothing selected, so Properties shows the scene; its length is ready to type."""
        if not self._has_project:
            return
        self.selection.clear()
        self.panel_toggles[self.properties].setChecked(True)
        self.properties.show_nothing()  # also when nothing was selected already
        self.properties.fields["canvas.duration"].widget.setFocus()

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
            self.layers.select(layer_id, self.selection.layer_ids)
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
            self.properties.others_selected = len(self.selection.layer_ids) - 1
            self.properties.show_layer(layer_id)
        else:
            self.properties.show_nothing()
        self.canvas.selected_layer = layer_id
        self.canvas.other_layers = tuple(i for i in self.selection.layer_ids if i != layer_id)
        self.refresh()

    def _on_pending_changed(self) -> None:
        if self.builds.busy:
            self.statusBar().showMessage("Building text...")
        elif self.statusBar().currentMessage() == "Building text...":
            self.statusBar().clearMessage()

    def _on_build_failed(self, text: str, message: str) -> None:
        self.statusBar().showMessage(f"{text}: not applied - {message}", 10000)

    def closeEvent(self, event: QCloseEvent) -> None:
        exporting = (self.export_dialog is not None and self.export_dialog.running) or self.deliver_busy()
        if exporting and self.ask_stop_export() != "stop":
            event.ignore()
            return
        if not self.confirm_discard():
            event.ignore()
            return
        self._save_preferences()
        self.autosave.timer.stop()
        self.autosave.discard()  # saved, or thrown away on purpose (ADR 0038)
        if exporting:
            if self.export_dialog is not None:
                self.export_dialog.cancel()
            self.pages.pages["deliver"].cancel_all()
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
        start = self.path.with_suffix(".py") if self.path else self.default_folder() / "scene.py"
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

    def show_presets_browser(self, layer_id: str | None = None, t: float | None = None) -> PresetsBrowser:
        """Animate > Browse Presets...: the presets as moving previews. From a timeline row
        (``layer_id`` and ``t``) it applies to that layer at that time, else to the selected
        layers at the playhead. One non-modal dialog, kept between openings."""
        if self.presets_browser is None:
            self.presets_browser = PresetsBrowser(self)
        self.presets_browser.set_target(layer_id, t)
        self.presets_browser.show()
        self.presets_browser.raise_()
        self.presets_browser.activateWindow()
        return self.presets_browser

    def apply_preset(
        self, preset: library.Preset, layer_id: str | None = None, t: float | None = None
    ) -> bool:
        """Apply ``preset`` to the layer (default: the selected one) at ``t`` (default: the playhead);
        a refusal is shown in the status bar. True when it was applied."""
        targets = [layer_id] if layer_id else list(self.selection.layer_ids)
        if self.project is None or not targets:
            self.statusBar().showMessage("Select a layer to animate first", 6000)
            return False
        at = self.t if t is None else t
        project = self.project
        try:  # every selected layer, or none of them (one undo step, ADR 0043)
            for target in targets:
                project = library.apply_preset(project, target, preset, at).project
        except edits.EditError as exc:
            name = self.project.layer(target).name or target
            self.statusBar().showMessage(f"{name}: {exc}" if len(targets) > 1 else str(exc), 10000)
            return False
        edit = edits.Edit(project, *edits.classify(self.project, project))
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
        if self.presets_browser is not None:  # open or not, it shows the new card next time
            self.presets_browser.reload()
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
        chosen_ids = set(self.selection.layer_ids)
        edit = library.apply_theme(self.project, chosen, chosen_ids if selected else None)
        self.document.apply(edit, f"Apply the {chosen.name} theme")
        where = "the selection" if selected else "the scene"
        self.statusBar().showMessage(f"{chosen.name} theme applied to {where}", 4000)

    # -- arrange (P6c.2, ADR 0043) -------------------------------------------------

    def _boxes(self) -> dict[str, tuple]:
        """The world box at the playhead of each object a move of the selection moves."""
        movers = self.move_tool._movers(self.selection.layer_ids)
        members = {i: {i} | {d.id for d in self.project.descendants(i)} for i in movers}
        boxes: dict[str, tuple] = {}
        for owner, mob in self.evaluator.frame_layers(self.t):
            family = mob.family_members_with_points()
            if not family:
                continue
            box = snap_guides.box_of(np.vstack([sub.points[:, :2] for sub in family]))
            for mover, ids in members.items():
                if owner in ids:
                    old = boxes.get(mover, box)
                    boxes[mover] = (np.minimum(old[0], box[0]), np.maximum(old[1], box[1]))
        return boxes

    def align(self, how: str) -> None:
        """Arrange > Align: the selected objects on their common box (one: on the frame)."""
        if self.project is None or not self.selection.layer_ids:
            self.statusBar().showMessage("Select the objects to align", 6000)
            return
        canvas = self.project.canvas
        half = np.array([canvas.frame_width / 2, canvas.frame_height / 2])
        self._arrange(arrange.align(self._boxes(), how, (-half, half)), f"Align {how}")

    def distribute(self, axis: int) -> None:
        """Arrange > Distribute: equal gaps between three or more selected objects."""
        boxes = self._boxes() if self.project is not None else {}
        if len(boxes) < 3:
            self.statusBar().showMessage("Select three or more objects to distribute", 6000)
            return
        self._arrange(arrange.distribute(boxes, axis), "Distribute")

    def _arrange(self, moves: dict, verb: str) -> None:
        edit = self.move_tool.move_by(moves) if moves else None
        if edit is None:
            self.statusBar().showMessage("Already lined up", 4000)
            return
        self.document.apply(edit, verb)

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
            folder = self.path.parent if self.path else self.default_folder()
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

    def deliver_busy(self) -> bool:
        """The Deliver page's queue is rendering (P6b.5)."""
        deliver = self.pages.pages.get("deliver")
        return deliver is not None and deliver.busy

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

    def default_folder(self) -> Path:
        """Where a never-saved project and its exports are suggested (GP, ``places``)."""
        return places.default_folder(self.prefs.recent())

    def save(self) -> None:
        if self.project is None:
            return
        if self.path is None:
            self.save_as()
            return
        self.path.write_text(self.project.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
        self._remember(self.path)
        self.document.undo_stack.setClean()
        self._update_title()
        log.info("saved %s", self.path)
        self.statusBar().showMessage(f"Saved {self.path}", 3000)

    def save_as(self) -> None:
        if self.project is None:
            return
        start = self.path or self.default_folder() / "untitled.json"
        name, _ = QFileDialog.getSaveFileName(self, "Save project", str(start), "*.json")
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
        self.playheadMoved.emit(self.t)

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

    def _set_follow_playhead(self, enabled: bool) -> None:
        self.timeline.follow_playhead = enabled
        if enabled and self.project is not None:
            self.timeline.set_playhead(self.t)  # back to where the video is

    def _set_half_resolution(self, enabled: bool) -> None:
        self.canvas.half_resolution = enabled
        self.refresh()


def report_exceptions(window: MainWindow):
    """An exception hook: Qt prints an exception raised in a slot or an event handler and goes
    on, so it reached no log and nobody saw it (the user's broken session). It is logged with its
    traceback and named in the status bar."""

    def hook(kind, value, tb) -> None:
        log.critical("unhandled exception", exc_info=(kind, value, tb))
        try:
            text = f"Internal error: {kind.__name__}: {value}"[:200]
            window.statusBar().showMessage(f"{text} - details in the log (Help menu)", 20000)
        except RuntimeError:  # the window is gone
            pass

    return hook


def run(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if not logging.getLogger(LOGGER_NAME).handlers:  # launched without the CLI
        setup_logging()
    app = QApplication(argv)
    app.setApplicationName("Manim Studio")
    theme.apply(app)  # the studio look (ADR 0040)
    adapter.configure(places.cache_folder())  # not under the folder it was started from (GP)
    window = MainWindow()
    sys.excepthook = report_exceptions(window)
    window.show()
    if len(argv) > 1:
        window.load(Path(argv[1]))  # offers that file's recovery copies (ADR 0038)
    else:
        window.check_recovery()
    return app.exec()
