"""File > New: the one question a new project asks (ADR 0056, amended).

How should the Transform clips you add match their pieces? **Smart** (the default) gives cleaner
in-between frames; **Classic** is Manim's own Transform, so the project's Python export stays
readable code. It can be changed later in Properties (Scene > New morphs), and it changes no
clip that exists.

Drawn as a Lumen dialog (ADR 0063): an icon header, the two answers as option cards, the actions at the right.
"""

from __future__ import annotations

from PySide6.QtWidgets import QButtonGroup, QDialog, QLabel, QRadioButton, QWidget

from ..style.dialog_chrome import DialogFrame, OptionCard

SMART = "smart"
CLASSIC = "classic"


class NewProjectDialog(QDialog):
    def __init__(self, remembered: str = SMART, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New project")
        self.setMinimumWidth(460)
        self.frame = DialogFrame(
            self,
            "add",
            "New project",
            "How should morphs (Transform clips) match their pieces in this project?",
        )

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
        self.group = QButtonGroup(self)  # the radios sit in different cards, so they need a group
        self.group.addButton(self.smart_button)
        self.group.addButton(self.classic_button)
        self.smart_card = OptionCard(
            self.smart_button, "The Python export becomes an exact replay of the editor."
        )
        self.classic_card = OptionCard(
            self.classic_button, "Manim's own Transform: the export stays plain Manim code."
        )
        self.frame.body.addWidget(self.smart_card)
        self.frame.body.addWidget(self.classic_card)
        hint = QLabel("You can change this later in Properties (Scene > New morphs).")
        hint.setWordWrap(True)
        hint.setProperty("role", "hint")
        self.frame.body.addWidget(hint)

        (self.classic_button if remembered == CLASSIC else self.smart_button).setChecked(True)
        self.cancel_button = self.frame.add_button("Cancel")
        self.ok_button = self.frame.add_button("Create project", "primary")
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button.clicked.connect(self.accept)

    def choice(self) -> str:
        return CLASSIC if self.classic_button.isChecked() else SMART
