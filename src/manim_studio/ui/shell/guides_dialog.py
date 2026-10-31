"""View > Layout Guides...: the project's layout guides, listed, added, moved and deleted (ADR 0074).

A guide is a vertical or horizontal line at a position in scene units (the frame's centre is 0). Margins,
Thirds and Centre add a ready-made set; guides already there are kept, not doubled. Each change is one
undo step. The guides draw nothing in the video; View > Layout Guides shows them on the canvas.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QWidget,
)

from ...core.editing import edits
from ...core.model.schema import Guide, Project
from ..style.dialog_chrome import DialogFrame

DEFAULT_MARGIN = 0.5  # scene units


def describe(guide: Guide) -> str:
    kind = "Vertical" if guide.axis == "x" else "Horizontal"
    text = f"{kind}   {guide.axis} = {guide.position:g}"
    return f"{text}   ({guide.name})" if guide.name else text


class GuidesDialog(QDialog):
    def __init__(
        self,
        current: Callable[[], Project],
        apply: Callable[[edits.Edit, str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Layout guides")
        self.current, self._apply = current, apply
        self.frame = DialogFrame(
            self,
            "compose",
            "Layout guides",
            "Lines on the canvas that moved objects snap to. They are never drawn in the video.",
        )
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._picked)
        self.frame.body.addWidget(self.list)

        row = QHBoxLayout()
        self.axis = QComboBox()
        self.axis.addItem("Vertical (x)", "x")
        self.axis.addItem("Horizontal (y)", "y")
        self.position = QDoubleSpinBox()
        self.position.setRange(-1000.0, 1000.0)
        self.position.setDecimals(3)
        self.position.setSingleStep(0.25)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name (optional)")
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self.add)
        self.move_button = QPushButton("Move Selected")
        self.move_button.clicked.connect(self.move_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_selected)
        for widget in (
            self.axis,
            self.position,
            self.name,
            self.add_button,
            self.move_button,
            self.delete_button,
        ):
            row.addWidget(widget)
        self.frame.body.addLayout(row)

        presets = QHBoxLayout()
        for text, slot in (
            ("Margins...", self.add_margins),
            ("Thirds", self.add_thirds),
            ("Centre", self.add_centre),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            presets.addWidget(button)
        presets.addStretch(1)
        self.frame.body.addLayout(presets)
        self.status = QLabel("")
        self.status.setProperty("role", "muted")
        self.status.setWordWrap(True)
        self.frame.body.addWidget(self.status)

        close = self.frame.add_button("Close", "primary")
        close.clicked.connect(self.close)
        self.resize(620, 440)
        self.reload()

    # -- the list ------------------------------------------------------------------------------

    def reload(self) -> None:
        selected = self.selected_id()
        self.list.clear()
        for guide in self.current().guides:
            item = QListWidgetItem(describe(guide))
            item.setData(Qt.ItemDataRole.UserRole, guide.id)
            self.list.addItem(item)
            if guide.id == selected:
                self.list.setCurrentItem(item)
        has = self.list.currentItem() is not None
        self.move_button.setEnabled(has)
        self.delete_button.setEnabled(has)

    def selected_id(self) -> str | None:
        item = self.list.currentItem() if hasattr(self, "list") else None
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _picked(self, _row: int) -> None:
        guide = next((g for g in self.current().guides if g.id == self.selected_id()), None)
        has = guide is not None
        self.move_button.setEnabled(has)
        self.delete_button.setEnabled(has)
        if guide is not None:
            self.axis.setCurrentIndex(self.axis.findData(guide.axis))
            self.position.setValue(guide.position)
            self.name.setText(guide.name)

    # -- changes -------------------------------------------------------------------------------

    def _run(self, make: Callable[[Project], edits.Edit], text: str) -> bool:
        try:
            edit = make(self.current())
        except edits.EditError as error:
            self.status.setText(str(error).capitalize() + ".")
            return False
        self._apply(edit, text)
        self.status.setText("")
        self.reload()
        return True

    def add(self) -> None:
        axis, position, name = self.axis.currentData(), self.position.value(), self.name.text().strip()
        self._run(lambda p: edits.add_guide(p, axis, position, name), "Add guide")

    def move_selected(self) -> None:
        guide_id = self.selected_id()
        if guide_id is None:
            return
        position, name = self.position.value(), self.name.text().strip()
        self._run(lambda p: edits.move_guide(p, guide_id, position, name), "Move guide")

    def delete_selected(self) -> None:
        guide_id = self.selected_id()
        if guide_id is not None:
            self._run(lambda p: edits.remove_guide(p, guide_id), "Delete guide")

    def ask_margin(self) -> float | None:
        """The margin in scene units, or None when cancelled."""
        value, ok = QInputDialog.getDouble(
            self,
            "Margin guides",
            "Margin from the frame's edges (scene units):",
            DEFAULT_MARGIN,
            0.01,
            100.0,
            3,
        )
        return value if ok else None

    def add_margins(self) -> None:
        margin = self.ask_margin()
        if margin is not None:
            self._run(lambda p: edits.guides_from_margins(p, margin), "Margin guides")

    def add_thirds(self) -> None:
        self._run(edits.guides_for_thirds, "Thirds guides")

    def add_centre(self) -> None:
        self._run(edits.guides_for_centre, "Centre guides")
