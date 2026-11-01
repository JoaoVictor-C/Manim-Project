"""A chip that is a checkable button (Lumen, ADR 0063, 0084): Follow playhead, Snap, Auto-key.

Off it is a neutral chip, on it takes the accent tone (or, for ``dot``, a red record dot in front of the
label, as the Auto-key chip of the mock-up). Like ``Chip`` its colours come from the stylesheet.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QPainter
from PySide6.QtWidgets import QToolButton, QWidget

from . import icons, theme

HEIGHT = 22


class ToggleChip(QToolButton):
    """``ToggleChip("Snap", icon="snap")``; ``bind(action)`` keeps it and a checkable action in step."""

    def __init__(
        self, text: str = "", parent: QWidget | None = None, *, icon: str | None = None, dot: bool = False
    ) -> None:
        super().__init__(parent)
        self.setProperty("chipButton", True)
        self.setCheckable(True)
        self.setText(text)
        self.setAutoRaise(True)
        self.setFixedHeight(HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(12, 12))
        self._dot = dot
        self.setProperty("dot", dot)
        if icon:
            self.setIcon(icons.icon(icon))
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

    def bind(self, action: QAction) -> None:
        """Two-way: the chip follows the action's checked state and tooltip, and clicking it toggles it."""
        self.setChecked(action.isChecked())
        self.setToolTip(action.toolTip())
        action.toggled.connect(self.setChecked)
        self.toggled.connect(action.setChecked)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(hint.width() + (12 if self._dot else 0), HEIGHT)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._dot:  # the record dot, left of the label
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.qcolor(theme.THEME.danger if self.isChecked() else theme.THEME.faint))
            painter.drawEllipse(9, (self.height() - 7) // 2, 7, 7)
            painter.end()


def rules(c: theme.Colours) -> str:
    return f"""
QToolButton[chipButton="true"] {{
    background: {c.raised}; border: 1px solid {theme.css(c.line)}; border-radius: 11px; padding: 0 9px;
    color: {c.muted}; font-size: 11px; font-weight: 500;
}}
QToolButton[chipButton="true"][dot="true"] {{ padding-left: 22px; }}
QToolButton[chipButton="true"]:hover {{ color: {c.text}; border-color: {theme.css(c.line_strong)}; }}
QToolButton[chipButton="true"]:checked {{
    background: {theme.css(c.accent_soft)}; border-color: {theme.css(c.accent_line)}; color: {c.accent_text};
}}
"""


theme.register_rules(rules)
