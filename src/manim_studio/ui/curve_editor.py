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

from PySide6.QtCore import QPointF, QRectF, QSize, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..core import adapter
from ..core.schema import Easing

Y_RANGE = (-0.5, 1.5)
MARGIN = 14.0
HANDLE_PX = 6.0
GRAB_PX = 10.0
SAMPLES = 96
CURVE_COLOR = QColor("#38bdf8")
HANDLE_COLOR = QColor("#fde047")


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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#1f2329"))
        rect = self.plot_rect()
        grid = QPen(QColor(255, 255, 255, 40), 1)
        painter.setPen(grid)
        for y in (0.0, 1.0):
            a, b = to_widget(rect, 0, y), to_widget(rect, 1, y)
            painter.drawLine(a, b)
        painter.drawLine(to_widget(rect, 0, Y_RANGE[0]), to_widget(rect, 0, Y_RANGE[1]))
        painter.drawLine(to_widget(rect, 1, Y_RANGE[0]), to_widget(rect, 1, Y_RANGE[1]))
        rate = adapter.rate_func(self.ease)
        path = QPainterPath(to_widget(rect, 0, rate(0.0)))
        for i in range(1, SAMPLES + 1):
            x = i / SAMPLES
            path.lineTo(to_widget(rect, x, float(rate(x))))
        painter.setPen(QPen(CURVE_COLOR, 2))
        painter.drawPath(path)
        if self.editable:
            p1, p2 = self.handle_positions()
            painter.setPen(QPen(HANDLE_COLOR, 1))
            painter.drawLine(to_widget(rect, 0, 0), p1)
            painter.drawLine(to_widget(rect, 1, 1), p2)
            painter.setBrush(HANDLE_COLOR)
            for p in (p1, p2):
                painter.drawEllipse(p, HANDLE_PX, HANDLE_PX)
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
