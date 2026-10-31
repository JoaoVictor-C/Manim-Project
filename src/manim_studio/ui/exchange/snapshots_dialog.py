"""File > Snapshots...: named milestones of the project, kept beside its file (ADR 0068).

Save one at a point worth coming back to ("rough cut", "final narration"), see what differs between it and the
project as it is now, and restore it. Restoring is one step of the editor's undo, so it can itself be undone,
and the snapshot stays. The dialog holds no state: the list is read from the folder each time it changes.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from ...core.model import snapshots
from ...core.model.schema import Project
from ..style.dialog_chrome import DialogFrame


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
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._show_difference)
        self.difference = QPlainTextEdit()
        self.difference.setReadOnly(True)
        self.difference.setPlaceholderText("Choose a snapshot to see what differs from the project now.")
        self.frame.body.addWidget(self.list, 2)
        self.frame.body.addWidget(self.difference, 3)

        self.delete_button = self.frame.add_left(QPushButton("Delete"))
        self.delete_button.clicked.connect(self.delete_selected)
        self.rename_button = self.frame.add_left(QPushButton("Rename..."))
        self.rename_button.clicked.connect(self.rename_selected)
        close = self.frame.add_button("Close")
        close.clicked.connect(self.close)
        self.save_button = self.frame.add_button("Save snapshot...")
        self.save_button.clicked.connect(self.save_new)
        self.restore_button = self.frame.add_button("Restore", "primary")
        self.restore_button.clicked.connect(self.restore_selected)
        self.resize(640, 520)
        self.refresh()

    # -- the list ------------------------------------------------------------------

    def refresh(self) -> None:
        self.list.clear()
        for snapshot in snapshots.listing(self.path):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(snapshot.saved_at))
            item = QListWidgetItem(
                f"{snapshot.name}\n{when} - {snapshot.layers} layers, {snapshot.duration:g} s"
            )
            item.setData(256, snapshot)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)
        self._buttons()

    def selected(self) -> snapshots.Snapshot | None:
        item = self.list.currentItem()
        return item.data(256) if item is not None else None

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
