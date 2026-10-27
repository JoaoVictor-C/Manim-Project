"""The status bar's left corner (Lumen, ADR 0063): a dot for saved or not, and the project's name."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from . import theme


class _Dot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.saved = True
        self.setFixedSize(10, 10)

    def sizeHint(self) -> QSize:
        return QSize(10, 10)

    def paintEvent(self, event: QPaintEvent) -> None:
        c = theme.THEME
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor(c.success if self.saved else c.warning))
        painter.drawEllipse(QRectF(1, 1, 8, 8))


class SavedIndicator(QWidget):
    """A dot (green: saved, amber: changes not saved), "Saved" or "Unsaved", and the project's name."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("savedIndicator")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(8)
        self.dot = _Dot()
        self.state = QLabel("Saved")
        self.state.setProperty("role", "hint")
        self.name = QLabel("untitled")
        for label in (self.state, self.name):
            label.setFont(theme.font("caption"))
        row.addWidget(self.dot)
        row.addWidget(self.state)
        row.addWidget(self.name)
        theme.signals.themeChanged.connect(
            self._on_theme
        )  # a method: it goes with the widget (a lambda did not)

    def _on_theme(self, _name: str = "") -> None:
        self.dot.update()

    def set_state(self, name: str, saved: bool) -> None:
        self.name.setText(name)
        self.state.setText("Saved" if saved else "Unsaved")
        self.dot.saved = saved
        self.dot.update()
