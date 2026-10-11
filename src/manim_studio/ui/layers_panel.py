"""Layers dock (S2.4, P2c.3): the layer tree, the object library, parts, delete, rename, z-order.

The tree shows the **front-most object at the top** (the last object in the
project), as image editors do, with its part layers (ADR 0012) nested under it.
Every change is an operation submitted to the ``BuildService`` (ADR 0015), so
adding a MathTex or a part never freezes the UI and each action is one undo step.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from pydantic import ValidationError
from PySide6.QtCore import QPoint, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QSpinBox,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from ..core import adapter, edits, parts
from ..core.expressions import check as check_expression
from ..core.schema import (
    CHILD_TYPES,
    CODE_TYPES,
    MEDIA_TYPES,
    PART_PARENT_TYPES,
    RASTER_TYPES,
    TRACE_TYPES,
    Layer,
    Project,
    Spec,
)
from .build_service import BuildService

ID_ROLE = Qt.ItemDataRole.UserRole


class LayerTree(QTreeWidget):
    """Drag-to-reorder tree of objects; reports the dragged object's new top-level row.

    Qt never moves items itself (the drop is ignored): the panel submits a
    ``move_layer`` edit and rebuilds from the document, so parts can never be
    dropped into another object.
    """

    rowDropped = Signal(str, int)  # object id, new top-level row (0 = front)

    def dropEvent(self, event) -> None:
        item = self.currentItem()
        event.ignore()
        if item is None or item.parent() is not None:
            return
        target = self.itemAt(event.position().toPoint())
        while target is not None and target.parent() is not None:
            target = target.parent()
        row = self.topLevelItemCount() - 1 if target is None else self.indexOfTopLevelItem(target)
        below = self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.BelowItem
        if target is not None and below and row < self.indexOfTopLevelItem(item):
            row += 1
        self.rowDropped.emit(item.data(0, ID_ROLE), row)


class PartDialog(QDialog):
    """Ask for a part of an equation: its TeX and which occurrence (P2c.3).

    Shows live whether the part resolves, using the same rules as the edit.
    """

    def __init__(self, project: Project, parent_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add part")
        self._project, self._parent_id = project, parent_id
        self.tex = QLineEdit()
        self.tex.setPlaceholderText(r"e.g. b^2 or \frac{1}{3}")
        self.occurrence = QSpinBox(minimum=1, maximum=1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        source = QLabel(_text_of(project, parent_id))
        source.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form = QFormLayout()
        form.addRow("In:", source)
        form.addRow("TeX:", self.tex)
        form.addRow("Occurrence:", self.occurrence)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)
        self.tex.textChanged.connect(self._update)
        self.occurrence.valueChanged.connect(self._update)
        self._update()

    def key(self) -> tuple[str, int]:
        return self.tex.text(), self.occurrence.value() - 1

    def _update(self) -> None:
        text = _text_of(self._project, self._parent_id)
        tex = self.tex.text()
        n = parts.count(text, tex) if tex else 0
        self.occurrence.setMaximum(max(1, n))
        ok = False
        if not tex:
            message = "Type the TeX of the part, exactly as it appears above."
        else:
            try:
                edits.add_part(self._project, self._parent_id, *self.key())
                ok, message = True, f"Matches {n} time{'s' * (n != 1)}."
            except edits.EditError as error:
                message = str(error).removeprefix(f"cannot add part {tex!r}: ")
        self.status.setText(message)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)


def _text_of(project: Project, layer_id: str) -> str:
    """The TeX a part key is matched in: the object's text, or a part's span of it."""
    layer = project.layer(layer_id)
    root = project.root_of(layer_id)
    text = str(root.spec.params.get("text", ""))
    if not layer.is_part:
        return text
    span = parts.resolve(project, root.id).spans.get(layer_id)
    return text[span.start : span.end] if span else ""


AXES_MENU = (  # Parts > Add to axes (ADR 0030): type, menu label
    ("Point", "Point"),
    ("Area", "Area"),
    ("RiemannRectangles", "Riemann rectangles"),
    ("AxisLabels", "Axis labels"),
    ("GraphLabel", "Graph label"),
)


class LayersPanel(QWidget):
    layerSelected = Signal(str)  # layer id, or "" for none
    message = Signal(str)  # errors for the status bar

    def __init__(self, builds: BuildService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.builds = builds
        self.document = builds.document
        # Hooks for tests and other front-ends: an image path or ""; a part key or None.
        self.choose_image: Callable[[], str] = self._choose_image_dialog
        self.choose_svg: Callable[[], str] = self._choose_svg_dialog  # an SVG path or "" (ADR 0027)
        self.ask_part: Callable[[str], tuple[str, int] | None] = self._ask_part_dialog
        self.ask_expression: Callable[[], str | None] = self._ask_expression_dialog  # Add graph (ADR 0024)
        self.trust_code: Callable[[str], None] = lambda code: None  # set by the window (ADR 0019)
        self._known_ids: set[str] = set()
        self._select_new = False

        self.list = LayerTree()
        self.list.setHeaderHidden(True)
        self.list.setRootIsDecorated(True)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
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
        self.part_button = QToolButton(text="Parts", popupMode=QToolButton.ToolButtonPopupMode.InstantPopup)
        part_menu = QMenu(self)
        self.add_part_action = part_menu.addAction("Add part...", self.add_part)
        self.split_action = part_menu.addAction("Split into terms", self.split_terms)
        part_menu.addSeparator()
        self.add_graph_action = part_menu.addAction("Add graph...", self.add_graph)
        self.axes_menu = part_menu.addMenu("Add to axes")  # more objects on axes (ADR 0030)
        self.axes_actions = {
            type_name: self.axes_menu.addAction(label, partial(self.add_to_axes, type_name))
            for type_name, label in AXES_MENU
        }
        self.part_button.setMenu(part_menu)
        self.part_button.setToolTip("Animate pieces of an equation as their own layers, or plot on axes")

        buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.part_button,
            self.delete_button,
            self.up_button,
            self.down_button,
        ):
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
                action = menu.addAction(adapter.LIBRARY_LABELS.get(type_name, type_name))
                action.triggered.connect(partial(self.add_object, type_name))
        self.library_menu = menu
        return menu

    # -- state ----------------------------------------------------------------------

    @property
    def project(self) -> Project:
        return self.document.project

    def selected_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(0, ID_ROLE) if item is not None else None

    def items(self) -> list[QTreeWidgetItem]:
        """Every item in display order (objects front first, each followed by its parts)."""
        out, iterator = [], QTreeWidgetItemIterator(self.list)
        while iterator.value() is not None:
            out.append(iterator.value())
            iterator += 1
        return out

    def select(self, layer_id: str | None) -> None:
        for item in self.items():
            if item.data(0, ID_ROLE) == layer_id:
                self.list.setCurrentItem(item)
                return
        self.list.setCurrentItem(None)

    def ids_front_to_back(self) -> list[str]:
        return [item.data(0, ID_ROLE) for item in self.items()]

    def sync(self) -> None:
        """Rebuild the tree from the document, keeping the selection."""
        selected = self.selected_id()
        ids = {layer.id for layer in self.project.layers}
        new = ids - self._known_ids
        self._known_ids = ids
        orphans: dict[str, str] = {}
        for root in self.project.roots():
            if self.project.children(root.id):
                orphans.update(parts.resolve(self.project, root.id).orphans)
        with QSignalBlocker(self.list):
            self.list.clear()
            for root in reversed(self.project.roots()):
                self.list.addTopLevelItem(self._item(root, orphans))
            self.list.expandAll()
            target = selected if selected in ids else None
            if self._select_new and new:
                self._select_new = False
                target = next(layer.id for layer in self.project.layers if layer.id in new)
            self.select(target)
        if target != selected:
            self.layerSelected.emit(target or "")
        self.update_buttons()

    def _item(self, layer: Layer, orphans: dict[str, str]) -> QTreeWidgetItem:
        item = QTreeWidgetItem([layer.name or layer.id])
        item.setData(0, ID_ROLE, layer.id)
        if layer.is_part:
            tip = f"{layer.id} - part {layer.part.tex!r} (occurrence {layer.part.occurrence + 1})"
            if layer.id in orphans:
                item.setText(0, f"{layer.name or layer.id} (not found)")
                tip += f"\nNot drawn: {orphans[layer.id]}"
            item.setToolTip(0, tip)
            item.setFlags((item.flags() | Qt.ItemFlag.ItemIsEditable) & ~Qt.ItemFlag.ItemIsDragEnabled)
        else:
            item.setToolTip(0, f"{layer.id} - {layer.spec.type}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        for child in self.project.children(layer.id):
            item.addChild(self._item(child, orphans))
        return item

    def _on_reset(self, _project: Project) -> None:
        self._known_ids = set()
        self._select_new = False
        self.sync()

    def update_buttons(self) -> None:
        layer_id = self.selected_id()
        layer = self.project.layer(layer_id) if layer_id else None
        roots = [root.id for root in self.project.roots()]
        index = roots.index(layer_id) if layer is not None and not layer.is_child else -1
        self.delete_button.setEnabled(layer is not None)
        self.up_button.setEnabled(index >= 0 and index < len(roots) - 1)
        self.down_button.setEnabled(index > 0)
        can_part = layer is not None and self.project.root_of(layer.id).spec.type in PART_PARENT_TYPES
        has_morph = layer is not None and (
            any(c.to_layer for c in layer.clips) or layer.id in self.project.morph_sources()
        )
        self.add_part_action.setEnabled(can_part and not has_morph)
        self.split_action.setEnabled(can_part and not has_morph)
        axes = self._axes_of(layer)
        can_graph = axes is not None
        self.add_graph_action.setEnabled(can_graph)
        self.axes_menu.setEnabled(can_graph)
        has_graph = axes is not None and self._first_graph(axes) is not None
        for type_name, action in self.axes_actions.items():
            needs_graph = any(p.kind == "graph" for p in adapter.MOBJECT_PARAMS[type_name])
            action.setEnabled(can_graph and (has_graph or not needs_graph))
        self.part_button.setEnabled((can_part and not has_morph) or can_graph)

    # -- actions --------------------------------------------------------------------

    def add_object(self, type_name: str) -> None:
        extra = {}
        if type_name in MEDIA_TYPES:
            path = self.choose_image() if type_name in RASTER_TYPES else self.choose_svg()
            if not path:
                return
            extra["path"] = path
        if type_name in TRACE_TYPES:  # traces the selected object (ADR 0033)
            selected = self.selected_id()
            if selected is None or selected not in self.project.traceable_ids(""):
                self.message.emit("Select the object to trace first")
                return
            extra["target"] = selected
        spec = adapter.default_spec(type_name, **extra)
        if type_name in CODE_TYPES:
            self.trust_code(str(spec.params["code"]))  # the library's own starter scene
        self._select_new = True
        self._submit(partial(edits.add_layer, spec=spec), f"Add {type_name}")

    def add_part(self) -> None:
        """Ask for a part of the selected equation (or part) and add it."""
        parent_id = self.selected_id()
        if parent_id is None:
            return
        key = self.ask_part(parent_id)
        if key is None:
            return
        self._select_new = True
        self._submit(partial(edits.add_part, parent_id=parent_id, tex=key[0], occurrence=key[1]), "Add part")

    def _axes_of(self, layer: Layer | None) -> Layer | None:
        """The axes a selection belongs to (the axes themselves, or one of their objects)."""
        if layer is None:
            return None
        root = self.project.root_of(layer.id)
        return root if root.spec is not None and "Graph" in CHILD_TYPES.get(root.spec.type, ()) else None

    def _first_graph(self, axes: Layer) -> Layer | None:
        return next((x for x in self.project.children(axes.id) if x.spec and x.spec.type == "Graph"), None)

    def add_to_axes(self, type_name: str) -> None:
        """Add a point, an area, rectangles or a label to the selected axes (ADR 0030); objects
        built from a graph start on the axes' first graph."""
        selected = self.selected_id()
        axes = self._axes_of(self.project.layer(selected)) if selected else None
        if axes is None:
            return
        extra = {}
        if any(p.kind == "graph" for p in adapter.MOBJECT_PARAMS[type_name]):
            graph = self._first_graph(axes)
            if graph is None:
                self.message.emit("Add a graph to these axes first")
                return
            extra["graph"] = graph.id
        spec = adapter.default_spec(type_name, **extra)
        self._select_new = True
        label = dict(AXES_MENU)[type_name]
        self._submit(partial(edits.add_child, parent_id=axes.id, spec=spec), f"Add {label.lower()}")

    def add_graph(self) -> None:
        """Ask for a function of x and plot it on the selected axes (ADR 0024)."""
        selected = self.selected_id()
        axes = self._axes_of(self.project.layer(selected)) if selected else None
        if axes is None:
            return
        parent_id = axes.id
        expression = self.ask_expression()
        if expression is None:
            return
        problem = check_expression(expression)
        if problem:
            self.message.emit(f"Add graph: {problem}")
            return
        axes = self.project.layer(parent_id).spec
        x_range = list(axes.params.get("x_range", (-5.0, 5.0)))
        spec = Spec(type="Graph", params={"expression": expression.strip(), "x_range": x_range})
        self._select_new = True
        self._submit(partial(edits.add_child, parent_id=parent_id, spec=spec), "Add graph")

    def split_terms(self) -> None:
        """Make each top-level term of the selected equation (or part) a part, in one step."""
        parent_id = self.selected_id()
        if parent_id is None:
            return
        keys = self._free_terms(parent_id)
        if not keys:
            self.message.emit("Split into terms: no terms left to split")
            return
        self._submit(partial(edits.add_parts, parent_id=parent_id, keys=keys), "Split into terms")

    def _free_terms(self, parent_id: str) -> list[tuple[str, int]]:
        """Top-level terms of the parent's text that do not overlap an existing part."""
        root = self.project.root_of(parent_id)
        resolution = parts.resolve(self.project, root.id)
        whole = str(root.spec.params.get("text", ""))
        parent_span = resolution.spans.get(parent_id, parts.Span(0, len(whole)))
        taken = [resolution.spans[c.id] for c in self.project.children(parent_id) if c.id in resolution.spans]
        keys = []
        for tex, occurrence in parts.split_terms(whole[parent_span.start : parent_span.end]):
            start = parts.find(whole, tex, occurrence, parent_span.start, parent_span.end)
            span = parts.Span(start, start + len(tex))
            if span != parent_span and not any(span.overlaps(other) for other in taken):
                keys.append((tex, occurrence))
        return keys

    def delete_selected(self) -> None:
        layer_id = self.selected_id()
        if layer_id is not None:
            self._submit(partial(edits.remove_layer, layer_id=layer_id), "Delete layer")

    def shift_selected(self, steps: int) -> None:
        """+1 brings the object one step forward (up the tree), -1 sends it back."""
        layer_id = self.selected_id()
        if layer_id is None or self.project.layer(layer_id).is_child:
            return
        roots = [root.id for root in self.project.roots()]
        index = roots.index(layer_id) + steps
        if 0 <= index < len(roots):
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

    def context_menu(self, layer_id: str | None) -> QMenu:
        """The right-click menu for a layer (built separately so it can be tested)."""
        menu = QMenu(self)
        if layer_id is None:
            menu.addMenu(self.library_menu).setText("Add object")
            return menu
        if self.add_part_action.isEnabled():
            menu.addAction(self.add_part_action)
            menu.addAction(self.split_action)
            menu.addSeparator()
        menu.addAction("Delete", self.delete_selected)
        return menu

    def _show_context_menu(self, pos: QPoint) -> None:
        item = self.list.itemAt(pos)
        if item is not None:
            self.list.setCurrentItem(item)
        self.context_menu(item.data(0, ID_ROLE) if item is not None else None).exec(
            self.list.viewport().mapToGlobal(pos)
        )

    # -- tree signals -----------------------------------------------------------------

    def _on_current_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        self.update_buttons()
        self.layerSelected.emit(current.data(0, ID_ROLE) if current is not None else "")

    def _on_item_renamed(self, item: QTreeWidgetItem) -> None:
        layer = self.project.layer(item.data(0, ID_ROLE))
        name = item.text(0).strip()
        if name == (layer.name or layer.id):
            return
        self.rename(layer.id, "" if name in ("", layer.id) else name)

    def _on_row_dropped(self, layer_id: str, row: int) -> None:
        roots = [root.id for root in self.project.roots()]
        index = len(roots) - 1 - row  # the tree is front-to-back
        if roots[index] == layer_id:
            self.sync()
            return
        self._submit(partial(edits.move_layer, layer_id=layer_id, index=index), "Reorder layers")

    def _choose_image_dialog(self) -> str:
        name, _ = QFileDialog.getOpenFileName(
            self, "Add image", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        return name

    def _choose_svg_dialog(self) -> str:
        name, _ = QFileDialog.getOpenFileName(self, "Add SVG", "", "SVG drawings (*.svg)")
        return name

    def _ask_expression_dialog(self) -> str | None:
        text, ok = QInputDialog.getText(
            self, "Add graph", "y = (a function of x, e.g. sin(x), x**2/10 - 1, exp(-x**2))", text="sin(x)"
        )
        return text if ok else None

    def _ask_part_dialog(self, parent_id: str) -> tuple[str, int] | None:
        dialog = PartDialog(self.project, parent_id, self)
        return dialog.key() if dialog.exec() == QDialog.DialogCode.Accepted else None
