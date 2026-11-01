"""File > Export Bundle...: what a portable bundle will carry, before asking where to write it (ADR 0077).

The list shows every file the project uses (sounds, images, SVGs) and the layers or sounds that use it; a
missing file is marked and will be left out, and the project keeps its path. The checkbox adds the project's
snapshots (ADR 0068), which needs a saved project that has some.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QListWidget, QListWidgetItem, QWidget

from ...core.exchange.bundle import Reference
from ..style.dialog_chrome import DialogFrame


class ExportBundleDialog(QDialog):
    def __init__(
        self,
        references: list[Reference],
        missing: set[str],
        snapshot_count: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export bundle")
        self.frame = DialogFrame(
            self,
            "export",
            "Export bundle",
            "One file with the project and every file it uses, to open on another computer.",
        )
        self.list = QListWidget()
        by_path: dict[str, list[str]] = {}
        for ref in references:
            by_path.setdefault(ref.path, []).append(ref.label)
        for path, users in by_path.items():
            gone = path in missing
            text = f"{Path(path).name}  -  {', '.join(users)}" + ("  (missing: left out)" if gone else "")
            item = QListWidgetItem(text)
            item.setToolTip(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.list.addItem(item)
        files = len(by_path)
        gone = sum(1 for path in by_path if path in missing)
        summary = (
            f"{files} file{'s' if files != 1 else ''} will be carried"
            if files
            else "The project uses no files"
        )
        if gone:
            summary += f"; {gone} missing and left out (they show a placeholder where the bundle is opened)"
        self.summary = QLabel(summary + ".")
        self.summary.setWordWrap(True)
        self.summary.setProperty("role", "muted")
        self.include_snapshots = QCheckBox(
            f"Include the {snapshot_count} snapshot{'s' if snapshot_count != 1 else ''}"
            if snapshot_count
            else "Include snapshots"
        )
        self.include_snapshots.setEnabled(snapshot_count > 0)
        self.include_snapshots.setToolTip(
            "Carry the project's named snapshots too"
            if snapshot_count
            else "This project has no snapshots (or was never saved)"
        )
        self.frame.body.addWidget(self.list, 1)
        self.frame.body.addWidget(self.summary)
        self.frame.body.addWidget(self.include_snapshots)
        cancel = self.frame.add_button("Cancel")
        cancel.clicked.connect(self.reject)
        self.export_button = self.frame.add_button("Export...", "primary")
        self.export_button.clicked.connect(self.accept)
        self.resize(560, 420)
