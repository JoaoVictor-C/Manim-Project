"""File > Snapshots...: named milestones of the project, kept beside its file (ADR 0068).

Save one at a point worth coming back to ("rough cut", "final narration"), see what differs between it and the
project as it is now, and restore it. Restoring is one step of the editor's undo, so it can itself be undone,
and the snapshot stays. The dialog holds no state: the list is read from the folder each time it changes.

Each snapshot is a row of the shared list (ADR 0084): a small picture of its middle frame (drawn one per tick
after the window shows), the name, the age in mono, chips for the layers and seconds it holds, and *Restore*
and *Delete* buttons on the row; choosing a row shows what differs from the project now. *Save snapshot* is
the dialog's primary action.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from ...core.model import snapshots
from ...core.model.schema import Project
from ..shell.beat_sheet_dialog import picture
from ..style.dialog_chrome import DialogFrame
from ..style.list_row import ListRow, RowList

PICTURE = (96, 54)  # px: a snapshot's picture in its row


def age(saved_at: float, now: float | None = None) -> str:
    """How long ago, in a few words ("just now", "5 min ago", "yesterday", else the date)."""
    seconds = (time.time() if now is None else now) - saved_at
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    if seconds < 2 * 86400:
        return "yesterday"
    return time.strftime("%Y-%m-%d", time.localtime(saved_at))


class SnapshotsDialog(QDialog):
    def __init__(
        self,
        path: Path,
        current: Callable[[], Project],
        restore: Callable[[Project, str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Snapshots")
        self.path, self.current, self._restore = path, current, restore
        self.frame = DialogFrame(
            self,
            "history",
            "Snapshots",
            "Milestones of this project, kept beside its file. Restoring one is a step you can undo.",
        )
        self.list = RowList()
        self.list.currentItemChanged.connect(self._show_difference)
        self.pictures: list[tuple[QLabel, snapshots.Snapshot]] = []
        self._drawn = 0
        self.difference = QPlainTextEdit()
        self.difference.setReadOnly(True)
        self.difference.setPlaceholderText("Choose a snapshot to see what differs from the project now.")
        self.empty_note = QLabel("No snapshots yet. Save one at a point worth coming back to.")
        self.empty_note.setProperty("role", "muted")
        self.empty_note.setWordWrap(True)
        self.frame.body.addWidget(self.list, 3)
        self.frame.body.addWidget(self.empty_note)
        self.frame.body.addWidget(self.difference, 2)

        self.delete_button = self.frame.add_left(QPushButton("Delete"))
        self.delete_button.clicked.connect(self.delete_selected)
        self.rename_button = self.frame.add_left(QPushButton("Rename..."))
        self.rename_button.clicked.connect(self.rename_selected)
        close = self.frame.add_button("Close")
        close.clicked.connect(self.close)
        self.restore_button = self.frame.add_button("Restore")
        self.restore_button.clicked.connect(self.restore_selected)
        self.save_button = self.frame.add_button("Save snapshot...", "primary")
        self.save_button.clicked.connect(self.save_new)
        self.resize(560, 560)
        self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self, self._draw_next)

    def _draw_next(self) -> None:
        """Draw the pictures one per tick, so the window opens at once."""
        if self._drawn >= len(self.pictures) or not self.isVisible():
            return
        label, snapshot = self.pictures[self._drawn]
        self._drawn += 1
        try:
            project = snapshots.load(snapshot)
            label.setPixmap(picture(project, project.canvas.duration / 2))
        except (snapshots.SnapshotError, OSError, ValueError):
            pass  # a snapshot that cannot be read shows its empty frame and says so when chosen
        QTimer.singleShot(0, self, self._draw_next)

    # -- the list ------------------------------------------------------------------

    def refresh(self) -> None:
        self.list.clear()
        self.pictures, self._drawn = [], 0
        for snapshot in snapshots.listing(self.path):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(snapshot.saved_at))
            thumbnail = QLabel()
            thumbnail.setFixedSize(*PICTURE)
            thumbnail.setScaledContents(True)
            self.pictures.append((thumbnail, snapshot))
            row = ListRow(snapshot.name, lead=thumbnail, mono=age(snapshot.saved_at))
            row.mono_label.setToolTip(when)
            row.add_head_chip(f"{snapshot.layers} layers")
            row.add_head_chip(f"{snapshot.duration:g} s")
            row.add_action(self._row_button("Restore", lambda _=False, sn=snapshot: self._restore_row(sn)))
            self.list.add_row(
                row, f"{snapshot.name}\n{when} - {snapshot.layers} layers, {snapshot.duration:g} s", snapshot
            )
        self.empty_note.setVisible(not self.pictures)
        if self.isVisible():
            QTimer.singleShot(0, self, self._draw_next)
        if self.list.count():
            self.list.setCurrentRow(0)
        self._buttons()

    @staticmethod
    def _row_button(text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("role", "ghost")
        button.clicked.connect(slot)
        return button

    def _restore_row(self, snapshot: snapshots.Snapshot) -> None:
        for k in range(self.list.count()):
            if self.list.item(k).data(Qt.ItemDataRole.UserRole) == snapshot:
                self.list.setCurrentRow(k)
        self.restore_selected()

    def selected(self) -> snapshots.Snapshot | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _buttons(self) -> None:
        has = self.selected() is not None
        for button in (self.restore_button, self.delete_button, self.rename_button):
            button.setEnabled(has)
        if not has:
            self.difference.clear()

    def _show_difference(self, *_args) -> None:
        self._buttons()
        snapshot = self.selected()
        if snapshot is None:
            return
        try:
            old = snapshots.load(snapshot)
        except snapshots.SnapshotError as error:
            self.difference.setPlainText(str(error))
            self.restore_button.setEnabled(False)
            return
        lines = snapshots.compare(old, self.current()).lines()
        self.difference.setPlainText(
            "From this snapshot to the project now:\n" + "\n".join(lines)
            if lines != ["No differences."]
            else lines[0]
        )

    # -- actions -------------------------------------------------------------------

    def save_new(self) -> None:
        name, ok = QInputDialog.getText(self, "Save snapshot", "Name (for example: rough cut):")
        if not ok:
            return
        try:
            snapshots.save(self.path, self.current(), name)
        except (snapshots.SnapshotError, OSError) as error:
            QMessageBox.warning(self, "Snapshots", str(error))
            return
        self.refresh()

    def restore_selected(self) -> None:
        snapshot = self.selected()
        if snapshot is None:
            return
        try:
            project = snapshots.load(snapshot)
        except snapshots.SnapshotError as error:
            QMessageBox.warning(self, "Snapshots", str(error))
            return
        self._restore(project, f"Restore snapshot {snapshot.name}")
        self._show_difference()

    def rename_selected(self) -> None:
        snapshot = self.selected()
        if snapshot is None:
            return
        name, ok = QInputDialog.getText(self, "Rename snapshot", "Name:", text=snapshot.name)
        if ok:
            try:
                snapshots.rename(snapshot, name)
            except (snapshots.SnapshotError, OSError) as error:
                QMessageBox.warning(self, "Snapshots", str(error))
            self.refresh()

    def delete_selected(self) -> None:
        snapshot = self.selected()
        if snapshot is None:
            return
        answer = QMessageBox.question(
            self, "Delete snapshot", f"Delete the snapshot {snapshot.name!r}? This cannot be undone."
        )
        if answer == QMessageBox.StandardButton.Yes:
            snapshots.delete(snapshot)
            self.refresh()
