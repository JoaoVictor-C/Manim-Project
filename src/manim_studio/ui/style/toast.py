"""Toasts (Lumen, ADR 0063): a message that arrives where you are looking, stays a few seconds and leaves.

``ToastHost`` floats over the window's bottom-right corner and stacks up to four toasts; ``show`` makes one
(``tone``: info, ok, warn or bad; optionally an action button such as Undo). The window's status
bar forwards every transient message to it (``LumenStatusBar``), and keeps the message itself too, so what
used to be said in the status bar is still there for the tests and for anyone looking for it.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from . import motion, theme

MAX_TOASTS = 4
WIDTH = 360
MARGIN = (24, 44)  # from the right and the bottom edge of the window
DEFAULT_MS = 4500
READY = "Ready"  # the idle line: said in the status bar, never as a toast

_BAD = re.compile(
    r"\b(fail|failed|error|cannot|can't|could not|couldn't|not applied|refused|invalid|unable)\b", re.I
)
_OK = re.compile(r"\b(saved|exported|copied|added|rendered|done|finished|applied|created|imported)\b", re.I)
_WARN = re.compile(r"\b(warning|still running|wait|not trusted|stale|skipped|nothing to)\b", re.I)


def tone_of(text: str) -> str:
    """A guess at a message's tone from its words (a toast is coloured by it)."""
    if _BAD.search(text):
        return "bad"
    if _WARN.search(text):
        return "warn"
    return "ok" if _OK.search(text) else "info"


class _Badge(QWidget):
    """The round icon at the left of a toast: a check, an exclamation mark or an i, in the tone's colour."""

    def __init__(self, tone: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tone = tone
        self.setFixedSize(26, 26)

    def paintEvent(self, event: QPaintEvent) -> None:
        c = theme.THEME
        colour = theme.qcolor(
            {"ok": c.success, "warn": c.warning, "bad": c.danger}.get(self.tone, c.accent_text)
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = theme.qcolor(colour.name())
        fill.setAlpha(46)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(QRectF(self.rect()))
        painter.setPen(
            QPen(colour, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        )
        w, h = self.width(), self.height()
        if self.tone == "ok":
            painter.drawPolyline(
                [
                    QPoint(int(w * 0.30), int(h * 0.52)),
                    QPoint(int(w * 0.44), int(h * 0.66)),
                    QPoint(int(w * 0.70), int(h * 0.36)),
                ]
            )
        elif self.tone in ("warn", "bad"):
            painter.drawLine(int(w / 2), int(h * 0.28), int(w / 2), int(h * 0.58))
            painter.drawPoint(int(w / 2), int(h * 0.74))
        else:
            painter.drawLine(int(w / 2), int(h * 0.45), int(w / 2), int(h * 0.72))
            painter.drawPoint(int(w / 2), int(h * 0.28))


class Toast(QFrame):
    def __init__(
        self,
        text: str,
        tone: str,
        detail: str = "",
        action: tuple[str, Callable[[], None]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(WIDTH)
        self.tone = tone
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(12)
        row.addWidget(_Badge(tone), 0, Qt.AlignmentFlag.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(2)
        self.text_label = QLabel(text)
        self.text_label.setWordWrap(True)
        self.text_label.setFont(theme.font("label"))
        column.addWidget(self.text_label)
        self.detail_label = QLabel(detail)
        self.detail_label.setWordWrap(True)
        self.detail_label.setProperty("role", "hint")
        self.detail_label.setVisible(bool(detail))
        column.addWidget(self.detail_label)
        row.addLayout(column, 1)
        self.action_button: QPushButton | None = None
        if action is not None:
            self.action_button = QPushButton(action[0])
            self.action_button.setProperty("role", "ghost")
            self.action_button.clicked.connect(lambda: (action[1](), self.dismiss()))
            row.addWidget(self.action_button, 0, Qt.AlignmentFlag.AlignTop)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.closing = False

    def dismiss(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.timer.stop()
        self.hide()
        self.deleteLater()

    def mousePressEvent(self, event) -> None:  # a click anywhere dismisses it
        self.dismiss()


class ToastHost(QObject):
    """Owns the toasts of one window and keeps them at its bottom-right corner."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.window_ = window
        self.container = QWidget(window)
        self.container.setObjectName("toastHost")
        self.container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.column = QVBoxLayout(self.container)
        self.column.setContentsMargins(0, 0, 0, 0)
        self.column.setSpacing(10)
        self.column.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        window.installEventFilter(self)
        self.toasts: list[Toast] = []

    def show(
        self,
        text: str,
        *,
        tone: str | None = None,
        detail: str = "",
        action: tuple[str, Callable[[], None]] | None = None,
        timeout: int = DEFAULT_MS,
    ) -> Toast:
        """Show a toast; ``tone`` is guessed from the words when not given."""
        toast = Toast(text, tone or tone_of(text), detail, action, self.container)
        while len(self.toasts) >= MAX_TOASTS:
            self.toasts.pop(0).dismiss()
        self.toasts = [t for t in self.toasts if not t.closing]
        self.toasts.append(toast)
        self.column.addWidget(toast)
        toast.show()
        self._place()
        toast.destroyed.connect(self._place)
        if timeout > 0:
            toast.timer.start(max(1500, timeout) if motion.enabled() else timeout)
        return toast

    def clear(self) -> None:
        for toast in self.toasts:
            toast.dismiss()
        self.toasts = []

    def active(self) -> list[Toast]:
        return [t for t in self.toasts if not t.closing]

    # -- placement ---------------------------------------------------------------------------------

    def _place(self, *_args) -> None:
        window = self.window_
        self.container.adjustSize()
        width = WIDTH
        height = self.container.sizeHint().height()
        self.container.setGeometry(
            window.width() - width - MARGIN[0], window.height() - height - MARGIN[1], width, max(height, 1)
        )
        self.container.raise_()
        self.container.setVisible(any(not t.closing for t in self.toasts))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.window_ and event.type() == QEvent.Type.Resize:
            self._place()
        return False


class LumenStatusBar(QStatusBar):
    """A status bar that also shows each transient message as a toast."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.toasts: ToastHost | None = None
        self.setSizeGripEnabled(False)

    def showMessage(self, text: str, timeout: int = 0) -> None:
        super().showMessage(text, timeout)
        if self.toasts is not None and timeout > 0 and text.strip() and text != READY:
            self.toasts.show(text, timeout=timeout)


def install_toast_rules() -> None:
    def rules(c: theme.Colours) -> str:
        return (
            f"QFrame#toast {{ background: {c.raised}; border: 1px solid {theme.css(c.line_strong)};"
            f" border-radius: 14px; }}"
        )

    theme.register_rules(rules)


install_toast_rules()
