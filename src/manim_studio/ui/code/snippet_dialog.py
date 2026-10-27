"""The snippet gallery (P13.3): search small pieces of Manim, read one, insert it at the cursor."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.assist import snippets
from ...core.assist.snippets import Snippet
from ..style import theme
from .dialog_frame import DialogFrame


class SnippetDialog(QDialog):
    def __init__(self, pool: tuple[Snippet, ...] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Insert Snippet")
        self.resize(760, 460)
        self.pool = snippets.SNIPPETS if pool is None else tuple(pool)
        self.chosen: Snippet | None = None
        self.shown: list[Snippet] = []
        frame = DialogFrame(self, "code", "Insert snippet", "Small pieces of Manim to start from")
        outer = frame.body
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search: circle, matrix, graph, updater...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self.accept)
        outer.addWidget(self.search)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.list = QListWidget()
        self.list.setObjectName("snippetList")
        self.list.currentRowChanged.connect(self._show)
        self.list.itemActivated.connect(lambda _item: self.accept())
        row.addWidget(self.list, 2)
        right = QVBoxLayout()
        right.setSpacing(8)
        self.description = QLabel("")
        self.description.setWordWrap(True)
        self.description.setProperty("role", "muted")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(theme.mono_font())
        self.preview.setObjectName("snippetPreview")
        right.addWidget(self.description)
        right.addWidget(self.preview, 1)
        row.addLayout(right, 3)
        outer.addLayout(row, 1)
        hint = QLabel("Inserted at the cursor. Tab moves between the places to fill in; Esc stops.")
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.insert_button = buttons.addButton("Insert", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        frame.add_footer(hint, 1)
        frame.add_buttons(buttons)
        self._filter("")
        self.search.setFocus()

    def _filter(self, text: str) -> None:
        self.shown = snippets.search(text, self.pool)
        self.list.clear()
        for snippet in self.shown:
            self.list.addItem(QListWidgetItem(f"{snippet.title}    {snippet.category}"))
        if self.shown:
            self.list.setCurrentRow(0)
        else:
            self._show(-1)

    def _show(self, row: int) -> None:
        snippet = self.shown[row] if 0 <= row < len(self.shown) else None
        self.description.setText(snippet.description if snippet else "No snippet matches.")
        self.preview.setPlainText(snippets.expand(snippet.code)[0] if snippet else "")
        self.insert_button.setEnabled(snippet is not None)

    def accept(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.shown):
            self.chosen = self.shown[row]
            super().accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.search.hasFocus():
            step = 1 if event.key() == Qt.Key.Key_Down else -1
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, self.list.currentRow() + step)))
            return
        super().keyPressEvent(event)
