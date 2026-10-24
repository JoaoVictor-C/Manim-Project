"""The Code page (P6b.3, ADR 0041; reworked as a workspace in P12, ADR 0057).

Layout: the explorer (this project's code layers and Python objects, then the preset library) |
tabs over the editor, the output and a status strip | the viewer. The model, settled in decision
session 36, is unchanged:

* **Run only** applies the text: Ctrl+Enter or the Run button trusts the exact text
  (as the Properties code field does, ADR 0019) and applies it as one undo step through
  ``set_param``; typing never reaches the project or starts a render. With unchanged
  text Run only trusts and retries a failed or untrusted render.
* **Drafts**: text not applied yet is kept per layer (``code_drafts``) through layer and
  page switches and layer deletion, and dropped - with a message saying how many - when
  another project is opened. A layer is *dirty* exactly while its editor text differs
  from the project's; the title, the tab, the explorer and the render output say so.
* **The project moves underneath** (undo, redo, a Properties edit): a clean editor shows
  the new code; a dirty one keeps its text and shows a notice. **Revert** drops the draft
  and shows the project's code (as one step of the editor's own undo).
* **Errors** from the code renderer show in the output under the editor with their line number;
  clicking moves the cursor to that line (kept inside the text) and tints it.
* **Python objects** (ADR 0051) are listed with the code layers: "New Python object" adds one
  with a starter (a right triangle) and opens it here; Run applies its code (keeping the values
  of parameters that still exist) and the object is rebuilt; its build error shows at its line.

What P12 adds to it:

* **Tabs** for the layers being edited, with a dot on the ones that have unapplied changes.
* **Presets** in the explorer (built in, yours, downloaded): choosing one shows its code read-only
  with the actions that make sense (add to the project, edit a copy, rename, delete, export). Rows
  of both kinds drag onto the timeline and the canvas (``code_drag``); ``.py`` files dropped on the
  explorer or the editor open the import window.
* **Files**: Add file(s), Import a folder of presets and Get presets online open the import window,
  where each item's kind (object or scene), name, scenes, time and place are chosen first; Export
  asks what to write and how, and asks about each file that already exists.
* **Editor**: find and replace (Ctrl+F, Ctrl+H, F3), go to line (Alt+G), quick open (Ctrl+P), the
  output panel (Ctrl+J), and every editor setting in the menu next to Run, remembered.
"""

from __future__ import annotations

import dataclasses
import html
import time
from functools import partial
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QMouseEvent, QShortcut
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core import adapter, code_files, edits, python_object
from ...core.schema import CODE_TYPES, PYTHON_TYPES
from .. import code_drag, icons, quick_open, theme
from ..code_drafts import Drafts, error_line, error_text, moved_on
from ..code_editor import CodeEditor
from ..code_explorer import CodeExplorer, Row, Section
from ..code_render import CodeStatus
from ..find_bar import FindBar
from ..properties_panel import _first_error, set_param, set_python_code
from ..values_panel import ValuesPanel
from . import Page, Shared

HINT = "Select a code layer or a Python object, or add one with New code layer or New Python object."
PRESET_ORIGINS = (
    ("builtin", "Presets — built in"),
    ("user", "Presets — mine"),
    ("online", "Presets — downloaded"),
)


