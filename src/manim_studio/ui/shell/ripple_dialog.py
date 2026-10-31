"""Edit > Ripple Edit...: open or close time at a point, or give a beat another length (ADR 0071).

Everything that starts at or after the point moves together; the check boxes choose which kinds go along, and
the line under them says exactly what would move (or why the edit cannot be made) before anything changes.
One undo step.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QWidget,
)

from ...core.editing import edits, ripple
from ...core.model.schema import Project
from ..style.dialog_chrome import DialogFrame

INSERT, BEAT = "insert", "beat"


class RippleDialog(QDialog):
    def __init__(
        self,
        current: Callable[[], Project],
        playhead: float,
        apply: Callable[[edits.Edit, str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ripple edit")
        self.current, self._apply = current, apply
        self.frame = DialogFrame(
            self,
            "chapters",
            "Ripple edit",
            "Open or close time and let what follows move with it, or change the length of a beat.",
        )
        self.mode = QComboBox()
        self.mode.addItem("Insert or remove time at a point", INSERT)
        self.mode.addItem("Change the length of a beat", BEAT)
        self.mode.currentIndexChanged.connect(self._mode_changed)

        self.at = QDoubleSpinBox()
        self.at.setRange(0.0, 36000.0)
        self.at.setDecimals(3)
        self.at.setSuffix(" s")
        self.at.setValue(playhead)
        self.amount = QDoubleSpinBox()
        self.amount.setRange(-3600.0, 3600.0)
        self.amount.setDecimals(3)
        self.amount.setSuffix(" s")
        self.amount.setValue(1.0)
        self.beat = QComboBox()
        for found in ripple.beats(current()):
            self.beat.addItem(f"{found.name}  ({found.start:g}-{found.end:g} s)", found)
        self.length = QDoubleSpinBox()
        self.length.setRange(0.01, 3600.0)
        self.length.setDecimals(3)
        self.length.setSuffix(" s")
        self.beat.currentIndexChanged.connect(self._beat_changed)

        self.scope_boxes = {
            name: QCheckBox(label)
            for name, label in (
                ("clips", "Clips"),
                ("keys", "Keys"),
                ("audio", "Sounds"),
                ("subtitles", "Subtitles"),
                ("markers", "Markers"),
            )
        }
        for box in self.scope_boxes.values():
            box.setChecked(True)
            box.toggled.connect(self._preview)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setProperty("role", "muted")

        self.form = QFormLayout()
        self.form.addRow("Mode", self.mode)
        self.form.addRow("At", self.at)
        self.form.addRow("Amount (negative closes)", self.amount)
        self.form.addRow("Beat", self.beat)
        self.form.addRow("New length", self.length)
        for name, box in self.scope_boxes.items():
            self.form.addRow("Moves along" if name == "clips" else "", box)
        self.frame.body.addLayout(self.form)
        self.frame.body.addWidget(self.summary)
        for spin in (self.at, self.amount, self.length):
            spin.valueChanged.connect(self._preview)
        cancel = self.frame.add_button("Cancel")
        cancel.clicked.connect(self.reject)
        self.apply_button = self.frame.add_button("Apply", "primary")
        self.apply_button.clicked.connect(self.run)
        self.resize(520, 460)
        self._beat_changed()
        self._mode_changed()

    # -- reading the form ------------------------------------------------------------

    def scope(self) -> ripple.Scope:
        return ripple.Scope(**{name: box.isChecked() for name, box in self.scope_boxes.items()})

    def edit(self) -> edits.Edit:
        """The edit the form describes (EditError when it cannot be made)."""
        project = self.current()
        if self.mode.currentData() == BEAT:
            found = self.beat.currentData()
            if found is None:
                raise edits.EditError("the project has no beats: add markers on the timeline")
            return ripple.retime_beat(project, found, self.length.value(), self.scope())
        return ripple.ripple(project, self.at.value(), self.amount.value(), self.scope())

    def _point(self) -> float:
        found = self.beat.currentData()
        return found.end if self.mode.currentData() == BEAT and found is not None else self.at.value()

    # -- keeping the form coherent -----------------------------------------------------

    def _mode_changed(self, *_args) -> None:
        beat = self.mode.currentData() == BEAT
        for widget in (self.at, self.amount):
            self.form.labelForField(widget).setVisible(not beat)
            widget.setVisible(not beat)
        for widget in (self.beat, self.length):
            self.form.labelForField(widget).setVisible(beat)
            widget.setVisible(beat)
        self._preview()

    def _beat_changed(self, *_args) -> None:
        found = self.beat.currentData()
        if found is not None:
            self.length.blockSignals(True)
            self.length.setValue(found.length)
            self.length.blockSignals(False)
        self._preview()

    def _preview(self, *_args) -> None:
        if not hasattr(self, "apply_button"):
            return
        try:
            self.edit()
        except edits.EditError as error:
            self.summary.setText(str(error))
            self.apply_button.setEnabled(False)
            return
        self.apply_button.setEnabled(True)
        found = ripple.affected(self.current(), self._point(), self.scope())
        self.summary.setText(found.summary())

    def run(self) -> None:
        try:
            edit = self.edit()
        except edits.EditError as error:
            self.summary.setText(str(error))
            return
        self._apply(edit, "Ripple edit")
        self.accept()
