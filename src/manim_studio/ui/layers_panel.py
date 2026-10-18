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
from PySide6.QtCore import QPoint, QSignalBlocker, QSize, Qt, Signal
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

from .. import plugins
from ..core import adapter, edits, parts, placement, python_object, shape
from ..core.expressions import check as check_expression
from ..core.layer_index import LayerIndex
from ..core.python_object import PYTHON_TYPE
from ..core.schema import (
    CHILD_TYPES,
    CODE_TYPES,
    CONNECTOR_TYPES,
    MEDIA_TYPES,
    PART_PARENT_TYPES,
    RASTER_TYPES,
    TRACE_TYPES,
    Layer,
    Project,
    Spec,
)
from . import icons
from .build_service import BuildService
from .equation_steps_dialog import EquationStepsDialog, StepsRequest
from .fields import pick_colour

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


def add_placed(project: Project, spec: Spec, t: float) -> edits.Edit:
    """Add an object where it does not cover the others (GP, ``core.placement``)."""
    edit = edits.add_layer(project, spec)
    where = placement.position_for(project, spec, t)
    if where == (0.0, 0.0):
        return edit
    new = edit.project.layers[-1]
    moved = edits.update_layer(edit.project, new.id, base=new.base.model_copy(update={"position": where}))
    return edits.Edit(moved.project, *edits.classify(project, moved.project))


def add_steps_placed(
    project: Project, request: StepsRequest, t: float, measurable: Callable[[Spec], bool]
) -> edits.Edit:
    """``edits.add_equation_steps`` for the dialog's answer (P11): in a free spot when asked and
    every step can be measured without a slow LaTeX build (``measurable``), else at the centre."""
    specs = [
        Spec(type="MathTex", params={"text": tex, "font_size": request.font_size}) for tex in request.steps
    ]
    position = (0.0, 0.0)
    if request.free_spot and all(measurable(spec) for spec in specs):
        boxes = [box for box in map(placement.drawn_box, specs) if box is not None]
        if boxes:
            size = (max(b[1][0] - b[0][0] for b in boxes), max(b[1][1] - b[0][1] for b in boxes))
            half = (project.canvas.frame_width / 2, project.canvas.frame_height / 2)
            frame = ((-half[0], -half[1]), half)
            position = placement.place(placement.occupied(project, t), size, frame)
    edit, _ = edits.add_equation_steps(
        project,
        request.steps,
        start=request.start,
        step_duration=request.step_duration,
        hold=request.hold,
        font_size=request.font_size,
        colour=request.colour,
        highlight_colour=request.highlight_colour,
        position=position,
        entrance=request.entrance,
    )
    return edit


