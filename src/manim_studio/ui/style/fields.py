"""Small editor widgets for the properties panel (S2.5; Lumen, ADR 0063).

Every field shows a value with ``set_value(value, pending=False)`` (signals
blocked, so showing never commits) and calls ``on_commit(value)`` once per
finished edit — Enter, focus out, a step of the arrows, a pick from a list, the
end of a drag — never per keystroke. ``None`` means "not set / default" where a
field allows it.

In Lumen a number field is 30 px high with its label *inside* it at the left and its unit at the right;
dragging the label sideways scrubs the number (``scrub_label``: Shift fine, Ctrl coarse, a double-click
types) and commits once when the drag ends. A colour field is a swatch and the hex; opacity is a slider
with a readout. ``Section`` is a collapsible group of fields with a hairline under it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme
from .scrub_label import ScrubLabel

Commit = Callable[[Any], None]
FIELD_HEIGHT = 30  # px: a control (Lumen)
INSIDE_GAP = 6  # px between an inside label and the text
PENDING_STYLE = "font-style: italic;"  # waiting for the build worker (the colour is the ``pending`` rule's)
PENDING_TIP = "Building... the change appears when it is ready."


def _rules(c: theme.Colours) -> str:
    r = theme.RADIUS
    return f"""
QPushButton#colourField {{
    background: {c.field}; color: {c.text}; border: 1px solid {theme.css(c.line)}; border-radius: {r}px;
    text-align: left; padding: 5px 10px 5px 36px; font-weight: 500;
}}
QPushButton#colourField:hover {{ border-color: {theme.css(c.line_strong)}; background: {c.field}; }}
QPushButton#colourField:focus {{ border-color: {c.accent}; }}
QPushButton#colourField:disabled {{ color: {c.disabled}; }}
QWidget[pending="true"] QLabel#sliderReadout {{ color: {c.muted}; }}
QLabel#sliderReadout {{ color: {c.text}; }}
"""


theme.register_rules(_rules)


# -- labels and units inside a field ---------------------------------------------------------------


class _Inside:
    """A label at the left and a unit at the right, drawn inside a line edit or a spin box (their text is
    moved aside with text margins). The label scrubs when the host can (``scrub``)."""

    def __init__(self, host: QWidget, edit: QLineEdit, scrub: bool) -> None:
        self.host, self.edit = host, edit
        self.label = ScrubLabel("", host)
        self.label.setFont(theme.font("section"))
        self.label.setProperty("role", "hint")
        self.label.set_scrubbable(scrub)
        self.label.hide()
        self.unit = QLabel("", host)
        self.unit.setFont(theme.font("caption"))
        self.unit.setProperty("role", "hint")
        self.unit.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.unit.hide()
        self.special = lambda: False  # True while the host shows its special value ("Auto")

    def set_label(self, text: str) -> None:
        self.label.setText(text)
        self.label.setVisible(bool(text))
        self.label.setAccessibleName(text)
        self.place()

    def set_unit(self, text: str) -> None:
        self.unit.setText(text)
        self.place()

    def place(self) -> None:
        """Put the label and the unit over the ends of the text area and keep the text clear of them."""
        host, edit = self.host, self.edit
        area = edit.geometry() if edit is not host else host.rect().adjusted(theme.SPACE + 5, 0, -9, 0)
        left = right = 0
        if self.label.text():
            self.label.adjustSize()
            width = self.label.sizeHint().width()
            self.label.setGeometry(area.left(), 0, width, host.height())
            left = width + INSIDE_GAP
        show_unit = bool(self.unit.text()) and not self.special()
        self.unit.setVisible(show_unit)
        if show_unit:
            width = self.unit.sizeHint().width()
            self.unit.setGeometry(area.right() - width + 1, 0, width, host.height())
            right = width + INSIDE_GAP
        edit.setTextMargins(left, 0, right, 0)


class _ScrubBox:
    """What the number fields' spin boxes share: an inside label that scrubs, a unit, 30 px, mono digits."""

    inside: _Inside
    _start = 0.0

    def _setup(self) -> None:
        self.setMinimumHeight(FIELD_HEIGHT)
        self.setFont(theme.font("body", kind="mono"))
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.inside = _Inside(self, self.lineEdit(), scrub=True)
        self.inside.special = lambda: bool(self.specialValueText()) and self.value() == self.minimum()
        self.lineEdit().textChanged.connect(lambda _text: self.inside.place())
        label = self.inside.label
        label.scrubStarted.connect(self._scrub_started)
        label.scrubbed.connect(self._scrub)
        label.scrubFinished.connect(self._scrub_finished)
        label.doubleClicked.connect(self._type)

    def set_label(self, text: str) -> None:
        self.inside.set_label(text)
        if len(text) > 2:  # "Stroke ... 0.0": the number goes to the right, as in the mock-up
            self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def set_unit(self, text: str) -> None:
        self.inside.set_unit(text)

    def _scrub_started(self) -> None:
        self._start = self.value()

    def _scrubbed_value(self, steps: float):
        return self._start + steps * self.singleStep()

    def _scrub(self, steps: float) -> None:
        with QSignalBlocker(self):  # shown while dragging, committed once at the end
            self.setValue(self._scrubbed_value(steps))

    def _scrub_finished(self) -> None:
        final = self.value()
        with QSignalBlocker(self):
            self.setValue(self._start)
        self.setValue(final)  # one valueChanged: one commit, one undo step

    def _type(self) -> None:
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.selectAll()


