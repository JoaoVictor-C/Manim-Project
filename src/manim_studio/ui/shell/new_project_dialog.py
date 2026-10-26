"""File > New: the one question a new project asks (ADR 0056, amended).

How should the Transform clips you add match their pieces? **Smart** (the default) gives cleaner
in-between frames; **Classic** is Manim's own Transform, so the project's Python export stays
readable code. It can be changed later in Properties (Scene > New morphs), and it changes no
clip that exists.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

SMART = "smart"
CLASSIC = "classic"


class NewProjectDialog(QDialog):
    def __init__(self, remembered: str = SMART, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New project")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        intro = QLabel("How should morphs (Transform clips) match their pieces in this project?")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.smart_button = QRadioButton("Smart - cleaner in-between frames (recommended)")
        self.smart_button.setToolTip(
            "Pieces are paired by place and shape, holes with holes, and outlines start where they "
            "travel least: fewer twisted or tangled frames.\n"
            "The project's Python export is then an exact replay of the editor, not readable code."
        )
        self.classic_button = QRadioButton("Classic - readable Python export")
        self.classic_button.setToolTip(
            "Manim's own Transform: pieces and points paired in order.\n"
            "The project's Python export stays plain, readable Manim code."
        )
        layout.addWidget(self.smart_button)
        smart_note = QLabel("The Python export becomes an exact replay of the editor.")
        smart_note.setWordWrap(True)
        smart_note.setContentsMargins(24, 0, 0, 0)
        layout.addWidget(smart_note)
        layout.addWidget(self.classic_button)
        classic_note = QLabel("Manim's own Transform: the export stays plain Manim code.")
        classic_note.setWordWrap(True)
        classic_note.setContentsMargins(24, 0, 0, 0)
        layout.addWidget(classic_note)
        hint = QLabel("You can change this later in Properties (Scene > New morphs).")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        (self.classic_button if remembered == CLASSIC else self.smart_button).setChecked(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choice(self) -> str:
        return CLASSIC if self.classic_button.isChecked() else SMART