class LayersPanel(QWidget):
    layerSelected = Signal(str)  # layer id, or "" for none
    layersPicked = Signal(list, str)  # several layers (Ctrl/Shift+click) and the current one (ADR 0043)
    message = Signal(str)  # errors for the status bar

    def __init__(self, builds: BuildService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.builds = builds
        self.document = builds.document
        # Hooks for tests and other front-ends: an image path or ""; a part key or None.
        self.choose_image: Callable[[], str] = self._choose_image_dialog
        self.choose_svg: Callable[[], str] = self._choose_svg_dialog  # an SVG path or "" (ADR 0027)
        self.ask_part: Callable[[str], tuple[str, int] | None] = self._ask_part_dialog
        self.ask_colour: Callable[[str | None], str | None] = lambda current: pick_colour(self, current)
        self.ask_expression: Callable[[], str | None] = self._ask_expression_dialog  # Add graph (ADR 0024)
        self.ask_steps: Callable[[float], StepsRequest | None] = self._ask_steps_dialog  # P11
        self.trust_code: Callable[[str], None] = lambda code: None  # set by the window (ADR 0019)
        self.freeze: Callable[[str], None] = lambda layer_id: None  # set by the window (ADR 0052)
        self._known_ids: set[str] = set()
        self.playhead: Callable[[], float] = lambda: 0.0  # set by the window: where new objects are placed
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
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        self.list.itemChanged.connect(self._on_item_renamed)
        self.list.rowDropped.connect(self._on_row_dropped)

        self.add_button = QToolButton(text="Add", popupMode=QToolButton.ToolButtonPopupMode.InstantPopup)
        self.add_button.setMenu(self._library_menu())
        self.add_button.setIcon(icons.icon("add"))  # (ADR 0040)
        self.add_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.add_button.setToolTip("Add an object, a simulation or a template")
        self.delete_button = self._button(
            "Delete", self.delete_selected, QKeySequence.StandardKey.Delete, "delete"
        )
        self.up_button = self._button("Up", lambda: self.shift_selected(+1), "Ctrl+]", "move-up")
        self.down_button = self._button("Down", lambda: self.shift_selected(-1), "Ctrl+[", "move-down")
        self.delete_button.setToolTip("Delete the selected layer (Delete)")
        self.up_button.setToolTip("Bring forward (Ctrl+])")
        self.down_button.setToolTip("Send backward (Ctrl+[)")
        self.part_button = QToolButton(text="Parts", popupMode=QToolButton.ToolButtonPopupMode.InstantPopup)
        part_menu = QMenu(self)
        self.add_part_action = part_menu.addAction("Add part...", self.add_part)
        self.split_action = part_menu.addAction("Split into terms", self.split_terms)
        self.colour_part_action = part_menu.addAction("Colour part...", self.colour_part)  # ADR 0049
        part_menu.addSeparator()
        self.add_graph_action = part_menu.addAction("Add graph...", self.add_graph)
        self.axes_menu = part_menu.addMenu("Add to axes")  # more objects on axes (ADR 0030)
        self.axes_actions = {
            type_name: self.axes_menu.addAction(label, partial(self.add_to_axes, type_name))
            for type_name, label in AXES_MENU
        }
        self.part_button.setMenu(part_menu)
        self.part_button.setIcon(icons.icon("parts"))
        self.part_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.part_button.setToolTip("Animate pieces of an equation as their own layers, or plot on axes")

        self.buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.part_button,
            self.delete_button,
            self.up_button,
            self.down_button,
        ):
            self.buttons.addWidget(button)
        self.buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(self.buttons)
        layout.addWidget(self.list, 1)
        self.labelled = (self.add_button, self.part_button)  # icons only when the panel is narrow (P6d.4)
        self._full_width = self._row_width()

        self.document.changed.connect(lambda *_: self.sync())
        self.document.reset.connect(self._on_reset)
        self.sync()

    # -- narrow panels (P6d.4) --------------------------------------------------------

    def _row_width(self, compact: bool = False) -> int:
        """The button row's width with its captions shown (or, ``compact``, icons only)."""
        icon_only = self.delete_button.sizeHint().width()
        widths = [
            icon_only if compact and button in self.labelled else button.sizeHint().width()
            for button in (
                self.add_button,
                self.part_button,
                self.delete_button,
                self.up_button,
                self.down_button,
            )
        ]
        margins = self.layout().contentsMargins() if self.layout() else None
        sides = margins.left() + margins.right() if margins else 8
        return sum(widths) + self.buttons.spacing() * (len(widths) - 1) + sides

    @property
    def compact(self) -> bool:
        return self.add_button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly

    def minimumSizeHint(self) -> QSize:
        return QSize(self._row_width(compact=True), super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        style = (
            Qt.ToolButtonStyle.ToolButtonIconOnly
            if self.width() < self._full_width
            else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        for button in self.labelled:
            if button.toolButtonStyle() != style:
                button.setToolButtonStyle(style)

    # -- building the widget ------------------------------------------------------

    def _button(self, text: str, slot: Callable[[], None], shortcut, icon_name: str) -> QToolButton:
        """An icon button for an action that keeps ``text`` (menus, accessibility, tests)."""
        action = QAction(icons.icon(icon_name), text, self)
        action.setShortcut(shortcut)
        action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        action.triggered.connect(slot)
        self.addAction(action)
        button = QToolButton()
        button.setDefaultAction(action)
        button.setAccessibleName(text)
        return button

    def _library_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        for section, types in adapter.LIBRARY:
            menu.addSection(section)
            for type_name in types:
                action = menu.addAction(adapter.LIBRARY_LABELS.get(type_name, type_name))
                action.triggered.connect(partial(self.add_object, type_name))
                if type_name == "MathTex":  # P11: a derivation, one MathTex per step
                    self.equation_steps_action = menu.addAction("Equation steps...", self.add_equation_steps)
                    self.equation_steps_action.setToolTip(
                        "Type the steps of a derivation, one equation per line: one MathTex per step, "
                        "morphing into the next"
                    )
        self.library_menu = menu
        return menu

    # -- state ----------------------------------------------------------------------

    @property
    def project(self) -> Project:
        return self.document.project

    def selected_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(0, ID_ROLE) if item is not None else None

    def selected_ids(self) -> list[str]:
        """Every selected layer, in display order (front first)."""
        chosen = {id(item) for item in self.list.selectedItems()}
        return [item.data(0, ID_ROLE) for item in self.items() if id(item) in chosen]

    def items(self) -> list[QTreeWidgetItem]:
        """Every item in display order (objects front first, each followed by its parts)."""
        out, iterator = [], QTreeWidgetItemIterator(self.list)
        while iterator.value() is not None:
            out.append(iterator.value())
            iterator += 1
        return out

    def select(self, layer_id: str | None, others=()) -> None:
        """Make ``layer_id`` current and select it with ``others`` (ADR 0043)."""
        wanted = {layer_id, *others} - {None}
        current = None
        for item in self.items():
            if item.data(0, ID_ROLE) == layer_id:
                current = item
        self.list.setCurrentItem(current)
        for item in self.items():
            item.setSelected(item.data(0, ID_ROLE) in wanted)

    def ids_front_to_back(self) -> list[str]:
        return [item.data(0, ID_ROLE) for item in self.items()]

    def sync(self) -> None:
        """Rebuild the tree from the document, keeping the selection."""
        selected = self.selected_id()
        chosen = self.selected_ids()
        ids = {layer.id for layer in self.project.layers}
        new = ids - self._known_ids
        self._known_ids = ids
        index = LayerIndex(self.project)  # one pass, not one scan per layer (B66)
        roots = index.roots()
        orphans: dict[str, str] = {}
        picked_many = False
        for root in roots:
            if index.children(root.id):
                orphans.update(parts.resolve(self.project, root.id, index).orphans)
        with QSignalBlocker(self.list):
            self.list.clear()
            for root in reversed(roots):
                self.list.addTopLevelItem(self._item(root, orphans, index))
            self.list.expandAll()
            target = selected if selected in ids else None
            if self._select_new and new:
                every = self._select_new == "all"  # all the new objects (equation steps, P11)
                self._select_new = False
                target = next(layer.id for layer in self.project.layers if layer.id in new)
                chosen = [x.id for x in roots if x.id in new] if every else []
                picked_many = len(chosen) > 1
            self.select(target, [i for i in chosen if i in ids])
        if picked_many:  # the new objects, all of them (the signals were blocked)
            self.layersPicked.emit(self.selected_ids(), target)
        elif target != selected:
            self.layerSelected.emit(target or "")
        self.update_buttons()

    def _item(self, layer: Layer, orphans: dict[str, str], index: LayerIndex) -> QTreeWidgetItem:
        item = QTreeWidgetItem([layer.label])
        item.setData(0, ID_ROLE, layer.id)
        if layer.is_part:
            tip = f"{layer.id} - part {layer.part.tex!r} (occurrence {layer.part.occurrence + 1})"
            if layer.id in orphans:
                item.setText(0, f"{layer.label} (not found)")
                tip += f"\nNot drawn: {orphans[layer.id]}"
            item.setToolTip(0, tip)
            item.setFlags((item.flags() | Qt.ItemFlag.ItemIsEditable) & ~Qt.ItemFlag.ItemIsDragEnabled)
        elif layer.is_group:  # ADR 0050
            count = len(index.children(layer.id))
            item.setToolTip(0, f"{layer.id} - group of {count} object{'s' if count != 1 else ''}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        else:
            item.setToolTip(0, f"{layer.id} - {layer.spec.type}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        for child in index.children(layer.id):
            item.addChild(self._item(child, orphans, index))
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
        is_part = layer is not None and layer.is_part
        self.colour_part_action.setEnabled(is_part or (can_part and not has_morph))
        self.colour_part_action.setText("Colour this part..." if is_part else "Colour part...")
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
        if type_name in CONNECTOR_TYPES:  # from the object before the selected one, to it (ADR 0036)
            selected = self.selected_id()
            joinable = self.project.traceable_ids("")
            if selected is None or selected not in joinable or len(joinable) < 2:
                self.message.emit("Select the object to connect to first (it needs another object)")
                return
            index = joinable.index(selected)
            extra = {"source": joinable[index - 1] if index > 0 else joinable[1], "target": selected}
        spec = adapter.default_spec(type_name, **extra)
        if type_name in CODE_TYPES:
            self.trust_code(str(spec.params["code"]))  # the library's own starter scene
        self._select_new = True
        self._submit(partial(add_placed, spec=spec, t=self.playhead()), f"Add {type_name}")

    def add_python_object(self, code: str | None = None) -> None:
        """A Python object (ADR 0051), from a template (the right triangle by default): made on the
        Code page, not the library."""
        code = python_object.STARTER if code is None else code
        spec = Spec(type=PYTHON_TYPE, params={"code": code})
        self.trust_code(code)  # the editor's own template
        self._select_new = True
        self._submit(partial(add_placed, spec=spec, t=self.playhead()), "Add Python object")

    def add_equation_steps(self) -> None:
        """Add > Equation steps... (P11): ask for the steps, then add one MathTex per step with
        the morphs between them as one undo step, and select them. On a computer without LaTeX
        they are added at once (each draws a placeholder that says why) instead of waiting for
        builds that cannot succeed."""
        request = self.ask_steps(self.playhead())
        if request is None:
            return
        builds = self.builds
        op = partial(
            add_steps_placed,
            request=request,
            t=self.playhead(),
            measurable=lambda spec: not builds.client.available or builds.is_warm(spec),
        )
        self._select_new = "all"
        text = "Add equation steps"
        if adapter.latex_problem() is None:
            if request.free_spot:  # the plain formulas are measured: warm them first (in order)
                builds.prewarm([Spec(type="MathTex", params={"text": tex}) for tex in request.steps])
            self._submit(op, text)
            return
        try:
            self.document.apply(op(self.project), text)
        except (edits.EditError, ValidationError) as exc:
            self._select_new = False
            self.message.emit(f"{text}: {exc}")
            return
        self.message.emit(f"{text}: {adapter.latex_problem()}; the steps show placeholders until it is")

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

    def colour_part(self) -> None:
        """Colour a part (ADR 0049): the selected part, or a part of the selected equation that is
        asked for (made a part layer if it is not one yet), in one undo step."""
        layer_id = self.selected_id()
        if layer_id is None:
            return
        layer = self.project.layer(layer_id)
        if layer.is_part:
            colour = self.ask_colour(layer.style.get("fill"))
            if colour is not None:
                self._submit(partial(edits.set_part_style, layer_id=layer_id, fill=colour), "Colour part")
            return
        key = self.ask_part(layer_id)
        if key is None:
            return
        colour = self.ask_colour(None)
        if colour is None:
            return
        op = partial(edits.colour_part, parent_id=layer_id, tex=key[0], occurrence=key[1], fill=colour)
        self._submit(op, "Colour part")

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
        chosen = self.selected_ids()
        if len(chosen) > 1:  # several: one undo step (ADR 0043)
            self._submit(partial(edits.remove_layers, layer_ids=chosen), "Delete layers")
            return
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
        if self.colour_part_action.isEnabled():
            menu.addAction(self.colour_part_action)
        if self.add_part_action.isEnabled() or self.colour_part_action.isEnabled():
            menu.addSeparator()
        layer = self.project.layer(layer_id) if layer_id in {x.id for x in self.project.layers} else None
        if (
            layer is not None
            and shape.kind_problem(layer) is None
            and layer.spec.type not in plugins.SIMULATIONS
        ):
            freeze = menu.addAction("Freeze to Shape", lambda: self.freeze(layer_id))  # ADR 0052
            freeze.setToolTip("Plain vector data as drawn now: no code, no LaTeX (undo turns it back)")
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
        if len(self.list.selectedItems()) > 1:
            return  # several: _on_selection_changed reports them
        self.layerSelected.emit(current.data(0, ID_ROLE) if current is not None else "")

    def _on_selection_changed(self) -> None:
        chosen = self.selected_ids()
        if len(chosen) > 1:
            current = self.selected_id()
            self.layersPicked.emit(chosen, current if current in chosen else chosen[-1])
        elif chosen and chosen[0] != self.selected_id():
            self.layerSelected.emit(chosen[0])

    def _on_item_renamed(self, item: QTreeWidgetItem) -> None:
        layer = self.project.layer(item.data(0, ID_ROLE))
        name = item.text(0).strip()
        if name == (layer.label):
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

    def _ask_steps_dialog(self, start: float) -> StepsRequest | None:
        dialog = EquationStepsDialog(start, self.builds, parent=self)
        return dialog.request() if dialog.exec() == QDialog.DialogCode.Accepted else None

    def _ask_part_dialog(self, parent_id: str) -> tuple[str, int] | None:
        dialog = PartDialog(self.project, parent_id, self)
        return dialog.key() if dialog.exec() == QDialog.DialogCode.Accepted else None
