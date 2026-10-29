"""A label that scrubs (Lumen, ADR 0063): drag it to change the number beside it.

``ScrubLabel`` reports a drag as a number of *steps* from where it began (``scrubbed``), so the
owner computes ``start + steps * step`` and rounding never drifts. The drag locks to its initial
horizontal or vertical direction. Shift makes it fine (a tenth of a step per pixel), Ctrl coarse
(ten steps per pixel). The cursor wraps at the active screen's edge so the drag can continue.
A double-click asks to type instead (``doubleClicked``). Nothing is committed while dragging: the
owner decides what a drag means when it ends (``scrubFinished``).
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QMouseEvent
from PySide6.QtWidgets import QLabel, QWidget

PIXELS_PER_STEP = 2  # a plain drag moves one step every two pixels
FINE = 0.1  # Shift
COARSE = 10.0  # Ctrl
THRESHOLD = 6  # px before locking the drag axis; ignores small hand jitter when starting vertically
AXIS_DOMINANCE = 1.5  # require one direction to be clearly larger than the other
AXIS_FALLBACK = 18  # px: choose the dominant direction for an intentionally diagonal drag


def steps_for(distance: float, modifiers: Qt.KeyboardModifier) -> float:
    """How many steps a travel of ``distance`` pixels means with these modifier keys."""
    factor = 1.0
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        factor = FINE
    elif modifiers & Qt.KeyboardModifier.ControlModifier:
        factor = COARSE
    return distance / PIXELS_PER_STEP * factor


class ScrubLabel(QLabel):
    """``scrubStarted`` on the first move, ``scrubbed(steps)`` while dragging, ``scrubFinished`` last."""

    scrubStarted = Signal()
    scrubbed = Signal(float)  # steps from where the drag began (fractional with Shift)
    scrubFinished = Signal()
    doubleClicked = Signal()

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.scrubbing = False
        self.enabled_scrub = True
        self._press: QPointF | None = None
        self._steps = 0.0  # the steps of the travel already reported, under the keys held then
        self._last_position = QPointF()
        self._axis: str | None = None
        self._screen = None
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def set_scrubbable(self, on: bool) -> None:
        self.enabled_scrub = on
        self.setCursor(Qt.CursorShape.SizeAllCursor if on else Qt.CursorShape.IBeamCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.enabled_scrub and self.isEnabled():
            self._press = event.globalPosition()
            self._last_position = self._press
            self._steps = 0.0
            self._axis = None
            self._screen = QGuiApplication.screenAt(self._press.toPoint()) or QGuiApplication.primaryScreen()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press is None:
            super().mouseMoveEvent(event)
            return
        position = event.globalPosition()
        if not self.scrubbing:
            dx, dy = position.x() - self._press.x(), position.y() - self._press.y()
            distance_x, distance_y = abs(dx), abs(dy)
            largest, smallest = max(distance_x, distance_y), min(distance_x, distance_y)
            if largest < THRESHOLD:
                event.accept()
                return
            if largest < smallest * AXIS_DOMINANCE and largest < AXIS_FALLBACK:
                event.accept()
                return
            self._axis = "horizontal" if distance_x >= distance_y else "vertical"
            self.scrubbing = True
            self.scrubStarted.emit()
        # Up/right increases; each move uses the modifier held during that segment of the drag.
        distance = (
            position.x() - self._last_position.x()
            if self._axis == "horizontal"
            else self._last_position.y() - position.y()
        )
        self._steps += steps_for(distance, event.modifiers())
        self._last_position = position
        self.scrubbed.emit(self._steps)
        self._wrap_cursor(position)
        event.accept()

    def _wrap_cursor(self, position: QPointF) -> None:
        """Wrap across the active screen along the scrub axis, without counting the warp as travel."""
        screen = QGuiApplication.screenAt(position.toPoint()) or self._screen
        if screen is None or self._axis is None:
            return
        bounds = screen.geometry()
        x, y = round(position.x()), round(position.y())
        inset = 2
        target = None
        if self._axis == "horizontal":
            if x <= bounds.left():
                target = QPoint(bounds.right() - inset, y)
            elif x >= bounds.right():
                target = QPoint(bounds.left() + inset, y)
        else:
            if y <= bounds.top():
                target = QPoint(x, bounds.bottom() - inset)
            elif y >= bounds.bottom():
                target = QPoint(x, bounds.top() + inset)
        if target is not None:
            QCursor.setPos(target)
            self._last_position = QPointF(QCursor.pos())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._press is not None and event.button() == Qt.MouseButton.LeftButton:
            self._press = None
            self._axis = None
            self._screen = None
            if self.scrubbing:
                self.scrubbing = False
                self.scrubFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = None
            self.scrubbing = False
            self._axis = None
            self._screen = None
            self.doubleClicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
