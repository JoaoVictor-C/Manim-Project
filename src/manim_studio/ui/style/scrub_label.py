"""A label that scrubs (Lumen, ADR 0063): drag it sideways to change the number beside it.

``ScrubLabel`` reports a drag as a number of *steps* from where the drag began (``scrubbed``), so the
owner computes ``start + steps * step`` and rounding never drifts. Shift makes the drag fine (a tenth of a
step per pixel), Ctrl coarse (ten steps per pixel). A double-click asks to type instead
(``doubleClicked``). Nothing is committed while dragging: the owner decides what a drag means when it ends
(``scrubFinished``).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QWidget

PIXELS_PER_STEP = 2  # a plain drag moves one step every two pixels
FINE = 0.1  # Shift
COARSE = 10.0  # Ctrl
THRESHOLD = 2  # px a press must travel before it is a drag (a click stays a click)


def steps_for(dx: float, modifiers: Qt.KeyboardModifier) -> float:
    """How many steps a horizontal travel of ``dx`` pixels means with these modifier keys."""
    factor = 1.0
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        factor = FINE
    elif modifiers & Qt.KeyboardModifier.ControlModifier:
        factor = COARSE
    return dx / PIXELS_PER_STEP * factor


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
        self._last_x = 0.0
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def set_scrubbable(self, on: bool) -> None:
        self.enabled_scrub = on
        self.setCursor(Qt.CursorShape.SizeHorCursor if on else Qt.CursorShape.IBeamCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.enabled_scrub and self.isEnabled():
            self._press = event.globalPosition()
            self._last_x = self._press.x()
            self._steps = 0.0
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press is None:
            super().mouseMoveEvent(event)
            return
        x = event.globalPosition().x()
        if not self.scrubbing:
            if abs(x - self._press.x()) < THRESHOLD:
                return
            self.scrubbing = True
            self.scrubStarted.emit()
        # Each move counts under the keys held during it, so pressing Shift mid-drag slows from there on.
        self._steps += steps_for(x - self._last_x, event.modifiers())
        self._last_x = x
        self.scrubbed.emit(self._steps)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._press is not None and event.button() == Qt.MouseButton.LeftButton:
            self._press = None
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
            self.doubleClicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
