"""A segmented control (Lumen, ADR 0063): a few exclusive choices side by side in one rounded track.

``Segmented`` reads like a combo box so a dialog can swap one for the other: ``addItem(text, data)``,
``currentData()``, ``currentIndex()``, ``setCurrentIndex()``, ``findData()`` and the ``currentIndexChanged``
signal. The chosen segment sits on the raised tint; the colours come from the stylesheet.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from . import theme


def _rules(c: theme.Colours) -> str:
    return f"""
QWidget#segmented {{
    background: {c.field}; border: 1px solid {theme.css(c.line)}; border-radius: {theme.RADIUS}px;
}}
QPushButton[seg="true"] {{
    background: transparent; color: {c.muted}; border: 1px solid transparent;
    border-radius: {theme.RADIUS_SMALL}px; padding: 4px 12px; font-weight: 550; min-height: 18px;
}}
QPushButton[seg="true"]:hover {{ color: {c.text}; background: transparent; }}
QPushButton[seg="true"]:checked {{
    background: {c.surface_3}; color: {c.text}; border-color: {theme.css(c.line_strong)};
}}
QPushButton[seg="true"]:disabled {{ color: {c.disabled}; }}
"""


theme.register_rules(_rules)


class Segmented(QWidget):
    currentIndexChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("segmented")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(2)
        self._row = row
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QPushButton] = []
        self._data: list[object] = []
        self._current = -1

    def addItem(self, text: str, data: object = None, tip: str = "") -> QPushButton:
        button = QPushButton(text)
        button.setProperty("seg", True)
        button.setCheckable(True)
        if tip:
            button.setToolTip(tip)
        index = len(self._buttons)
        self._group.addButton(button, index)
        self._row.addWidget(button)
        self._buttons.append(button)
        self._data.append(data)
        button.clicked.connect(lambda _checked=False, k=index: self.setCurrentIndex(k))
        if self._current < 0:
            self.setCurrentIndex(0)
        return button

    def count(self) -> int:
        return len(self._buttons)

    def button(self, index: int) -> QPushButton:
        return self._buttons[index]

    def itemText(self, index: int) -> str:
        return self._buttons[index].text()

    def currentIndex(self) -> int:
        return self._current

    def currentData(self) -> object:
        return self._data[self._current] if 0 <= self._current < len(self._data) else None

    def findData(self, data: object) -> int:
        for k, value in enumerate(self._data):
            if value == data:
                return k
        return -1

    def setCurrentIndex(self, index: int) -> None:
        if not 0 <= index < len(self._buttons):
            return
        self._buttons[index].setChecked(True)
        if index != self._current:
            self._current = index
            self.currentIndexChanged.emit(index)


class SegmentedControl(Segmented):
    """The same control addressed by key: ``add(key, label, tip)``, ``current()`` (the chosen key, or None),
    ``set_current(key)`` and the ``changed(key)`` signal (the Deliver page's Encoder)."""

    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.currentIndexChanged.connect(lambda _k: self.changed.emit(str(self.current() or "")))

    def add(self, key: str, label: str, tip: str = "") -> QPushButton:
        return self.addItem(label, key, tip)

    def current(self) -> str | None:
        data = self.currentData()
        return None if data is None else str(data)

    def set_current(self, key: str) -> None:
        self.setCurrentIndex(self.findData(key))
