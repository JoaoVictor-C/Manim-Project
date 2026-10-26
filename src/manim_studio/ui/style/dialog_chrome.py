"""The look every dialog shares (Lumen, ADR 0063): a header with an icon tile, a title and a line of
description; a body; a footer with the actions at the right, the secondary ones first and the primary last.

``DialogFrame(dialog, "export", "Export video", "What it does, in one line")`` lays the dialog out and
gives ``frame.body`` (a layout to add the content to) and ``frame.footer`` (``add_button``, ``add_left``).
Spacing sits on the 4 px grid: 22 px at the sides, 12 px between the header's parts, 10 px between buttons.
The surface is the raised colour (a dialog floats), set by a rule that follows the theme.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme
from .icon_tile import IconTile

SIDE = 22  # px: the dialog's left and right padding
HEADER_GAP = 12  # px: between the icon tile and the words
BUTTON_GAP = 10  # px: between footer buttons


def _rules(c: theme.Colours) -> str:
    return f"""
QDialog[lumen="true"] {{ background: {c.raised}; }}
QFrame#dialogHeader, QFrame#dialogBody, QFrame#dialogFooter {{ background: transparent; border: 0; }}
QLabel[role="dialogTitle"] {{ color: {c.text}; font-size: 15px; font-weight: 650; }}
QFrame[option="true"] {{
    background: {c.field}; border: 1px solid {theme.css(c.line)}; border-radius: 12px;
}}
QFrame[option="true"]:hover {{ border-color: {theme.css(c.line_strong)}; }}
QFrame[option="true"][chosen="true"] {{
    background: {theme.css(c.accent_soft)}; border-color: {theme.css(c.accent_line)};
}}
QFrame[option="true"] QLabel, QFrame[option="true"] QRadioButton {{ background: transparent; }}
"""


theme.register_rules(_rules)


class DialogFrame:
    """The header, body and footer of a dialog: content goes in ``body``, the actions in ``footer``."""

    def __init__(
        self, dialog: QDialog, icon: str, title: str, description: str = "", *, tone: str = "accent"
    ) -> None:
        self.dialog = dialog
        dialog.setProperty("lumen", True)
        root = QVBoxLayout(dialog)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = QFrame()
        self.header.setObjectName("dialogHeader")
        head = QHBoxLayout(self.header)
        head.setContentsMargins(SIDE, 18, SIDE, 18)
        head.setSpacing(HEADER_GAP)
        self.tile = IconTile(icon, tone=tone, size=36, radius=11)
        words = QVBoxLayout()
        words.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "dialogTitle")
        self.description_label = QLabel(description)
        self.description_label.setProperty("role", "muted")
        self.description_label.setWordWrap(True)
        self.description_label.setVisible(bool(description))
        words.addWidget(self.title_label)
        words.addWidget(self.description_label)
        head.addWidget(self.tile, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(words, 1)

        self.body_frame = QFrame()
        self.body_frame.setObjectName("dialogBody")
        self.body = QVBoxLayout(self.body_frame)
        self.body.setContentsMargins(SIDE, 16, SIDE, 16)
        self.body.setSpacing(theme.SPACE * 3)

        self.footer_frame = QFrame()
        self.footer_frame.setObjectName("dialogFooter")
        self.footer = QHBoxLayout(self.footer_frame)
        self.footer.setContentsMargins(SIDE, 14, SIDE, 14)
        self.footer.setSpacing(BUTTON_GAP)
        self._stretched = False

        root.addWidget(self.header)
        root.addWidget(self._rule())
        root.addWidget(self.body_frame, 1)
        root.addWidget(self._rule())
        root.addWidget(self.footer_frame)

    @staticmethod
    def _rule() -> QFrame:
        rule = QFrame()
        rule.setObjectName("cardRule")
        rule.setFixedHeight(1)
        return rule

    def set_description(self, text: str) -> None:
        self.description_label.setText(text)
        self.description_label.setVisible(bool(text))

    def add_left(self, widget: QWidget) -> QWidget:
        """A widget at the footer's left edge (an extra action, a count)."""
        if self._stretched:
            raise RuntimeError("add the left-hand widgets before the buttons")
        self.footer.addWidget(widget)
        return widget

    def _stretch(self) -> None:
        if not self._stretched:
            self.footer.addStretch(1)
            self._stretched = True

    def add_button(self, text: str, role: str | None = None, *, icon: str | None = None) -> QPushButton:
        """A button at the footer's right: the secondary ones first, the primary (role ``primary``) last."""
        self._stretch()
        button = QPushButton(text)
        if icon is not None:
            button.setIcon(icons.icon(icon))
        if role:
            button.setProperty("role", role)
        if role == "primary":
            button.setDefault(True)
        self.footer.addWidget(button)
        return button


class OptionCard(QFrame):
    """A radio button with a note under it, drawn as a card that is accent-tinted when chosen; a click
    anywhere on the card chooses it."""

    def __init__(self, radio: QRadioButton, note: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.radio = radio
        self.setProperty("option", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        column = QVBoxLayout(self)
        column.setContentsMargins(14, 12, 14, 12)
        column.setSpacing(2)
        column.addWidget(radio)
        self.note = QLabel(note)
        self.note.setWordWrap(True)
        self.note.setProperty("role", "muted")
        self.note.setContentsMargins(26, 0, 0, 0)
        self.note.setVisible(bool(note))
        column.addWidget(self.note)
        radio.toggled.connect(self._mark)
        self._mark(radio.isChecked())

    def _mark(self, checked: bool) -> None:
        self.setProperty("chosen", bool(checked))
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.radio.click()
        super().mouseReleaseEvent(event)
