"""The Code page (P6b.3, ADR 0041): code layers in a real editor, next to the viewer.

Layout: the project's code layers (and a "New code layer" button) | the editor over the
render output | the viewer. The model, settled in decision session 36:

* **Run only** applies the text: Ctrl+Enter or the Run button trusts the exact text
  (as the Properties code field does, ADR 0019) and applies it as one undo step through
  ``set_param``; typing never reaches the project or starts a render. With unchanged
  text Run only trusts and retries a failed or untrusted render.
* **Drafts**: text not applied yet is kept per layer (``code_drafts``) through layer and
  page switches and layer deletion, and dropped - with a message saying how many - when
  another project is opened. A layer is *dirty* exactly while its editor text differs
  from the project's; the title, the layer list and the render output say so.
* **The project moves underneath** (undo, redo, a Properties edit): a clean editor shows
  the new code; a dirty one keeps its text and shows a notice. **Revert** drops the draft
  and shows the project's code (as one step of the editor's own undo).
* **Errors** from the code renderer show under the editor with their line number; clicking
  moves the cursor to that line (kept inside the text) and tints it.
"""

from __future__ import annotations

import html
from functools import partial

from pydantic import ValidationError
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QKeySequence, QMouseEvent, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core import edits
from ...core.schema import CODE_TYPES
from .. import icons, theme
from ..code_drafts import Drafts, error_line, error_text, moved_on
from ..code_editor import CodeEditor
from ..properties_panel import set_param
from . import Page, Shared

HINT = "Select a code layer, or add one with New code layer."


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


