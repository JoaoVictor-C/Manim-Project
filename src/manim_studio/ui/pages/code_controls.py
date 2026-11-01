"""The controls of a Python object's declared parameters, on the Code page (ADR 0051, 0084).

``PARAMS`` in the code declares each parameter (a number with a range, a yes/no, a colour...). The Values tab
shows them as fields that change the object as they move; here they get the controls the design draws for them
(Lumen, ``docs/design/lumen.md``): a **slider** with a mono readout for a number that has both a minimum and a
maximum, a **switch** for a yes/no, a colour **swatch** for a colour (``ColorField``, as in Properties), and
the plain fields for the rest. A slider commits while it is dragged - the build service replaces the value
that is still waiting (``supersede``), so the object follows the hand - and a switch at once.

``ControlsPanel`` is ``ValuesPanel`` with these controls; it builds the same document edits.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRectF, QSignalBlocker, QSize, Qt
from PySide6.QtGui import QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QAbstractButton, QVBoxLayout, QWidget

from ...core.engine.adapter import Param
from ..panels.properties_panel import _param_field
from ..panels.values_panel import ValuesPanel
from ..style import theme
from ..style.fields import Commit, Field, SliderBox, caption

UNBOUNDED = 1e6  # what ``adapter.python_params`` puts for an end the code did not declare


def has_range(param: Param) -> bool:
    """Does the parameter declare both ends (a slider needs them)? An end left at the adapter's default
    (+-1e6) is not declared."""
    return (
        param.kind in ("float", "int")
        and param.minimum is not None
        and param.maximum is not None
        and param.maximum > param.minimum
        and abs(param.minimum) < UNBOUNDED
        and abs(param.maximum) < UNBOUNDED
    )


class ParamSlider(SliderBox):
    """A slider over ``param``'s range; an int parameter steps by whole numbers."""

    def __init__(self, param: Param) -> None:
        super().__init__(float(param.minimum), float(param.maximum), percent=False)
        self.param = param
        self.setObjectName("paramSlider")
        self.readout.setMinimumWidth(self.readout.fontMetrics().horizontalAdvance("-0000.00 mm") + 4)
        self._show_readout()

    def value(self) -> float:
        value = super().value()
        return float(round(value)) if self.param.kind == "int" else value

    def _show_readout(self) -> None:
        param = getattr(self, "param", None)
        if param is None:  # the base class shows it once while it is being built
            return
        value = self.value()
        digits = 0 if param.kind == "int" else (param.precision if param.precision is not None else 2)
        unit = f" {param.unit}" if param.unit else ""
        self.readout.setText(f"{value:.{digits}f}{unit}")


class ParamSliderField(Field):
    """A number with a range on a slider: it commits as it is dragged, and from the keyboard."""

    def __init__(self, on_commit: Commit, param: Param) -> None:
        super().__init__(on_commit)
        box = ParamSlider(param)
        self.integer = param.kind == "int"
        box.slider.valueChanged.connect(lambda _v: self.commit(self._number(box.value())))
        self.widget = box

    def _number(self, value: float) -> Any:
        return round(value) if self.integer else round(value, 4)

    def set_value(self, value: Any, pending: bool = False) -> None:
        if self.widget.slider.isSliderDown():
            return  # the user is dragging it
        super().set_value(value, pending)

    def _show(self, value: Any) -> None:
        with QSignalBlocker(self.widget.slider):
            self.widget.setValue(float(value) if value is not None else self.widget.minimum())


class SwitchBox(QAbstractButton):
    """A switch: a small track and a knob, with its label to the right (the toggle of the design)."""

    TRACK = QSize(30, 17)

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.setObjectName("paramSwitch")
        self.setCheckable(True)
        self.setText(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(text)

    def sizeHint(self) -> QSize:
        label = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(self.TRACK.width() + (10 + label if self.text() else 0), max(self.TRACK.height(), 22))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _event: QPaintEvent) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        track = QRectF(0, (self.height() - self.TRACK.height()) / 2, self.TRACK.width(), self.TRACK.height())
        painter.setPen(QPen(theme.qcolor(c.accent if on else c.line_strong), 1))
        painter.setBrush(theme.qcolor(c.accent if on else c.surface_3))
        painter.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5), track.height() / 2, track.height() / 2)
        knob = track.height() - 6
        left = track.right() - 3 - knob if on else track.left() + 3
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor(c.on_accent if on else c.muted))
        painter.drawEllipse(QRectF(left, track.top() + 3, knob, knob))
        if self.text():
            painter.setPen(theme.qcolor(c.text))
            painter.drawText(
                QRectF(self.TRACK.width() + 10, 0, self.width() - self.TRACK.width() - 10, self.height()),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                self.text(),
            )
        if self.hasFocus():
            painter.setPen(QPen(theme.qcolor(c.accent), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
        painter.end()


class SwitchField(Field):
    """A yes/no as a switch with its name beside it."""

    def __init__(self, on_commit: Commit) -> None:
        super().__init__(on_commit)
        box = SwitchBox()
        box.toggled.connect(self.commit)
        self.widget = box

    def set_label(self, text: str) -> bool:
        self.widget.setText(text)
        self.widget.setAccessibleName(text)
        self.widget.updateGeometry()
        return True

    def _show(self, value: Any) -> None:
        self.widget.setChecked(bool(value))


def control_field(param: Param, commit: Commit) -> Field:
    """The field that shows ``param``: a slider, a switch, a swatch (``ColorField``) or a plain field."""
    if has_range(param):
        return ParamSliderField(commit, param)
    if param.kind == "bool":
        return SwitchField(commit)
    return _param_field(param, commit)


class ControlsPanel(ValuesPanel):
    """The Values tab with sliders, switches and swatches."""

    def _build(self, layer_id: str, params: tuple) -> None:
        self.fields = {}
        self._empty()
        for param in params:
            field = control_field(param, self._commit(layer_id, param.name))
            self.fields[param.name] = field
            if field.set_label(param.title):
                self.form.addWidget(field.widget)
                continue
            row = QWidget()
            column = QVBoxLayout(row)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(5)
            column.addWidget(caption(param.title))
            column.addWidget(field.widget)
            self.form.addWidget(row)
        self.section.show()
