"""A chip that can be pressed (Lumen, ADR 0063, 0084): the health chips of Deliver, the farm chip of Code.

It looks like ``Chip`` (a small rounded label with a tone: neutral, accent, ok, warn, bad) and is a
``QToolButton``, so it has focus, a pointer and a ``clicked`` signal. A chip that has nothing to open is
disabled-looking only through its tone, never greyed: ``set_actionable(False)`` just drops the pointer.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton, QWidget

from . import theme

TONES = ("neutral", "accent", "ok", "warn", "bad")


class ChipButton(QToolButton):
    """``ChipButton("Fonts ok", "ok")``; ``set_tone`` and ``setText`` change it later."""

    def __init__(self, text: str = "", tone: str = "neutral", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("chipAction", True)
        self.setText(text)
        self.setAutoRaise(True)
        self.setFixedHeight(22)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.set_actionable(True)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        if tone not in TONES:
            raise ValueError(tone)
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)

    def tone(self) -> str:
        return str(self.property("tone"))

    def set_actionable(self, actionable: bool) -> None:
        self.setCursor(Qt.CursorShape.PointingHandCursor if actionable else Qt.CursorShape.ArrowCursor)


def rules(c: theme.Colours) -> str:
    return f"""
QToolButton[chipAction="true"] {{
    background: {c.raised}; border: 1px solid {theme.css(c.line)}; border-radius: 11px; padding: 0 9px;
    color: {c.muted}; font-size: 11px; font-weight: 500;
}}
QToolButton[chipAction="true"]:hover {{ border-color: {theme.css(c.line_strong)}; color: {c.text}; }}
QToolButton[chipAction="true"][tone="accent"] {{
    background: {theme.css(c.accent_soft)}; border-color: {theme.css(c.accent_line)}; color: {c.accent_text};
}}
QToolButton[chipAction="true"][tone="ok"] {{ color: {c.success}; }}
QToolButton[chipAction="true"][tone="warn"] {{ color: {c.warning}; }}
QToolButton[chipAction="true"][tone="bad"] {{ color: {c.error_text}; }}
QToolButton[chipAction="true"]:focus {{ border-color: {c.accent}; }}
"""


theme.register_rules(rules)
