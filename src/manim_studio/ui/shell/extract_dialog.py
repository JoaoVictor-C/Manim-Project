"""Edit > Extract Selection as Code...: the code the selected layers would become, before they are replaced
(ADR 0076, 0084).

The window builds the extraction (``core.engine.extract_code``) and shows it here: a code card with the
generated Manim scene, chips for what goes in (layers, lines, plain Manim) and the primary *Extract*. A
*Same picture* ok chip appears after a check says the code draws what the layers drew; the check is a
callable the window may pass (it renders both and compares), and without one the chip says *Not checked*
- the dialog never claims a match it did not see. Cancel changes nothing.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QWidget

from ..style import theme
from ..style.card import Chip
from ..style.dialog_chrome import DialogFrame

SAME, DIFFERENT, UNCHECKED = "Same picture", "Differs", "Not checked"


class ExtractCodeDialog(QDialog):
    def __init__(
        self,
        code: str,
        layers: int,
        verify: Callable[[], bool] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Extract as code")
        self.code, self._verify = code, verify
        noun = "layer" if layers == 1 else "layers"
        self.frame = DialogFrame(
            self,
            "code",
            "Extract as code",
            f"{'The selected layer becomes' if layers == 1 else f'The {layers} selected layers become'} "
            "one code layer that draws the same. Undo brings the layers back.",
        )
        chips = QHBoxLayout()
        chips.setSpacing(6)
        lines = len(code.splitlines())
        self.layers_chip = Chip(f"{layers} {noun}", "accent")
        self.lines_chip = Chip(f"{lines} lines")
        self.plain_chip = Chip("plain Manim")
        self.check_chip = Chip(UNCHECKED if verify is None else "Checking...")
        for chip in (self.layers_chip, self.lines_chip, self.plain_chip):
            chips.addWidget(chip)
        chips.addStretch(1)
        chips.addWidget(self.check_chip)
        self.frame.body.addLayout(chips)
        self.preview = QPlainTextEdit(code)
        self.preview.setReadOnly(True)
        self.preview.setFont(theme.mono_font())
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.frame.body.addWidget(self.preview, 1)
        note = QLabel(
            "Edit the scene afterwards on the Code page; the editor keeps drawing it with the layers' frame."
        )
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        self.frame.body.addWidget(note)
        cancel = self.frame.add_button("Cancel")
        cancel.clicked.connect(self.reject)
        self.extract_button = self.frame.add_button("Extract", "primary")
        self.extract_button.clicked.connect(self.accept)
        self.resize(560, 520)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._verify is not None:
            QTimer.singleShot(0, self, self.check)

    def check(self) -> None:
        """Run the check (when there is one) and say what it found."""
        if self._verify is None:
            return
        self.set_checked(bool(self._verify()))

    def set_checked(self, same: bool) -> None:
        self.check_chip.setText(SAME if same else DIFFERENT)
        self.check_chip.set_tone("ok" if same else "warn")
