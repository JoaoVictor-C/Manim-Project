"""Quick open (P12.5): type a few letters, press Enter, and the layer or preset is open.

A small window with a search field over a list, like a code editor's Ctrl+P. Matching is by letters
in order (``mtx`` finds ``Matrix``), best matches first: a match at the start, or at the start of a
word, ranks higher than letters spread through the name.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget


@dataclass(frozen=True)
class QuickItem:
    source: str  # "layer" or "preset"
    key: str
    label: str
    detail: str = ""  # the section it is in: "Python object", "Scene", "Built in preset"...


def score(query: str, text: str) -> int | None:
    """How well ``query``'s letters appear in order in ``text`` (higher is better); None: they do not."""
    query, text = query.casefold(), text.casefold()
    if not query:
        return 0
    position, total, last = 0, 0, -2
    for letter in query:
        found = text.find(letter, position)
        if found < 0:
            return None
        total += 10
        if found == last + 1:
            total += 8  # letters next to each other
        if found == 0:
            total += 12  # the start
        elif not text[found - 1].isalnum():
            total += 6  # the start of a word
        total -= min(found - position, 5)  # a long gap costs a little
        last = found
        position = found + 1
    return total - len(text) // 8  # a shorter name is a closer match


def rank(items: list[QuickItem], query: str) -> list[QuickItem]:
    """The items that match ``query``, best first (the original order for ties)."""
    scored = []
    for order, item in enumerate(items):
        value = score(query, item.label)
        if value is not None:
            scored.append((-value, order, item))
    return [item for _, _, item in sorted(scored, key=lambda t: (t[0], t[1]))]


class QuickOpen(QDialog):
    def __init__(self, items: list[QuickItem], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Go to")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setMinimumWidth(420)
        self.items = items
        self.chosen: QuickItem | None = None
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a name to open a layer or a preset")
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._accept_current)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName("quickOpenList")
        self.list.itemActivated.connect(lambda _item: self._accept_current())
        self.list.itemClicked.connect(lambda _item: self._accept_current())
        layout.addWidget(self.list)
        self.shown: list[QuickItem] = []
        self._filter("")
        self.search.setFocus()

    def _filter(self, text: str) -> None:
        self.shown = rank(self.items, text.strip())
        self.list.clear()
        for item in self.shown:
            entry = QListWidgetItem(f"{item.label}    {item.detail}" if item.detail else item.label)
            self.list.addItem(entry)
        if self.shown:
            self.list.setCurrentRow(0)

    def _accept_current(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self.shown):
            self.chosen = self.shown[row]
            self.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            step = 1 if event.key() == Qt.Key.Key_Down else -1
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, self.list.currentRow() + step)))
            return
        super().keyPressEvent(event)
