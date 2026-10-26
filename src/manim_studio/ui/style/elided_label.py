"""A one-line label that shortens its text with "..." instead of being cut off (P6d.2).

``text()`` keeps the whole text (and the tooltip shows it); only the drawing is elided,
so the label can shrink with its panel without forcing the window wider.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class ElidedLabel(QLabel):
    elides = True  # the layout checks skip it: shortening is by design

    def __init__(self, text: str = "", parent: QWidget | None = None, minimum: int = 80) -> None:
        super().__init__(text, parent)
        self._minimum = minimum
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setToolTip(text)

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._minimum, super().minimumSizeHint().height())

    def shown_text(self) -> str:
        """The text as drawn: whole when it fits, else shortened at the end."""
        width = self.contentsRect().width()
        return self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, width)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.contentsRect(), int(self.alignment()), self.shown_text())
        painter.end()
