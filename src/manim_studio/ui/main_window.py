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
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QSlider,
    QToolButton,
    QWidget,
)

from ..core.code import limits
from ..core.code.code_cache import code_hash
from ..core.code.trust import TrustStore
from ..core.code.trust import label as trust_label
from ..core.editing import edits, library, recipes, sequences, shift_timing
from ..core.editing.edits import Edit, EditKind
from ..core.engine import adapter, extract_code
from ..core.engine.evaluator import Evaluator
from ..core.engine.frame_cache import frame_index, frame_time
from ..core.engine.python_export import PythonExport, class_name, to_python
from ..core.exchange import bundle
from ..core.exchange.preset_library import PresetLibrary
from ..core.exchange.scene_import import import_scene, scene_classes
from ..core.model import parts, recovery, shape, snapshots
from ..core.model.new_project import NewProjectSettings
from ..core.model.schema import CODE_TYPES, MEDIA_TYPES, TEXT_TYPES, Project
from ..core.sound import audio, subtitles
from ..logging_config import LOGGER_NAME, get_logger, log_dir, setup_logging
from .canvas import arrange, snap_guides
from .canvas.canvas import INSERT_MODES, CanvasWidget
from .canvas.canvas_tools import MoveTool
from .canvas.stage_header import GAME_HINT, SCENE_HINT, StageHeader
from .canvas.tool_rail import RailColumn, ToolRail
from .canvas.viewport import ZOOM_STEP
from .deliver.export_dialog import ExportDialog
from .exchange.bundle_dialog import BundleProblemDialog, ExportBundleDialog
from .exchange.code_importer import CodeImporter
from .exchange.script_dialog import ScriptDialog
from .exchange.snapshots_dialog import SnapshotsDialog
from .pages import PageHost, Shared
from .pages.animate import AnimatePage
from .pages.audio import AudioPage
from .pages.code import CodePage
from .pages.compose import ComposePage
from .pages.deliver import DeliverPage
from .panels.layers_panel import LayersPanel
from .panels.presets_browser import PresetsBrowser
from .panels.properties_panel import PropertiesPanel
from .playback.audio_player import make_audio_player
from .playback.presenter import Presenter
from .playback.transport import PlayButton, TransportPill, float_at_bottom
from .services import children
from .services.code_render import make_code_renderer
from .services.preview_client import make_preview
from .services.render_ahead import RenderAhead
from .services.scene_import import ImportReport, SceneImporter
from .services.worker_process import make_worker
from .session import places
from .session.build_service import BuildService
from .session.document import Document
from .session.preferences import Preferences
from .session.selection import Selection
from .shell import shortcuts_help
from .shell.autosave import Autosave
from .shell.beat_sheet_dialog import BeatSheetDialog
from .shell.clipboard_actions import ClipboardActions
from .shell.explain_dialog import ExplainDialog
from .shell.extract_dialog import ExtractCodeDialog
from .shell.guides_dialog import GuidesDialog
from .shell.new_project_dialog import NewProjectDialog, available_templates, template_by_key
from .shell.palette import CommandPalette, collect_items
from .shell.plugins_dialog import PluginsDialog, startup_message
from .shell.recipe_dialog import RecipeParametersDialog
from .shell.ripple_dialog import RippleDialog
from .shell.shortcuts_help import ShortcutsDialog
from .shell.topbar import TopBar
from .shell.welcome import EXAMPLE, WelcomePanel
from .style import icons, motion, theme
from .style.card import Card, Chip
from .style.elided_label import ElidedLabel
from .style.render_activity import RenderActivity
from .style.saved_indicator import SavedIndicator
from .style.toast import LumenStatusBar, ToastHost
from .timeline.header import TimelineHeader
from .timeline.view import TimelineView

log = get_logger(__name__)


def _set_checked(control, on: bool) -> None:
    """Set a checkable control without it announcing the change (it mirrors another one)."""
    control.blockSignals(True)
    control.setChecked(on)
    control.blockSignals(False)


START_HINT = "Create a project (File > New) or open one (File > Open)."


