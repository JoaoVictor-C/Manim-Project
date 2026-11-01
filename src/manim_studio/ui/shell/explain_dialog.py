"""Edit > Explain This Moment...: which layers, clips, keys, subtitles and sounds make the frame (ADR 0082).

A window beside the editor, not modal: it explains the playhead and follows it as it moves. Previous and Next
step to the moments where something changes; clicking an item selects its layer (and clip) in the editor, so
what made the moment can be inspected and changed there. Copy as text puts the explanation on the clipboard.

Each reason is a row of the shared list (ADR 0084): the sentence, a chip saying what kind of reason it is
(the clip's kind, the key's track, the layer's type, subtitle, sound), the time it spans, and a *Go to*
ghost button that selects it in the editor.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QListWidgetItem, QPushButton, QWidget

from ...core.editing import explain
from ...core.editing.beat_sheet import clock
from ...core.model.schema import Project
from ..style.dialog_chrome import DialogFrame
from ..style.list_row import ROW_GAP, ROW_PAD, ListRow, RowList

LAYER_ROLE = Qt.ItemDataRole.UserRole
CLIP_ROLE = Qt.ItemDataRole.UserRole + 1


def chip_for(item) -> tuple[str, str]:
    """The chip that names what kind of reason ``item`` is, and its tone."""
    if isinstance(item, explain.ActiveClip):
        return item.kind, "accent"
    if isinstance(item, explain.AnimatingKey):
        return item.track.replace("_", " ") + " key", "accent"
    if isinstance(item, explain.VisibleLayer):
        return item.type, "warn" if item.hidden else "neutral"
    if isinstance(item, explain.ShownSubtitle):
        return "subtitle", "neutral"
    return "sound", "neutral"


def span_of(item) -> str:
    """The clock range an item covers, for the mono text (empty when it has none)."""
    start, end = getattr(item, "start", None), getattr(item, "end", None)
    if start is None or end is None:
        return ""
    return f"{clock(start)} - {clock(end) if end == end and end < 1e9 else 'end'}"


class ExplainDialog(QDialog):
    def __init__(
        self,
        current: Callable[[], Project | None],
        now: Callable[[], float],
        seek: Callable[[float], None],
        select: Callable[[str, str | None], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Explain this moment")
        self.setModal(False)
        self.current, self.now, self._seek, self._select = current, now, seek, select
        self.frame = DialogFrame(self, "clock", "Explain this moment")
        self.list = RowList()
        self.list.itemClicked.connect(self.pick)
        self.frame.body.addWidget(self.list)
        self.previous_button = self.frame.add_left(QPushButton("Previous moment"))
        self.previous_button.setToolTip("The moment before, where something last changed")
        self.previous_button.clicked.connect(lambda: self.step(-1))
        self.next_button = self.frame.add_left(QPushButton("Next moment"))
        self.next_button.setToolTip("The next moment where something changes")
        self.next_button.clicked.connect(lambda: self.step(+1))
        copy = self.frame.add_button("Copy as text")
        copy.clicked.connect(self.copy_text)
        close = self.frame.add_button("Close", "primary")
        close.clicked.connect(self.close)
        self.explanation: explain.Explanation | None = None
        self.resize(560, 560)
        self.go_buttons: list[QPushButton] = []
        self.refresh()

    def refresh(self, t: float | None = None) -> None:
        """Explain ``t`` (the playhead when None)."""
        t = self.now() if t is None else t
        project = self.current()
        if project is None:  # the project was closed
            self.explanation = None
            self.list.clear()
            return
        self.explanation = found = explain.explain(project, t)
        times = explain.moments(project)
        index = sum(1 for m in times if m <= t + explain.EPS)
        where = f"At {clock(t)}" + (f', in the beat "{found.beat}"' if found.beat else "")
        self.frame.set_description(
            f"{where} - moment {max(index, 1)} of {len(times)}. Click an item to select it in the editor."
        )
        self.previous_button.setEnabled(explain.step(times, t, -1) is not None)
        self.next_button.setEnabled(explain.step(times, t, +1) is not None)
        self._fill(found)

    def _fill(self, found: explain.Explanation) -> None:
        self.list.clear()
        self.go_buttons = []
        for title, name in explain.SECTIONS:
            items = getattr(found, name)
            if not items:
                continue
            header = QLabel(title.upper())
            header.setProperty("role", "section")
            header.setContentsMargins(ROW_PAD, ROW_GAP, ROW_PAD, 0)
            self.list.add_row(header, title, selectable=False)
            for item in items:
                self._add(item)
        if found.empty:
            self.list.add_note("Nothing is on screen at this moment.")

    def _add(self, item) -> None:
        kind, tone = chip_for(item)
        row = ListRow(item.sentence, mono=span_of(item), plain=True)
        row.add_head_chip(kind, tone)
        layer_id = getattr(item, "layer_id", None)
        clip_id = getattr(item, "clip_id", None)
        entry = self.list.add_row(row, item.sentence)
        entry.setData(LAYER_ROLE, layer_id)
        entry.setData(CLIP_ROLE, clip_id)
        if layer_id:
            go = QPushButton("Go to")
            go.setProperty("role", "ghost")
            go.setToolTip("Select this in the editor")
            go.clicked.connect(lambda _=False, it=entry: self.pick(it))
            row.add_action(go)
            self.go_buttons.append(go)
            self.list.refit()

    def follow(self, t: float) -> None:
        """The playhead moved (or the project changed): explain where it is now, while shown."""
        if self.isVisible():
            self.refresh(t)

    def step(self, direction: int) -> float | None:
        """Move the playhead to the moment before or after this one."""
        if self.current() is None:
            return None
        t = self.explanation.t if self.explanation is not None else self.now()
        target = explain.step(explain.moments(self.current()), t, direction)
        if target is None:
            return None
        self._seek(target)
        self.refresh(target)
        return target

    def pick(self, item: QListWidgetItem | None = None) -> None:
        item = item or self.list.currentItem()
        layer_id = item.data(LAYER_ROLE) if item is not None else None
        if layer_id:
            self._select(str(layer_id), item.data(CLIP_ROLE) or None)

    def text(self) -> str:
        return explain.to_text(self.explanation) if self.explanation is not None else ""

    def copy_text(self) -> None:
        QApplication.clipboard().setText(self.text())
