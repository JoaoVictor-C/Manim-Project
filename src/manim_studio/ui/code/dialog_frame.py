"""The Lumen dialog frame (P17.4d, ADR 0063) for the Code page's windows and the exchange package's.

``DialogFrame(dialog, icon, title, subtitle)`` gives a dialog the layout of the design: a header with an icon
in a tinted rounded chip, a title and a line under it; the body (``frame.body``, a column on the 4 px grid);
and a footer with the actions at the right, the primary one last. ``add_buttons`` puts a ``QDialogButtonBox``
there and marks its accepting button as the primary one; the box keeps its signals and buttons, so the
dialogs' code and tests are unchanged. Colours come from the stylesheet rules below, so a theme switch
reaches an open dialog.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..style import icons, theme

TONES = {
    "accent": ("accent_soft", "accent_text"),
    "warn": ("warning", "warning"),
    "bad": ("danger", "error_text"),
}
ACCEPTING = (QDialogButtonBox.ButtonRole.AcceptRole, QDialogButtonBox.ButtonRole.YesRole)


class IconChip(QWidget):
    """A 32 px rounded square tinted by ``tone`` with the icon in the middle."""

    def __init__(self, icon: str, tone: str = "accent", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.icon_name, self.tone = icon, tone
        self.setFixedSize(32, 32)

    def sizeHint(self) -> QSize:
        return QSize(32, 32)

    def paintEvent(self, event) -> None:
        colours = theme.THEME
        fill, ink = TONES.get(self.tone, TONES["accent"])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        colour = theme.qcolor(getattr(colours, fill))
        if self.tone != "accent":
            colour.setAlpha(38)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawRoundedRect(QRectF(self.rect()), 10, 10)
        icons.icon(self.icon_name, tint=ink).paint(painter, QRect(7, 7, 18, 18))
        painter.end()


class DialogFrame:
    """Header, body and footer of a Lumen dialog. Build the body into ``frame.body``."""

    def __init__(
        self, dialog: QDialog, icon: str, title: str, subtitle: str = "", tone: str = "accent"
    ) -> None:
        self.dialog = dialog
        dialog.setProperty("lumen", True)
        root = QVBoxLayout(dialog)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = QFrame()
        self.header.setObjectName("dialogHeader")
        row = QHBoxLayout(self.header)
        row.setContentsMargins(20, 16, 20, 16)
        row.setSpacing(12)
        self.icon = IconChip(icon, tone)
        row.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        words = QVBoxLayout()
        words.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("dialogTitle")
        self.title.setFont(theme.font("heading"))
        self.title.setWordWrap(True)
        words.addWidget(self.title)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("dialogSubtitle")
        self.subtitle.setWordWrap(True)
        self.subtitle.setVisible(bool(subtitle))
        words.addWidget(self.subtitle)
        row.addLayout(words, 1)
        root.addWidget(self.header)
        content = QWidget()
        content.setObjectName("dialogBody")
        self.body = QVBoxLayout(content)
        self.body.setContentsMargins(20, 16, 20, 16)
        self.body.setSpacing(12)
        root.addWidget(content, 1)
        self.footer_frame = QFrame()
        self.footer_frame.setObjectName("dialogFooter")
        self.footer = QHBoxLayout(self.footer_frame)
        self.footer.setContentsMargins(20, 12, 20, 12)
        self.footer.setSpacing(8)
        root.addWidget(self.footer_frame)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))

    def add_buttons(self, buttons: QDialogButtonBox) -> QDialogButtonBox:
        """Put the dialog's button box in the footer, the accepting button styled as the primary one."""
        buttons.setProperty("lumen", True)
        for button in buttons.buttons():
            if buttons.buttonRole(button) in ACCEPTING:
                primary(button)
        if self.footer.count() == 0:
            self.footer.addStretch(1)  # the actions sit at the right
        self.footer.addWidget(buttons)
        return buttons

    def add_footer(self, item: QWidget | QLayout, stretch: int = 0) -> None:
        """A widget or a layout in the footer, after what is there (put the primary button last)."""
        if isinstance(item, QLayout):
            self.footer.addLayout(item, stretch)
        else:
            self.footer.addWidget(item, stretch)


def primary(button: QPushButton) -> QPushButton:
    button.setProperty("role", "primary")
    button.style().unpolish(button)
    button.style().polish(button)
    return button


def ghost(button: QPushButton) -> QPushButton:
    button.setProperty("role", "ghost")
    button.style().unpolish(button)
    button.style().polish(button)
    return button


def rules(c: theme.Colours) -> str:
    line = theme.css(c.line)
    return f"""
QDialog[lumen="true"] {{ background: {c.raised}; }}
QDialog[lumen="true"] QWidget#dialogBody {{ background: transparent; }}
QFrame#dialogHeader {{ background: transparent; border: 0; border-bottom: 1px solid {line}; }}
QFrame#dialogFooter {{ background: transparent; border: 0; border-top: 1px solid {line}; }}
QLabel#dialogTitle {{ color: {c.text}; }}
QLabel#dialogSubtitle {{ color: {c.muted}; }}
QDialogButtonBox[lumen="true"] {{ button-layout: 1; }}
QDialog[lumen="true"] QLabel#dialogSection {{ color: {c.faint}; font-size: 11px; font-weight: 650; }}
QDialog[lumen="true"] QLabel[role="message"] {{ color: {c.warning}; }}
"""


theme.register_rules(rules)
