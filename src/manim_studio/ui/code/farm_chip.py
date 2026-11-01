"""The farm chip of the Code page's toolbar (ADR 0061, 0084): *Farm 3 / 4*, the code layers rendering over
all of them, and a popover with each one's state and the two things to do with it.

The editor renders every code layer of the project in warm processes (``CodeRenderService``); the chip counts
the ones working now over the ones there are, and is the accent while any works. Pressing it opens a popover:
a row for each code layer with its name, a chip (*Waiting*, *Running*, *Ready*, *Failed*, *Not run*,
*Stopped*) and *Run again* (for a failed or stopped one) or *Stop* (for one waiting or running). The name
opens the layer in the editor. The chip owns no state: the page hands it ``FarmEntry`` rows and listens to
``runRequested``, ``stopRequested`` and ``openRequested`` (a layer id each).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..style import theme
from ..style.card import Chip
from ..style.chip_button import ChipButton

WORDS = {  # a render state -> (what the row says, the chip's tone)
    "queued": ("Waiting", "neutral"),
    "rendering": ("Running", "accent"),
    "ready": ("Ready", "ok"),
    "error": ("Failed", "bad"),
    "untrusted": ("Not run", "warn"),
    "cancelled": ("Stopped", "neutral"),
}
RUNNING = ("rendering",)
WORKING = ("rendering", "queued")  # a layer that can be stopped
RERUNNABLE = ("error", "cancelled")


@dataclass(frozen=True)
class FarmEntry:
    layer_id: str
    label: str
    state: str  # a render state (see ``WORDS``); "" before the first render


def counts(entries: list[FarmEntry]) -> tuple[int, int]:
    """(running, total) of the code layers."""
    return sum(1 for e in entries if e.state in RUNNING), len(entries)


class _FarmRow(QFrame):
    def __init__(self, entry: FarmEntry, owner: FarmChip) -> None:
        super().__init__()
        self.setObjectName("farmRow")
        self.entry = entry
        name = QToolButton()
        name.setObjectName("farmName")
        name.setText(entry.label)
        name.setAutoRaise(True)
        name.setToolTip("Open this layer in the editor")
        name.setCursor(Qt.CursorShape.PointingHandCursor)
        name.clicked.connect(lambda: owner.openRequested.emit(entry.layer_id))
        word, tone = WORDS.get(entry.state, ("Not rendered", "neutral"))
        self.chip = Chip(word, tone)
        self.chip.setObjectName("farmState")
        self.chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.chip.setMinimumWidth(64)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 8, 6)
        row.setSpacing(8)
        row.addWidget(name, 1, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.chip)
        self.run_button = self.stop_button = None
        if entry.state in RERUNNABLE:
            self.run_button = QPushButton("Run again")
            self.run_button.setObjectName("farmRun")
            self.run_button.setProperty("role", "ghost")
            self.run_button.setProperty("size", "sm")
            self.run_button.clicked.connect(lambda: owner.runRequested.emit(entry.layer_id))
            row.addWidget(self.run_button)
        if entry.state in WORKING:
            self.stop_button = QPushButton("Stop")
            self.stop_button.setObjectName("farmStop")
            self.stop_button.setProperty("role", "ghost")
            self.stop_button.setProperty("size", "sm")
            self.stop_button.clicked.connect(lambda: owner.stopRequested.emit(entry.layer_id))
            row.addWidget(self.stop_button)


class FarmPopover(QFrame):
    """The list under the chip; it closes when the user clicks elsewhere (a Qt popup)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("farmPopover")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(340)
        self.title = QLabel("Python layers")
        self.title.setProperty("role", "hint")
        self.rows = QVBoxLayout()
        self.rows.setSpacing(2)
        self.note = QLabel("")
        self.note.setProperty("role", "hint")
        self.note.setWordWrap(True)
        column = QVBoxLayout(self)
        column.setContentsMargins(10, 10, 10, 10)
        column.setSpacing(6)
        column.addWidget(self.title)
        column.addLayout(self.rows)
        column.addWidget(self.note)

    def show_entries(self, entries: list[FarmEntry], owner: FarmChip) -> None:
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        for entry in entries:
            self.rows.addWidget(_FarmRow(entry, owner))
        running, total = counts(entries)
        self.title.setText(f"Python layers - {running} running of {total}")
        self.note.setText("Scenes render side by side in their own processes; Stop frees one.")
        self.adjustSize()


class FarmChip(ChipButton):
    """``Farm n / m``; ``set_entries`` after every change of a layer's state."""

    runRequested = Signal(str)
    stopRequested = Signal(str)
    openRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Farm 0 / 0", "neutral", parent)
        self.setObjectName("farmChip")
        self.entries: list[FarmEntry] = []
        self.popover = FarmPopover(self)
        self.setToolTip("The code layers rendering now, over all of them: press for each one's state")
        self.clicked.connect(self.toggle_popover)
        self.openRequested.connect(lambda _id: self.popover.hide())

    def set_entries(self, entries: list[FarmEntry]) -> None:
        if entries == self.entries:
            return
        self.entries = list(entries)
        running, total = counts(self.entries)
        self.setText(f"Farm {running} / {total}")
        self.set_tone("accent" if running else "neutral")
        self.setAccessibleName(f"Farm: {running} of {total} code layers rendering")
        if self.popover.isVisible():
            self.popover.show_entries(self.entries, self)

    def toggle_popover(self) -> None:
        if self.popover.isVisible():
            self.popover.hide()
            return
        self.popover.show_entries(self.entries, self)
        self.popover.move(self.mapToGlobal(self.rect().bottomLeft()) + QPoint(0, 6))
        self.popover.show()


def _rules(c: theme.Colours) -> str:
    return f"""
QFrame#farmPopover {{
    background: {c.raised}; border: 1px solid {theme.css(c.line_strong)}; border-radius: 12px;
}}
QFrame#farmPopover QLabel {{ background: transparent; }}
QFrame#farmRow {{ background: transparent; border: 0; border-radius: 9px; }}
QFrame#farmRow:hover {{ background: {theme.css(c.hover)}; }}
QToolButton#farmName {{
    background: transparent; border: 0; color: {c.text}; font-weight: 600; text-align: left; padding: 2px 4px;
}}
QToolButton#farmName:hover {{ color: {c.accent_text}; }}
"""


theme.register_rules(_rules)
