"""Small editor widgets for the properties panel (S2.5).

Every field shows a value with ``set_value(value, pending=False)`` (signals
blocked, so showing never commits) and calls ``on_commit(value)`` once per
finished edit — Enter, focus out, a step of the arrows, a pick from a list —
never per keystroke. ``None`` means "not set / default" where a field allows it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QWidget,
)

from . import theme

Commit = Callable[[Any], None]
PENDING_STYLE = f"font-style: italic; color: {theme.css(theme.THEME.muted)};"  # waiting for the build worker


class Field:
    widget: QWidget

    def __init__(self, on_commit: Commit) -> None:
        self.on_commit = on_commit
        self._shown: Any = None

    def set_value(self, value: Any, pending: bool = False) -> None:
        self._shown = value
        with QSignalBlocker(self.widget):
            self._show(value)
        self.widget.setStyleSheet(PENDING_STYLE if pending else "")
        self.widget.setToolTip("Building... the change appears when it is ready." if pending else "")

    def has_focus(self) -> bool:
        focused = QApplication.focusWidget()
        return focused is not None and (focused is self.widget or self.widget.isAncestorOf(focused))

    def commit(self, value: Any) -> None:
        """Commit ``value`` as if the user had entered it (also used by tests)."""
        if value != self._shown:
            self._shown = value
            self.on_commit(value)

    def _show(self, value: Any) -> None:
        raise NotImplementedError


class FloatField(Field):
    """A number; with ``none_text`` the lowest value means "not set"."""

    def __init__(
        self,
        on_commit: Commit,
        minimum: float = -1e6,
        maximum: float = 1e6,
        step: float = 0.1,
        decimals: int = 3,
        none_text: str | None = None,
        suffix: str = "",
    ) -> None:
        super().__init__(on_commit)
        box = QDoubleSpinBox()
        box.setDecimals(decimals)
        self._none = minimum - step if none_text else None
        box.setRange(self._none if none_text else minimum, maximum)
        box.setSingleStep(step)
        box.setKeyboardTracking(False)  # valueChanged on Enter / focus out / arrows only
        box.setAccelerated(True)
        if none_text:
            box.setSpecialValueText(none_text)
        if suffix:
            box.setSuffix(suffix)
        box.setCorrectionMode(QAbstractSpinBox.CorrectionMode.CorrectToNearestValue)
        box.valueChanged.connect(lambda v: self.commit(None if self._is_none(v) else v))
        self.widget = box

    def _is_none(self, value: float) -> bool:
        return self._none is not None and value <= self._none + 1e-9

    def _show(self, value: Any) -> None:
        self.widget.setValue(self._none if value is None else float(value))


class IntField(Field):
    def __init__(self, on_commit: Commit, minimum: int = 0, maximum: int = 1000) -> None:
        super().__init__(on_commit)
        box = QSpinBox()
        box.setRange(minimum, maximum)
        box.setKeyboardTracking(False)
        box.valueChanged.connect(self.commit)
        self.widget = box

    def _show(self, value: Any) -> None:
        self.widget.setValue(int(value))


class TextField(Field):
    def __init__(self, on_commit: Commit, placeholder: str = "") -> None:
        super().__init__(on_commit)
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.editingFinished.connect(lambda: self.commit(edit.text()))
        self.widget = edit

    def _show(self, value: Any) -> None:
        self.widget.setText("" if value is None else str(value))


class _PlainText(QPlainTextEdit):
    finished = Signal()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.finished.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier
        ):
            self.finished.emit()
            return
        super().keyPressEvent(event)


class LongTextField(Field):
    """Multi-line text (LaTeX): commits on focus out or Ctrl+Enter."""

    def __init__(self, on_commit: Commit) -> None:
        super().__init__(on_commit)
        edit = _PlainText()
        edit.setTabChangesFocus(True)
        edit.setFixedHeight(64)
        edit.setPlaceholderText("Ctrl+Enter to apply")
        edit.finished.connect(lambda: self.commit(edit.toPlainText()))
        self.widget = edit

    def _show(self, value: Any) -> None:
        if self.widget.toPlainText() != value:
            self.widget.setPlainText("" if value is None else str(value))


class CodeField(LongTextField):
    """Python source for a code layer (ADR 0019): monospace, tall, Tab indents."""

    def __init__(self, on_commit: Commit) -> None:
        super().__init__(on_commit)
        edit = self.widget
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        edit.setFont(font)
        edit.setTabChangesFocus(False)
        edit.setTabStopDistance(4 * edit.fontMetrics().horizontalAdvance(" "))
        edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        edit.setFixedHeight(280)
        edit.setPlaceholderText("class MyScene(Scene): ...   (Ctrl+Enter to apply)")


class BoolField(Field):
    def __init__(self, on_commit: Commit, text: str = "") -> None:
        super().__init__(on_commit)
        box = QCheckBox(text)
        box.toggled.connect(self.commit)
        self.widget = box

    def _show(self, value: Any) -> None:
        self.widget.setChecked(bool(value))


class ChoiceField(Field):
    """A list of ``(label, value)``; values may be any comparable objects."""

    def __init__(
        self,
        on_commit: Commit,
        choices: Sequence[tuple[str, Any]] = (),
        label_for: Callable[[Any], str] = str,
    ) -> None:
        super().__init__(on_commit)
        self.label_for = label_for  # how a value that is not among the choices is shown
        box = QComboBox()
        self.widget = box
        self.set_choices(choices)
        box.activated.connect(lambda index: self.commit(box.itemData(index)))

    def set_choices(self, choices: Sequence[tuple[str, Any]]) -> None:
        self._values = [value for _, value in choices]
        with QSignalBlocker(self.widget):
            self.widget.clear()
            for label, value in choices:
                self.widget.addItem(label, value)

    def _show(self, value: Any) -> None:
        if value not in self._values:
            self.widget.addItem(self.label_for(value), value)  # e.g. a custom curve, or set in JSON
            self._values.append(value)
        self.widget.setCurrentIndex(self._values.index(value))


class PointField(Field):
    """An (x, y) pair."""

    def __init__(self, on_commit: Commit, step: float = 0.1) -> None:
        super().__init__(on_commit)
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.x, self.y = QDoubleSpinBox(), QDoubleSpinBox()
        for box, prefix in ((self.x, "x "), (self.y, "y ")):
            box.setRange(-1000, 1000)
            box.setDecimals(3)
            box.setSingleStep(step)
            box.setKeyboardTracking(False)
            box.setPrefix(prefix)
            box.valueChanged.connect(lambda _v: self.commit((self.x.value(), self.y.value())))
            layout.addWidget(box)
        self.widget = widget

    def _show(self, value: Any) -> None:
        for box, v in zip((self.x, self.y), value, strict=True):
            with QSignalBlocker(box):
                box.setValue(float(v))


class PathField(Field):
    def __init__(
        self, on_commit: Commit, file_filter: str = "Images (*.png *.jpg *.jpeg *.bmp *.gif)"
    ) -> None:
        super().__init__(on_commit)
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.editingFinished.connect(lambda: self.commit(self.edit.text()))
        browse = QToolButton(text="...")
        browse.clicked.connect(self._browse)
        layout.addWidget(self.edit, 1)
        layout.addWidget(browse)
        self._filter = file_filter
        self.widget = widget

    def _browse(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self.widget, "Choose file", self.edit.text(), self._filter)
        if name:
            self.edit.setText(name)
            self.commit(name)

    def _show(self, value: Any) -> None:
        self.edit.setText("" if value is None else str(value))


def pick_colour(parent: QWidget | None, current: str | None = None) -> str | None:
    """Ask for a colour (``#rrggbb``), starting from ``current``; None when cancelled."""
    white = QColor(255, 255, 255)  # content: Manim's default fill, not a theme colour
    start = QColor(current) if current else white
    color = QColorDialog.getColor(start, parent, "Choose colour")
    return color.name() if color.isValid() else None


class ColorField(Field):
    """A colour button (``#rrggbb``) with a reset to "default" (None)."""

    def __init__(self, on_commit: Commit) -> None:
        super().__init__(on_commit)
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton()
        self.button.clicked.connect(self._pick)
        reset = QToolButton(text="x")
        reset.setToolTip("Use the default colour")
        reset.clicked.connect(lambda: self.commit(None))
        layout.addWidget(self.button, 1)
        layout.addWidget(reset)
        self.widget = widget

    def _pick(self) -> None:
        colour = pick_colour(self.widget, self._shown)
        if colour is not None:
            self.commit(colour)

    def _show(self, value: Any) -> None:
        self.button.setText(value or "Default")
        self.button.setStyleSheet(f"background: {value}; color: {theme.readable_on(value)};" if value else "")