class CodePage(Page):
    name = "code"
    title = "Code"
    icon = "code-page"
    tooltip = "Write and run code layers: an editor with highlighting, errors at their line (Shift+3)"

    def build(self) -> QWidget:
        window = self.window
        self.layer_id: str | None = None  # the layer the editor shows
        self.drafts = Drafts()  # unapplied text of the other layers
        self._base = ""  # the project's code the editor's text was started from
        self._moved = False  # the project's code changed under unapplied text
        self._loading = False
        self._last_dirty: bool | None = None
        self._signature: tuple | None = None
        self._selection_connected = False
        self._sized = False

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)

        left = QWidget()
        column = QVBoxLayout(left)
        heading = QLabel("Code layers")
        heading.setProperty("role", "section")
        self.list = QListWidget()
        self.list.setObjectName("codeLayers")
        self.list.currentItemChanged.connect(self._on_list_current)
        self.new_button = QPushButton(icons.icon("add"), "New code layer")
        self.new_button.setToolTip("Add a code layer with a starter scene")
        self.new_button.clicked.connect(self.new_layer)
        column.addWidget(heading)
        column.addWidget(self.list, 1)
        column.addWidget(self.new_button)

        centre = QWidget()
        stack = QVBoxLayout(centre)
        bar = QHBoxLayout()
        self.title_label = QLabel("")
        self.title_label.setProperty("role", "section")
        self.dirty_label = QLabel("Unapplied changes")
        self.dirty_label.setObjectName("codeDirty")
        self.dirty_label.setStyleSheet(f"color: {theme.css(theme.THEME.warning)};")
        self.revert_button = QPushButton(icons.icon("revert"), "Revert")
        self.revert_button.setToolTip("Drop the changes that were not run and show the layer's code again")
        self.revert_button.clicked.connect(self.revert)
        self.run_button = QPushButton(icons.icon("play"), "Run")
        self.run_button.setToolTip("Apply the code to the layer and run it (Ctrl+Enter)")
        self.run_button.clicked.connect(self.run)
        bar.addWidget(self.title_label)
        bar.addWidget(self.dirty_label)
        bar.addStretch(1)
        bar.addWidget(self.revert_button)
        bar.addWidget(self.run_button)
        self.notice = QLabel(
            "The layer's code changed in the project (undo, redo or Properties) while you were editing. "
            "Your text is kept: Revert shows the project's code, Run replaces it."
        )
        self.notice.setWordWrap(True)
        self.notice.setStyleSheet(f"color: {theme.css(theme.THEME.warning)};")
        self.editor = CodeEditor()
        self.editor.runRequested.connect(self.run)
        self.editor.textChanged.connect(self._on_text_changed)
        self.state_label = QLabel("")
        self.state_label.setWordWrap(True)
        self.state_label.setObjectName("codeState")
        self.error_label = ErrorLine()
        self.error_label.setObjectName("codeError")
        self.error_label.clicked.connect(self.go_to_error)
        output = QWidget()
        lines = QVBoxLayout(output)
        lines.setContentsMargins(0, 0, 0, 0)
        lines.addWidget(self.state_label)
        lines.addWidget(self.error_label)
        stack.addLayout(bar)
        stack.addWidget(self.notice)
        stack.addWidget(self.editor, 1)
        stack.addWidget(output)

        self.split.addWidget(left)
        self.split.addWidget(centre)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)

        for keys in ("Ctrl+Return", "Ctrl+Enter"):  # at once (a button's shortcut animates for 100 ms first)
            shortcut = QShortcut(QKeySequence(keys), self.split)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self.run)
        window.document.reset.connect(self._on_reset)
        window.document.changed.connect(self._on_changed)
        window.code.statusChanged.connect(self._on_status)
        self._set_editor("", 0)
        self._after_change()
        return self.split

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
            self.split.setSizes([200, total * 45 // 100, total - 200 - total * 45 // 100])
        self._refresh_list(force=True)
        self._ensure_layer()
        self._after_change()

    # -- the project ----------------------------------------------------------------------

    def _layers(self) -> list:
        project = self.window.project
        if project is None:
            return []
        return [x for x in project.layers if x.spec is not None and x.spec.type in CODE_TYPES]

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

    def _on_list_current(self, item: QListWidgetItem | None, _previous) -> None:
        if item is not None:
            self.window.selection.select_layer(item.data(Qt.ItemDataRole.UserRole))

    # -- following the project ---------------------------------------------------------------

    def _on_reset(self, _project) -> None:
        """Another project was opened: unapplied text belongs to the old one."""
        dropped = len(self.drafts) + (
            1 if self.layer_id is not None and self.editor.text() != self._base else 0
        )
        self.drafts.clear()
        self.layer_id = None
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
        self._refresh_list()
        if layer_id == self.layer_id:
            self._refresh_output()

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
        if layer_id is None or project is None:
            return
        text = self.editor.text()
        self.window.trust.trust([text])  # code the user applies here is theirs (ADR 0019)
        if text != self._code_of(layer_id):
            try:
                self.window.builds.submit(
                    partial(set_param, layer_id=layer_id, name="code", value=text), "Run code"
                )
            except (edits.EditError, ValidationError) as error:
                self.window.statusBar().showMessage(f"Run code: {error}", 10000)
            return  # the change reaches _on_changed, which marks the editor clean
        status = self.window.code.status(layer_id)
        self.window.code.trust_layers(project, [layer_id])
        if status is not None and status.state == "error":
            self.window.code.retry(layer_id)

    def revert(self) -> None:
        """Drop the unapplied text: show the layer's code again."""
        code = self._code_of(self.layer_id)
        if code is None or not self.is_dirty():
            return
        self._base, self._moved = code, False
        self.editor.replace_text(code)  # one step of the editor's own undo
        self._last_dirty = None
        self._after_change()

    def new_layer(self) -> None:
        if self.window.project is None:
            self.window.statusBar().showMessage("Create or open a project first.", 5000)
            return
        self.window.layers.add_object("Code")  # selects it; the page follows the selection

    def go_to_error(self) -> None:
        """Move the cursor to the line the render error points at."""
        if self.error_label.line:
            self.editor.go_to_line(self.error_label.line)

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
        self.run_button.setEnabled(self.layer_id is not None)
        self.revert_button.setEnabled(dirty)
        self._refresh_list()
        self._refresh_output()

    def _refresh_output(self) -> None:
        """The render state under the editor, and the error line tinted in the editor."""
        colours = theme.THEME
        status = self.window.code.status(self.layer_id) if self.layer_id else None
        dirty = self.is_dirty()
        line = None
        self.error_label.hide()
        if self.layer_id is None:
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
        if dirty and status is not None and status.state != "error":
            text += " - the editor has changes that were not run (Ctrl+Enter)"
        self.state_label.setText(text)
        self.state_label.setStyleSheet(f"color: {theme.css(colour)};")
        self.editor.set_error_line(None if dirty else line)  # an edited text's lines have moved

    def _refresh_list(self, force: bool = False) -> None:
        layers = self._layers()
        dirty = self.dirty_layers()
        failed = {
            x.id for x in layers if (s := self.window.code.status(x.id)) is not None and s.state == "error"
        }
        signature = tuple((x.id, x.name or x.id, x.id in dirty, x.id in failed) for x in layers)
        if signature != self._signature or force:
            self._signature = signature
            with QSignalBlocker(self.list):
                self.list.clear()
                for layer in layers:
                    text = layer.label
                    if layer.id in dirty:
                        text += " *"
                    if layer.id in failed:
                        text += "  (error)"
                    item = QListWidgetItem(text)
                    item.setData(Qt.ItemDataRole.UserRole, layer.id)
                    if layer.id in dirty:
                        item.setToolTip("Unapplied changes: Run applies them")
                    self.list.addItem(item)
        with QSignalBlocker(self.list):  # follow the layer without rebuilding under a click
            for row in range(self.list.count()):
                if self.list.item(row).data(Qt.ItemDataRole.UserRole) == self.layer_id:
                    self.list.setCurrentRow(row)
                    break
            else:
                self.list.setCurrentRow(-1)
