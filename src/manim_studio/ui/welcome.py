"""The welcome (P6d.1, ADR 0044): what the viewer shows until a project is open.

A title, a line of text, the ways in (New, Open..., the example) and the recent files as
links. Pure view: the window connects the signals and keeps the recent list current.
Colours and fonts come from the theme's stylesheet (roles ``title``, ``hint``, ``link``).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import icons

# examples/ sits beside src/ in a checkout; an installed copy has no example to offer.
EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "showcase.json"


class WelcomePanel(QWidget):
    newRequested = Signal()
    openRequested = Signal()
    exampleRequested = Signal()
    recentRequested = Signal(Path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("welcome")
        self.recent_links: list[QPushButton] = []

        title = QLabel("Manim Studio")
        title.setProperty("role", "title")
        text = QLabel(
            "Animate with Manim the way you would in a video editor: layers, a timeline, "
            "keyframes and easing. Start a new scene, open a project, or look at the example."
        )
        text.setProperty("role", "hint")
        text.setWordWrap(True)

        self.new_button = self._button("add", "New", "An empty scene (Ctrl+N)", self.newRequested)
        self.open_button = self._button("open", "Open...", "Open a project file (Ctrl+O)", self.openRequested)
        self.example_button = self._button(
            "example",
            "Open Example",
            "The showcase scene, as a copy you can change freely",
            self.exampleRequested,
        )
        self.example_button.setVisible(EXAMPLE.is_file())
        buttons = QHBoxLayout()
        for button in (self.new_button, self.open_button, self.example_button):
            buttons.addWidget(button)
        buttons.addStretch(1)

        self.recent_heading = QLabel("Recent")
        self.recent_heading.setProperty("role", "section")
        self.recent_column = QVBoxLayout()
        self.recent_column.setSpacing(2)

        column = QVBoxLayout()
        column.addStretch(1)  # a little above the middle
        column.addWidget(title)
        column.addWidget(text)
        column.addSpacing(12)
        column.addLayout(buttons)
        column.addSpacing(16)
        column.addWidget(self.recent_heading)
        column.addLayout(self.recent_column)
        column.addStretch(2)

        outer = QHBoxLayout(self)  # the column, centred with room on both sides
        outer.addStretch(1)
        host = QWidget()
        host.setLayout(column)
        host.setMaximumWidth(560)
        outer.addWidget(host, 4)
        outer.addStretch(1)
        self.set_recent([])

    def _button(self, icon: str, text: str, tip: str, signal) -> QPushButton:
        button = QPushButton(icons.icon(icon), text)
        button.setToolTip(tip)
        button.clicked.connect(lambda: signal.emit())
        return button

    def set_recent(self, paths: list[Path]) -> None:
        """Show these files as links, newest first (none: the section is hidden)."""
        for link in self.recent_links:
            row = link.parentWidget()
            self.recent_column.removeWidget(row)
            row.setParent(None)  # gone at once; deleted when control returns to the event loop
            row.deleteLater()
        self.recent_links = []
        for path in paths:
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            link = QPushButton(path.name)
            link.setProperty("role", "link")
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.setToolTip(str(path))
            link.clicked.connect(lambda _=False, p=path: self.recentRequested.emit(p))
            folder = QLabel(path.parent.name)
            folder.setProperty("role", "hint")
            line.addWidget(link)
            line.addWidget(folder, 1)
            self.recent_column.addWidget(row)
            self.recent_links.append(link)
        self.recent_heading.setVisible(bool(paths))
