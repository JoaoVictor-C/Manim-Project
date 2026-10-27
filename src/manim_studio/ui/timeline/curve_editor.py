"""The easing curve editor (P2b): shape an ease by dragging two bezier handles.

The graph shows progress (y) over time (x) for one clip or keyframe segment.
y runs from -0.5 to 1.5 so overshooting curves (back, "Overshoot") fit. The
curve is drawn with ``adapter.rate_func``, the same function the evaluator uses.

A named Manim ease starts from the cubic bezier fitted to it
(``adapter.EASE_BEZIER_FITS``, B27), so the curve does not jump on the first
drag. Eases no cubic bezier can follow (bounce, elastic, there_and_back,
double_smooth) are shown but cannot be dragged: pick a preset to edit.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ...core.engine import adapter
from ...core.model.schema import Easing
from . import paint
from .paint import colour

Y_RANGE = (-0.5, 1.5)
MARGIN = 14.0
HANDLE_PX = 6.0
GRAB_PX = 10.0
SAMPLES = 96


def to_widget(rect: QRectF, x: float, y: float) -> QPointF:
    """Curve coordinates (x in 0..1, y in Y_RANGE) -> widget pixels inside ``rect``."""
    lo, hi = Y_RANGE
    return QPointF(rect.left() + x * rect.width(), rect.bottom() - (y - lo) / (hi - lo) * rect.height())


def from_widget(rect: QRectF, point: QPointF) -> tuple[float, float]:
    """Widget pixels -> curve coordinates, clamped to the editable range (x 0..1)."""
    lo, hi = Y_RANGE
    x = (point.x() - rect.left()) / rect.width()
    y = lo + (rect.bottom() - point.y()) / rect.height() * (hi - lo)
    return min(max(x, 0.0), 1.0), min(max(y, lo), hi)


def ease_label(ease: Easing | None) -> str:
    if ease is None:
        return "Animation default"
    if ease.bezier is not None:
        for label, preset in adapter.BEZIER_PRESETS.items():
            if tuple(preset) == tuple(ease.bezier):
                return label
        return "Custom curve ({:.2f}, {:.2f}, {:.2f}, {:.2f})".format(*ease.bezier)
    return (ease.name or "linear").replace("_", " ")


class CurveEditor(QWidget):
    changed = Signal(object)  # the new Easing

    def __init__(self, ease: Easing, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(240, 240)
        self._dragging: int | None = None  # which control point: 0 or 1
        self.set_ease(ease)

    def sizeHint(self) -> QSize:
        return QSize(280, 280)

    def set_ease(self, ease: Easing) -> None:
        self.ease = ease
        self.points = adapter.ease_as_bezier(ease)  # None: not editable as a curve
        self.update()

    @property
    def editable(self) -> bool:
        return self.points is not None

    def plot_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)

    def handle_positions(self) -> list[QPointF]:
        rect = self.plot_rect()
        x1, y1, x2, y2 = self.points
        return [to_widget(rect, x1, y1), to_widget(rect, x2, y2)]

    # -- painting ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        """Lumen (P17.4b): a hairline grid with mono labels, the curve in a gradient stroke with a soft
        fill under it, its ends as rounded diamonds, the handles as dots on dashed stems."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), colour("track"))
        rect = self.plot_rect()
        grid = colour("line")
        for i in range(1, 4):  # quarters of time and of progress
            a = to_widget(rect, i / 4, 0)
            painter.fillRect(QRectF(round(a.x()), rect.top(), 1, rect.height()), grid)
            painter.fillRect(QRectF(rect.left(), round(to_widget(rect, 0, i / 4).y()), rect.width(), 1), grid)
        strong = colour("line_strong")
        for y in (0.0, 1.0):  # where the motion starts and ends
            painter.fillRect(QRectF(rect.left(), round(to_widget(rect, 0, y).y()), rect.width(), 1), strong)
        painter.fillRect(QRectF(rect.left(), rect.top(), 1, rect.height()), strong)
        painter.fillRect(QRectF(rect.right(), rect.top(), 1, rect.height()), strong)
        painter.setFont(paint.font("caption", kind="mono", weight=QFont.Weight.Normal))
        painter.setPen(colour("faint"))
        for y in (0.0, 1.0):
            painter.drawText(to_widget(rect, 0, y) + QPointF(4, -4), f"{y:g}")
        rate = adapter.rate_func(self.ease)
        start = to_widget(rect, 0, rate(0.0))
        path = QPainterPath(start)
        for i in range(1, SAMPLES + 1):
            x = i / SAMPLES
            path.lineTo(to_widget(rect, x, float(rate(x))))
        base = to_widget(rect, 0, 0).y()
        area = QPainterPath(path)
        area.lineTo(QPointF(rect.right(), base))
        area.lineTo(QPointF(rect.left(), base))
        area.closeSubpath()
        painter.fillPath(area, colour("accent", 0.1))
        stroke = QLinearGradient(rect.topLeft(), rect.topRight())
        stroke.setColorAt(0.0, colour("accent"))
        stroke.setColorAt(1.0, colour("curve"))
        pen = QPen(QBrush(stroke), 3.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        ends = (to_widget(rect, 0, 0), to_widget(rect, 1, 1))
        if self.editable:
            handle = colour("curve_handle")
            stem = QPen(colour("faint"), 1, Qt.PenStyle.CustomDashLine)
            stem.setDashPattern([3, 3])
            painter.setPen(stem)
            for end, p in zip(ends, self.handle_positions(), strict=True):
                painter.drawLine(end, p)
            painter.setPen(QPen(colour("key_edge"), 1.2))
            painter.setBrush(handle)
            for p in self.handle_positions():
                painter.drawEllipse(p, HANDLE_PX - 1, HANDLE_PX - 1)
        for end in ends:  # the segment's two keys
            paint.paint_key(painter, end, 6.0, colour("key_selected"), False)
        painter.end()

    # -- dragging the handles ---------------------------------------------------------

    def handle_at(self, pos: QPointF) -> int | None:
        if not self.editable:
            return None
        near = [(QPointF(p - pos).manhattanLength(), i) for i, p in enumerate(self.handle_positions())]
        distance, index = min(near)
        return index if distance <= GRAB_PX else None

    def mousePressEvent(self, event) -> None:
        self._dragging = self.handle_at(event.position())

    def mouseMoveEvent(self, event) -> None:
        if self._dragging is None:
            return
        x, y = from_widget(self.plot_rect(), event.position())
        points = list(self.points)
        points[2 * self._dragging], points[2 * self._dragging + 1] = round(x, 3), round(y, 3)
        self.points = tuple(points)
        self.ease = Easing(name=None, bezier=self.points)
        self.update()
        self.changed.emit(self.ease)

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = None


class CurveDialog(QDialog):
    """Pick a preset or drag the handles; OK returns the new ease."""

    def __init__(self, ease: Easing | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Easing curve")
        start = ease if ease is not None else Easing()
        self.editor = CurveEditor(start)
        self.presets = QComboBox()
        self._choices: list[Easing] = [Easing(name=name) for name in adapter.EASE_NAMES]
        self._choices += [Easing(name=None, bezier=b) for b in adapter.BEZIER_PRESETS.values()]
        for choice in self._choices:
            self.presets.addItem(ease_label(choice))
        self.presets.setCurrentIndex(self._choices.index(start) if start in self._choices else -1)
        self.presets.activated.connect(lambda i: self._pick(self._choices[i]))
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.editor.changed.connect(lambda _ease: self._update_hint())
        layout = QVBoxLayout(self)
        layout.addWidget(self.presets)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.hint)
        layout.addWidget(buttons)
        self._update_hint()

    @property
    def ease(self) -> Easing:
        return self.editor.ease

    def _pick(self, ease: Easing) -> None:
        self.editor.set_ease(ease)
        self._update_hint()

    def _update_hint(self) -> None:
        if self.editor.editable:
            self.hint.setText("Drag the yellow handles to shape the motion; y above 1 overshoots.")
        else:
            self.hint.setText("This curve cannot be edited as a bezier. Pick a preset to start from.")


def edit_curve(parent: QWidget | None, ease: Easing | None) -> Easing | None:
    """Show the dialog; the chosen ease, or None if cancelled."""
    dialog = CurveDialog(ease, parent)
    return dialog.ease if dialog.exec() == QDialog.DialogCode.Accepted else None


CurveEditorFunction = Callable[[Easing | None], Easing | None]
