"""View > Layout Guides...: the project's layout guides, listed, added, moved and deleted (ADR 0074).

A guide is a vertical or horizontal line at a position in scene units (the frame's centre is 0). Margins,
Thirds and Centre add a ready-made set; guides already there are kept, not doubled. Each change is one
undo step. The guides draw nothing in the video; View > Layout Guides shows them on the canvas.

The design (lumen.md, Stage, guides and labels) wants this as a popover on the stage header's ruler
button rather than a window. That needs the stage header (owned by the canvas package, which this package may
not import), so the dialog keeps its place here, in the dialog shape of ADR 0084: rows with chips, a
segmented axis, one task; moving it into a popover is a change of container, not of content.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from ...core.editing import edits
from ...core.model.schema import Guide, Project
from ..style.dialog_chrome import DialogFrame
from ..style.list_row import ListRow, RowList
from ..style.segmented import Segmented

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
        self.list = RowList()
        self.list.currentRowChanged.connect(self._picked)
        self.frame.body.addWidget(self.list, 1)
        self.empty_note = QLabel("No guides yet. Add one below, or pull one from a ruler on the canvas.")
        self.empty_note.setProperty("role", "muted")
        self.empty_note.setWordWrap(True)
        self.frame.body.addWidget(self.empty_note)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.axis = Segmented()
        self.axis.addItem("Vertical", "x", "A line at x = position")
        self.axis.addItem("Horizontal", "y", "A line at y = position")
        self.position = QDoubleSpinBox()
        self.position.setRange(-1000.0, 1000.0)
        self.position.setDecimals(3)
        self.position.setSingleStep(0.25)
        self.position.setSuffix(" u")
        self.position.setToolTip("Scene units from the frame's centre")
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name (optional)")
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self.add)
        self.move_button = QPushButton("Move Selected")
        self.move_button.clicked.connect(self.move_selected)
        self.delete_button = QPushButton("Delete")
        self.delete_button.setProperty("role", "danger")
        self.delete_button.clicked.connect(self.delete_selected)
        row.addWidget(self.axis)
        row.addWidget(self.position, 1)
        row.addWidget(self.name, 2)
        self.frame.body.addLayout(row)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        buttons.addWidget(self.move_button)
        buttons.addWidget(self.add_button)
        self.frame.body.addLayout(buttons)

        presets = QHBoxLayout()
        for text, slot in (
            ("Margins...", self.add_margins),
            ("Thirds", self.add_thirds),
            ("Centre", self.add_centre),
        ):
            button = QPushButton(text)
            button.setProperty("role", "ghost")
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
        self.resize(560, 520)
        self.reload()

    # -- the list ------------------------------------------------------------------------------

    def reload(self) -> None:
        selected = self.selected_id()
        self.list.clear()
        for guide in self.current().guides:
            vertical = guide.axis == "x"
            widget = ListRow(guide.name or ("Vertical guide" if vertical else "Horizontal guide"))
            widget.mono_label.setText(f"{guide.axis} = {guide.position:g}")
            widget.mono_label.show()
            widget.add_head_chip(
                "Vertical" if vertical else "Horizontal", "accent" if vertical else "neutral"
            )
            item = self.list.add_row(widget, describe(guide), guide.id)
            if guide.id == selected:
                self.list.setCurrentItem(item)
        self.empty_note.setVisible(not self.current().guides)
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