class MainWindow(QMainWindow):
    SLIDER_STEPS_PER_SECOND = 1000
    playheadMoved = Signal(float)  # every seek and playback tick: pages' own views follow it
    codePresetsChanged = Signal()  # the code preset library changed (P12)
    playingChanged = Signal(bool)  # playback started or stopped (the full-screen player follows it)
    playUntilReached = Signal()  # playback stopped on ``play_until`` (a slide's stop, ADR 0087)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Manim Studio")
        self.resize(1280, 820)
        self.status = LumenStatusBar(self)  # messages also arrive as toasts (ADR 0063)
        self.setStatusBar(self.status)
        self.saved_indicator = SavedIndicator()
        self.status.addPermanentWidget(
            self.saved_indicator
        )  # at the right: a message draws from the left edge
        self.toasts = ToastHost(self)
        self.status.toasts = self.toasts
        self.prefs = Preferences()  # how the editor was left (ADR 0044)
        limits.set_unlimited(bool(self.prefs.option("code_no_time_limit", False)))  # ADR 0059
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
        self.loop_playback = False  # play again from the start at the end (the full-screen player's repeat)
        self.play_speed = 1.0  # a silent scene may play slower or faster
        # Presenting slides (ADR 0087): playing stops exactly here, or goes round (a, b) silently. Any pause
        # clears both, so they belong to one play.
        self.play_until: float | None = None
        self.play_loop: tuple[float, float] | None = None
        self._play_origin: tuple[float, float] | None = None  # (wall clock, t) at play start
        # The project's sound plays through this; its played time is the clock (ADR 0034).
        self.audio_player = make_audio_player(self)
        self._audio_signature: str | None = None  # the mix playing, None: the wall clock drives
        # Every panel edit goes through the build service (ADR 0015).
        self.builds = BuildService(self.document, make_worker(adapter.cache_dir(), self), self)
        self.builds.failed.connect(self._on_build_failed)
        # Code layers render in separate processes, only if trusted (ADR 0019).
        self.trust = TrustStore()
        self.code = make_code_renderer(adapter.cache_dir(), self.trust, self)
        # Manim scenes are imported by recording them in another process (P10.3, ADR 0053).
        self.code_presets = PresetLibrary()  # built-in, yours and downloaded presets (P12.2)
        legacy_presets = self.prefs.python_code_templates()
        if legacy_presets:
            try:
                self.code_presets.import_legacy(legacy_presets)
            except OSError as error:
                log.warning("could not migrate old code presets: %s", error)
            else:
                # Drop the old source after it is safely in the library; otherwise deleted migrated
                # presets would be re-imported every time the application starts.
                self.prefs.set_python_code_templates({})
        self.importer = CodeImporter(self)  # code into the project (P12.4)
        self.scene_importer = SceneImporter(adapter.cache_dir(), parent=self)
        self.scene_importer.finished.connect(self._on_scene_recorded)
        self.scene_importer.failed.connect(self._on_scene_failed)
        self._scene_job: dict | None = None  # what the running import is for
        self.import_report: ImportReport | None = None
        self.last_bundle: bundle.BundleReport | None = None  # the last File > Export Bundle (ADR 0077)

        self.canvas = CanvasWidget()
        self.canvas.resized.connect(self.refresh)
        self.canvas.view_changed.connect(self.refresh)
        self._canvas_view_save_timer = QTimer(self)
        self._canvas_view_save_timer.setSingleShot(True)
        self._canvas_view_save_timer.setInterval(300)
        self._canvas_view_save_timer.timeout.connect(self._save_canvas_view)
        self.canvas.view_changed.connect(self._queue_canvas_view_save)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(self._on_slider)
        self.play_button = PlayButton()
        self.play_button.setIcon(
            icons.icon("play")
        )  # (drawn by the button itself; kept as its accessible icon)
        self.play_button.clicked.connect(self.toggle_play)
        self.time_label = ElidedLabel("0.00 s", minimum=84)  # shortened, not cut, in a narrow window
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.time_label.setFont(theme.font("caption", kind="mono"))
        self.time_label.setProperty("role", "hint")

        self.stage = QWidget()  # the canvas, with the transport floating over its bottom (ADR 0063)
        layout = QHBoxLayout(self.stage)
        layout.setContentsMargins(0, 0, 0, 0)
        # the tool rail (ADR 0087): a pill in a strip beside the canvas; insert tools keep their variant
        self.stage_tools = ToolRail(self.prefs.insert_variants())
        self.stage_tools.modeRequested.connect(self._set_stage_tool)
        self.stage_tools.variantsChanged.connect(
            lambda: self.prefs.set_insert_variants(self.stage_tools.variants)
        )
        self.stage_tools.bind_shortcuts(self.canvas)  # V, H, R, L, T... while the canvas has the keyboard
        self.canvas.toolCancelled.connect(lambda: self._set_stage_tool("select"))
        self.stage_tool_buttons = self.stage_tools.buttons
        self.stage_tool_column = RailColumn(self.stage_tools)
        layout.addWidget(self.stage_tool_column)
        layout.addWidget(self.canvas, 1)
        self.transport = TransportPill(
            self.play_button,
            self.slider,
            to_start=lambda: self.seek(0.0),
            to_end=self._seek_to_end,
            set_loop=self._set_loop,
            set_speed=self.set_play_speed,
            parent=self.stage,
        )
        self._transport_placer = float_at_bottom(self.stage, self.transport)
        # What the pages show: the stage; the welcome stands in for the pages until a project is open
        # (ADR 0041, 0044, 0063).
        self.viewer = self.stage
        self.welcome = WelcomePanel()

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
        self.canvas.addRequested.connect(self._add_from_stage)
        self.layers.playhead = lambda: self.t  # new objects are placed where they are free then (GP)
        self.layers.set_recent_keys(self.prefs.insert_recent())  # the Add object card's Recent row (ADR 0087)
        self.layers.recent_save = self.prefs.set_insert_recent
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
        self.properties.edit_code = self.edit_code
        self.properties.freeze = self.freeze_layer
        self.layers.freeze = self.freeze_layer
        self.layers.extract_code = self.extract_selection_as_code  # ADR 0076
        self.layers.unpin_position = self._unpin_position  # Unpin leaves the label where it is (ADR 0075)
        self.properties.code_ends = lambda: self.evaluator.code_ends() if self.evaluator is not None else []
        self.code.statusChanged.connect(self.properties.refresh_code_status)
        self.code.rendered.connect(self._on_code_rendered)
        # The workspace pages share the views above (ADR 0041); Compose is the first.
        # The shared views sit in cards (Lumen, ADR 0063); the pages place the cards.
        self.viewer_card = Card("Stage", clip=True)
        self.viewer_card.set_body(self.viewer)
        self.scene_chip = Chip("")  # the scene's size and frame rate
        # the header strip: size, Scene | Game, readout, Follow playhead, Fit / 75 % / 100 %, full screen
        self.stage_header = StageHeader(self.canvas, self.scene_chip, self.time_label)
        self.viewer_card.add_header_content(self.stage_header)
        self.timeline_card = Card("Timeline")
        self.timeline_card.set_body(self.timeline)
        self.timeline_header = TimelineHeader(self.timeline)  # Snap, Auto-key, + Clip, zoom (ADR 0084)
        self.timeline_header.selected_layer = lambda: self.selection.layer_id
        self.timeline_card.add_header_content(self.timeline_header)
        self.layers_card = Card("Layers")
        self.layers_card.set_body(self.layers)
        self.layers_count = Chip("0")  # how many objects, after the title (ADR 0084)
        self.layers_count.setToolTip("Objects in the scene")
        self.layers.countChanged.connect(lambda n: self.layers_count.setText(str(n)))
        self.layers_card.add_title_widget(self.layers_count)
        for button in self.layers.header_buttons:  # "+" and "..." (ADR 0084)
            self.layers_card.add_action(button)
        self.layers.browse_presets = lambda: self.show_presets_browser()
        self.properties_card = Card("Properties")
        self.properties_card.set_body(self.properties)
        self.properties_card.title_label.hide()  # the tabs say it: Properties | Clip | Scene
        self.properties_card.add_header_content(self.properties.tabs)
        self.pages = PageHost(
            Shared(self.viewer_card, self.timeline_card, self.layers_card, self.properties_card), self
        )
        self.pages.set_welcome(self.welcome)
        self.topbar = TopBar(self)  # the real menu bar, with the page switcher and the daily tools
        self.setMenuBar(self.topbar)
        self.pages.attach_topbar(self.topbar)
        self.topbar.exportRequested.connect(self.show_export_dialog)
        self.topbar.paletteRequested.connect(self.show_palette)
        self.presenter = Presenter(self)  # the animation alone, full screen (P12)
        for page in (
            ComposePage,
            AnimatePage,
            CodePage,
            AudioPage,
            DeliverPage,
        ):  # Ctrl+1..5 (Shift+1..5 too)
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
        # Code dragged from the Code workspace, .py files from the desktop (P12.7).
        self.timeline.codeDropped.connect(lambda code, t: self.place_code(code, t=t, position=None))
        self.timeline.filesDropped.connect(lambda paths, t: self.import_code_files(paths, t=t, position=None))
        self.canvas.codeDropped.connect(lambda code, x, y: self.place_code(code, t=None, position=(x, y)))
        self.canvas.filesDropped.connect(
            lambda paths, x, y: self.import_code_files(paths, t=None, position=(x, y))
        )
        self.layers.codeDropped.connect(lambda code: self.place_code(code, t=None, position=None))
        self.layers.filesDropped.connect(lambda paths: self.import_code_files(paths, t=None, position=None))
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
        self.pages.show_welcome(True)
        self._wire_welcome()
        self._restore_preferences()
        app = QApplication.instance()
        if app is not None:  # coming back from another program: files may have changed (ADR 0027)
            app.applicationStateChanged.connect(self._on_application_state)
        self.statusBar().showMessage(startup_message() or self._library_message() or START_HINT)
        self.render_activity = RenderActivity(self.code, self._layer_label, self)  # ADR 0059
        self.render_activity.layerRequested.connect(self.edit_code)
        self.render_activity.textChanged.connect(self.canvas.set_busy)
        self.statusBar().addPermanentWidget(self.render_activity)

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
            (
                "Export &Bundle...",
                QKeySequence(),
                self.export_bundle,
                "Write one file with the project and every sound, image and SVG it uses, to open on another "
                "computer",
            ),
            (
                "Open B&undle...",
                QKeySequence(),
                self.open_bundle_dialog,
                "Unpack a bundle into a new folder beside it and open its project (its code is asked about "
                "before it runs)",
            ),
            (
                "Import &Script...",
                QKeySequence(),
                self.import_script,
                "Turn a written script into subtitles on the timeline, timed by reading speed",
            ),
            (
                "Snapshots...",
                QKeySequence("Ctrl+Alt+S"),
                self.show_snapshots,
                "Keep named milestones of the project (rough cut, final narration), compare them with the "
                "project now and restore one",
            ),
            (
                "Import &Manim Scene...",
                QKeySequence(),
                self.import_manim_scene,
                "Turn a Manim scene (.py) into layers and clips you can edit: its code runs once, in "
                "another process",
            ),
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
        self.undo_action, self.redo_action = undo, redo
        self.topbar.bind_history(undo, redo)
        edit_menu.addSeparator()
        self.clipboard.add_to(edit_menu)
        edit_menu.addSeparator()  # groups (U6, ADR 0050)
        self.group_action = QAction("&Group", self)
        self.group_action.setShortcut(QKeySequence("Ctrl+G"))
        self.group_action.setToolTip(
            "Put the selected objects in a group that moves, scales and fades them together"
        )
        self.group_action.triggered.connect(self.group_selection)
        self.ungroup_action = QAction("&Ungroup", self)
        self.ungroup_action.setShortcut(QKeySequence("Ctrl+Shift+G"))
        self.ungroup_action.setToolTip("Take the selected group's objects out of it, each looking as it did")
        self.ungroup_action.triggered.connect(self.ungroup_selection)
        edit_menu.addActions([self.group_action, self.ungroup_action])
        self.freeze_action = QAction("&Freeze to Shape", self)  # ADR 0052
        self.freeze_action.setToolTip(
            "Turn the selected object into plain vector data as drawn now: no code, no LaTeX"
        )
        self.freeze_action.triggered.connect(lambda: self.freeze_layer())
        edit_menu.addAction(self.freeze_action)
        self.extract_code_action = QAction("E&xtract Selection as Code", self)  # ADR 0076
        self.extract_code_action.setToolTip(
            "Replace the selected objects with one code layer that draws the same, to go on by hand in code"
        )
        self.extract_code_action.triggered.connect(lambda: self.extract_selection_as_code())
        edit_menu.addAction(self.extract_code_action)
        self.characters_action = QAction("Colour C&haracters...", self)  # ADR 0055
        self.characters_action.setToolTip(
            "Colour the letters or symbols of the selected Text, MathTex or Tex one by one"
        )
        self.characters_action.triggered.connect(
            lambda: self._has_project and self.layers.colour_characters(self.selection.layer_id)
        )
        edit_menu.addAction(self.characters_action)
        edit_menu.addSeparator()
        self.add_object_action = QAction("Add &Object...", self)  # the Add object card (ADR 0087)
        self.add_object_action.setShortcut(QKeySequence("Shift+A"))
        self.add_object_action.setToolTip("Search every object, add a recent one or browse by category")
        self.add_object_action.triggered.connect(self.show_add_object)
        edit_menu.addAction(self.add_object_action)
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
        self.timeline_header.autokey_chip.bind(self.auto_key_action)
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
        ripple_action = QAction("&Ripple Edit...", self)
        ripple_action.setToolTip(
            "Open or close time at a point and move what follows with it, or change the length of a beat"
        )
        ripple_action.setShortcut(QKeySequence("Ctrl+Alt+R"))
        ripple_action.triggered.connect(self.show_ripple)
        beats_action = QAction("&Beat Sheet...", self)
        beats_action.setToolTip("The video beat by beat between your markers: picture, appears, said")
        beats_action.setShortcut(QKeySequence("Ctrl+Alt+B"))
        beats_action.triggered.connect(self.show_beat_sheet)
        self.explain_action = QAction("E&xplain This Moment...", self)
        self.explain_action.setToolTip(
            "Which layers, clips, keys, subtitles and sounds make the frame at the playhead; step through"
        )
        self.explain_action.setShortcut(QKeySequence("Ctrl+Alt+E"))
        self.explain_action.triggered.connect(self.show_explain)
        self.explain_dialog: ExplainDialog | None = None
        edit_menu.addActions(
            [scene_settings, fit_length, shift_action, ripple_action, beats_action, self.explain_action]
        )
        edit_menu.addSeparator()  # sequences (ADR 0079)
        self.make_sequence_action = QAction("Make Se&quence from Selection...", self)
        self.make_sequence_action.setToolTip(
            "Name the selected clips and keys as one sequence: its bar on the timeline moves them together"
        )
        self.make_sequence_action.triggered.connect(self.make_sequence_from_selection)
        self.ask_sequence_name = self._ask_sequence_name  # tests and other front-ends answer here
        self.dissolve_sequence_action = QAction("&Dissolve Sequence", self)
        self.dissolve_sequence_action.setToolTip(
            "Remove the sequence of the selected clip or key; its clips and keys stay where they are"
        )
        self.dissolve_sequence_action.triggered.connect(self.dissolve_selected_sequence)
        edit_menu.addActions([self.make_sequence_action, self.dissolve_sequence_action])
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
        animate_menu.addSeparator()  # recipes (ADR 0080)
        self.make_recipe_action = QAction("Make &Recipe from Sequence...", self)
        self.make_recipe_action.setToolTip(
            "The selected clip's or key's sequence as a recipe of your own, to apply to other layers"
        )
        self.make_recipe_action.triggered.connect(self.make_recipe_from_sequence)
        animate_menu.addAction(self.make_recipe_action)
        self.ask_recipe_name = self._ask_recipe_name  # tests and other front-ends answer here
        self.apply_recipe_menu = animate_menu.addMenu("Apply Re&cipe")
        self.apply_recipe_menu.setToolTipsVisible(True)
        self._fill_recipes_menu()
        self.recipe_parameters_action = QAction("Recipe Parame&ters...", self)
        self.recipe_parameters_action.setToolTip(
            "The length and the delay between layers of the selected clip's or key's sequence"
        )
        self.recipe_parameters_action.triggered.connect(self.edit_recipe_parameters)
        animate_menu.addAction(self.recipe_parameters_action)
        self.ask_recipe_parameters = self._ask_recipe_parameters  # tests answer here
        animate_menu.addSeparator()
        steps_action = QAction("&Equation Steps...", self)  # P11 (ADR 0054)
        steps_action.setToolTip(
            "Type the steps of a derivation, one equation per line: "
            "one MathTex per step, morphing into the next"
        )
        steps_action.triggered.connect(lambda: self._has_project and self.layers.add_equation_steps())
        animate_menu.addAction(steps_action)
        self.equation_steps_action = steps_action
        self._fill_templates_menu()
        view_menu = self.menuBar().addMenu("&View")
        pages_menu = view_menu.addMenu("&Pages")  # the workspace pages (ADR 0041)
        for number, (name, page) in enumerate(self.pages.pages.items(), start=1):
            action = QAction(page.title, self)
            action.setShortcuts([QKeySequence(f"Ctrl+{number}"), QKeySequence(f"Shift+{number}")])
            action.setToolTip(page.tooltip)
            action.triggered.connect(lambda _=False, n=name: self.show_page(n))
            pages_menu.addAction(action)
        self.panel_toggles: dict[QWidget, QAction] = {}  # by the card and by the panel inside it
        for title, panel, glyph in (
            ("&Layers", self.layers_card, "sidebar"),
            ("P&roperties", self.properties_card, "sidebar-right"),
            ("&Timeline", self.timeline_card, "panel"),
        ):
            name = title.replace("&", "")
            toggle = QAction(title, self, checkable=True, checked=True)
            toggle.setToolTip(f"Show or hide the {name} panel on every page that has it")
            toggle.toggled.connect(lambda on, p=panel: self.pages.set_visible(p, on))
            view_menu.addAction(toggle)
            self.panel_toggles[panel] = toggle
            self.panel_toggles[panel.body()] = toggle
            button = QToolButton()  # the same switch on the page bar
            button.setIcon(icons.icon(glyph))
            button.setCheckable(True)
            button.setChecked(True)
            button.setAutoRaise(True)
            button.setToolTip(f"Hide or show {name}")
            button.toggled.connect(toggle.setChecked)
            toggle.toggled.connect(lambda on, b=button: _set_checked(b, on))
            self.pages.add_panel_button(panel, button)
        view_menu.addSeparator()
        self.palette_action = QAction("Command &Palette...", self)
        self.palette_action.setShortcut(QKeySequence("Ctrl+K"))
        self.palette_action.setToolTip("Search every command, layer and page by name")
        self.palette_action.triggered.connect(self.show_palette)
        view_menu.addAction(self.palette_action)
        self.fullscreen_action = QAction("&Full Screen", self)
        self.fullscreen_action.setShortcut(QKeySequence("F11"))
        self.fullscreen_action.setToolTip(
            "Show the animation alone, filling the screen (Space plays, Esc or F11 leaves)"
        )
        self.fullscreen_action.triggered.connect(self.present)
        view_menu.addAction(self.fullscreen_action)
        self.fullscreen_button = self.stage_header.fullscreen_button  # in the Stage header (ADR 0084)
        self.fullscreen_button.setIcon(icons.icon("fullscreen"))
        self.fullscreen_button.setToolTip("Full screen: the animation alone (F11)")
        self.fullscreen_button.setAccessibleName("Full screen")
        self.fullscreen_button.clicked.connect(self.present)
        view_menu.addSeparator()
        self.half_action = QAction("Half-resolution playback", self, checkable=True)
        self.half_action.setToolTip("Draw the canvas at half resolution: smoother playback of heavy scenes")
        self.half_action.toggled.connect(self._set_half_resolution)
        view_menu.addAction(self.half_action)
        self.draft_action = QAction("&Draft Preview While Editing", self, checkable=True, checked=True)
        self.draft_action.setToolTip(
            "A heavy edit (a drag, a scrub) is drawn at half size, marked DRAFT, and in full when you pause"
        )
        self.draft_action.toggled.connect(self._set_draft_preview)
        view_menu.addAction(self.draft_action)
        self.follow_action = QAction("&Follow Playhead", self, checkable=True, checked=True)
        self.follow_action.setToolTip(
            "The timeline scrolls to keep the playhead in view (also when you scrub or play)"
        )
        self.follow_action.toggled.connect(self._set_follow_playhead)
        self.stage_header.follow_chip.bind(self.follow_action)
        view_menu.addAction(self.follow_action)
        self.render_ahead_action = QAction("Render Ahead", self, checkable=True, checked=True)
        self.render_ahead_action.setToolTip("Render frames ahead of the playhead in another process")
        self.render_ahead_action.toggled.connect(self._set_render_ahead)
        view_menu.addAction(self.render_ahead_action)
        view_menu.addSeparator()
        self._add_appearance_menu(view_menu)
        view_menu.addSeparator()  # the canvas view (ADR 0023)
        self.canvas_view_actions: list[QAction] = []
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
                ("Ctrl+Shift+0",),
                self.canvas.actual_size,
                "One video pixel per screen pixel",
            ),
        ):
            action = QAction(text, self)
            action.setToolTip(tip)
            action.setShortcuts([QKeySequence(k) for k in keys])
            action.triggered.connect(slot)
            view_menu.addAction(action)
            self.canvas_view_actions.append(action)
        self.stage_view_lock_action = QAction("Lock Stage View", self, checkable=True)
        self.stage_view_lock_action.setToolTip(
            "Prevent accidental panning and zooming of the stage with the wheel, middle mouse, "
            "or view commands"
        )
        self.stage_view_lock_action.toggled.connect(self._set_stage_view_locked)
        view_menu.addAction(self.stage_view_lock_action)
        self.stage_view_lock_button = QToolButton()
        self.stage_view_lock_button.setObjectName("iconButton")
        self.stage_view_lock_button.setFixedSize(30, 30)
        self.stage_view_lock_button.setAutoRaise(True)
        self.stage_view_lock_button.setCheckable(True)
        self.stage_view_lock_button.setAccessibleName("Lock Stage View")
        self.stage_view_lock_button.toggled.connect(self.stage_view_lock_action.setChecked)
        self.stage_view_lock_action.toggled.connect(self._sync_stage_view_lock_button)
        self.viewer_card.add_action(self.stage_view_lock_button)
        self._sync_stage_view_lock_button(self.stage_view_lock_action.isChecked())
        self.edit_handles_action = QAction("Show Object Edit Handles", self, checkable=True, checked=True)
        self.edit_handles_action.setToolTip(
            "Show editable geometry, size and endpoint handles plus independent width/height resizing"
        )
        self.edit_handles_action.toggled.connect(self.canvas.set_edit_handles)
        view_menu.addAction(self.edit_handles_action)
        self.select_by_bounds_action = QAction("Select by Object Bounds", self, checkable=True)
        self.select_by_bounds_action.setToolTip(
            "Select an object by clicking anywhere inside its canvas bounds, even away from its visible lines"
        )
        self.select_by_bounds_action.toggled.connect(self.canvas.set_select_by_bounds)
        view_menu.addAction(self.select_by_bounds_action)
        fit_timeline = QAction("Fit &Timeline", self)
        fit_timeline.setShortcut(QKeySequence("Shift+F"))
        fit_timeline.setToolTip("Zoom the timeline so the whole scene fits its width")
        fit_timeline.triggered.connect(self.timeline.fit_to_width)
        view_menu.addAction(fit_timeline)
        self.timeline_snap_action = QAction("Snap &Clips and Keys", self, checkable=True, checked=True)
        self.timeline_snap_action.setToolTip(
            "Snap clip edges, keys and markers to each other and to the playhead (hold Alt: off for one drag)"
        )
        self.timeline_snap_action.toggled.connect(lambda on: setattr(self.timeline, "snap_enabled", on))
        view_menu.addAction(self.timeline_snap_action)
        self.timeline_header.snap_chip.bind(self.timeline_snap_action)
        self.snap_action = QAction("&Snap to Objects", self, checkable=True, checked=True)
        self.snap_action.setShortcut(QKeySequence("Ctrl+;"))
        self.snap_action.setToolTip(
            "Moved objects and dragged handles line up with other objects and the frame (hold Alt: off)"
        )
        self.snap_action.toggled.connect(lambda on: setattr(self.move_tool, "snapping", on))
        view_menu.addAction(self.snap_action)
        self.layout_guides_action = QAction("&Layout Guides", self, checkable=True)  # ADR 0074
        self.layout_guides_action.setToolTip(
            "Show the project's layout guides on the canvas; moved objects snap to them (hold Alt: off)"
        )
        self.layout_guides_action.setShortcut(QKeySequence("Ctrl+'"))
        self.layout_guides_action.toggled.connect(self._set_layout_guides)
        self.stage_header.bind_guides(self.layout_guides_action)
        view_menu.addAction(self.layout_guides_action)
        self.game_view_action = QAction("&Game View (through the camera)", self, checkable=True, checked=True)
        self.game_view_action.setToolTip(  # ADR 0083: off is the Scene view
            "On: the canvas shows the picture through the camera layer, as the video does. "
            "Off (Scene view): the scene unmoved, objects editable, the camera drawn as the rectangle it sees"
        )
        self.game_view_action.setShortcut(QKeySequence("G"))
        self.game_view_action.toggled.connect(self._set_game_view)
        self.stage_header.on_view_chosen = lambda scene: self.game_view_action.setChecked(not scene)
        view_menu.addAction(self.game_view_action)
        self.edit_guides_action = QAction("Layout &Guides...", self)
        self.edit_guides_action.setToolTip("Add, move and delete layout guides: margins, thirds, centre")
        self.edit_guides_action.triggered.connect(self.show_guides)
        view_menu.addAction(self.edit_guides_action)
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

    def place_code(
        self, payload: dict, t: float | None = None, position: tuple[float, float] | None = None
    ) -> None:
        """Put what was dragged from the Code workspace (``code_drag.decode``) into the project at
        time ``t`` and scene position ``position`` (None: the playhead / where it fits). P12.7."""
        self.importer.place(payload, t, position)

    def import_code_files(
        self, paths: list, t: float | None = None, position: tuple[float, float] | None = None
    ) -> None:
        """Open the import window for ``.py`` files dropped or chosen; same placement as
        ``place_code``. P12.4."""
        self.importer.import_paths(paths, t, position)

    def new_project(self, template: str = "blank") -> None:
        """File > New: the New project dialog (a template, a name and folder, the canvas, how morphs
        match). The project is written to its file at once, so it is in the recent list; a template starts
        from that example's project. ``template`` preselects a starting point."""
        if not isinstance(template, str):  # a menu action passes whether it is checked
            template = "blank"
        if not self.confirm_discard():
            return
        self._warm_defaults()  # the dialog takes a while: Manim is imported in the worker meanwhile
        settings = self.ask_new_project(self.prefs.option("morph_matching", "smart"), template)
        if settings is None:
            return
        try:
            project = self._project_for(settings)
        except Exception as exc:  # a damaged template: say so, change nothing
            log.exception("could not start from template %s", settings.template)
            QMessageBox.critical(self, "Could not create the project", str(exc))
            return
        self.prefs.set_option("morph_matching", settings.morph_matching)
        path = settings.path
        if path is not None:
            self.prefs.set_option("new_project_folder", str(path.parent))
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(project.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
            except OSError as exc:
                log.exception("could not create %s", path)
                QMessageBox.critical(self, "Could not create the project", str(exc))
                return
        self._flush_canvas_view_save()
        self.path = path
        self.document.replace(project)
        if path is not None:
            self._remember(path)
            self.document.undo_stack.setClean()
            self._update_title()
        log.info(
            "new project %s (template %s, morphs %s)",
            path or "untitled",
            settings.template,
            settings.morph_matching,
        )

    def _project_for(self, settings: NewProjectSettings) -> Project:
        """The project a ``NewProjectSettings`` describes: the blank scene with its canvas, or the template's
        project with the morph choice (its canvas is the template's own)."""
        template = template_by_key(settings.template)
        if template.source is None:
            return settings.blank_project()
        project = Project.model_validate_json(template.source.read_text(encoding="utf-8"))
        return project.model_copy(update={"morph_matching": settings.morph_matching})

    def ask_new_project(self, remembered: str, template: str = "blank") -> NewProjectSettings | None:
        """The settings for a new project, or None when cancelled (tests and other front-ends answer here
        instead of showing the dialog)."""
        folder = self.prefs.option("new_project_folder", "")
        dialog = NewProjectDialog(
            remembered,
            self,
            folder=Path(folder) if folder and Path(folder).is_dir() else self.default_folder(),
            template=template,
        )
        return dialog.settings() if dialog.exec() == QDialog.DialogCode.Accepted else None

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
        self._flush_canvas_view_save()
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
        self._flush_canvas_view_save()
        self.path = None
        self.document.replace(project)

    def _wire_welcome(self) -> None:
        self.welcome.newRequested.connect(self.new_project)
        self.welcome.openRequested.connect(self.open_dialog)
        self.welcome.exampleRequested.connect(self.open_example)
        self.welcome.recentRequested.connect(self.open_recent)
        self.welcome.templateRequested.connect(self.new_project)
        self.welcome.set_templates(
            [
                (t.key, t.name, t.description)
                for t in available_templates()
                if t.key not in ("blank", "showcase")
            ]
        )
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

    def _add_appearance_menu(self, view_menu) -> None:
        """View > Appearance (Ink, Paper, match the system) and Reduce motion (Lumen, ADR 0063)."""
        menu = view_menu.addMenu("&Appearance")
        group = QActionGroup(self)
        group.setExclusive(True)
        self.appearance_actions: dict[str, QAction] = {}
        for name, text, tip in (
            ("ink", "&Ink (dark)", "The dark interface"),
            ("paper", "&Paper (light)", "The light interface"),
            ("system", "Match the &System", "Follow the operating system's light or dark setting"),
        ):
            action = QAction(text, self, checkable=True)
            action.setToolTip(tip)
            action.setActionGroup(group)
            action.triggered.connect(lambda _=False, n=name: self.set_appearance(n))
            menu.addAction(action)
            self.appearance_actions[name] = action
        self.appearance_actions[self.prefs.appearance()].setChecked(True)
        self.reduce_motion_action = QAction("Reduce &motion", self, checkable=True)
        self.reduce_motion_action.setToolTip("Turn the interface's small animations off")
        self.reduce_motion_action.setChecked(self.prefs.toggle("reduce_motion", False))
        self.reduce_motion_action.toggled.connect(self._set_reduce_motion)
        menu.addAction(self.reduce_motion_action)
        hints = QGuiApplication.styleHints()
        if hints is not None:  # a method, not a lambda: a closure here would keep this window alive for ever
            hints.colorSchemeChanged.connect(self._on_color_scheme)

    def set_appearance(self, name: str) -> None:
        """Ink, Paper or the system's scheme: remembered, and applied now."""
        self.prefs.set_appearance(name)
        self.appearance_actions[name].setChecked(True)
        theme.set_theme(QApplication.instance(), theme.resolve_appearance(name))

    def _on_color_scheme(self, _scheme=None) -> None:
        self._follow_system()

    def _follow_system(self) -> None:
        if self.prefs.appearance() == "system":
            theme.set_theme(QApplication.instance(), theme.resolve_appearance("system"))

    def _set_reduce_motion(self, on: bool) -> None:
        motion.set_reduced(on)
        self.prefs.set_toggle("reduce_motion", on)

    def _set_stage_view_locked(self, on: bool) -> None:
        self.canvas.set_view_locked(on)
        for action in self.canvas_view_actions:
            action.setEnabled(not on)
        self.prefs.set_toggle("stage_view_locked", on)

    def _set_game_view(self, game: bool) -> None:
        """Game or Scene view (ADR 0083): the canvas, the Stage header's segmented control (which explains
        itself in its tooltip) and a one-line hint in the status bar - never prose over the picture."""
        self.canvas.set_scene_view(not game)
        self.stage_header.set_scene_view(not game)
        self.stage_header.sync_notice()
        if self._has_project:
            self.statusBar().showMessage(GAME_HINT if game else SCENE_HINT, 8000)

    def show_add_object(self) -> None:
        """Edit > Add Object (Shift+A): the Add object card, on the Compose page's Layers panel."""
        if not self._has_project:
            return
        if not self.layers.isVisible():
            self.show_page("compose")
        button = self.layers.add_button
        shown = button.isVisible()
        self.layers.show_add_popover(button if shown else self.stage, below=not shown)

    def _set_stage_tool(self, mode: str) -> None:
        self.canvas.set_interaction_mode(mode)
        self.stage_tools.set_mode(mode)

    def _add_from_stage(self, mode: str, x: float, y: float) -> None:
        """An insert tool was clicked on the Stage: add the variant it holds there (ADR 0087)."""
        if mode not in INSERT_MODES:
            return
        self.layers.add_object(self.stage_tools.variant(mode), position=(x, y))
        self._set_stage_tool("select")

    def _sync_stage_view_lock_button(self, locked: bool) -> None:
        self.stage_view_lock_button.setChecked(locked)
        self.stage_view_lock_button.setIcon(
            icons.icon("lock" if locked else "lock-open", "accent" if locked else "muted")
        )
        tip = (
            "Stage view locked. Click to unlock."
            if locked
            else "Lock the stage view against accidental panning and zooming"
        )
        self.stage_view_lock_button.setToolTip(tip)

    def _toggles(self) -> tuple[tuple[str, QAction, bool], ...]:
        """The view toggles that are remembered: name in the file, action, default."""
        return (
            ("snap", self.snap_action, True),
            ("timeline_snap", self.timeline_snap_action, True),
            ("layout_guides", self.layout_guides_action, False),
            ("game_view", self.game_view_action, True),
            ("stage_view_locked", self.stage_view_lock_action, False),
            ("object_edit_handles", self.edit_handles_action, True),
            ("select_by_bounds", self.select_by_bounds_action, True),
            ("half_resolution", self.half_action, False),
            ("draft_preview", self.draft_action, True),
            ("follow_playhead", self.follow_action, True),
            ("render_ahead", self.render_ahead_action, True),
            ("panel_layers", self.panel_toggles[self.layers_card], True),
            ("panel_properties", self.panel_toggles[self.properties_card], True),
            ("panel_timeline", self.panel_toggles[self.timeline_card], True),
        )

    def present(self) -> None:
        """View > Full Screen (F11): the animation alone, filling the screen; again to leave."""
        if self.presenter.active:
            self.presenter.finish()
        else:
            self._flush_canvas_view_save()
            if not self.presenter.start():
                self.statusBar().showMessage(
                    "Open or create a project to see its animation full screen", 5000
                )

    def _on_page_changed(self, name: str) -> None:
        self.prefs.set_last_page(name)
        self._save_page_sizes()

    def _save_page_sizes(self) -> None:
        for name, sizes in self.pages.page_states().items():
            self.prefs.set_page_sizes(name, sizes)

    def _save_preferences(self) -> None:
        self._flush_canvas_view_save()
        self.prefs.save_window(self.saveGeometry(), self.saveState())
        for name, action, _ in self._toggles():
            self.prefs.set_toggle(name, action.isChecked())
        self._save_page_sizes()

    def _queue_canvas_view_save(self) -> None:
        if self.path is None or not self._has_project:
            return
        if getattr(self, "presenter", None) is not None and self.presenter.active:
            return
        self._canvas_view_save_timer.start()

    def _save_canvas_view(self) -> None:
        if self.path is None or not self._has_project:
            return
        if getattr(self, "presenter", None) is not None and self.presenter.active:
            return
        self.prefs.set_canvas_view(self.path, self.canvas.view)

    def _flush_canvas_view_save(self) -> None:
        self._canvas_view_save_timer.stop()
        self._save_canvas_view()

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
        self._flush_canvas_view_save()
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
        self.pages.show_welcome(False)  # the welcome is for an empty start
        self._update_scene_chip(project)
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
        if self.path is not None:
            saved_view = self.prefs.canvas_view(self.path)
            if saved_view is not None:
                self.canvas.set_view(saved_view)
        # What an earlier project left is garbage now; frozen, its reference cycles would never be collected
        # (3 MB for every project opened), so everything is thawed and collected before it is frozen again.
        gc.unfreeze()
        gc.collect()
        gc.freeze()  # measured: removes the gen-2 GC hitches during playback
        self.idle_timer.start()
        self.code.sync(project)
        self._warm_defaults()
        self._warm_subtitles(project)
        self._media_errors = {}
        self.report_media()
        untrusted = self.trust.untrusted(project)
        if untrusted:  # opening a file must never run its code silently (ADR 0019)
            names = [trust_label(project, i) for i in untrusted]  # helpers too (ADR 0058)
            if self.ask_trust(names) == "run":
                self.code.trust_layers(project, untrusted)
                self.reload_media()  # Python objects drawn as placeholders are built now (ADR 0051)
            else:
                self.statusBar().showMessage(
                    "Code layers and Python objects were not run: they show a placeholder. "
                    "Apply their code on the Code page to run it.",
                    15000,
                )
        self._restore_last_page()  # the first project of this run (ADR 0044)

    def _layer_label(self, layer_id: str) -> str:
        layer = next((layer for layer in self.document.project.layers if layer.id == layer_id), None)
        return layer.label if layer is not None else layer_id

    def edit_code(self, layer_id: str) -> None:
        """Show a layer's code on the Code page (a Python object's Edit code, ADR 0051)."""
        self.selection.select_layer(layer_id)
        self.show_page("code")

    def ask_trust(self, names: list[str]) -> str:
        """``"run"`` or ``"skip"``: may this project's code run on this computer?"""
        answer = QMessageBox.question(
            self,
            "Run code from this project?",
            "This project contains Python code that will run on your computer:\n\n"
            + "\n".join(f"  - {name}" for name in names)
            + "\n\nRunning code is not sandboxed: it can read and write your files and use the network, "
            "like any program you start. Only run it if you trust where the project came from. Run it?",
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
        self._update_scene_chip(project)
        shape = ("width_px", "height_px", "frame_height")
        same_shape = all(getattr(before.canvas, f) == getattr(project.canvas, f) for f in shape)
        view = self.canvas.view
        self.canvas.set_scene(project.canvas, self.evaluator)
        if same_shape:
            self.canvas.view = view
        else:
            self._queue_canvas_view_save()
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
        if self.timeline.picked_count() > 1:  # the timeline's multi-selection (U4b)
            return self.timeline.timing_selection()
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

    def group_selection(self) -> None:
        """Edit > Group (U6, ADR 0050): the selected objects in a new group, which is selected."""
        if not self._has_project:
            return
        chosen = [i for i in self.selection.layer_ids if i]
        if not chosen:
            self.statusBar().showMessage("Group: select the objects to group", 6000)
            return
        try:
            edit = edits.group_layers(self.project, chosen)
        except edits.EditError as exc:
            self.statusBar().showMessage(f"Group: {exc}", 10000)
            return
        (group_id,) = {x.id for x in edit.project.layers} - {x.id for x in self.project.layers}
        self.document.apply(edit, "Group")
        self.selection.select_layer(group_id)

    def _unpin_position(self, layer_id: str) -> tuple[float, float] | None:
        """Where an unpinned label stays: where it is drawn at the playhead (ADR 0075)."""
        if self.evaluator is None or layer_id not in {x.id for x in self.project.layers}:
            return None
        return self.evaluator.unpinned_position(self.project.layer(layer_id), self.t)

    def freeze_layer(self, layer_id: str | None = None) -> bool:
        """Edit > Freeze to Shape (ADR 0052): the object (default: the selected one) becomes plain
        vector data as it is drawn now, one undo step. Says why in the status bar when it cannot."""
        if not self._has_project or self.evaluator is None:
            return False
        layer_id = layer_id or self.selection.layer_id
        if not layer_id:
            self.statusBar().showMessage("Freeze to Shape: select an object", 6000)
            return False
        layer = self.project.layer(layer_id)
        try:
            problem = shape.freeze_problem(self.project, layer_id)
            if problem is not None:
                raise edits.EditError(problem)
            drawn = self.evaluator.build_errors().get(layer_id)  # what this editor shows
            if drawn is not None:
                raise edits.EditError(
                    f"it is drawn as a placeholder ({drawn}): only what is drawn can be frozen"
                )
            signature = self.evaluator.signature_of(layer.spec)  # a Python object's helpers (ADR 0058)
            edit = edits.freeze_layer(self.project, layer_id, adapter.freeze_data(layer.spec, signature))
        except (edits.EditError, ValueError) as exc:
            reason = str(exc).removeprefix(f"cannot freeze {layer_id!r}: ")
            self.statusBar().showMessage(f"Freeze to Shape: {layer.label}: {reason}", 15000)
            return False
        self.document.apply(edit, "Freeze to shape")
        self.statusBar().showMessage(
            f"{layer.label} is a shape now: plain vector data (undo turns it back)", 8000
        )
        return True

    def extract_selection_as_code(self, layer_ids: list[str] | None = None) -> bool:
        """Edit > Extract Selection as Code (ADR 0076): the selected objects become one code layer drawing
        the same, one undo step; it is selected and shown on the Code page. Says why when it cannot."""
        if not self._has_project:
            return False
        chosen = [i for i in (layer_ids if layer_ids is not None else self.selection.layer_ids) if i]
        if not chosen:
            self.statusBar().showMessage("Extract as Code: select the objects to turn into code", 6000)
            return False
        try:
            result = extract_code.extract_as_code(self.project, chosen)
        except edits.EditError as exc:
            self.statusBar().showMessage(f"Extract as Code: {exc}", 20000)
            return False
        if not self.ask_extract(result.code, len(chosen)):  # the code is shown first (ADR 0084)
            return False
        # The editor wrote this code from the user's own layers, so it may run as they did - unless it
        # embeds a Python object or helper that is not trusted yet: then it is asked about as usual.
        if all(self.trust.is_trusted(code) for code in result.embedded):
            self.trust.trust([result.code])
        self.document.apply(result.edit, "Extract as code")
        self.edit_code(result.layer_id)
        self.statusBar().showMessage(
            f"{len(chosen)} layer(s) are one code layer now: edit its scene here (undo brings them back)",
            8000,
        )
        return True

    def ask_extract(self, code: str, layers: int) -> bool:
        """Show the code the layers would become; True when the user chose Extract."""
        return ExtractCodeDialog(code, layers, parent=self).exec() == QDialog.DialogCode.Accepted

    def ungroup_selection(self) -> None:
        """Edit > Ungroup: the selected group's objects (or the group of a selected object) out of it."""
        if not self._has_project or not self.selection.layer_id:
            return
        layer = self.project.layer(self.selection.layer_id)
        group = layer if layer.is_group else None
        if group is None and layer.parent_id is not None and self.project.layer(layer.parent_id).is_group:
            group = self.project.layer(layer.parent_id)
        if group is None:
            self.statusBar().showMessage("Ungroup: select a group", 6000)
            return
        try:
            edit = edits.ungroup(self.project, group.id)
        except edits.EditError as exc:
            self.statusBar().showMessage(f"Ungroup: {exc}", 10000)
            return
        kids = [x.id for x in self.project.children(group.id)]
        self.document.apply(edit, "Ungroup")
        self.selection.set_layers(kids)

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

    def _selected_members(self) -> sequences.Members:
        """The selected clips and keys (the timeline's picks, or the one selected), as sequence members."""
        chosen = self._selected_timing()
        if chosen is None:
            return sequences.Members()
        try:
            return sequences.members_from_selection(self.project, chosen)
        except edits.EditError:
            return sequences.Members()

    def make_sequence_from_selection(self) -> None:
        """Edit > Make Sequence from Selection... (ADR 0079): the selected clips and keys, named, as one
        sequence the timeline moves together. One undo step."""
        if not self._has_project:
            return
        members = self._selected_members()
        if members.empty:
            self.statusBar().showMessage("Make sequence: select the clips and keys to put in it", 6000)
            return
        name = self.ask_sequence_name(sequences.new_sequence_name(self.project))
        if name is None:
            return
        try:
            edit = sequences.make_sequence(self.project, name, members)
        except edits.EditError as exc:
            self.statusBar().showMessage(f"Make sequence: {exc}", 10000)
            return
        self.document.apply(edit, "Make sequence")

    def _ask_sequence_name(self, suggested: str) -> str | None:
        text, ok = QInputDialog.getText(self, "Make Sequence", "Name of the sequence:", text=suggested)
        return text if ok else None

    def selected_sequence(self):
        """The sequence holding a selected clip or key, if any (ADR 0079)."""
        if not self._has_project:
            return None
        project = self.project
        members = self._selected_members()
        for layer_id, clip_id in members.clips:
            if (found := sequences.sequence_of_clip(project, layer_id, clip_id)) is not None:
                return found
        for layer_id, track, t in members.keys:
            if (found := sequences.sequence_of_key(project, layer_id, track, t)) is not None:
                return found
        return None

    def dissolve_selected_sequence(self) -> None:
        """Edit > Dissolve Sequence (ADR 0079): the selected clip's or key's sequence goes; they stay."""
        found = self.selected_sequence()
        if found is None:
            if self._has_project:
                self.statusBar().showMessage("Dissolve sequence: select a clip or key of a sequence", 6000)
            return
        self.document.apply(sequences.dissolve_sequence(self.project, found.id), "Dissolve sequence")
        self.statusBar().showMessage(f"Dissolved {found.name!r}: its clips and keys stay", 6000)

    def show_ripple(self) -> None:
        """Edit > Ripple Edit...: time opened or closed at a point, or a beat given a length (ADR 0071)."""
        if not self._has_project:
            return
        RippleDialog(lambda: self.document.project, self.t, self.document.apply, self).exec()

    def show_beat_sheet(self) -> None:
        """Edit > Beat Sheet...: the video as beats between markers (ADR 0073)."""
        if not self._has_project:
            return
        title = self.path.stem if self.path is not None else "Beat sheet"
        BeatSheetDialog(lambda: self.document.project, self.seek, title, self).exec()

    def show_explain(self) -> ExplainDialog | None:
        """Edit > Explain This Moment...: what makes the frame at the playhead, in a window (ADR 0082)."""
        if not self._has_project:
            return None
        if self.explain_dialog is None:
            self.explain_dialog = ExplainDialog(
                lambda: self.document.project, lambda: self.t, self.seek, self._select_explained, self
            )
            self.playheadMoved.connect(self.explain_dialog.follow)
            self.document.changed.connect(lambda *_: self.explain_dialog.follow(self.t))
        self.explain_dialog.refresh(self.t)
        self.explain_dialog.show()
        self.explain_dialog.raise_()
        return self.explain_dialog

    def _select_explained(self, layer_id: str, clip_id: str | None = None) -> None:
        """An item of the explanation was clicked: its layer (and clip) is selected to inspect or change."""
        if clip_id:
            self.selection.set(layer_id, clip_id)
        else:
            self.selection.select_layer(layer_id)

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
        self.timeline.set_selected_layers(self.selection.layer_ids)  # their bands drag them (U4b)
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
        self.presenter.finish()  # the canvas goes back into the editor first
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
        children.ask_all_to_stop()  # every helper at once: the stops below then wait for them together
        if exporting:
            if self.export_dialog is not None:
                self.export_dialog.cancel()
            self.pages.pages["deliver"].cancel_all()
        if self.export_dialog is not None:
            self.export_dialog.close()
        self.builds.client.stop()
        self.code.stop()
        self.pages.pages["code"].helper_actions.checker.stop()  # a helper being test-imported (ADR 0058)
        self.scene_importer.stop()
        self.pages.pages["audio"].narration.client.stop()  # voices being spoken (ADR 0060)
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

    def _warm_defaults(self) -> None:
        """Build the library's text objects ahead of time, so adding one never waits. This starts the build
        worker, which is why it waits for a project: the welcome page runs no helper process."""
        self.builds.prewarm([adapter.default_spec(t) for t in sorted(TEXT_TYPES)])

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

    # -- recipes (ADR 0080) --------------------------------------------------------------------

    def _fill_recipes_menu(self) -> None:
        """Animate > Apply Recipe: each recipe of the library, applied to the selected layers."""
        menu = self.apply_recipe_menu
        menu.clear()
        for recipe in self.library.recipes:
            action = menu.addAction(recipe.name, lambda r=recipe: self.apply_recipe(r))
            action.setToolTip(recipe.description)
        menu.setEnabled(bool(menu.actions()))

    def make_recipe_from_sequence(self) -> None:
        """Animate > Make Recipe from Sequence...: the selected clip's or key's sequence, saved with the
        user's presets as a recipe."""
        found = self.selected_sequence()
        if found is None:
            if self._has_project:
                self.statusBar().showMessage("Make recipe: select a clip or key of a sequence", 6000)
            return
        name = self.ask_recipe_name(found.name)
        if not name:
            return
        try:
            recipe = recipes.make_recipe(self.project, found.id, name)
        except edits.EditError as exc:
            self.statusBar().showMessage(f"Make recipe: {exc}", 10000)
            return
        path = library.save_item(recipe)
        self.library.add(recipe)
        self._fill_recipes_menu()
        self.statusBar().showMessage(f"Saved the recipe {recipe.name} ({path.name})", 6000)

    def _ask_recipe_name(self, suggested: str) -> str | None:
        text, ok = QInputDialog.getText(self, "Make Recipe", "Name of the recipe:", text=suggested)
        return text.strip() if ok and text.strip() else None

    def apply_recipe(self, recipe: library.Recipe) -> bool:
        """Animate > Apply Recipe: ``recipe`` on the selected layers (in the order they were picked) at the
        playhead, as a new sequence; one undo step. A refusal is shown in the status bar."""
        targets = list(self.selection.layer_ids)
        if self.project is None or not targets:
            self.statusBar().showMessage("Select the layers to animate first", 6000)
            return False
        try:
            edit = recipes.apply_recipe(self.project, recipe, targets, self.t)
        except edits.EditError as exc:
            self.statusBar().showMessage(f"Apply recipe: {exc}", 10000)
            return False
        self.document.apply(edit, f"Apply recipe {recipe.name}")
        self.statusBar().showMessage(f"{recipe.name} at {self.t:.2f} s", 4000)
        return True

    def edit_recipe_parameters(self) -> None:
        """Animate > Recipe Parameters...: the selected sequence's length and delay between layers."""
        found = self.selected_sequence()
        if found is None:
            if self._has_project:
                self.statusBar().showMessage("Recipe parameters: select a clip or key of a sequence", 6000)
            return
        length, stagger = recipes.recipe_parameters(self.project, found.id)
        layers = len(sequences.member_layers(self.project, found))
        answer = self.ask_recipe_parameters(found.name, length, stagger, layers)
        if answer is None:
            return
        new_length, new_stagger = answer
        try:
            edit = sequences.reparameterise_sequence(self.project, found.id, new_length, new_stagger)
        except edits.EditError as exc:
            self.statusBar().showMessage(f"Recipe parameters: {exc}", 10000)
            return
        if edit.project is not self.project:
            self.document.apply(edit, "Recipe parameters")

    def _ask_recipe_parameters(
        self, name: str, length: float, stagger: float | None, layers: int
    ) -> tuple[float, float | None] | None:
        dialog = RecipeParametersDialog(name, length, stagger, layers, self)
        return dialog.answer() if dialog.exec() == QDialog.DialogCode.Accepted else None

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

    # -- importing Manim scenes (P10.3, ADR 0053) ----------------------------------------------

    def import_manim_scene(self) -> None:
        """File > Import Manim Scene...: a scene file's objects as layers and clips on top of the
        others, from 0 s (the scene's own timeline), one undo step; or one code layer when the scene
        cannot be reproduced exactly. The file's code runs once, in another process, after asking."""
        if self.project is None:
            self.statusBar().showMessage("Create or open a project first.", 5000)
            return
        if self.scene_importer.busy:
            self.statusBar().showMessage("A scene is being imported already", 5000)
            return
        self.scene_importer.warm()  # Manim is imported while the file is chosen
        name = self.ask_scene_path()
        if not name:
            return
        path = Path(name)
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.statusBar().showMessage(f"Cannot read {path.name}: {exc}", 10000)
            return
        scenes = scene_classes(source)
        if not scenes:
            self.statusBar().showMessage(f"{path.name} defines no Scene class to import", 10000)
            return
        scene = scenes[0] if len(scenes) == 1 else self.ask_scene_name(path.name, scenes)
        if not scene:
            return
        if not self.trust.is_trusted(source):  # running a file's code is asked once (ADR 0019)
            if self.ask_run_scene(path.name) != "run":
                self.statusBar().showMessage(f"Not imported: {path.name} was not run", 6000)
                return
            self.trust.trust([source])
        self._start_scene_import(path, scene, source, path.name, prelude=False, replace=None, offset=0.0)

    def convert_code_layer(self, layer_id: str) -> bool:
        """The Code page's Convert to Layers: a code layer's scene as layers and clips in its place,
        from its start, one undo step; refused (with the report) when it must stay code."""
        if self.project is None or self.scene_importer.busy:
            return False
        layer = self.project.layer(layer_id)
        if layer.spec is None or layer.spec.type not in CODE_TYPES:
            self.statusBar().showMessage("Convert to Layers: choose a code layer", 6000)
            return False
        code = str(layer.spec.params.get("code", ""))
        scenes = scene_classes(code)
        if len(scenes) != 1:
            self.statusBar().showMessage(
                f"Convert to Layers: {layer.label} needs exactly one Scene class", 8000
            )
            return False
        if not self.trust.is_trusted(code):
            if self.ask_run_scene(layer.label) != "run":
                return False
            self.trust.trust([code])
        folder = adapter.cache_dir() / "imports"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{code_hash(code)[:16]}.py"
        path.write_text(code, encoding="utf-8")
        start = self.evaluator.lifetime(layer)[0] if self.evaluator is not None else 0.0
        self._start_scene_import(
            path, scenes[0], code, layer.label, prelude=True, replace=layer_id, offset=start
        )
        return True

    def _start_scene_import(
        self,
        path: Path,
        scene: str,
        source: str,
        label: str,
        *,
        prelude: bool,
        replace: str | None,
        offset: float,
    ) -> None:
        self._scene_job = {"source": source, "label": label, "replace": replace, "offset": offset}
        self.statusBar().showMessage(f"Importing {label}: playing {scene} once...")
        self.scene_importer.start(path, scene, prelude)

    def _on_scene_recorded(self, recording: dict) -> None:
        job, self._scene_job = self._scene_job, None
        if job is None or self.project is None:
            return
        verb = "Convert to Layers" if job["replace"] else "Import Manim Scene"
        try:
            result = import_scene(recording, job["source"])
        except ValueError as exc:  # it cannot even be one code layer
            self.statusBar().showMessage(f"{verb}: {exc}", 15000)
            return
        if job["replace"] is not None:
            if not result.converted:
                self.show_import_report(f"{job['label']} stays a code layer", result.report)
                self.statusBar().showMessage(
                    f"{verb}: {job['label']} stays a code layer - {result.reasons[0]}", 15000
                )
                return
            if job["replace"] not in {x.id for x in self.project.layers}:
                self.statusBar().showMessage(f"{verb}: the code layer was deleted meanwhile", 8000)
                return
        else:  # a scene kept as code: the user agreed to run it
            self.trust.trust(
                [str(x.spec.params["code"]) for x in result.project.layers if x.spec.type in CODE_TYPES]
            )
        try:
            edit, ids = edits.insert_scene(self.project, result.project, job["offset"], job["replace"])
        except (edits.EditError, ValueError) as exc:
            self.statusBar().showMessage(f"{verb}: {exc}", 15000)
            return
        self.document.apply(edit, "Convert to layers" if job["replace"] else "Import Manim scene")
        self.selection.set_layers(ids)
        lines = list(result.report)
        if result.project.subtitles and self.project.subtitle_style.burn_in:
            lines.append(
                "This project burns subtitles into the video; Manim only wrote them as an .srt file."
            )
        if abs(result.project.canvas.frame_height - self.project.canvas.frame_height) > 1e-9:
            lines.append(
                f"The scene's frame is {result.project.canvas.frame_height:g} units high, this project's "
                f"{self.project.canvas.frame_height:g}: positions are kept in units."
            )
        self.show_import_report(recording.get("scene", "Scene"), lines)
        self.statusBar().showMessage(result.report[0], 15000)

    def _on_scene_failed(self, message: str) -> None:
        job, self._scene_job = self._scene_job, None
        verb = "Convert to Layers" if job and job["replace"] else "Import Manim Scene"
        self.statusBar().showMessage(f"{verb}: {message}", 20000)

    def ask_scene_path(self) -> str:
        name, _ = QFileDialog.getOpenFileName(
            self, "Import Manim Scene", str(self.default_folder()), "Python (*.py);;All files (*)"
        )
        return name

    def ask_scene_name(self, file: str, scenes: list[str]) -> str | None:
        name, ok = QInputDialog.getItem(
            self, "Import Manim Scene", f"{file} has several scenes. Import:", scenes, 0, False
        )
        return name if ok else None

    def ask_run_scene(self, name: str) -> str:
        """``"run"`` or ``"skip"``: may this scene's Python run on this computer (ADR 0019)?"""
        answer = QMessageBox.question(
            self,
            "Run this scene's code?",
            f"Importing runs the Python in {name} on your computer, once, in another process.\n\n"
            "Only run it if you trust where it came from. Run it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return "run" if answer == QMessageBox.StandardButton.Yes else "skip"

    def show_import_report(self, title: str, lines: list[str]) -> ImportReport:
        """What the import made of the scene, in a window that stays open beside the editor."""
        if self.import_report is not None:
            self.import_report.close()
        self.import_report = ImportReport(f"Imported: {title}", lines, self)
        self.import_report.show()
        return self.import_report

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

    def import_script(self) -> None:
        """File > Import Script...: a written script becomes subtitles (ADR 0069), one undo step."""
        if self.project is None:
            self.statusBar().showMessage("Create or open a project first.", 5000)
            return
        ScriptDialog(lambda: self.document.project, self.document.apply, self).exec()

    def show_snapshots(self) -> None:
        """File > Snapshots...: named milestones kept beside the project file (ADR 0068)."""
        if self.project is None:
            self.statusBar().showMessage("Create or open a project first.", 5000)
            return
        if self.path is None:
            self.statusBar().showMessage("Save the project first: snapshots are kept beside its file.", 6000)
            return
        dialog = SnapshotsDialog(self.path, lambda: self.document.project, self.restore_snapshot, self)
        dialog.exec()

    def export_bundle(self) -> None:
        """File > Export Bundle...: the project and every file it uses in one ``.msbundle`` (ADR 0077)."""
        if self.project is None:
            self.statusBar().showMessage("Create or open a project first.", 5000)
            return
        project = self.document.project
        references = bundle.external_references(project)
        missing = bundle.missing_paths(references, self.path)
        count = len(snapshots.listing(self.path)) if self.path is not None else 0
        include = self.ask_bundle_options(references, missing, count)
        if include is None:
            return
        name = self.path.stem if self.path else "untitled"
        folder = self.path.parent if self.path else self.default_folder()
        target = self.ask_bundle_save_path(folder / f"{name}{bundle.EXTENSION}")
        if not target:
            return
        target = Path(target)
        if not target.name.lower().endswith((bundle.EXTENSION, ".zip")):
            target = target.with_name(target.name + bundle.EXTENSION)
        try:
            report = bundle.build_bundle(
                project, target, name=name, project_path=self.path, include_snapshots=include
            )
        except (bundle.BundleError, OSError) as error:
            log.exception("could not write the bundle %s", target)
            QMessageBox.critical(self, "Could not export the bundle", str(error))
            return
        carried = sum(1 for entry in report.files if not entry["missing"])
        log.info("bundle %s (%d files, %d missing)", target, carried, len(report.missing))
        self.last_bundle = report
        self.statusBar().showMessage(f"Wrote {target.name}: the project and {carried} files", 10000)
        if report.missing:
            QMessageBox.warning(
                self,
                "Some files were not found",
                "These files were not found and are not in the bundle; they show a placeholder where it is "
                "opened:\n\n" + "\n".join(f"  - {ref.label}: {ref.path}" for ref in report.missing[:12]),
            )

    def ask_bundle_options(self, references: list, missing: set[str], snapshot_count: int) -> bool | None:
        """Whether to include the snapshots, or None when cancelled (tests answer here, not the dialog)."""
        dialog = ExportBundleDialog(references, missing, snapshot_count, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.include_snapshots.isChecked()

    def ask_bundle_save_path(self, start: Path) -> str:
        name, _ = QFileDialog.getSaveFileName(
            self, "Export Bundle", str(start), f"Manim Studio bundle (*{bundle.EXTENSION})"
        )
        return name

    def ask_bundle_open_path(self, start: Path) -> str:
        name, _ = QFileDialog.getOpenFileName(
            self,
            "Open Bundle",
            str(start),
            f"Manim Studio bundle (*{bundle.EXTENSION} *.zip);;All files (*)",
        )
        return name

    def show_bundle_problem(self, title: str, message: str) -> None:
        """A bundle that failed its check: the failure as a bad chip, in the dialog shape (ADR 0084)."""
        BundleProblemDialog(title, message, self).exec()

    def open_bundle_dialog(self) -> None:
        """File > Open Bundle...: unpack into a new folder beside the bundle and open it (ADR 0077). Its code
        is not trusted by being in a bundle: ``_on_reset`` asks about it as for any file."""
        if not self.confirm_discard():
            return
        name = self.ask_bundle_open_path(self.path.parent if self.path else self.default_folder())
        if not name:
            return
        try:
            opened = bundle.open_bundle(Path(name))
        except (bundle.BundleError, OSError) as error:
            log.exception("could not open the bundle %s", name)
            self.show_bundle_problem("Could not open the bundle", str(error))
            return
        log.info("unpacked %s into %s", name, opened.folder)
        self.load(opened.project_path)
        text = f"Unpacked {Path(name).name} into {opened.folder}"
        if opened.missing:
            text += f" - {len(opened.missing)} files were missing when it was made"
        self.statusBar().showMessage(text, 15000)

    def restore_snapshot(self, restored: Project, text: str) -> None:
        """One undo step that replaces the project with a snapshot's."""
        self.document.apply(edits.restore_project(self.document.project, restored), text)

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
        self.saved_indicator.set_state(name, not dirty)

    def default_folder(self) -> Path:
        """Where a never-saved project and its exports are suggested (GP, ``places``)."""
        return places.default_folder(self.prefs.recent())

    def save(self) -> None:
        if self.project is None:
            return
        if self.path is None:
            self.save_as()
            return
        self._flush_canvas_view_save()
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
            self._flush_canvas_view_save()
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
        self.transport.set_time(self.t, self.project.canvas.duration)
        self.transport.set_loop(self.loop_playback)
        self.stage_header.sync_notice()

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
        self.playingChanged.emit(True)

    def _start_sound(self) -> None:
        """Play the project's mix from the playhead and follow its clock, or the wall clock
        when there is nothing to hear or no player (ADR 0034)."""
        project = self.project
        if self.audio_player is not None:
            self.audio_player.stop()
        self._audio_signature = None
        if project is not None and project.audio and self.audio_player is not None:
            self.audio_player.play(audio.source(project), self.t)  # read in spans (B70)
            self._audio_signature = audio.mix_signature(project)
        self._play_origin = (time.perf_counter(), self.t)

    def play_silent_loop(self, start: float, end: float) -> None:
        """Go round ``start``..``end`` on the wall clock with no sound until paused (a looping slide stop)."""
        if self.project is None:
            return
        self.pause()
        self.play_loop = (start, end)
        self.seek(start)
        self._play_origin = (time.perf_counter(), start)
        self.play_timer.start(int(1000 / self.project.canvas.fps))
        self.play_button.setText("Pause")
        self.play_button.setIcon(icons.icon("pause"))
        self.canvas.playing = True
        self.playingChanged.emit(True)

    def pause(self) -> None:
        self.play_until = None
        self.play_loop = None
        self.play_timer.stop()
        if self._audio_signature is not None:
            self.audio_player.stop()
            self._audio_signature = None
        self.play_button.setText("Play")
        self.play_button.setIcon(icons.icon("play"))
        self.playingChanged.emit(False)
        if self.canvas.playing:
            self.canvas.playing = False
            self.refresh()  # the motion path comes back

    def _on_play_tick(self) -> None:
        assert self.project is not None and self._play_origin is not None
        wall0, t0 = self._play_origin
        if self._audio_signature is not None:  # the sound's clock (ADR 0034)
            t = self.audio_player.position()
        else:
            # wall clock: slow frames are dropped, never queued
            t = t0 + (time.perf_counter() - wall0) * self.play_speed
        fps = self.project.canvas.fps
        t = frame_time(frame_index(t, fps), fps)  # the frames the export has (ADR 0028)
        if self.play_loop is not None:  # a looping slide stop: round again, never past its end (ADR 0087)
            start, end = self.play_loop
            if t > end + 1e-9:
                self.seek(start)
                self._play_origin = (time.perf_counter(), start)
                return
            self.seek(t)
            return
        if self.play_until is not None and t >= self.play_until - 1e-9:  # a slide's stop: exactly there
            stop = self.play_until
            self.pause()
            self.seek(stop)
            self.playUntilReached.emit()
            return
        if t >= self.project.canvas.duration:
            if self.loop_playback:  # again from the start, the sound with it
                self.seek(0.0)
                self._start_sound()
                return
            self.seek(self.project.canvas.duration)
            self.pause()
            return
        self.seek(t)

    def show_palette(self) -> None:
        """Ctrl K: search every command, layer and page by name, and run the chosen one."""
        items = collect_items(self)
        palette = CommandPalette(items, self)
        self.palette = palette  # (tests look at it while it is open)
        palette.open_over(self)
        if (
            palette.exec() == palette.DialogCode.Accepted
            and palette.chosen is not None
            and palette.chosen.run
        ):
            palette.chosen.run()
        self.palette = None

    def _seek_to_end(self) -> None:
        if self.project is not None:
            self.pause()
            self.seek(self.project.canvas.duration)

    def _set_loop(self, on: bool) -> None:
        self.loop_playback = bool(on)

    def _update_scene_chip(self, project: Project | None) -> None:
        canvas = project.canvas if project is not None else None
        text = f"{canvas.width_px} × {canvas.height_px} · {canvas.fps:g} fps" if canvas else ""
        self.scene_chip.setText(text)

    def set_play_speed(self, speed: float) -> None:
        """Play a silent scene at ``speed`` times (1 = as made); the clock restarts from here."""
        self.play_speed = max(0.05, float(speed))
        self.transport.set_speed(self.play_speed)
        self._play_origin = (time.perf_counter(), self.t)

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

    def _set_layout_guides(self, shown: bool) -> None:
        self.canvas.set_layout_guides(shown)

    def show_guides(self) -> None:
        """View > Layout Guides...: edit the guides (ADR 0074); they are shown while it is open."""
        if not self._has_project:
            return
        self.layout_guides_action.setChecked(True)
        GuidesDialog(lambda: self.document.project, self.document.apply, self).exec()

    def _set_draft_preview(self, enabled: bool) -> None:
        self.canvas.set_draft_enabled(enabled)

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
    children.install(app)  # no helper process outlives the application
    prefs = Preferences()
    motion.set_reduced(prefs.toggle("reduce_motion", False))
    theme.apply(app, theme.THEMES[theme.resolve_appearance(prefs.appearance())])  # the studio look (ADR 0040)
    adapter.configure(places.cache_folder())  # not under the folder it was started from (GP)
    window = MainWindow()
    sys.excepthook = report_exceptions(window)
    window.show()
    if len(argv) > 1:
        window.load(Path(argv[1]))  # offers that file's recovery copies (ADR 0038)
    else:
        window.check_recovery()
    return app.exec()