class ScrubDoubleSpinBox(_ScrubBox, QDoubleSpinBox):
    """A number with its label inside (drag the label to scrub) and its unit at the right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        QDoubleSpinBox.__init__(self, parent)
        self._setup()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.inside.place()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.inside.place()


class ScrubSpinBox(_ScrubBox, QSpinBox):
    """A whole number with its label inside (drag the label to scrub)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        QSpinBox.__init__(self, parent)
        self._setup()

    def _scrubbed_value(self, steps: float):
        return round(self._start + steps * self.singleStep())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.inside.place()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.inside.place()


class LabelledLineEdit(QLineEdit):
    """A line edit with its label inside at the left (the label does not scrub)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(FIELD_HEIGHT)
        self.inside = _Inside(self, self, scrub=False)
        self.inside.label.doubleClicked.connect(self.selectAll)
        self.inside.label.setCursor(Qt.CursorShape.IBeamCursor)

    def set_label(self, text: str) -> None:
        self.inside.set_label(text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.inside.place()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.inside.place()


def inside_label(widget: QWidget, text: str) -> QWidget:
    """Give a ``LabelledLineEdit`` or a scrubbing spin box its inside label; returns the widget."""
    widget.set_label(text)
    return widget


# -- the fields ------------------------------------------------------------------------------------


class Field:
    widget: QWidget

    def __init__(self, on_commit: Commit) -> None:
        self.on_commit = on_commit
        self._shown: Any = None

    def set_value(self, value: Any, pending: bool = False) -> None:
        self._shown = value
        with QSignalBlocker(self.widget):
            self._show(value)
        if bool(self.widget.property("pending")) != pending:
            self.widget.setProperty("pending", pending)
            self.widget.style().unpolish(self.widget)
            self.widget.style().polish(self.widget)
        self.widget.setStyleSheet(PENDING_STYLE if pending else "")
        self.widget.setToolTip(PENDING_TIP if pending else "")

    def has_focus(self) -> bool:
        focused = QApplication.focusWidget()
        return focused is not None and (focused is self.widget or self.widget.isAncestorOf(focused))

    def commit(self, value: Any) -> None:
        """Commit ``value`` as if the user had entered it (also used by tests)."""
        if value != self._shown:
            self._shown = value
            self.on_commit(value)

    def set_label(self, text: str) -> bool:
        """Show ``text`` inside the field when it can (True); else the caller shows it above (False)."""
        return False

    def _show(self, value: Any) -> None:
        raise NotImplementedError


class FloatField(Field):
    """A number; with ``none_text`` the lowest value means "not set". ``suffix`` is shown as a unit at
    the right of the field (not in its text)."""

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
        box = ScrubDoubleSpinBox()
        box.setDecimals(decimals)
        self._none = minimum - step if none_text else None
        box.setRange(self._none if none_text else minimum, maximum)
        box.setSingleStep(step)
        box.setKeyboardTracking(False)  # valueChanged on Enter / focus out / arrows only
        box.setAccelerated(True)
        if none_text:
            box.setSpecialValueText(none_text)
        if suffix:
            box.set_unit(suffix.strip())
        box.setCorrectionMode(QAbstractSpinBox.CorrectionMode.CorrectToNearestValue)
        box.valueChanged.connect(lambda v: self.commit(None if self._is_none(v) else v))
        self.widget = box

    def set_label(self, text: str) -> bool:
        self.widget.set_label(text)
        return True

    def _is_none(self, value: float) -> bool:
        return self._none is not None and value <= self._none + 1e-9

    def _show(self, value: Any) -> None:
        self.widget.setValue(self._none if value is None else float(value))
        self.widget.inside.place()


class IntField(Field):
    def __init__(self, on_commit: Commit, minimum: int = 0, maximum: int = 1000) -> None:
        super().__init__(on_commit)
        box = ScrubSpinBox()
        box.setRange(minimum, maximum)
        box.setKeyboardTracking(False)
        box.valueChanged.connect(self.commit)
        self.widget = box

    def set_label(self, text: str) -> bool:
        self.widget.set_label(text)
        return True

    def _show(self, value: Any) -> None:
        self.widget.setValue(int(value))


class TextField(Field):
    def __init__(self, on_commit: Commit, placeholder: str = "") -> None:
        super().__init__(on_commit)
        edit = LabelledLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.editingFinished.connect(lambda: self.commit(edit.text()))
        self.widget = edit

    def set_label(self, text: str) -> bool:
        self.widget.set_label(text)
        return True

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
        edit.setFont(theme.font("body", kind="mono"))
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
        edit.setFont(theme.font("body", kind="mono"))
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


class _Diamond(QToolButton):
    """A keyframe diamond: filled in the key colour when the property has keys, an outline when not."""

    SIZE = 24

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoRaise(True)

    def sizeHint(self) -> QSize:
        return QSize(self.SIZE, self.SIZE)

    def paintEvent(self, _event) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.underMouse() and self.isEnabled():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.qcolor(c.hover))
            painter.drawRoundedRect(QRectF(self.rect()), theme.RADIUS_SMALL, theme.RADIUS_SMALL)
        centre, half = QRectF(self.rect()).center(), 5.0
        diamond = QPolygonF(
            [
                QPointF(centre.x(), centre.y() - half),
                QPointF(centre.x() + half, centre.y()),
                QPointF(centre.x(), centre.y() + half),
                QPointF(centre.x() - half, centre.y()),
            ]
        )
        if not self.isEnabled():
            painter.setPen(QPen(theme.qcolor(c.disabled), 1.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        elif self.isChecked():
            painter.setPen(QPen(theme.qcolor(c.key_edge), 1.0))
            painter.setBrush(theme.qcolor(c.key))
        else:
            painter.setPen(QPen(theme.qcolor(c.text if self.underMouse() else c.faint), 1.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(diamond)
        painter.end()


class KeyToggle(Field):
    """Keyframes on or off for one property (ADR 0016), as a diamond beside its value."""

    def __init__(self, on_commit: Commit, tooltip: str = "") -> None:
        super().__init__(on_commit)
        button = _Diamond()
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip or "Keyframes")
        button.toggled.connect(self.commit)
        self.widget = button

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
        box.setMinimumHeight(FIELD_HEIGHT)
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
    """An (x, y) pair: two number fields labelled X and Y inside, side by side."""

    def __init__(self, on_commit: Commit, step: float = 0.1) -> None:
        super().__init__(on_commit)
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2 * theme.SPACE)
        self.x, self.y = ScrubDoubleSpinBox(), ScrubDoubleSpinBox()
        for box, label in ((self.x, "X"), (self.y, "Y")):
            box.setRange(-1000, 1000)
            box.setDecimals(3)
            box.setSingleStep(step)
            box.setKeyboardTracking(False)
            box.set_label(label)
            box.valueChanged.connect(lambda _v: self.commit((self.x.value(), self.y.value())))
            layout.addWidget(box, 1)
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
        layout.setSpacing(theme.SPACE)
        self.edit = QLineEdit()
        self.edit.setMinimumHeight(FIELD_HEIGHT)
        self.edit.editingFinished.connect(lambda: self.commit(self.edit.text()))
        browse = QToolButton(text="...")
        browse.setIcon(icons.icon("open", tint="muted"))
        browse.setToolTip("Choose a file")
        browse.setFixedSize(FIELD_HEIGHT, FIELD_HEIGHT)
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


class SwatchButton(QPushButton):
    """A field-shaped button: a swatch of ``colour`` (a document colour, or None for "default") and its
    text. The swatch is painted from the colour and the theme's lines when it is drawn."""

    SWATCH = 18

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("colourField")
        self.colour: str | None = None
        self.setMinimumHeight(FIELD_HEIGHT)
        self.setFont(theme.font("body", kind="mono"))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_colour(self, colour: str | None) -> None:
        self.colour = colour
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(10, (self.height() - self.SWATCH) / 2, self.SWATCH, self.SWATCH)
        path = QPainterPath()
        path.addRoundedRect(box, 6, 6)
        fill = QColor(self.colour) if self.colour else None  # content: the document's colour
        if fill is not None and fill.isValid():
            painter.fillPath(path, fill)
        else:
            painter.fillPath(path, theme.qcolor(c.panel))
            painter.setPen(QPen(theme.qcolor(c.faint), 1.2))
            painter.drawLine(box.bottomLeft() + QPointF(4, -4), box.topRight() + QPointF(-4, 4))
        painter.setPen(QPen(theme.qcolor(c.line_strong), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()


class ColorField(Field):
    """A colour (``#rrggbb``): a swatch and its hex, clicking opens the picker; x goes back to the default
    (None)."""

    def __init__(self, on_commit: Commit) -> None:
        super().__init__(on_commit)
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE)
        self.button = SwatchButton()
        self.button.setToolTip("Choose the colour")
        self.button.clicked.connect(self._pick)
        reset = QToolButton(text="x")
        reset.setIcon(icons.icon("close", tint="muted"))
        reset.setToolTip("Use the default colour")
        reset.setAccessibleName("Use the default colour")
        reset.setFixedSize(26, 26)
        reset.clicked.connect(lambda: self.commit(None))
        layout.addWidget(self.button, 1)
        layout.addWidget(reset)
        self.reset_button = reset
        self.widget = widget

    def _pick(self) -> None:
        colour = pick_colour(self.widget, self._shown)
        if colour is not None:
            self.commit(colour)

    def _show(self, value: Any) -> None:
        self.button.setText(value or "Default")
        self.button.set_colour(value or None)


class SliderBox(QWidget):
    """A slider with the accent gradient and a mono readout (``value`` in ``minimum..maximum``)."""

    STEPS = 1000

    def __init__(self, minimum: float = 0.0, maximum: float = 1.0, percent: bool = True) -> None:
        super().__init__()
        self._min, self._max, self.percent = minimum, maximum, percent
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self.STEPS)
        self.slider.setPageStep(self.STEPS // 10)
        self.slider.setSingleStep(self.STEPS // 100)
        self.readout = QLabel()
        self.readout.setObjectName("sliderReadout")
        self.readout.setFont(theme.font("body", kind="mono"))
        self.readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.readout.setMinimumWidth(self.readout.fontMetrics().horizontalAdvance("100%") + 4)
        self.setMinimumHeight(FIELD_HEIGHT - 6)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.readout)
        self.slider.valueChanged.connect(lambda _v: self._show_readout())
        self._show_readout()

    def minimum(self) -> float:
        return self._min

    def maximum(self) -> float:
        return self._max

    def value(self) -> float:
        span = self._max - self._min
        return round(self._min + span * self.slider.value() / self.STEPS, 4)

    def setValue(self, value: float) -> None:
        span = self._max - self._min or 1.0
        self.slider.setValue(round((min(max(float(value), self._min), self._max) - self._min) / span * self.STEPS))
        self._show_readout()

    def _show_readout(self) -> None:
        value = self.value()
        self.readout.setText(f"{round(value * 100)}%" if self.percent else f"{value:.2f}")


class SliderField(Field):
    """A number on a slider (opacity): commits when the drag ends, or at once from the keyboard."""

    def __init__(self, on_commit: Commit, minimum: float = 0.0, maximum: float = 1.0) -> None:
        super().__init__(on_commit)
        box = SliderBox(minimum, maximum)
        box.slider.valueChanged.connect(lambda _v: None if box.slider.isSliderDown() else self.commit(box.value()))
        box.slider.sliderReleased.connect(lambda: self.commit(box.value()))
        self.widget = box

    def set_value(self, value: Any, pending: bool = False) -> None:
        if self.widget.slider.isSliderDown():
            return  # the user is dragging it
        super().set_value(value, pending)

    def _show(self, value: Any) -> None:
        with QSignalBlocker(self.widget.slider):
            self.widget.setValue(1.0 if value is None else float(value))


# -- sections and captions -------------------------------------------------------------------------


def caption(text: str) -> QLabel:
    """The small muted label above a field that cannot hold its label inside (a list, a colour)."""
    label = QLabel(text)
    label.setFont(theme.font("caption"))
    label.setProperty("role", "muted")
    return label


class _ClickLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class Section(QWidget):
    """A collapsible group of fields: a header (caret, bold title, actions at the right) over a body,
    with 14 px padding and a hairline under it. ``toggled(collapsed)`` follows the caret."""

    toggled = Signal(bool)

    def __init__(self, title: str, parent: QWidget | None = None, *, collapsible: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("propertySection")
        self.rule = True  # draw the hairline under it
        self._collapsed = False
        column = QVBoxLayout(self)
        column.setContentsMargins(14, 10, 14, 14)
        column.setSpacing(2 * theme.SPACE)
        self.header = QWidget()
        self.header.setFixedHeight(22)
        row = QHBoxLayout(self.header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2 * theme.SPACE)
        self.caret = QToolButton()
        self.caret.setAutoRaise(True)
        self.caret.setFixedSize(18, 18)
        self.caret.setIconSize(QSize(14, 14))
        self.caret.setToolTip(f"Show or hide {title}")
        self.caret.setAccessibleName(f"Collapse {title}")
        self.caret.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        self.caret.setVisible(collapsible)
        self.title = _ClickLabel(title)
        font: QFont = theme.font("body")
        font.setWeight(QFont.Weight.DemiBold)
        self.title.setFont(font)
        if collapsible:
            self.title.setCursor(Qt.CursorShape.PointingHandCursor)
            self.title.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        row.addWidget(self.caret)
        row.addWidget(self.title, 1)
        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSpacing(2)
        row.addLayout(self.actions)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(2 * theme.SPACE)
        column.addWidget(self.header)
        column.addWidget(self.body)
        self._show_caret()

    def text(self) -> str:
        return self.title.text()

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.addWidget(widget)
        return widget

    def add_widget(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self.body_layout.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout) -> None:
        self.body_layout.addLayout(layout)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.body.setVisible(not collapsed)
        layout = self.layout()
        margins = layout.contentsMargins()
        layout.setContentsMargins(margins.left(), margins.top(), margins.right(), 10 if collapsed else 14)
        self._show_caret()
        self.toggled.emit(collapsed)

    def _show_caret(self) -> None:
        self.caret.setIcon(icons.icon("caret-right" if self._collapsed else "caret-down", tint="faint"))

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.rule:
            painter = QPainter(self)
            painter.fillRect(0, self.height() - 1, self.width(), 1, theme.qcolor(theme.THEME.line))
            painter.end()
