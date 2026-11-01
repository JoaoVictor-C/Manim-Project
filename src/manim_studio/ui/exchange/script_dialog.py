"""File > Import Script...: a written script becomes subtitle cues on the timeline (ADR 0069).

Paste the text or load a .txt/.md file, choose whether a cue is a sentence or a paragraph, how fast it is read
and whether each paragraph gets a placeholder Text layer; the line under the text says what it will make.
Import is one
undo step. The cues are ordinary subtitles: the Audio page narrates them (ADR 0060).

Dialog shape of ADR 0084: the text, the options (a segmented choice of what a cue is), chips for what will be
made (subtitles, time, placeholder layers, long sentences) and the sentence that says it. The design's second
pane (the proposed timeline as lanes) is not drawn: the chips carry the structure in one line.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from ...core.editing import edits, script_import
from ...core.model.schema import Project
from ..style.card import Chip
from ..style.dialog_chrome import DialogFrame
from ..style.segmented import Segmented


class ScriptDialog(QDialog):
    def __init__(
        self,
        current: Callable[[], Project],
        apply: Callable[[edits.Edit, str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import script")
        self.current, self._apply = current, apply
        self.frame = DialogFrame(
            self,
            "import",
            "Import script",
            "Each sentence or paragraph becomes a subtitle, timed by reading speed, after the existing ones.",
        )
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Paste the script here, or load a .txt or .md file.")
        self.text.textChanged.connect(self._preview)
        self.unit = Segmented()
        self.unit.addItem("A sentence", "sentence")
        self.unit.addItem("A paragraph", "paragraph")
        self.unit.currentIndexChanged.connect(self._preview)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.5, 8.0)
        self.speed.setSingleStep(0.1)
        self.speed.setValue(script_import.WORDS_PER_SECOND)
        self.speed.setSuffix(" words/s")
        self.speed.valueChanged.connect(self._preview)
        self.placeholders = QCheckBox("Add a placeholder Text layer for each paragraph")
        self.placeholders.setToolTip(
            "A layer named Beat 1, Beat 2... shown while its paragraph is read, to replace"
        )
        self.placeholders.toggled.connect(self._preview)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setProperty("role", "muted")
        self.chips = QHBoxLayout()  # what will be made, one chip each (empty while nothing can be made)
        self.chips.setSpacing(6)
        form = QFormLayout()
        form.addRow("A cue is", self.unit)
        form.addRow("Reading speed", self.speed)
        form.addRow("", self.placeholders)
        self.frame.body.addWidget(self.text, 1)
        self.frame.body.addLayout(form)
        self.frame.body.addLayout(self.chips)
        self.frame.body.addWidget(self.summary)

        self.load_button = self.frame.add_left(QPushButton("Load file..."))
        self.load_button.clicked.connect(self.load_file)
        close = self.frame.add_button("Cancel")
        close.clicked.connect(self.reject)
        self.import_button = self.frame.add_button("Import", "primary")
        self.import_button.clicked.connect(self.run)
        self.resize(560, 560)
        self._preview()

    def load_file(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, "Load script", "", "Scripts (*.txt *.md *.markdown);;All files (*)"
        )
        if name:
            try:
                self.text.setPlainText(Path(name).read_text(encoding="utf-8-sig", errors="replace"))
            except OSError as error:
                self.summary.setText(f"Cannot read {Path(name).name}: {error.strerror or error}")

    def options(self) -> dict:
        return {
            "unit": self.unit.currentData(),
            "words_per_second": self.speed.value(),
            "placeholders": self.placeholders.isChecked(),
        }

    def _chips(self, made: list[tuple[str, str]]) -> None:
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for text, tone in made:
            self.chips.addWidget(Chip(text, tone))
        self.chips.addStretch(1)

    def _preview(self, *_args) -> None:
        try:
            _, report = script_import.import_script(self.current(), self.text.toPlainText(), **self.options())
        except edits.EditError as error:
            self.summary.setText(str(error))
            self._chips([("nothing to import", "warn")])
            self.import_button.setEnabled(False)
            return
        self.import_button.setEnabled(True)
        made = [(f"{report.cues} subtitles", "accent"), (f"{report.seconds:.0f} s", "neutral")]
        if report.layers:
            made.append((f"{report.layers} layers", "neutral"))
        if report.long_sentences:
            made.append((f"{len(report.long_sentences)} long", "warn"))
        self._chips(made)
        text = (
            f"{report.cues} subtitles in {report.paragraphs} paragraphs, {report.seconds:.0f} s of reading."
        )
        if report.layers:
            text += f" {report.layers} placeholder layers."
        if report.long_sentences:
            text += f" {len(report.long_sentences)} are long: consider cutting them."
        self.summary.setText(text)

    def run(self) -> None:
        try:
            edit, report = script_import.import_script(
                self.current(), self.text.toPlainText(), **self.options()
            )
        except edits.EditError as error:
            self.summary.setText(str(error))
            return
        self._apply(edit, f"Import script ({report.cues} subtitles)")
        self.accept()
