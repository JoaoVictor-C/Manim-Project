"""The health card of the Deliver page (ADR 0066, 0084): what is worth a look before exporting, as chips.

``health_items`` turns the export health report (``processes.export_health``) and the project into a few
items - *Fonts*, *Media*, *Python layers*, *Sound* - each with a tone (ok, warn, bad), a short text and
where to look when it is not ok (a page, and a layer to open there). ``HealthCard`` shows them as chips
that wrap; a warn or bad chip is a button that says its target through ``openRequested(page, layer_id)``,
and the page opens it. The card holds no state of its own and never runs anything.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QLayout, QLayoutItem, QVBoxLayout, QWidget

from ...core.engine import adapter
from ...core.exchange import bundle
from ...core.model.schema import Project
from ...core.voice import narration as speech
from ...processes import export_health
from ..style import theme
from ..style.chip_button import ChipButton

KEYS = ("fonts", "media", "python", "sound")


@dataclass(frozen=True)
class HealthItem:
    key: str  # one of KEYS
    text: str  # "Fonts ok", "Python layers 2 slow"
    tone: str  # "ok", "warn" or "bad"
    tip: str = ""
    page: str | None = None  # where a warn or bad chip leads: "code", "audio" or "compose"
    layer: str | None = None  # the layer to select there

    @property
    def actionable(self) -> bool:
        return self.tone != "ok" and self.page is not None


def _missing_media(project: Project) -> list[bundle.Reference]:
    """The files the project uses that are not on disk (relative paths as the renderer resolves them)."""
    return [
        ref for ref in bundle.external_references(project) if not Path(os.path.expanduser(ref.path)).is_file()
    ]


def health_items(project: Project, report: export_health.Report | None) -> list[HealthItem]:
    """The four chips for ``project`` and its export ``report`` (None: no report, so what only the project
    tells - media and sound - is still shown)."""
    findings = report.findings if report is not None else ()

    def of(*kinds: str) -> list[export_health.Finding]:
        return [f for f in findings if f.kind in kinds]

    # Fonts: text drawn through LaTeX has to be built the first time, and needs a LaTeX compiler.
    text = of("text")
    latex = adapter.latex_problem() if text else None
    if latex is not None:
        fonts = HealthItem("fonts", "Fonts: LaTeX missing", "bad", latex, "compose", text[0].layers[0])
    elif text:
        count = len(text[0].layers)
        fonts = HealthItem(
            "fonts", f"Fonts: {count} to build", "warn", text[0].detail, "compose", text[0].layers[0]
        )
    else:
        fonts = HealthItem("fonts", "Fonts ok", "ok", "Every text and formula is built or needs no building.")

    # Media: pictures and sounds the project names that are not where it says.
    missing = _missing_media(project)
    if missing:
        first = missing[0]
        page = "audio" if first.kind == "audio" else "compose"
        names = ", ".join(f"{ref.label} ({ref.path})" for ref in missing[:4])
        media = HealthItem(
            "media", f"Media: {len(missing)} missing", "bad", f"Not found: {names}", page, first.owner
        )
    else:
        media = HealthItem(
            "media", "Media ok", "ok", "Every picture and sound file is where the project says."
        )

    # Python layers: scenes that must be rendered at the export's size, or that will not run untrusted.
    slow, untrusted = of("code"), of("untrusted")
    if untrusted and not slow:
        found = untrusted[0]
        python = HealthItem(
            "python",
            f"Python layers: {len(found.layers)} not run",
            "warn",
            f"{found.title}. {found.detail}",
            "code",
            found.layers[0],
        )
    elif slow:
        found = slow[0]
        seconds = f" (about {export_health.clock(found.seconds)})" if found.seconds >= 1 else ""
        python = HealthItem(
            "python",
            f"Python layers {len(found.layers)} slow",
            "warn",
            f"{found.title}{seconds}. {found.detail}",
            "code",
            found.layers[0],
        )
    else:
        python = HealthItem("python", "Python layers ok", "ok", "Nothing here waits for code to render.")

    # Sound: narration whose text or voice changed since it was spoken.
    stale = [cue for cue in project.subtitles if speech.state(project, cue) == speech.STALE]
    if stale:
        sound = HealthItem(
            "sound",
            "Sound stale" if len(stale) == 1 else f"Sound: {len(stale)} stale",
            "warn",
            "Narration was spoken with an older text or voice; the export uses what was spoken.",
            "audio",
            None,
        )
    else:
        sound = HealthItem("sound", "Sound ok", "ok", "The narration matches its text and voice.")
    return [fonts, media, python, sound]


class FlowLayout(QLayout):
    """Widgets in rows that wrap when the width runs out."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._place(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _place(self, rect: QRect, apply: bool) -> int:
        margins: QMargins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, row = area.x(), area.y(), 0
        gap = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and row:
                x, y, row = area.x(), y + row + gap, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + gap
            row = max(row, hint.height())
        return y + row - rect.y() + margins.bottom()


class HealthCard(QFrame):
    """A caption and the four chips; a warn or bad chip emits ``openRequested(page, layer_id)`` when pressed
    (``layer_id`` is "" when it names no layer)."""

    openRequested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("healthCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.caption = QLabel("Export health")
        self.caption.setProperty("role", "hint")
        self.chips: dict[str, ChipButton] = {}
        self._items: dict[str, HealthItem] = {}
        host = QWidget()
        self._flow = FlowLayout(host, spacing=6)
        for key in KEYS:
            chip = ChipButton("", "neutral")
            chip.setObjectName(f"health_{key}")
            chip.clicked.connect(lambda _checked=False, k=key: self._pressed(k))
            self.chips[key] = chip
            self._flow.addWidget(chip)
        column = QVBoxLayout(self)
        column.setContentsMargins(14, 10, 14, 12)
        column.setSpacing(6)
        column.addWidget(self.caption)
        column.addWidget(host)

    def show_items(self, items: list[HealthItem]) -> None:
        for item in items:
            chip = self.chips[item.key]
            self._items[item.key] = item
            chip.setText(item.text)
            chip.setToolTip(item.tip + ("\nClick to open it." if item.actionable else ""))
            chip.set_tone(item.tone)
            chip.set_actionable(item.actionable)
        self.updateGeometry()

    def item(self, key: str) -> HealthItem | None:
        return self._items.get(key)

    def _pressed(self, key: str) -> None:
        item = self._items.get(key)
        if item is not None and item.actionable:
            self.openRequested.emit(item.page or "", item.layer or "")


def _rules(c: theme.Colours) -> str:
    return f"""
QFrame#healthCard {{ background: {c.raised}; border: 1px solid {theme.css(c.line)}; border-radius: 12px; }}
QFrame#healthCard QLabel {{ background: transparent; }}
"""


theme.register_rules(_rules)
