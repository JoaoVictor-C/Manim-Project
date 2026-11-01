"""Animate > Recipe Parameters...: a recipe's length and delay between layers, edited after it is applied
(ADR 0080).

The dialog only asks: the main window turns the answer into ``sequences.reparameterise_sequence``, one undo
step. "Keep the delays as they are" leaves each layer's start where it is (the delays may differ).
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QWidget

from ..style.dialog_chrome import DialogFrame


class RecipeParametersDialog(QDialog):
    def __init__(
        self, name: str, length: float, stagger: float | None, layers: int, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Recipe parameters")
        self.frame = DialogFrame(
            self,
            "animate",
            f"Recipe parameters: {name}",
            "The whole length stretches every layer's part by one factor; the delay is between the "
            f"starts of consecutive layers ({layers} here).",
        )
        form = QFormLayout()
        self.length = QDoubleSpinBox()
        self.length.setRange(0.1, 3600.0)
        self.length.setDecimals(2)
        self.length.setSingleStep(0.25)
        self.length.setSuffix(" s")
        self.length.setValue(length)
        self.stagger = QDoubleSpinBox()
        self.stagger.setRange(0.0, 3600.0)
        self.stagger.setDecimals(2)
        self.stagger.setSingleStep(0.1)
        self.stagger.setSuffix(" s")
        self.stagger.setValue(stagger or 0.0)
        self.keep = QCheckBox("Keep the delays as they are")
        self.keep.toggled.connect(lambda on: self.stagger.setEnabled(not on))
        self.keep.setChecked(stagger is None)
        form.addRow("Length:", self.length)
        form.addRow("Delay between layers:", self.stagger)
        form.addRow("", self.keep)
        self.frame.body.addLayout(form)
        cancel = self.frame.add_button("Cancel")
        cancel.clicked.connect(self.reject)
        ok = self.frame.add_button("Apply", "primary")
        ok.clicked.connect(self.accept)

    def answer(self) -> tuple[float, float | None]:
        """The length, and the delay (None: keep the delays)."""
        return self.length.value(), None if self.keep.isChecked() else self.stagger.value()
