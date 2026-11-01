"""Edit > Explain This Moment...: which layers, clips, keys, subtitles and sounds make the frame (ADR 0082).

A window beside the editor, not modal: it explains the playhead and follows it as it moves. Previous and Next
step to the moments where something changes; clicking an item selects its layer (and clip) in the editor, so
what made the moment can be inspected and changed there. Copy as text puts the explanation on the clipboard.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QListWidget, QListWidgetItem, QPushButton, QWidget

from ...core.editing import explain
from ...core.editing.beat_sheet import clock
from ...core.model.schema import Project
from ..style.dialog_chrome import DialogFrame

LAYER_ROLE = Qt.ItemDataRole.UserRole
CLIP_ROLE = Qt.ItemDataRole.UserRole + 1


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
        self.frame = DialogFrame(self, "chapters", "Explain this moment")
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.itemClicked.connect(self.pick)
        self.frame.body.addWidget(self.list)
        self.previous_button = self.frame.add_left(QPushButton("Previous"))
        self.previous_button.setToolTip("The moment before, where something last changed")
        self.previous_button.clicked.connect(lambda: self.step(-1))
        self.next_button = self.frame.add_left(QPushButton("Next"))
        self.next_button.setToolTip("The next moment where something changes")
        self.next_button.clicked.connect(lambda: self.step(+1))
        copy = self.frame.add_button("Copy as text")
        copy.clicked.connect(self.copy_text)
        close = self.frame.add_button("Close")
        close.clicked.connect(self.close)
        self.explanation: explain.Explanation | None = None
        self.resize(520, 560)
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
        self.list.clear()
        for title, name in explain.SECTIONS:
            items = getattr(found, name)
            if not items:
                continue
            header = QListWidgetItem(title)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            self.list.addItem(header)
            for item in items:
                row = QListWidgetItem(item.sentence)
                row.setData(LAYER_ROLE, getattr(item, "layer_id", None))
                row.setData(CLIP_ROLE, getattr(item, "clip_id", None))
                self.list.addItem(row)
        if found.empty:
            empty = QListWidgetItem("Nothing is on screen at this moment.")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)

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
