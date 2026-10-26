"""Showing that code is running (ADR 0059): a spinner glyph and the status-bar indicator.

Code layers render in other processes, sometimes for minutes. ``spinner()`` is the glyph every place
uses (the explorer, the tabs, the canvas badge), ``activity_text()`` words what the render service is
doing, and ``RenderActivity`` is the button at the right of the status bar that shows it on every page
and takes you to the layer that is rendering.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QToolButton

from ..core import limits
from . import theme

FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
INTERVAL_MS = 100


def spinner(now: float | None = None) -> str:
    """The glyph of this moment: one full turn a second."""
    t = time.monotonic() if now is None else now
    return FRAMES[int(t * 1000 / INTERVAL_MS) % len(FRAMES)]


def activity_text(active: list[tuple[str, str, float]], label_of: Callable[[str], str], frames_of) -> str:
    """One line for ``CodeRenderService.active()``: what renders, for how long, what waits ('' = idle)."""
    if not active:
        return ""
    running = [item for item in active if item[1] == "rendering"]
    waiting = len(active) - len(running)
    if not running:
        return f"Waiting to render {waiting} scene{'s' if waiting != 1 else ''}"
    layer_id, _state, seconds = running[0]
    parts = [f"Rendering {label_of(layer_id)}"]
    frames = frames_of(layer_id)
    if frames:
        parts.append(f"{frames} frames")
    parts.append(f"{seconds:.0f} s")
    if len(running) > 1:
        parts.append(f"+{len(running) - 1} more")
    if waiting:
        parts.append(f"{waiting} waiting")
    if limits.unlimited():
        parts.append("no time limit")
    return " · ".join(parts)


class RenderActivity(QToolButton):
    """The status-bar indicator: hidden while nothing renders; a spinner and a line when something does."""

    layerRequested = Signal(str)  # the layer that is rendering: take me to it
    textChanged = Signal(str)  # the line shown ('' when idle), for the canvas badge

    def __init__(self, service, label_of: Callable[[str], str], parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._label_of = label_of
        self._first = ""
        self._text = ""
        self.setObjectName("renderActivity")
        self.setAutoRaise(True)
        self.setToolTip("Code is rendering. Click to open it on the Code page, where Cancel stops it")
        self.setStyleSheet(f"QToolButton {{ color: {theme.css(theme.THEME.accent)}; padding: 0 8px; }}")
        self.clicked.connect(lambda: self._first and self.layerRequested.emit(self._first))
        self._timer = QTimer(self)
        self._timer.setInterval(INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self.hide()
        service.statusChanged.connect(lambda _layer: self.refresh())

    @property
    def line(self) -> str:
        return self._text

    def refresh(self) -> None:
        active = self._service.active()
        status = self._service.status
        text = activity_text(
            active, self._label_of, lambda i: s.frames if (s := status(i)) is not None else 0
        )
        self._first = active[0][0] if active else ""
        if text != self._text:
            self._text = text
            self.textChanged.emit(text)
        if text:
            self.setText(f"{spinner()}  {text}")
            if not self._timer.isActive():
                self._timer.start()
            self.show()
        else:
            self._timer.stop()
            self.hide()
