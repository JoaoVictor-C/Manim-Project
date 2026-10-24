"""The export window (P12.4): choose what to write, where, and how.

Lists this project's code layers and Python objects and the presets, ticked as the user asked
(everything, or what was selected), and lets them pick the folder, the line endings, a first-line
comment, and whether to also write an ``index.json`` that makes the folder importable from the internet.
A file that already exists is asked about when it is written, not here.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.code_export import ExportEntry, ExportOptions

GROUP_TITLES = {"project": "In this project", "preset": "Presets"}


class ExportCodeDialog(QDialog):
    def __init__(
        self,
        entries: list[ExportEntry],
        *,
        checked: set[str] | None = None,
        folder: str = "",
        options: ExportOptions | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export code")
        self.resize(520, 560)
        options = options or ExportOptions()
        self.entries = entries
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Write these as .py files:"))
        self.list = QListWidget()
        self.list.setObjectName("exportItems")
        self.list.itemChanged.connect(self._refresh)
        self._rows: list[ExportEntry | None] = []
        for group in ("project", "preset"):
            members = [e for e in entries if e.group == group]
            if not members:
                continue
            header = QListWidgetItem(GROUP_TITLES[group])
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            self.list.addItem(header)
            self._rows.append(None)
            for entry in members:
                item = QListWidgetItem(f"{entry.name}  ({'object' if entry.kind == 'object' else 'scene'})")
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                on = checked is None or entry.key in checked
                item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                item.setToolTip(entry.description or entry.name)
                self.list.addItem(item)
                self._rows.append(entry)
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        all_button = QPushButton("Select all")
        none_button = QPushButton("Select none")
        all_button.clicked.connect(lambda: self._set_all(True))
        none_button.clicked.connect(lambda: self._set_all(False))
        row.addWidget(all_button)
        row.addWidget(none_button)
        row.addStretch(1)
        layout.addLayout(row)

        form = QFormLayout()
        place = QHBoxLayout()
        self.folder_edit = QLineEdit(folder)
        self.folder_edit.setPlaceholderText("Choose a folder")
        self.folder_edit.textChanged.connect(self._refresh)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        place.addWidget(self.folder_edit, 1)
        place.addWidget(browse)
        form.addRow("Folder", place)
        self.newline = QComboBox()
        self.newline.addItem("LF (recommended)", "\n")
        self.newline.addItem("CRLF (Windows)", "\r\n")
        self.newline.setCurrentIndex(1 if options.newline == "\r\n" else 0)
        form.addRow("Line endings", self.newline)
        layout.addLayout(form)
        self.header = QCheckBox("Start each file with a comment naming it")
        self.header.setChecked(options.header)
        self.manifest = QCheckBox("Also write index.json so the folder can be imported from a link")
        self.manifest.setChecked(options.manifest)
        layout.addWidget(self.header)
        layout.addWidget(self.manifest)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._refresh()

    def _set_all(self, on: bool) -> None:
        self.list.blockSignals(True)
        for row, entry in enumerate(self._rows):
            if entry is not None:
                self.list.item(row).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.list.blockSignals(False)
        self._refresh()

    def _browse(self) -> None:
        name = QFileDialog.getExistingDirectory(self, "Export code to folder", self.folder_edit.text())
        if name:
            self.folder_edit.setText(name)

    def chosen(self) -> list[ExportEntry]:
        return [
            entry
            for row, entry in enumerate(self._rows)
            if entry is not None and self.list.item(row).checkState() == Qt.CheckState.Checked
        ]

    def folder(self) -> str:
        return self.folder_edit.text().strip()

    def options(self) -> ExportOptions:
        return ExportOptions(self.newline.currentData(), self.header.isChecked(), self.manifest.isChecked())

    def _refresh(self, *_args) -> None:
        problems = []
        if not self.chosen():
            problems.append("Tick at least one item")
        folder = self.folder()
        if not folder:
            problems.append("Choose a folder")
        elif Path(folder).exists() and not Path(folder).is_dir():
            problems.append("That is a file, not a folder")
        self.message.setText("; ".join(problems))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not problems)