class ErrorLine(QLabel):
    """The error message under the editor; with a line number it is a link to that line."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setFont(theme.mono_font())
        self.line: int | None = None
        self.plain = ""

    def show_error(self, message: str, line: int | None) -> None:
        colours = theme.THEME
        self.line, self.plain = line, error_text(message, line)
        text = html.escape(message)
        if line:
            link = f"<u>line {line}</u>"
            text = f'<span style="color:{theme.css(colours.outline)}">{link}</span>: {text}'
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Go to this line")
        else:
            self.unsetCursor()
            self.setToolTip("")
        self.setText(text)
        self.setAccessibleName(self.plain)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.line:
            self.clicked.emit()
        super().mousePressEvent(event)


class _DropFilter(QObject):
    """Lets ``.py`` files dropped on the editor open the import window instead of being typed in."""

    def __init__(self, callback, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.callback = callback

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind in (QEvent.Type.DragEnter, QEvent.Type.DragMove) and code_drag.python_files(event.mimeData()):
            event.acceptProposedAction()
            return True
        if kind == QEvent.Type.Drop:
            files = code_drag.python_files(event.mimeData())
            if files:
                event.acceptProposedAction()
                self.callback(files)
                return True
        return False


class CodePage(Page):
    name = "code"
    title = "Code"
    icon = "code-page"
    tooltip = (
        "Write and run code layers and Python objects, and keep presets: an editor with highlighting, "
        "find, tabs, errors at their line (Ctrl+3)"
    )

    def build(self) -> QWidget:
        window = self.window
        self.layer_id: str | None = None  # the layer the editor shows
        self.preset_id: str | None = None  # the preset shown read-only instead (the editor keeps its layer)
        self.open_ids: list[str] = []  # the layers with a tab
        self.drafts = Drafts()  # unapplied text of the other layers
        self._base = ""  # the project's code the editor's text was started from
        self._moved = False  # the project's code changed under unapplied text
        self._loading = False
        self._last_dirty: bool | None = None
        self._signature: tuple | None = None
        self._selection_connected = False
        self._sized = False
        self._failed: tuple[str, str, str] | None = None  # (layer, text, why) of an apply refused
        self._starts: dict[str, float] = {}  # layer id -> when its run began (self.now())
        self.durations: dict[str, float] = {}  # seconds the last run of each layer took
        self.now = time.perf_counter  # tests replace the clock
        self._loading_tabs = False

        # Hooks for tests and other front-ends.
        self.ask_name = self._ask_name_dialog  # a new name, or None (cancelled)
        self.ask_line = self._ask_line_dialog  # a line number, or None
        self.confirm = self._confirm_dialog  # (title, text) -> bool
        self.quick = self._quick_dialog  # (items) -> QuickItem | None

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.addWidget(self._build_sidebar())
        self.split.addWidget(self._build_centre())
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)

        if not window.prefs.option("code_output_open", True):
            self.output_toggle.setChecked(False)
        if not window.prefs.option("code_sidebar_open", True):
            self.sidebar_button.setChecked(False)
        self.outline_button.setChecked(bool(window.prefs.option("code_canvas_outline", False)))
        window.builds.pendingChanged.connect(self._refresh_running)
        self._shortcuts()
        self._drops = _DropFilter(self._import_dropped, self.split)
        for target in (self.editor.viewport(), self.preview_editor.viewport()):
            target.installEventFilter(self._drops)
        self.apply_settings(window.prefs.editor_settings())
        window.builds.failed.connect(self._on_build_failed)
        window.document.reset.connect(self._on_reset)
        window.document.changed.connect(self._on_changed)
        window.code.statusChanged.connect(self._on_status)
        window.codePresetsChanged.connect(lambda: self._refresh_list(force=True))
        self._set_editor("", 0)
        self._after_change()
        return self.split

    # -- building -------------------------------------------------------------------------------

    def _button(self, text: str, tip: str, slot, icon: str | None = None) -> QPushButton:
        button = QPushButton(icons.icon(icon), text) if icon else QPushButton(text)
        button.setToolTip(tip)
        button.clicked.connect(slot)
        return button

    def _build_sidebar(self) -> QWidget:
        left = QWidget()
        column = QVBoxLayout(left)
        heading = QLabel("Explorer")
        heading.setProperty("role", "section")
        self.filter = QLineEdit()
        self.filter.setClearButtonEnabled(True)
        self.filter.setPlaceholderText("Filter layers and presets")
        self.explorer = CodeExplorer()
        self.filter.textChanged.connect(self.explorer.set_filter)
        self.explorer.chosen.connect(self._on_chosen)
        self.explorer.opened.connect(self._on_opened)
        self.explorer.menuRequested.connect(self._on_row_menu)
        self.explorer.filesDropped.connect(self._import_dropped)

        self.new_button = self._button(
            "New layer", "Add a code layer with a starter scene", self.new_layer, "add"
        )
        self.new_python_button = self._button(
            "New object",
            "Add a Python object: an object built by your own Manim code (PARAMS + build(p)), starting "
            "from a right triangle; the arrow lists the object presets. Its parameters become fields "
            "in Properties",
            lambda: self.new_python_object(),
            "add",
        )
        self.python_templates_menu = QMenu(self.new_python_button)  # the arrow: choose a starter
        self._refresh_python_templates()
        self.new_python_button.setMenu(self.python_templates_menu)
        self.add_code_file_button = self._button(
            "Add file…",
            "Add .py files to the project: a window asks what each becomes (a Python object or a scene) "
            "and its name, time and place first",
            self.add_code_file,
        )
        self.import_folder_button = self._button(
            "Import…",
            "Import a folder: add every .py file in it to your presets (a window asks about each)",
            self.import_code_folder,
        )
        self.online_button = self._button(
            "Online…",
            "Get presets from the internet: paste a link to a .py file, a GitHub folder or gist, "
            "or an index.json",
            self.get_online,
        )
        self.export_folder_button = self._button(
            "Export…",
            "Write layers and presets as .py files; asks about files that already exist",
            self.export_code_folder,
        )
        self.rename_button = self._button(
            "Rename", "Rename the chosen layer or preset (F2, or double-click a layer)", self.rename_item
        )
        self.delete_button = self._button(
            "Delete",
            "Delete the chosen layer (Delete; Ctrl+Z brings it back) or preset (asks first)",
            self.delete_item,
            "delete",
        )
        grid = QVBoxLayout()
        for pair in (
            (self.new_button, self.new_python_button),
            (self.add_code_file_button, self.import_folder_button),
            (self.online_button, self.export_folder_button),
            (self.rename_button, self.delete_button),
        ):
            row = QHBoxLayout()
            for button in pair:
                row.addWidget(button)
            grid.addLayout(row)
        column.addWidget(heading)
        column.addWidget(self.filter)
        column.addWidget(self.explorer, 1)
        column.addLayout(grid)
        return left

    def _build_centre(self) -> QWidget:
        centre = QWidget()
        stack = QVBoxLayout(centre)
        stack.setSpacing(2)
        self.editor = CodeEditor()
        self.preview_editor = CodeEditor()
        self.tabs = QTabBar()
        self.tabs.setObjectName("codeTabs")
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setExpanding(False)
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._on_tab)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.tabMoved.connect(self._on_tab_moved)

        bar = QHBoxLayout()
        self.title_label = QLabel("")
        self.title_label.setProperty("role", "section")
        self.dirty_label = QLabel("Unapplied")
        self.dirty_label.setObjectName("codeDirty")
        self.dirty_label.setStyleSheet(f"color: {theme.css(theme.THEME.warning)};")
        self.revert_button = self._button(
            "Revert",
            "Drop the changes that were not run and show the layer's code again",
            self.revert,
            "revert",
        )
        self.run_button = self._button(
            "Run", "Apply the code to the layer and run it (Ctrl+Enter)", self.run, "play"
        )
        self.convert_button = self._button(
            "Convert",
            "Convert to layers: turn this code layer's scene into layers and clips you can edit, in its "
            "place (ADR 0053); a scene with updaters, cameras or custom animations stays code and the "
            "report says why",
            self.convert,
        )
        self.convert_button.setObjectName("convertToLayers")
        self.save_code_button = self._button(
            "Save…", "Save the code shown in the editor as a standalone Python file", self.save_code
        )
        self.outline_button = QToolButton()
        self.outline_button.setIcon(icons.icon("outline"))
        self.outline_button.setCheckable(True)
        self.outline_button.setToolTip(
            "Draw the selection outline and handles over the picture (off: only the picture shows)"
        )
        self.outline_button.toggled.connect(self._on_outline_toggled)
        self.progress = QProgressBar()
        self.progress.setObjectName("codeProgress")
        self.progress.setRange(0, 0)  # busy: it does not know how long
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.hide()
        self._elapsed_timer = QTimer(self.progress)  # the seconds on Run while it works
        self._elapsed_timer.setInterval(200)
        self._elapsed_timer.timeout.connect(self._refresh_running)
        self.editor_menu_button = QToolButton()
        self.editor_menu_button.setText("Editor")
        self.editor_menu_button.setToolTip("Find, go to, settings and saving")
        self.editor_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.editor_menu = self._build_editor_menu()
        self.editor_menu_button.setMenu(self.editor_menu)
        bar.addWidget(self.title_label)
        bar.addWidget(self.dirty_label)
        bar.addStretch(1)
        for widget in (
            self.revert_button,
            self.convert_button,
            self.run_button,
            self.save_code_button,
            self.outline_button,
            self.editor_menu_button,
        ):
            bar.addWidget(widget)

        self.notice = QLabel(
            "The layer's code changed in the project (undo, redo or Properties) while you were editing. "
            "Your text is kept: Revert shows the project's code, Run replaces it."
        )
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet(f"color: {theme.css(theme.THEME.warning)};")

        self.editor.runRequested.connect(self.run)
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.cursorPositionChanged.connect(self._refresh_status)
        self.editor.zoomChanged.connect(lambda _size: self._save_settings())
        self.find_bar = FindBar(self.editor)
        editing = QWidget()
        lines = QVBoxLayout(editing)
        lines.setContentsMargins(0, 0, 0, 0)
        lines.setSpacing(0)
        lines.addWidget(self.find_bar)
        lines.addWidget(self.editor, 1)

        self.preview_editor.setReadOnly(True)
        self.preview_editor.setObjectName("presetPreview")
        self.preset_view = self._build_preset_view()

        self.views = QStackedWidget()
        self.views.addWidget(editing)
        self.views.addWidget(self.preset_view)

        self.state_label = QLabel("")
        self.state_label.setWordWrap(True)
        self.state_label.setObjectName("codeState")
        self.error_label = ErrorLine()
        self.error_label.setObjectName("codeError")
        self.error_label.clicked.connect(self.go_to_error)
        self.output_toggle = QToolButton()
        self.output_toggle.setText("Output")
        self.output_toggle.setIcon(icons.icon("panel"))
        self.output_toggle.setCheckable(True)
        self.output_toggle.setChecked(True)
        self.output_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.output_toggle.setToolTip("Show or hide the render output (Ctrl+J)")
        output_page = QWidget()
        output_lines = QVBoxLayout(output_page)
        output_lines.setContentsMargins(0, 0, 0, 0)
        output_lines.addWidget(self.state_label)
        output_lines.addWidget(self.error_label)
        output_lines.addStretch(1)
        self.values = ValuesPanel(
            self.window.builds, lambda text: self.window.statusBar().showMessage(text, 8000)
        )
        self.output = QTabWidget()  # the bottom panel: what the run said, and the object's values
        self.output.setObjectName("codePanel")
        self.output.addTab(output_page, "Output")
        self.output.addTab(self.values, "Values")
        self.output.setMaximumHeight(240)
        self.output_toggle.toggled.connect(self._on_output_toggled)

        self.sidebar_button = QToolButton()
        self.sidebar_button.setIcon(icons.icon("sidebar"))
        self.sidebar_button.setCheckable(True)
        self.sidebar_button.setChecked(True)
        self.sidebar_button.setToolTip("Hide or show the explorer (Ctrl+B)")
        self.sidebar_button.toggled.connect(self._on_sidebar_toggled)
        tab_row = QHBoxLayout()
        tab_row.addWidget(self.sidebar_button)
        tab_row.addWidget(self.tabs, 1)
        stack.addLayout(tab_row)
        stack.addLayout(bar)
        stack.addWidget(self.progress)
        stack.addWidget(self.notice)
        stack.addWidget(self.views, 1)
        stack.addWidget(self.output_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        stack.addWidget(self.output)
        stack.addLayout(self._build_status())
        return centre

    def _build_preset_view(self) -> QWidget:
        view = QWidget()
        column = QVBoxLayout(view)
        column.setContentsMargins(0, 0, 0, 0)
        self.preset_title = QLabel("")
        self.preset_title.setProperty("role", "section")
        self.preset_note = QLabel("")
        self.preset_note.setWordWrap(True)
        row = QHBoxLayout()
        self.preset_add_button = self._button(
            "Add to project", "Add this preset to the project at the playhead", self.add_preset_to_project
        )
        self.preset_copy_button = self._button(
            "Edit a copy",
            "Add this preset to the project and open it here to change it (the preset stays as it is)",
            partial(self.add_preset_to_project, True),
        )
        self.preset_export_button = self._button(
            "Export…", "Write this preset as a .py file", self.export_preset
        )
        self.close_preset_button = self._button(
            "Close", "Go back to the layer you were editing", self.close_preset
        )
        for button in (
            self.preset_add_button,
            self.preset_copy_button,
            self.preset_export_button,
            self.close_preset_button,
        ):
            row.addWidget(button)
        row.addStretch(1)
        column.addWidget(self.preset_title)
        column.addWidget(self.preset_note)
        column.addLayout(row)
        column.addWidget(self.preview_editor, 1)
        return view

    def _build_status(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.cursor_label = QLabel("")
        self.kind_label = QLabel("")
        self.indent_label = QLabel("")
        self.trust_label = QLabel("")
        for label in (self.cursor_label, self.indent_label, self.kind_label, self.trust_label):
            label.setProperty("role", "hint")
            label.setStyleSheet(f"color: {theme.css(theme.THEME.muted)};")
        encoding = QLabel("UTF-8")
        encoding.setStyleSheet(f"color: {theme.css(theme.THEME.muted)};")
        row.addWidget(self.cursor_label)
        row.addWidget(self.indent_label)
        row.addWidget(encoding)
        row.addStretch(1)
        row.addWidget(self.kind_label)
        row.addWidget(self.trust_label)
        return row

    def _build_editor_menu(self) -> QMenu:
        menu = QMenu(self.editor_menu_button)
        self.find_action = menu.addAction("Find…", self.open_find, QKeySequence("Ctrl+F"))
        self.replace_action = menu.addAction("Replace…", self.open_replace, QKeySequence("Ctrl+H"))
        menu.addAction("Go to line…", self.goto_line, QKeySequence("Alt+G"))
        menu.addAction("Go to layer or preset…", self.quick_open, QKeySequence("Ctrl+P"))
        menu.addAction("Show or hide output", self.toggle_output, QKeySequence("Ctrl+J"))
        menu.addSeparator()
        menu.addAction("Save code as file…", self.save_code)
        menu.addAction("Save as preset…", self.save_as_preset)
        menu.addSeparator()
        self.setting_actions: dict[str, QAction] = {}
        for key, text in (
            ("word_wrap", "Word wrap"),
            ("line_numbers", "Line numbers"),
            ("highlight_line", "Highlight the current line"),
            ("show_whitespace", "Show spaces and tabs"),
            ("auto_close_brackets", "Close brackets and quotes"),
            ("trim_trailing_whitespace", "Trim trailing spaces when running"),
        ):
            action = menu.addAction(text)
            action.setCheckable(True)
            action.toggled.connect(lambda on, k=key: self._set_setting(**{k: on}))
            self.setting_actions[key] = action
        tab_menu = menu.addMenu("Indent size")
        group = QActionGroup(tab_menu)
        self.tab_actions: dict[int, QAction] = {}
        for width in (2, 4, 8):
            action = tab_menu.addAction(f"{width} spaces")
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(lambda _=False, w=width: self._set_setting(tab_width=w))
            self.tab_actions[width] = action
        menu.addSeparator()
        menu.addAction("Zoom in", self.editor.zoom_in, QKeySequence("Ctrl+="))
        menu.addAction("Zoom out", self.editor.zoom_out, QKeySequence("Ctrl+-"))
        menu.addAction("Reset zoom", self.editor.zoom_reset, QKeySequence("Ctrl+0"))
        return menu

    def _shortcuts(self) -> None:
        # Plain shortcuts of the page (the editor keeps Ctrl+Enter, Ctrl+/ and the line commands).
        for keys, slot in (
            ("Ctrl+F", self.open_find),
            ("Ctrl+H", self.open_replace),
            ("F3", self.find_next),
            ("Shift+F3", self.find_previous),
            ("Alt+G", self.goto_line),
            ("Ctrl+P", self.quick_open),
            ("Ctrl+J", self.toggle_output),
            ("Ctrl+B", self.toggle_sidebar),
        ):
            shortcut = QShortcut(QKeySequence(keys), self.split)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        for keys in ("Ctrl+Return", "Ctrl+Enter"):  # at once (a button's shortcut animates for 100 ms first)
            shortcut = QShortcut(QKeySequence(keys), self.split)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self.run)
        for keys, slot in (
            (QKeySequence(Qt.Key.Key_F2), self.rename_item),
            (QKeySequence.StandardKey.Delete, self.delete_item),
        ):
            shortcut = QShortcut(keys, self.explorer)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(slot)

    # -- the page protocol ----------------------------------------------------------------

    def place(self, shared: Shared) -> None:
        self.split.insertWidget(2, shared.viewer)
        self.split.setStretchFactor(2, 1)
        selection = getattr(self.window, "selection", None)
        if selection is not None and not self._selection_connected:  # created after the pages
            self._selection_connected = True
            selection.changed.connect(self._on_selection)

    def on_show(self) -> None:
        if not self._sized:
            self._sized = True
            total = max(self.split.width(), 1200)
            side = 230
            self.split.setSizes([side, total * 45 // 100, total - side - total * 45 // 100])
        self.window.canvas.set_overlays(self.outline_button.isChecked())
        self._refresh_list(force=True)
        self._ensure_layer()
        self._after_change()

    def on_hide(self) -> None:
        self.window.canvas.set_overlays(True)  # the other pages edit on the canvas

    # -- the project ----------------------------------------------------------------------

    def _layers(self) -> list:
        project = self.window.project
        if project is None:
            return []
        return [x for x in project.layers if x.spec is not None and x.spec.type in CODE_TYPES | PYTHON_TYPES]

    def _is_python(self, layer_id: str | None) -> bool:
        layer = next((x for x in self._layers() if x.id == layer_id), None)
        return layer is not None and layer.spec.type in PYTHON_TYPES

    def status(self, layer_id: str | None) -> CodeStatus | None:
        """A code layer's render status, or a Python object's build status (ADR 0051)."""
        if layer_id is None:
            return None
        if self._is_python(layer_id):
            spec = self.window.project.layer(layer_id).spec
            problem = adapter.python_problem(spec)
            if problem is None:
                return CodeStatus("built")
            if problem.message == python_object.NOT_TRUSTED:
                return CodeStatus("untrusted")
            return CodeStatus("error", error=problem.message, line=problem.line)
        return self.window.code.status(layer_id)

    def _code_of(self, layer_id: str | None) -> str | None:
        """The applied code of a code layer (None: no such code layer)."""
        for layer in self._layers():
            if layer.id == layer_id:
                return str(layer.spec.params.get("code", ""))
        return None

    def is_dirty(self) -> bool:
        """Does the editor hold text that is not the layer's applied code?"""
        code = self._code_of(self.layer_id)
        return code is not None and self.editor.text() != code

    def dirty_layers(self) -> set[str]:
        ids = {x.id for x in self._layers() if self.drafts.dirty(x.id, self._code_of(x.id))}
        if self.layer_id is not None and self.is_dirty():
            ids.add(self.layer_id)
        return ids

    # -- showing a layer ------------------------------------------------------------------

    def _set_editor(self, text: str, cursor: int) -> None:
        self._loading = True
        try:
            self.editor.set_text(text, cursor)
        finally:
            self._loading = False
        self.editor.setEnabled(self.layer_id is not None)
        self.editor.setPlaceholderText(HINT if self.layer_id is None else "")

    def _park(self) -> None:
        """Remember the editor's text for its layer (unless it is the layer's code)."""
        if self.layer_id is None:
            return
        code = self._code_of(self.layer_id)
        self.drafts.park(
            self.layer_id,
            self.editor.text(),
            self.editor.cursor_position(),
            self._base,
            self._base if code is None else code,  # a deleted layer: what it last had
        )

    def show_layer(self, layer_id: str | None) -> None:
        """Show a code layer in the editor, parking the one it was showing."""
        if self.preset_id is not None and layer_id is not None:
            self.close_preset()
        if layer_id == self.layer_id:
            return
        self._park()
        self.layer_id = layer_id
        code = self._code_of(layer_id)
        if layer_id is None or code is None:
            self.layer_id = None
            self._base, self._moved = "", False
            self._set_editor("", 0)
        else:
            if layer_id not in self.open_ids:
                self.open_ids.append(layer_id)
            draft = self.drafts.get(layer_id, code)
            if draft is None:
                self._base, text, cursor = code, code, 0
            else:
                self._base, text, cursor = draft.base, draft.text, draft.cursor
                self.drafts.discard(layer_id)  # the editor holds it now
            self._moved = moved_on(text, self._base, code)
            self._set_editor(text, cursor)
        self._last_dirty = None
        self._after_change()

    def _ensure_layer(self) -> None:
        """Keep the editor on a code layer that exists, and the selection on it while the page shows."""
        if self.preset_id is not None:
            return  # a preset is being looked at: leave it until the user chooses a layer
        ids = [x.id for x in self._layers()]
        selection = getattr(self.window, "selection", None)
        selected = selection.layer_id if selection is not None else None
        if selected in ids:
            target = selected
        elif self.layer_id in ids:
            target = self.layer_id
        else:
            target = ids[0] if ids else None
        self.show_layer(target)
        if self.window.page == self.name and selection is not None and target and selected != target:
            selection.select_layer(target)

    def _on_selection(self) -> None:
        layer_id = self.window.selection.layer_id
        if layer_id is None and self.window.page == self.name:
            self._ensure_layer()  # a cleared selection (e.g. a new project): stay on a code layer
        elif layer_id is not None and self._code_of(layer_id) is not None:
            self.show_layer(layer_id)

    # -- the explorer and the tabs ---------------------------------------------------------

    def chosen_row(self) -> tuple[str, str] | None:
        """(``"layer"`` | ``"preset"``, id) of the explorer's current row."""
        return self.explorer.current()

    def chosen_layer(self) -> str | None:
        row = self.chosen_row()
        return row[1] if row is not None and row[0] == "layer" else None

    def chosen_preset(self) -> str | None:
        row = self.chosen_row()
        return row[1] if row is not None and row[0] == "preset" else None

    def _on_chosen(self, source: str, key: str) -> None:
        if source == "layer":
            self.window.selection.select_layer(key)  # the page follows the selection
            self.show_layer(key)
        else:
            self.show_preset(key)

    def _on_opened(self, source: str, key: str) -> None:
        """Double-click or Enter: a layer takes the keyboard, a preset is added to the project."""
        if source == "layer":
            self.editor.setFocus()
        else:
            self.add_preset_to_project()

    def _on_tab(self, index: int) -> None:
        if index < 0 or self._loading_tabs:
            return
        layer_id = self.tabs.tabData(index)
        if layer_id and layer_id != self.layer_id:
            self.window.selection.select_layer(layer_id)
            self.show_layer(layer_id)

    def _on_tab_moved(self, _from: int, _to: int) -> None:
        self.open_ids = [self.tabs.tabData(i) for i in range(self.tabs.count())]

    def _close_tab(self, index: int) -> None:
        layer_id = self.tabs.tabData(index)
        if layer_id in self.open_ids and len(self.open_ids) > 1:
            self.open_ids.remove(layer_id)
            if layer_id == self.layer_id:
                neighbour = self.open_ids[min(index, len(self.open_ids) - 1)]
                self.window.selection.select_layer(neighbour)
                self.show_layer(neighbour)
            self._refresh_tabs()

    def _refresh_tabs(self) -> None:
        layers = {x.id: x for x in self._layers()}
        self.open_ids = [i for i in self.open_ids if i in layers]
        dirty = self.dirty_layers()
        self._loading_tabs = True
        try:
            while self.tabs.count() > len(self.open_ids):
                self.tabs.removeTab(self.tabs.count() - 1)
            for index, layer_id in enumerate(self.open_ids):
                text = layers[layer_id].label + ("  ●" if layer_id in dirty else "")
                if index >= self.tabs.count():
                    self.tabs.addTab(text)
                else:
                    self.tabs.setTabText(index, text)
                self.tabs.setTabIcon(
                    index,
                    icons.icon("py-object" if layers[layer_id].spec.type in PYTHON_TYPES else "py-scene"),
                )
                self.tabs.setTabData(index, layer_id)
                self.tabs.setTabToolTip(
                    index, "Unapplied changes: Run applies them" if layer_id in dirty else ""
                )
            if self.layer_id in self.open_ids and self.preset_id is None:
                self.tabs.setCurrentIndex(self.open_ids.index(self.layer_id))
            self.tabs.setTabsClosable(len(self.open_ids) > 1)
        finally:
            self._loading_tabs = False

    # -- presets ---------------------------------------------------------------------------

    def _preset(self, preset_id: str | None):
        return self.window.code_presets.get(preset_id) if preset_id else None

    def show_preset(self, preset_id: str) -> None:
        """Look at a preset: its code, read-only, with the actions that fit it."""
        preset = self._preset(preset_id)
        if preset is None:
            return
        self._park()
        self.preset_id = preset_id
        self.preview_editor.set_text(preset.code, 0)
        where = {"builtin": "built in", "user": "yours", "online": "downloaded"}[preset.origin]
        self.preset_title.setText(f"{preset.name}  —  preset ({where}, {preset.kind})")
        note = preset.description
        if preset.source_url:
            note = f"{note}\n{preset.source_url}".strip()
        self.preset_note.setText(note)
        self.preset_note.setVisible(bool(note))
        self.views.setCurrentIndex(1)
        self._after_change()

    def close_preset(self) -> None:
        """Back to the editor."""
        if self.preset_id is None:
            return
        self.preset_id = None
        self.views.setCurrentIndex(0)
        self._after_change()

    def add_preset_to_project(self, edit_copy: bool = False) -> None:
        """Add the chosen preset to the project at the playhead; the copy opens in the editor."""
        preset_id = self.preset_id or self.chosen_preset()
        preset = self._preset(preset_id)
        if preset is None:
            return
        if self.window.project is None:
            self.window.statusBar().showMessage("Create or open a project first.", 5000)
            return
        payload = {"from": "preset", "id": preset.id, "name": preset.name, "kind": preset.kind}
        self.window.importer.place(payload)
        if edit_copy:
            self.close_preset()  # the new layer is selected, so the page follows it

    def export_preset(self) -> None:
        preset_id = self.preset_id or self.chosen_preset()
        if preset_id is not None:
            self.window.importer.export_code(self._export_entries(), checked={preset_id})

    def rename_preset(self) -> None:
        preset = self._preset(self.preset_id or self.chosen_preset())
        if preset is None:
            return
        if preset.builtin:
            self.window.statusBar().showMessage(
                "Built-in presets cannot be renamed; Edit a copy instead", 6000
            )
            return
        name = self.ask_name(preset.name)
        if name is None or name.strip() == preset.name:
            return
        self.window.code_presets.rename(preset.id, name.strip())
        self.window.codePresetsChanged.emit()
        self.show_preset(preset.id)

    def delete_preset(self) -> None:
        preset = self._preset(self.preset_id or self.chosen_preset())
        if preset is None:
            return
        if preset.builtin:
            self.window.statusBar().showMessage("Built-in presets cannot be deleted", 6000)
            return
        if not self.confirm("Delete preset", f"Delete the preset “{preset.name}”? This cannot be undone."):
            return
        self.window.code_presets.remove(preset.id)
        self.close_preset()
        self.window.codePresetsChanged.emit()

    def save_as_preset(self) -> None:
        """Keep the code in the editor as a preset of yours; a name that is taken asks what to do."""
        layer_id = self.layer_id
        if layer_id is None or self.window.project is None:
            return
        layer = self.window.project.layer(layer_id)
        name = self.ask_name(layer.label)
        if name is None:
            return
        kind = "object" if self._is_python(layer_id) else "scene"
        outcome = self.window.importer.store_preset(name.strip(), kind, self.editor.text())
        words = {
            "added": "Saved as a preset",
            "replaced": "Replaced the preset",
            "copied": "Saved as a new preset (the name was taken)",
            "skipped": "Not saved",
            "same": "That preset already exists",
            "cancelled": "Not saved",
        }
        self.window.statusBar().showMessage(f"{words[outcome]}: {name.strip()}", 8000)

    def _refresh_python_templates(self) -> None:
        """Rebuild the arrow menu of New Python object: the object presets, built in first."""
        menu = self.python_templates_menu
        menu.clear()
        for preset in self.window.code_presets.presets():
            if preset.kind != "object":
                continue
            action = menu.addAction(preset.name)
            action.setToolTip(f"Start from the {preset.name} preset")
            if preset.builtin:  # the editor's own code: trusted like the starter
                action.triggered.connect(lambda _=False, c=preset.code: self.new_python_object(c))
            else:  # yours or downloaded: added untrusted, until it is run
                action.triggered.connect(lambda _=False, p=preset: self._add_untrusted(p))

    def _add_untrusted(self, preset) -> None:
        if self.window.project is None:
            self.window.statusBar().showMessage("Create or open a project first.", 5000)
            return
        payload = {"from": "preset", "id": preset.id, "name": preset.name, "kind": preset.kind}
        self.window.importer.place(payload)
        if self.window.page != self.name:
            self.window.show_page(self.name)

    # -- following the project ---------------------------------------------------------------

    def _on_reset(self, _project) -> None:
        """Another project was opened: unapplied text belongs to the old one."""
        dropped = len(self.drafts) + (
            1 if self.layer_id is not None and self.editor.text() != self._base else 0
        )
        self.drafts.clear()
        self.layer_id = None
        self.open_ids = []
        self._base, self._moved = "", False
        self._set_editor("", 0)
        self._signature = None
        self._last_dirty = None
        if dropped:
            plural = "" if dropped == 1 else "s"
            self.window.statusBar().showMessage(
                f"Discarded {dropped} unapplied code change{plural} from the previous project", 10000
            )
        self._refresh_list(force=True)
        if self.window.page == self.name:
            self._ensure_layer()
        else:
            self.show_layer(next((x.id for x in self._layers()), None))
        self._after_change()

    def _on_changed(self, _project, _layer_ids, _kind) -> None:
        self._refresh_list()
        self.values.refresh(self.window.project)
        if self.layer_id is None:
            self._ensure_layer()
            return
        code = self._code_of(self.layer_id)
        if code is None:  # the layer was deleted: its unapplied text is kept for an undo
            self._park()
            self.layer_id = None
            self._ensure_layer()
            return
        if code != self._base:
            text = self.editor.text()
            if text == self._base:  # nothing unapplied: show the new code
                self._base, self._moved = code, False
                self._set_editor(code, self.editor.cursor_position())
            else:  # an apply from here, or the project moved under unapplied text
                self._base = code
                self._moved = text != code
            self._last_dirty = None
            self._after_change()

    def _on_status(self, layer_id: str) -> None:
        status = self.status(layer_id)
        if status is not None and layer_id != self.layer_id:  # another layer's render: time it too
            self._track(layer_id, status.state in ("queued", "rendering"))
        self._refresh_list()
        if layer_id == self.layer_id:
            self._refresh_output()
            self._refresh_status()
            self._refresh_running()

    def _on_text_changed(self) -> None:
        if self._loading:
            return
        if self.is_dirty() != self._last_dirty:  # only a change of state needs the views redone
            self._after_change()

    # -- actions ------------------------------------------------------------------------------

    def run(self) -> None:
        """Trust and apply the editor's text (one undo step), then the renderer runs it."""
        layer_id = self.layer_id
        project = self.window.project
        if layer_id is None or project is None or self.preset_id is not None:
            return
        if self.window.builds.busy:  # an apply is still on its way: running again would stack them
            self.window.statusBar().showMessage("Still running - wait for it to finish", 4000)
            return
        trimmed = self.editor.trimmed_text()
        if trimmed != self.editor.text():
            self.editor.replace_text(trimmed)  # one step of the editor's own undo
        text = self.editor.text()
        self.window.trust.trust([text])  # code the user applies here is theirs (ADR 0019)
        python = self._is_python(layer_id)
        if text != self._code_of(layer_id):
            if python:  # its values are kept for the parameters still declared (ADR 0051)
                op, label = partial(set_python_code, layer_id=layer_id, code=text), "Apply code"
            else:
                op, label = partial(set_param, layer_id=layer_id, name="code", value=text), "Run code"
            self._failed = None
            try:
                self.window.builds.submit(op, label)
            except (edits.EditError, ValidationError) as error:
                message = _first_error(error)
                self._failed = (layer_id, text, message)
                self.window.statusBar().showMessage(f"{label}: {message}", 10000)
                self._refresh_output()
            return  # the change reaches _on_changed, which marks the editor clean
        if python:  # unchanged text: now trusted, so built (it showed the placeholder before)
            self.window.reload_media()
            self._after_change()
            return
        status = self.window.code.status(layer_id)
        self.window.code.trust_layers(project, [layer_id])
        if status is not None and status.state == "error":
            self.window.code.retry(layer_id)

    def save_code(self) -> None:
        """Save the editor's current text, including unapplied edits, as a Python file (the system's
        dialog asks before replacing a file)."""
        layer_id = self.layer_id
        if layer_id is None or self.window.project is None:
            return
        layer = self.window.project.layer(layer_id)
        stem = code_files.safe_stem(layer.label, layer.id)
        start = self.window.default_folder() / f"{stem}.py"
        name, _ = QFileDialog.getSaveFileName(self.widget, "Save Code", str(start), "Python (*.py)")
        if not name:
            return
        path = Path(name)
        if path.suffix.lower() != ".py":
            path = path.with_suffix(".py")
        try:
            path.write_text(self.editor.text(), encoding="utf-8", newline="\n")
        except OSError as error:
            self.window.statusBar().showMessage(f"Could not save code: {error}", 10000)
            return
        self.window.statusBar().showMessage(f"Saved code to {path}", 10000)

    def convert(self) -> None:
        """Convert to layers (P10.3, ADR 0053): the window records the scene in another process and
        replaces the layer by its objects, or says why it stays code."""
        if self.layer_id is not None and not self._is_python(self.layer_id) and not self.is_dirty():
            self.window.convert_code_layer(self.layer_id)

    def revert(self) -> None:
        """Drop the unapplied text: show the layer's code again."""
        code = self._code_of(self.layer_id)
        if code is None or not self.is_dirty():
            return
        self._base, self._moved = code, False
        self.editor.replace_text(code)  # one step of the editor's own undo
        self._last_dirty = None
        self._after_change()

    # -- files: import, export, online (P12.4, P12.6) -----------------------------------------

    def add_code_file(self) -> None:
        """Choose .py files; the import window asks what each becomes."""
        names, _ = QFileDialog.getOpenFileNames(
            self.widget, "Add Code Files", str(self.window.default_folder()), "Python (*.py);;All files (*)"
        )
        if names:
            self.window.importer.import_paths(list(names))

    def import_code_folder(self) -> None:
        """Choose a folder; its .py files are offered as presets."""
        folder = QFileDialog.getExistingDirectory(
            self.widget, "Import Presets from Folder", str(self.window.default_folder())
        )
        if folder:
            self.window.importer.import_folder(folder)

    def get_online(self) -> None:
        self.window.importer.get_online()

    def _import_dropped(self, files: list) -> None:
        self.window.importer.import_paths(list(files))

    def _draft_text(self, layer_id: str, applied: str) -> str:
        if layer_id == self.layer_id:
            return self.editor.text()
        draft = self.drafts.get(layer_id, applied)
        return applied if draft is None else draft.text

    def _export_entries(self) -> list:
        """What can be exported: the layers with the text in the editor and in the drafts (not just
        what was applied), then the presets."""
        entries = []
        for entry in self.window.importer.entries():
            if entry.group == "project":
                entry = dataclasses.replace(entry, source=self._draft_text(entry.key, entry.source))
            entries.append(entry)
        return entries

    def export_code_folder(self, checked: set[str] | None = None) -> None:
        """Choose what to write and how; asks about each file that already exists."""
        entries = self._export_entries()
        if checked is None:  # the project's code and the presets you added; the built-in ones are not ticked
            builtin = {p.id for p in self.window.code_presets.presets() if p.builtin}
            checked = {e.key for e in entries if e.key not in builtin}
        self.window.importer.export_code(entries, checked)

    # -- managing code layers (P7.1) ------------------------------------------------------

    def row_menu(self, source: str | None = None, key: str | None = None) -> QMenu:
        """The right-click menu for a row (built separately so it can be tested); the current row
        when none is given."""
        if source is None:
            row = self.chosen_row()
            source, key = row if row is not None else ("", "")
        menu = QMenu(self.explorer)
        if source == "layer":
            for text, slot, tip in (
                ("Open", lambda: self.editor.setFocus(), "Edit this code"),
                ("Rename...", self.rename_layer, "Give the code layer a name (F2)"),
                ("Duplicate", self.duplicate_layer, "Add another copy of this layer"),
                ("Save as preset...", self.save_as_preset, "Keep this code in your presets"),
                ("Export...", partial(self.export_code_folder, {key}), "Write this layer as a .py file"),
                ("Delete", self.delete_layer, "Delete the code layer (Delete)"),
            ):
                menu.addAction(text, slot).setToolTip(tip)
        elif source == "preset":
            preset = self._preset(key)
            menu.addAction("Add to project", self.add_preset_to_project)
            menu.addAction("Edit a copy", partial(self.add_preset_to_project, True))
            menu.addAction("Export...", self.export_preset)
            if preset is not None and not preset.builtin:
                menu.addSeparator()
                menu.addAction("Rename...", self.rename_preset)
                menu.addAction("Delete", self.delete_preset)
        else:
            menu.addAction("New code layer", self.new_layer)
            menu.addAction("New Python object", lambda: self.new_python_object())
            menu.addSeparator()
            menu.addAction("Add file...", self.add_code_file)
            menu.addAction("Import folder...", self.import_code_folder)
            menu.addAction("Get online...", self.get_online)
            menu.addAction("Export...", self.export_code_folder)
        return menu

    # kept for the old name
    list_menu = row_menu

    def _on_row_menu(self, source: str, key: str, where: QPoint) -> None:
        self.row_menu(source if source != "section" else "", key).exec(where)

    def rename_item(self) -> None:
        if self.chosen_preset() is not None or self.preset_id is not None:
            self.rename_preset()
        else:
            self.rename_layer()

    def delete_item(self) -> None:
        if self.chosen_preset() is not None or self.preset_id is not None:
            self.delete_preset()
        else:
            self.delete_layer()

    def rename_layer(self) -> None:
        layer_id = self.chosen_layer()
        if layer_id is None or self.window.project is None:
            return
        layer = self.window.project.layer(layer_id)
        name = self.ask_name(layer.label)
        if name is None or name.strip() == layer.label:
            return
        self.window.layers.rename(layer_id, "" if name.strip() == layer.id else name)

    def duplicate_layer(self) -> None:
        layer_id = self.chosen_layer() or self.layer_id
        if layer_id is not None and self.window.project is not None:
            self.window.layers.duplicate_code_layer(layer_id)

    def delete_layer(self) -> None:
        """Delete the chosen code layer (one undo step); its unapplied text stays in the drafts."""
        layer_id = self.chosen_layer()
        if layer_id is None or self.window.project is None:
            return
        try:
            self.window.builds.submit(partial(edits.remove_layer, layer_id=layer_id), "Delete layer")
        except (edits.EditError, ValidationError) as error:
            self.window.statusBar().showMessage(f"Delete layer: {error}", 10000)

    def _ask_name_dialog(self, current: str) -> str | None:
        name, ok = QInputDialog.getText(self.explorer, "Name", "Name:", text=current)
        return name if ok and name.strip() else None

    def _ask_line_dialog(self, current: int, last: int) -> int | None:
        line, ok = QInputDialog.getInt(self.editor, "Go to line", f"Line (1-{last}):", current, 1, last)
        return line if ok else None

    def _confirm_dialog(self, title: str, text: str) -> bool:
        return QMessageBox.question(self.widget, title, text) == QMessageBox.StandardButton.Yes

    def _quick_dialog(self, items: list):
        dialog = quick_open.QuickOpen(items, self.widget)
        return dialog.chosen if dialog.exec() == dialog.DialogCode.Accepted else None

    def new_layer(self) -> None:
        if self.window.project is None:
            self.window.statusBar().showMessage("Create or open a project first.", 5000)
            return
        self.window.layers.add_object("Code")  # selects it; the page follows the selection

    def new_python_object(self, code: str | None = None) -> None:
        """Add a Python object from a template (ADR 0051; the right triangle unless ``code``); the
        page shows it."""
        if self.window.project is None:
            self.window.statusBar().showMessage("Create or open a project first.", 5000)
            return
        self.window.layers.add_python_object(code)  # selects it; the page follows the selection
        if self.window.page != self.name:
            self.window.show_page(self.name)

    def _on_build_failed(self, text: str, message: str) -> None:
        """An apply the build worker refused (new code that ran too long, ADR 0051)."""
        if text == "Apply code" and self.layer_id is not None:
            self._failed = (self.layer_id, self.editor.text(), message)
            self._refresh_output()

    def go_to_error(self) -> None:
        """Move the cursor to the line the render error points at."""
        if self.error_label.line:
            self.editor.go_to_line(self.error_label.line)

    # -- find, go to, quick open, output, settings (P12.5) ---------------------------------------

    def open_find(self) -> None:
        self.close_preset()
        self.find_bar.open()

    def open_replace(self) -> None:
        self.close_preset()
        self.find_bar.open(replace=True)

    def find_next(self) -> None:
        if self.find_bar.is_open:
            self.find_bar.find_next()

    def find_previous(self) -> None:
        if self.find_bar.is_open:
            self.find_bar.find_previous()

    def goto_line(self) -> None:
        if self.layer_id is None:
            return
        last = max(1, self.editor.blockCount())
        line = self.ask_line(self.editor.current_line(), last)
        if line is not None:
            self.editor.go_to_line(line)

    def quick_items(self) -> list:
        items = []
        for layer in self._layers():
            detail = "Python object" if layer.spec.type in PYTHON_TYPES else "Scene"
            items.append(quick_open.QuickItem("layer", layer.id, layer.label, detail))
        for preset in self.window.code_presets.presets():
            items.append(
                quick_open.QuickItem(
                    "preset", preset.id, preset.name, f"{preset.origin} preset ({preset.kind})"
                )
            )
        return items

    def quick_open(self) -> None:
        """Ctrl+P: type a few letters of a layer's or a preset's name."""
        chosen = self.quick(self.quick_items())
        if chosen is None:
            return
        self.explorer.set_filter("")
        self.filter.clear()
        self.explorer.select(chosen.source, chosen.key)
        self._on_chosen(chosen.source, chosen.key)

    def toggle_output(self) -> None:
        self.output_toggle.toggle()

    def toggle_sidebar(self) -> None:
        self.sidebar_button.toggle()

    def _on_sidebar_toggled(self, shown: bool) -> None:
        self.split.widget(0).setVisible(shown)
        self.window.prefs.set_option("code_sidebar_open", shown)

    def _on_outline_toggled(self, shown: bool) -> None:
        self.window.prefs.set_option("code_canvas_outline", shown)
        if self.window.page == self.name:
            self.window.canvas.set_overlays(shown)

    def is_running(self) -> bool:
        """Is the layer in the editor being applied, built or rendered? Until it is not, it is not
        ready to be used in full."""
        if self.layer_id is None:
            return False
        if self.window.builds.busy:
            return True
        status = self.status(self.layer_id)
        return status is not None and status.state in ("queued", "rendering")

    def _refresh_running(self) -> None:
        """The progress bar under the toolbar and the Run button say that it is still working."""
        running = self.is_running()
        if self.layer_id is not None:
            self._track(self.layer_id, running)
        self.progress.setVisible(running)
        self.run_button.setText(f"Running… {self.elapsed():.1f} s" if running else "Run")
        self.run_button.setEnabled(self.layer_id is not None and self.preset_id is None and not running)

    def _track(self, layer_id: str, running: bool) -> None:
        """Time a layer's run: note when it starts, and how long it took when it ends."""
        if running and layer_id not in self._starts:
            self._starts[layer_id] = self.now()
            self._elapsed_timer.start()
        elif not running and layer_id in self._starts:
            self.durations[layer_id] = self.now() - self._starts.pop(layer_id)
            if not self._starts:
                self._elapsed_timer.stop()
            if layer_id == self.layer_id:
                self._refresh_output()

    def elapsed(self) -> float:
        """Seconds the run of the layer in the editor has been going (0 when it is not running)."""
        start = self._starts.get(self.layer_id or "")
        return 0.0 if start is None else self.now() - start

    def _on_output_toggled(self, shown: bool) -> None:
        self.output.setVisible(shown)
        self.window.prefs.set_option("code_output_open", shown)

    def apply_settings(self, settings) -> None:
        """Show ``settings`` in both editors and in the menu."""
        self.editor.apply_settings(settings)
        self.preview_editor.apply_settings(dataclasses.replace(settings, trim_trailing_whitespace=False))
        for key, action in self.setting_actions.items():
            action.blockSignals(True)
            action.setChecked(bool(getattr(settings, key)))
            action.blockSignals(False)
        self.tab_actions[settings.tab_width].setChecked(True)
        self._refresh_status()

    def _set_setting(self, **changes) -> None:
        settings = dataclasses.replace(self.editor.settings, **changes)
        self.window.prefs.set_editor_settings(settings)
        self.apply_settings(settings)

    def _save_settings(self) -> None:
        settings = self.editor.settings
        self.window.prefs.set_editor_settings(settings)
        self.preview_editor.apply_settings(dataclasses.replace(settings, trim_trailing_whitespace=False))
        self._refresh_status()

    # -- the views --------------------------------------------------------------------------------

    def _after_change(self) -> None:
        """Redo everything that depends on the layer, the text being dirty, or the render status."""
        dirty = self.is_dirty()
        self._last_dirty = dirty
        if not dirty:
            self._moved = False
        layer = next((x for x in self._layers() if x.id == self.layer_id), None)
        self.title_label.setText("" if layer is None else layer.label)
        self.dirty_label.setVisible(dirty)
        self.notice.setVisible(self._moved)  # _moved is false while clean
        editing = self.layer_id is not None and self.preset_id is None
        self.save_code_button.setEnabled(self.layer_id is not None)
        self.convert_button.setEnabled(editing and not dirty and not self._is_python(self.layer_id))
        self.revert_button.setEnabled(dirty and self.preset_id is None)
        self._refresh_list()
        self._refresh_tabs()
        self._refresh_output()
        self._refresh_status()
        self._refresh_running()
        self._refresh_values()

    def _refresh_values(self) -> None:
        """The Values tab follows the layer in the editor (only a Python object has values)."""
        project = self.window.project
        self.values.show_layer(project, self.layer_id)
        python = self._is_python(self.layer_id)
        self.output.setTabEnabled(1, python)
        if not python and self.output.currentIndex() == 1:
            self.output.setCurrentIndex(0)

    def _refresh_status(self) -> None:
        """The strip under the editor: cursor, indent, what the layer is and whether it may run."""
        cursor = self.editor.textCursor()
        self.cursor_label.setText(f"Ln {cursor.blockNumber() + 1}, Col {cursor.positionInBlock() + 1}")
        self.indent_label.setText(f"Spaces: {self.editor.settings.tab_width}")
        if self.layer_id is None:
            self.kind_label.setText("")
            self.trust_label.setText("")
            return
        self.kind_label.setText("Python object" if self._is_python(self.layer_id) else "Manim scene")
        status = self.status(self.layer_id)
        state = "" if status is None else status.state
        self.trust_label.setText(
            {
                "untrusted": "Not run yet - Ctrl+Enter to allow",
                "error": "Error",
                "ready": "Ready",
                "built": "Built",
                "rendering": "Rendering...",
                "queued": "Waiting...",
            }.get(state, "")
        )

    def _refresh_output(self) -> None:
        """The render state under the editor, and the error line tinted in the editor."""
        colours = theme.THEME
        status = self.status(self.layer_id)
        dirty = self.is_dirty()
        line = None
        self.error_label.hide()
        failed = self._failed
        if failed is not None and (failed[0], failed[1]) != (self.layer_id, self.editor.text()):
            failed = self._failed = None  # another layer or other text: that refusal is old
        if failed is not None:  # the code was not applied: why (ADR 0051)
            text, colour = "Not applied", colours.error_text
            self.error_label.show_error(failed[2], None)
            self.error_label.show()
        elif self.layer_id is None:
            text, colour = "", colours.muted
        elif status is None:
            text, colour = "Not rendered yet", colours.muted
        elif status.state == "error":
            text, colour = "Error", colours.error_text
            self.error_label.show_error(status.error, error_line("error", status.line))
            self.error_label.show()
            line = self.error_label.line
            if dirty:
                text += " (from the last run)"
        else:
            text, colour = status.text, colours.muted
            took = self.durations.get(self.layer_id or "")
            if took is not None and took >= 0.05 and status.state in ("ready", "built"):
                text += f" (took {took:.2f} s)"
        if dirty and status is not None and status.state != "error":
            text += " - the editor has changes that were not run (Ctrl+Enter)"
        self.state_label.setText(text)
        self.state_label.setStyleSheet(f"color: {theme.css(colour)};")
        self.editor.set_error_line(None if dirty else line)  # an edited text's lines have moved
        has_error = failed is not None or (status is not None and status.state == "error")
        self.output_toggle.setText("Output  (error)" if has_error else "Output")

    def _sections(self) -> list[Section]:
        layers = self._layers()
        dirty = self.dirty_layers()
        project_rows = []
        for layer in layers:
            status = self.status(layer.id)
            state = status.state if status is not None and status.state in ("error", "untrusted") else ""
            kind = "object" if layer.spec.type in PYTHON_TYPES else "scene"
            tip = {
                "error": "Has an error: see the output",
                "untrusted": "Not run yet: Ctrl+Enter allows it",
            }.get(state, "")
            if layer.id in dirty:
                tip = "Unapplied changes: Run applies them"
            project_rows.append(Row(layer.id, layer.label, kind, "layer", tip, layer.id in dirty, state))
        sections = [
            Section(
                "project",
                "This project",
                tuple(project_rows),
                empty="No code yet - add a layer, a file or a preset",
            )
        ]
        presets = self.window.code_presets.presets()
        for origin, title in PRESET_ORIGINS:
            rows = tuple(
                Row(p.id, p.name, p.kind, "preset", p.description or p.name)
                for p in presets
                if p.origin == origin
            )
            empty = "Import a folder or get presets online" if origin != "builtin" else ""
            sections.append(Section(origin, title, rows, empty=empty))
        return sections

    def _refresh_list(self, force: bool = False) -> None:
        sections = self._sections()
        signature = tuple((s.key, s.rows) for s in sections)
        if signature != self._signature or force:
            self._signature = signature
            current = ("preset", self.preset_id) if self.preset_id else ("layer", self.layer_id)
            self.explorer.blockSignals(True)  # follow the layer without rebuilding under a click
            try:
                self.explorer.set_sections(sections, current if current[1] else None)
            finally:
                self.explorer.blockSignals(False)
            self._refresh_python_templates()
        elif self.preset_id is None:
            self.explorer.blockSignals(True)
            try:
                if self.layer_id is not None:
                    self.explorer.select("layer", self.layer_id)
            finally:
                self.explorer.blockSignals(False)
