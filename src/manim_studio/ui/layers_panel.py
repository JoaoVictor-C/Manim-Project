"""Layers dock (S2.4): the layer list, the object library, delete, rename, z-order.

The list shows the **front-most layer at the top** (the last layer in the
project), as image editors do. Every change is an operation submitted to the
``BuildService`` (ADR 0015), so adding a MathTex never freezes the UI and each
action is one undo step.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from pydantic import ValidationError
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import adapter, edits
from ..core.schema import RASTER_TYPES, Project
from .build_service import BuildService

ID_ROLE = Qt.ItemDataRole.UserRole


class LayerList(QListWidget):
    """Drag-to-reorder list; reports the dragged layer's new row."""

    rowDropped = Signal(str, int)  # layer id, new row (0 = front)

    def dropEvent(self, event) -> None:
        item = self.currentItem()
        super().dropEvent(event)
        if item is not None:
            self.rowDropped.emit(item.data(ID_ROLE), self.row(item))


class LayersPanel(QWidget):
    layerSelected = Signal(str)  # layer id, or "" for none
    message = Signal(str)  # errors for the status bar

    def __init__(self, builds: BuildService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.builds = builds
        self.document = builds.document
        # Hook for tests and other front-ends: returns an image path or "".
        self.choose_image: Callable[[], str] = self._choose_image_dialog
        self._known_ids: set[str] = set()
        self._select_new = False

        self.list = LayerList()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.itemChanged.connect(self._on_item_renamed)
        self.list.rowDropped.connect(self._on_row_dropped)

        self.add_button = QToolButton(text="Add", popupMode=QToolButton.ToolButtonPopupMode.InstantPopup)
        self.add_button.setMenu(self._library_menu())
        self.delete_button = self._button("Delete", self.delete_selected, QKeySequence.StandardKey.Delete)
        self.up_button = self._button("Up", lambda: self.shift_selected(+1), "Ctrl+]")
        self.down_button = self._button("Down", lambda: self.shift_selected(-1), "Ctrl+[")
        self.up_button.setToolTip("Bring forward (Ctrl+])")
        self.down_button.setToolTip("Send backward (Ctrl+[)")

        buttons = QHBoxLayout()
        for button in (self.add_button, self.delete_button, self.up_button, self.down_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(buttons)
        layout.addWidget(self.list, 1)

        self.document.changed.connect(lambda *_: self.sync())
        self.document.reset.connect(self._on_reset)
        self.sync()

    # -- building the widget ------------------------------------------------------

    def _button(self, text: str, slot: Callable[[], None], shortcut) -> QToolButton:
        action = QAction(text, self)
        action.setShortcut(shortcut)
        action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        action.triggered.connect(slot)
        self.addAction(action)
        button = QToolButton()
        button.setDefaultAction(action)
        return button

    def _library_menu(self) -> QMenu:
        menu = QMenu(self)
        for section, types in adapter.LIBRARY:
            menu.addSection(section)
            for type_name in types:
                action = menu.addAction(type_name)
                action.triggered.connect(partial(self.add_object, type_name))
        self.library_menu = menu
        return menu

    # -- state ----------------------------------------------------------------------

    @property
    def project(self) -> Project:
        return self.document.project

    def selected_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(ID_ROLE) if item is not None else None

    def select(self, layer_id: str | None) -> None:
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(ID_ROLE) == layer_id:
                self.list.setCurrentItem(item)
                return
        self.list.setCurrentItem(None)

    def ids_front_to_back(self) -> list[str]:
        return [self.list.item(row).data(ID_ROLE) for row in range(self.list.count())]

    def sync(self) -> None:
        """Rebuild the list from the document, keeping the selection."""
        selected = self.selected_id()
        ids = {layer.id for layer in self.project.layers}
        new = ids - self._known_ids
        self._known_ids = ids
        with QSignalBlocker(self.list):
            self.list.clear()
            for layer in reversed(self.project.layers):
                item = QListWidgetItem(layer.name or layer.id)
                item.setData(ID_ROLE, layer.id)
                item.setToolTip(f"{layer.id} - {layer.spec.type}")
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                self.list.addItem(item)
            target = selected if selected in ids else None
            if self._select_new and len(new) == 1:
                self._select_new = False
                target = next(iter(new))
            self.select(target)
        if target != selected:
            self.layerSelected.emit(target or "")
        self._update_buttons()

    def _on_reset(self, _project: Project) -> None:
        self._known_ids = set()
        self._select_new = False
        self.sync()

    def _update_buttons(self) -> None:
        row = self.list.currentRow()
        has = row >= 0
        self.delete_button.setEnabled(has)
        self.up_button.setEnabled(has and row > 0)
        self.down_button.setEnabled(has and row < self.list.count() - 1)

    # -- actions --------------------------------------------------------------------

    def add_object(self, type_name: str) -> None:
        extra = {}
        if type_name in RASTER_TYPES:
            path = self.choose_image()
            if not path:
                return
            extra["path"] = path
        spec = adapter.default_spec(type_name, **extra)
        self._select_new = True
        self._submit(partial(edits.add_layer, spec=spec), f"Add {type_name}")

    def delete_selected(self) -> None:
        layer_id = self.selected_id()
        if layer_id is not None:
            self._submit(partial(edits.remove_layer, layer_id=layer_id), "Delete layer")

    def shift_selected(self, steps: int) -> None:
        """+1 brings the layer one step forward (up the list), -1 sends it back."""
        layer_id = self.selected_id()
        if layer_id is None:
            return
        index = [layer.id for layer in self.project.layers].index(layer_id) + steps
        if 0 <= index < len(self.project.layers):
            self._submit(partial(edits.move_layer, layer_id=layer_id, index=index), "Reorder layers")

    def rename(self, layer_id: str, name: str) -> None:
        self._submit(partial(edits.update_layer, layer_id=layer_id, name=name.strip()), "Rename layer")

    def _submit(self, op, text: str) -> None:
        try:
            self.builds.submit(op, text)
        except (edits.EditError, ValidationError) as exc:
            self._select_new = False
            self.message.emit(f"{text}: {exc}")
            self.sync()

    # -- list signals -----------------------------------------------------------------

    def _on_current_changed(self, current: QListWidgetItem | None, _previous) -> None:
        self._update_buttons()
        self.layerSelected.emit(current.data(ID_ROLE) if current is not None else "")

    def _on_item_renamed(self, item: QListWidgetItem) -> None:
        layer = self.project.layer(item.data(ID_ROLE))
        name = item.text().strip()
        if name == (layer.name or layer.id):
            return
        self.rename(layer.id, "" if name in ("", layer.id) else name)

    def _on_row_dropped(self, layer_id: str, row: int) -> None:
        index = len(self.project.layers) - 1 - row  # the list is front-to-back
        if self.project.layers[index].id == layer_id:
            return
        self._submit(partial(edits.move_layer, layer_id=layer_id, index=index), "Reorder layers")

    def _choose_image_dialog(self) -> str:
        name, _ = QFileDialog.getOpenFileName(
            self, "Add image", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        return name
