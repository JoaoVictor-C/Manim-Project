"""File > Export Bundle...: what a portable bundle will carry, before asking where to write it (ADR 0077).

The list shows every file the project uses (sounds, images, SVGs) and the layers or sounds that use it; a
missing file is marked and will be left out, and the project keeps its path. The checkbox adds the project's
snapshots (ADR 0068), which needs a saved project that has some.

Each file is a row of the shared list (ADR 0084): its name with a chip for its kind, the layers or sounds
that use it, and a *missing* bad chip when it will be left out. ``BundleProblemDialog`` is what opening a
bundle that fails its check shows: the failure as a bad chip and its words, and nothing is opened.
There is no progress ring: the bundle is written after this dialog, in a moment, with a status-bar line.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QWidget

from ...core.exchange.bundle import Reference
from ..style.dialog_chrome import DialogFrame
from ..style.list_row import ListRow, RowList

KINDS = {  # file suffix -> the chip
    ".wav": "sound",
    ".mp3": "sound",
    ".ogg": "sound",
    ".flac": "sound",
    ".m4a": "sound",
    ".svg": "svg",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
}


def kind_of(path: str) -> str:
    return KINDS.get(Path(path).suffix.lower(), "file")


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
        self.list = RowList()
        by_path: dict[str, list[str]] = {}
        for ref in references:
            by_path.setdefault(ref.path, []).append(ref.label)
        for path, users in by_path.items():
            gone = path in missing
            text = f"{Path(path).name}  -  {', '.join(users)}" + ("  (missing: left out)" if gone else "")
            row = ListRow(Path(path).name, subtitle=f"Used by {', '.join(users)}")
            row.add_head_chip(kind_of(path))
            if gone:
                row.add_head_chip("missing", "bad", "This file was not found: it is left out of the bundle")
            else:
                row.add_head_chip("carried", "ok")
            item = self.list.add_row(row, text, path)
            item.setToolTip(path)
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
        self.resize(560, 480)


class BundleProblemDialog(QDialog):
    """A bundle that cannot be opened (it failed its check) or written: the failure as a bad chip and the
    words, one button. Nothing was opened or left behind."""

    def __init__(
        self,
        title: str,
        message: str,
        parent: QWidget | None = None,
        note: str = "Nothing was opened and nothing was left behind.",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.message = message
        self.frame = DialogFrame(self, "error", title, "", tone="bad")
        row = ListRow("The bundle failed its check")
        self.chip = row.add_head_chip("failed", "bad")
        row.add_line(message)
        self.list = RowList()
        self.list.add_row(row, message, selectable=False)
        self.list.setMaximumHeight(160)
        self.frame.body.addWidget(self.list)
        hint = QLabel(note)
        hint.setProperty("role", "muted")
        self.frame.body.addWidget(hint)
        ok = self.frame.add_button("Close", "primary")
        ok.clicked.connect(self.accept)
        self.resize(560, 300)
