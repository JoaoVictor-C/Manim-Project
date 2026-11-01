"""Layers dock (S2.4, P2c.3): the layer tree, the object library, parts, delete, rename, z-order.

The tree shows the **front-most object at the top** (the last object in the
project), as image editors do, with its part layers (ADR 0012) nested under it.
Every change is an operation submitted to the ``BuildService`` (ADR 0015), so
adding a MathTex or a part never freezes the UI and each action is one undo step.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from pydantic import ValidationError
from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QPoint,
    QRect,
    QRectF,
    QSignalBlocker,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QFont, QFontMetrics, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from ... import plugins
from ...core.code import python_object, python_templates
from ...core.code.python_object import PYTHON_TYPE
from ...core.editing import clipboard, edits
from ...core.engine import adapter, placement
from ...core.model import glyph_colours, parts, shape
from ...core.model.expressions import check as check_expression
from ...core.model.layer_index import LayerIndex
from ...core.model.schema import (
    CHILD_TYPES,
    CODE_TYPES,
    CONNECTOR_TYPES,
    GLYPH_COLOURS,
    MEDIA_TYPES,
    PART_PARENT_TYPES,
    PIN_ANCHORS,
    RASTER_TYPES,
    TEXT_TYPES,
    TRACE_TYPES,
    Layer,
    Lifetime,
    Project,
    Spec,
)
from ..session import code_drag
from ..session.build_service import BuildService
from ..style import icons, theme
from ..style.fields import pick_colour
from .equation_steps_dialog import EquationStepsDialog, StepsRequest
from .glyph_colours_dialog import ask_glyph_colours
from .kinds import KINDS, kind_of, paint_chip

ID_ROLE = Qt.ItemDataRole.UserRole
KIND_ROLE = Qt.ItemDataRole.UserRole + 1  # the key of the layer's kind (kinds.KINDS)
LOCKED_ROLE = Qt.ItemDataRole.UserRole + 2  # follows its parent exactly (a graph on its axes)
MISSING_ROLE = Qt.ItemDataRole.UserRole + 3  # a part whose TeX is not found
VISIBLE_ROLE = Qt.ItemDataRole.UserRole + 4  # whether the layer is included in preview and export
ROW_HEIGHT = 36  # px (Lumen): one layer row
ROW_GAP = 1  # px above and below a row
ROW_SIDE = 6  # px between a row and the list's sides
CHIP = 22  # px: the kind chip
CARET = 16  # px: the expand caret of a row with children


def _layer_rules(c: theme.Colours) -> str:
    return f"""
QTreeView#layerTree {{ background: transparent; border: 0; show-decoration-selected: 0; }}
QTreeView#layerTree::item, QTreeView#layerTree::item:hover, QTreeView#layerTree::item:selected {{
    background: transparent; border: 0; padding: 0; margin: 0;
}}
QTreeView#layerTree::branch, QTreeView#layerTree::branch:selected, QTreeView#layerTree::branch:hover {{
    background: transparent; image: none; border-image: none;
}}
QFrame#layersFooter {{ background: transparent; border: 0; border-top: 1px solid {theme.css(c.line)}; }}
"""


theme.register_rules(_layer_rules)


class LayerDelegate(QStyledItemDelegate):
    """Draws a layer row (Lumen): a 36 px rounded row with the kind chip, the name, a kind word for code,
    objects and groups, a lock for a layer that follows its parent, and a caret on a row with children.
    The selected row is tinted with the accent and ringed; the hovered one is raised."""

    def __init__(self, tree: QTreeWidget) -> None:
        super().__init__(tree)
        self.tree = tree

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), ROW_HEIGHT + 2 * ROW_GAP)

    @staticmethod
    def row_rect(rect: QRect) -> QRectF:
        return QRectF(rect).adjusted(ROW_SIDE, ROW_GAP, -ROW_SIDE, -ROW_GAP)

    def caret_rect(self, rect: QRect) -> QRectF:
        row = self.row_rect(rect)
        return QRectF(row.right() - 34 - CARET, row.center().y() - CARET / 2, CARET, CARET)

    def visibility_rect(self, rect: QRect) -> QRectF:
        row = self.row_rect(rect)
        return QRectF(row.right() - 23, row.center().y() - 7, 14, 14)

    def name_left(self, rect: QRect) -> float:
        return self.row_rect(rect).left() + 12 + CHIP + 9

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        c = theme.THEME
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        row = self.row_rect(option.rect)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        path = QPainterPath()
        path.addRoundedRect(row.adjusted(0.5, 0.5, -0.5, -0.5), theme.RADIUS_ROW, theme.RADIUS_ROW)
        if selected:
            painter.fillPath(path, theme.qcolor(c.accent_soft))
            painter.setPen(QPen(theme.qcolor(c.accent_line), 1))
            painter.drawPath(path)
        elif hovered:
            painter.fillPath(path, theme.qcolor(c.raised))
        kind = KINDS.get(index.data(KIND_ROLE) or "", KINDS["shape"])
        chip = QRectF(row.left() + 12, row.center().y() - CHIP / 2, CHIP, CHIP)
        paint_chip(painter, chip, kind, theme.RADIUS_SMALL, enabled)
        eye = self.visibility_rect(option.rect)
        icon = "hidden" if index.data(VISIBLE_ROLE) is False else "visible"
        icons.icon(icon, tint="muted").paint(painter, eye.toRect())
        left, right = self.name_left(option.rect), eye.left() - 6
        if self.tree.model().hasChildren(index):
            caret = self.caret_rect(option.rect)
            name = "caret-down" if self.tree.isExpanded(index) else "caret-right"
            icons.icon(name, tint="faint").paint(painter, caret.toRect())
            right = caret.left() - 6
        if index.data(LOCKED_ROLE):
            lock = QRectF(right - 14, row.center().y() - 7, 14, 14)
            icons.icon("lock", tint="faint").paint(painter, lock.toRect())
            right = lock.left() - 6
        if kind.chip:
            right = self._paint_word(painter, kind.chip, right, row)
        font: QFont = theme.font("label")
        painter.setFont(font)
        missing = bool(index.data(MISSING_ROLE))
        token = c.disabled if not enabled else c.warning if missing else c.text
        painter.setPen(theme.qcolor(token))
        text_rect = QRectF(left, row.top(), max(right - left, 0), row.height())
        text = QFontMetrics(font).elidedText(
            str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
            Qt.TextElideMode.ElideRight,
            int(text_rect.width()),
        )
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        painter.restore()

    @staticmethod
    def _paint_word(painter: QPainter, word: str, right: float, row: QRectF) -> float:
        """A small neutral chip (``group``, ``code``...) ending at ``right``; returns its left edge."""
        c = theme.THEME
        font = theme.font("caption")
        font.setPixelSize(10)
        metrics = QFontMetrics(font)
        width = metrics.horizontalAdvance(word) + 14
        box = QRectF(right - width, row.center().y() - 9, width, 18)
        path = QPainterPath()
        path.addRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
        painter.fillPath(path, theme.qcolor(c.raised))
        painter.setPen(QPen(theme.qcolor(c.line), 1))
        painter.drawPath(path)
        painter.setFont(font)
        painter.setPen(theme.qcolor(c.muted))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, word)
        return box.left() - 6

    def editorEvent(self, event, model, option: QStyleOptionViewItem, index: QModelIndex) -> bool:
        """The eye toggles visibility; the caret opens or closes a row."""
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and self.visibility_rect(option.rect).adjusted(-4, -4, 4, 4).contains(event.position())
        ):
            layer_id = str(index.data(ID_ROLE) or "")
            if layer_id:
                self.tree.visibilityToggled.emit(layer_id, index.data(VISIBLE_ROLE) is False)
            return True
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and model.hasChildren(index)
            and self.caret_rect(option.rect).adjusted(-4, -4, 4, 4).contains(event.position())
        ):
            self.tree.setExpanded(index, not self.tree.isExpanded(index))
            return True
        return super().editorEvent(event, model, option, index)

    def updateEditorGeometry(self, editor: QWidget, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        """Renaming edits over the name, not over the chip."""
        row = self.row_rect(option.rect)
        left = int(self.name_left(option.rect)) - 4
        editor.setGeometry(
            QRect(left, int(row.top()) + 4, int(row.right()) - 8 - left, int(row.height()) - 8)
        )


class LayerTree(QTreeWidget):
    """Drag-to-reorder tree of objects; reports the dragged object's new top-level row.

    Qt never moves items itself (the drop is ignored): the panel submits a
    ``move_layer`` edit and rebuilds from the document, so parts can never be
    dropped into another object. Code dragged from the Code workspace and ``.py``
    files from the desktop (P12.7) are taken too - the list is outlined while one
    hovers - and reported; any other drag from outside is refused as before.
    """

    rowDropped = Signal(str, int)  # object id, new top-level row (0 = front)
    visibilityToggled = Signal(str, bool)  # layer id, new visible state
    codeDropped = Signal(dict)  # a Code workspace drag (code_drag payload) (P12.7)
    filesDropped = Signal(list)  # .py files dropped from the desktop (P12.7)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.code_hover = False  # code is dragged over the list: it is outlined

    def _set_code_hover(self, on: bool) -> None:
        if on != self.code_hover:
            self.code_hover = on
            self.viewport().update()

    def dragEnterEvent(self, event) -> None:
        if code_drag.accepts(event.mimeData()):
            event.acceptProposedAction()
            self._set_code_hover(True)
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self.code_hover:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._set_code_hover(False)
        super().dragLeaveEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.code_hover:
            painter = QPainter(self.viewport())
            painter.setPen(QPen(theme.qcolor(theme.THEME.accent), 2))
            painter.drawRect(self.viewport().rect().adjusted(1, 1, -1, -1))
            painter.end()

    def dropEvent(self, event) -> None:
        self._set_code_hover(False)
        mime = event.mimeData()
        if code_drag.accepts(mime):
            event.acceptProposedAction()
            payload, files = code_drag.decode(mime), code_drag.python_files(mime)
            # After the drop returns: the window may open a dialog, which must not run inside
            # the system's drag loop (the program dragged from would wait for it).
            if payload is not None:
                QTimer.singleShot(0, lambda: self.codeDropped.emit(payload))
            else:
                QTimer.singleShot(0, lambda: self.filesDropped.emit(files))
            return
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
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("role", "primary")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setProperty("role", "ghost")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.status.setProperty("role", "muted")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(3 * theme.SPACE)
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


@dataclass(frozen=True)
class PinRequest:
    """What Pin to... asks for (ADR 0075)."""

    target: str
    anchor: str = "top"
    follow_rotation: bool = False
    follow_scale: bool = False


_ANCHOR_LABELS = {"top": "Above", "bottom": "Below", "left": "Left of", "right": "Right of", "centre": "On"}


class PinDialog(QDialog):
    """Pin a label to another layer (ADR 0075): which layer, on which side, and whether it turns and grows
    with it."""

    def __init__(self, project: Project, label_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        label = project.layer(label_id)
        self.setWindowTitle("Pin label")
        self.target = QComboBox()
        for target in project.pin_targets(label_id):
            self.target.addItem(target.label, target.id)
        self.anchor = QComboBox()
        for anchor in PIN_ANCHORS:
            self.anchor.addItem(_ANCHOR_LABELS[anchor], anchor)
        self.follow_rotation = QCheckBox("Turn with it")
        self.follow_scale = QCheckBox("Grow and shrink with it")
        if label.pin is not None:  # Pin to... on a pinned label edits its pin
            self.target.setCurrentIndex(max(0, self.target.findData(label.pin.target)))
            self.anchor.setCurrentIndex(self.anchor.findData(label.pin.anchor))
            self.follow_rotation.setChecked(label.pin.follow_rotation)
            self.follow_scale.setChecked(label.pin.follow_scale)
        hint = QLabel(
            "The label follows the object through every move, upright and its own size unless you choose "
            "otherwise. Moving the label on the canvas changes how far it sits from its place."
            if self.target.count()
            else "There is nothing this label can be pinned to."
        )
        hint.setWordWrap(True)
        hint.setProperty("role", "muted")
        form = QFormLayout()
        form.addRow(f"Pin {label.label!r} to:", self.target)
        form.addRow("Where:", self.anchor)
        form.addRow("", self.follow_rotation)
        form.addRow("", self.follow_scale)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("role", "primary")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.target.count() > 0)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setProperty("role", "ghost")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(3 * theme.SPACE)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(self.buttons)

    def request(self) -> PinRequest | None:
        if self.target.count() == 0:
            return None
        return PinRequest(
            self.target.currentData(),
            self.anchor.currentData(),
            self.follow_rotation.isChecked(),
            self.follow_scale.isChecked(),
        )


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


def add_placed(
    project: Project,
    spec: Spec,
    t: float,
    name: str = "",
    position: tuple[float, float] | None = None,
    appear: float | None = None,
) -> edits.Edit:
    """Add an object where it does not cover the others (GP, ``core.placement``), or at ``position``
    and appearing at ``appear`` seconds when those are given (dropped on the scene or the timeline)."""
    edit = edits.add_layer(project, spec, name=name)
    new = edit.project.layers[-1]
    where = position if position is not None else placement.position_for(project, spec, t)
    changes: dict = {}
    if tuple(where) != (0.0, 0.0):
        changes["base"] = new.base.model_copy(update={"position": tuple(where)})
    if appear is not None and appear > 0:
        changes["lifetime"] = Lifetime(**{"in": appear})
    if not changes:
        return edit
    moved = edits.update_layer(edit.project, new.id, **changes)
    return edits.Edit(moved.project, *edits.classify(project, moved.project))


def add_many_placed(project: Project, items: list[tuple[Spec, str]], t: float, **where) -> edits.Edit:
    """``add_placed`` for several (spec, name) in order, as one edit."""
    current = project
    for spec, name in items:
        current = add_placed(current, spec, t, name=name, **where).project
    return edits.Edit(current, *edits.classify(project, current))


def duplicate_placed(
    project: Project, layer_id: str, position: tuple[float, float] | None = None, appear: float | None = None
) -> edits.Edit:
    """A copy of a layer (its code, values, keys and clips), appearing at ``appear`` and placed at
    ``position`` when given."""
    pasted = clipboard.duplicate_layers(project, [layer_id])
    changes: dict = {}
    new = pasted.edit.project.layer(pasted.selected)
    if position is not None:
        changes["base"] = new.base.model_copy(update={"position": tuple(position)})
    if appear is not None and appear > 0:
        changes["lifetime"] = Lifetime(**{"in": appear})
    if not changes:
        return pasted.edit
    moved = edits.update_layer(pasted.edit.project, new.id, **changes)
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
    countChanged = Signal(int)  # how many objects the list shows (the card header's count chip, ADR 0084)
    codeDropped = Signal(dict)  # a Code workspace drag dropped on the list (code_drag payload, P12.7)
    filesDropped = Signal(list)  # .py files dropped on the list from the desktop (P12.7)

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
        self.extract_code: Callable[[list[str]], object] = lambda layer_ids: None  # by the window (ADR 0076)
        # Colour characters (ADR 0055): (layer id, current colours) -> the new list, or None.
        self.ask_glyph_colours: Callable[[str, list | None], list | None] = lambda layer_id, current: (
            ask_glyph_colours(self, self.project, layer_id)
        )
        # Pin to... (ADR 0075): the label's id -> what to pin it to, or None; and where Unpin leaves it (the
        # window asks its evaluator; None keeps the offset as the position).
        self.ask_pin: Callable[[str], PinRequest | None] = self._ask_pin_dialog
        self.unpin_position: Callable[[str], tuple[float, float] | None] = lambda layer_id: None
        self._known_ids: set[str] = set()
        self.playhead: Callable[[], float] = lambda: 0.0  # set by the window: where new objects are placed
        self._select_new = False

        self._collapsed_ids: set[str] = set()  # rows the user closed (they stay closed across rebuilds)
        self.list = LayerTree()
        self.list.setObjectName("layerTree")
        self.list.setHeaderHidden(True)
        self.list.setRootIsDecorated(False)  # the caret is at the right of the row (Lumen)
        self.list.setIndentation(26)
        self.list.setUniformRowHeights(True)
        self.list.setMouseTracking(True)
        self.list.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.delegate = LayerDelegate(self.list)
        self.list.setItemDelegate(self.delegate)
        self.list.itemCollapsed.connect(lambda item: self._collapsed_ids.add(item.data(0, ID_ROLE)))
        self.list.itemExpanded.connect(lambda item: self._collapsed_ids.discard(item.data(0, ID_ROLE)))
        self.filter = QLineEdit()
        self.filter.setObjectName("layerFilter")
        self.filter.setPlaceholderText("Filter layers")
        self.filter.setClearButtonEnabled(True)
        self.filter.setToolTip("Show only the layers whose name has this text (and what holds them)")
        self.filter.setAccessibleName("Filter layers")
        self.filter.setMinimumHeight(30)
        # Click to filter: as the first field of the window it would otherwise take the keyboard at
        # start, and keys meant for the window (Ctrl+1..5, Ctrl+D) would go to it.
        self.filter.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.filter.addAction(icons.icon("search", tint="faint"), QLineEdit.ActionPosition.LeadingPosition)
        self.filter.textChanged.connect(lambda _text: self.apply_filter())
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
        self.list.visibilityToggled.connect(self._on_visibility_toggled)
        self.list.codeDropped.connect(self.codeDropped)
        self.list.filesDropped.connect(self.filesDropped)

        self.add_button = QToolButton(
            text="Add object", popupMode=QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.add_button.setMenu(self._library_menu())
        self.add_button.setIcon(icons.icon("add"))  # (ADR 0040)
        self.add_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.add_button.setToolTip("Browse every object type, including plugins")
        self.add_button.setAccessibleName("All object types")
        self.quick_add_buttons = self._quick_add_buttons()
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
        self.part_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)  # Lumen: Add has the room
        self.part_button.setToolTip(
            "Parts: animate pieces of an equation as their own layers, or plot on axes"
        )
        self.part_button.setAccessibleName("Parts")

        self.add_button.setProperty("role", "outlined")
        self.part_button.setProperty("role", "outlined")
        self.presets_button = QToolButton(text="Presets")  # the presets browser (Animate > Browse Presets)
        self.presets_button.setIcon(icons.icon("presets"))
        self.presets_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.presets_button.setToolTip("Browse the animation presets by their moving preview (Ctrl+Shift+P)")
        self.presets_button.setAccessibleName("Presets")
        self.presets_button.clicked.connect(lambda: self.browse_presets())
        self.browse_presets: Callable[[], object] = lambda: None  # set by the window (ADR 0084)
        for button in (self.add_button, self.presets_button):
            button.setMinimumHeight(26)
        # Delete, order and Parts live in the header's "..." menu (the mock-up's footer is Add object and
        # Presets); their buttons stay as the actions' widgets, out of the layout.
        for button in (self.part_button, self.delete_button, self.up_button, self.down_button):
            button.setParent(self)
            button.hide()
        self.footer = QFrame()
        self.footer.setObjectName("layersFooter")
        self.buttons = QHBoxLayout(self.footer)
        self.buttons.setContentsMargins(10, 10, 10, 10)
        self.buttons.setSpacing(theme.GUTTER)
        self.add_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.buttons.addWidget(self.add_button, 1)
        self.buttons.addWidget(self.presets_button)
        self._header_buttons()
        top = QVBoxLayout()
        top.setContentsMargins(10, 10, 10, 4)
        top.setSpacing(7)
        top.addWidget(self.filter)
        quick_header = QLabel("QUICK ADD")
        quick_header.setProperty("role", "section")
        quick_header.setFont(theme.font("section"))
        top.addWidget(quick_header)
        quick_grid = QGridLayout()
        quick_grid.setContentsMargins(0, 0, 0, 0)
        quick_grid.setHorizontalSpacing(6)
        quick_grid.setVerticalSpacing(5)
        quick_grid.setColumnStretch(0, 1)
        quick_grid.setColumnStretch(1, 1)
        for i, button in enumerate(self.quick_add_buttons.values()):
            quick_grid.addWidget(button, i // 2, i % 2)
        top.addLayout(quick_grid)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
        layout.addSpacing(6)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.footer)
        self.labelled = (self.add_button, self.presets_button)  # icons only when the panel is narrow (P6d.4)
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
            for button in (self.add_button, self.presets_button)
        ]
        margins = self.buttons.contentsMargins()
        sides = margins.left() + margins.right()
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

    def _header_buttons(self) -> None:
        """The card header's "+" (add an object: the library menu) and "..." (the layer options: delete,
        order and parts) as small icon buttons; the window puts them in the Layers card (ADR 0084)."""
        self.header_add_button = QToolButton(popupMode=QToolButton.ToolButtonPopupMode.InstantPopup)
        self.header_add_button.setObjectName("iconButton")
        self.header_add_button.setIcon(icons.icon("add"))
        self.header_add_button.setMenu(self.library_menu)
        self.header_add_button.setToolTip("Add an object to the scene")
        self.header_add_button.setAccessibleName("Add layer")
        self.options_menu = QMenu(self)
        self.options_menu.setToolTipsVisible(True)
        for button in (self.delete_button, self.up_button, self.down_button):
            self.options_menu.addAction(button.defaultAction())
        self.options_menu.addSeparator()
        self.parts_menu_action = self.options_menu.addMenu(self.part_button.menu())
        self.parts_menu_action.setText("Parts")
        self.parts_menu_action.setIcon(icons.icon("parts"))
        self.header_options_button = QToolButton(popupMode=QToolButton.ToolButtonPopupMode.InstantPopup)
        self.header_options_button.setObjectName("iconButton")
        self.header_options_button.setIcon(icons.icon("more"))
        self.header_options_button.setMenu(self.options_menu)
        self.header_options_button.setToolTip("Layer options: delete, bring forward, send backward, parts")
        self.header_options_button.setAccessibleName("Layer options")
        self.header_buttons = (self.header_add_button, self.header_options_button)
        for button in self.header_buttons:
            button.setFixedSize(26, 26)
            button.setAutoRaise(True)

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
        self._add_python_objects_menu(menu)
        menu.addSection("Scene")
        self.add_camera_action = menu.addAction("Camera", self.add_camera)
        self.add_camera_action.setToolTip(self.CAMERA_TIP)
        self.library_menu = menu
        return menu

    def _add_python_objects_menu(self, menu: QMenu) -> QMenu:
        """Add ready-to-edit Python objects that complement the native Manim types."""
        submenu = menu.addMenu("Python objects")
        submenu.setToolTipsVisible(True)
        for name, code in python_templates.LAYER_TEMPLATES.items():
            action = submenu.addAction(name, partial(self.add_python_object, code))
            action.setToolTip(f"Add the editable {name.lower()} Python object")
        return submenu

    def _quick_add_buttons(self) -> dict[str, QToolButton]:
        """A small, categorized front door to the full library (the footer keeps the full menu)."""
        definitions = (
            ("Shapes", "shape", ("Shapes",), None),
            ("Lines", "line", ("Lines & Arrows", "Curves & Annotations"), None),
            ("Text", "text", ("Text",), "plain"),
            ("Math", "maths", ("Text",), "math"),
            ("Media", "image", ("Media",), None),
            ("Graphs", "axes", ("Graphing", "Coordinates"), None),
            ("3D", "object", ("3D Solids",), None),
            ("More", "more", None, None),  # simulations, code and plugin sections
        )
        buttons: dict[str, QToolButton] = {}
        built_in_sections = {
            "Shapes",
            "Lines & Arrows",
            "Curves & Annotations",
            "Text",
            "Media",
            "Graphing",
            "Coordinates",
            "3D Solids",
            "Simulation",
            "Python",
        }
        for label, icon_name, sections, text_kind in definitions:
            menu = QMenu(self)
            menu.setToolTipsVisible(True)
            for library_section, types in adapter.LIBRARY:
                if sections is not None and library_section not in sections:
                    continue
                if (
                    label == "More"
                    and library_section in built_in_sections
                    and library_section
                    not in {
                        "Simulation",
                        "Python",
                    }
                ):
                    continue
                visible_types = types
                if text_kind == "plain" and library_section == "Text":
                    visible_types = tuple(t for t in types if t not in {"MathTex", "Tex"})
                elif text_kind == "math" and library_section == "Text":
                    visible_types = tuple(t for t in types if t in {"MathTex", "Tex"})
                if not visible_types:
                    continue
                menu.addSection("Math" if label == "Math" and library_section == "Text" else library_section)
                for type_name in visible_types:
                    action = menu.addAction(adapter.LIBRARY_LABELS.get(type_name, type_name))
                    action.triggered.connect(partial(self.add_object, type_name))
                    if type_name == "MathTex":
                        action.setToolTip("Build a LaTeX equation")
                        steps = menu.addAction("Equation steps...", self.add_equation_steps)
                        steps.setToolTip("Create a derivation with one equation per step")
            if label == "More":
                self._add_python_objects_menu(menu)
            button = QToolButton(text=label, popupMode=QToolButton.ToolButtonPopupMode.InstantPopup)
            button.setObjectName(f"quickAdd{label.replace(' ', '')}")
            button.setMenu(menu)
            button.setIcon(icons.icon(icon_name))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setProperty("role", "outlined")
            button.setMinimumHeight(29)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setToolTip(f"Add {label.lower()} to the scene")
            button.setAccessibleName(f"Add {label.lower()}")
            buttons[label] = button
        return buttons

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
            self._collapsed_ids &= ids
            for item in self.items():
                if item.data(0, ID_ROLE) in self._collapsed_ids:
                    item.setExpanded(False)
            self.apply_filter()
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
        self.countChanged.emit(len(roots))

    def _item(self, layer: Layer, orphans: dict[str, str], index: LayerIndex) -> QTreeWidgetItem:
        item = QTreeWidgetItem([layer.label])
        item.setData(0, ID_ROLE, layer.id)
        item.setData(0, KIND_ROLE, kind_of(layer).key)
        item.setData(0, LOCKED_ROLE, layer.locked)
        item.setData(0, VISIBLE_ROLE, layer.visible)
        if layer.is_part:
            tip = f"{layer.id} - part {layer.part.tex!r} (occurrence {layer.part.occurrence + 1})"
            if layer.id in orphans:
                item.setData(0, MISSING_ROLE, True)
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

    def apply_filter(self) -> None:
        """Hide the rows whose name lacks every typed word, keeping the objects that hold a match."""
        words = self.filter.text().lower().split()

        def show(item: QTreeWidgetItem) -> bool:
            children = [show(item.child(i)) for i in range(item.childCount())]
            match = all(w in item.text(0).lower() for w in words)
            item.setHidden(not (match or any(children)))
            return match or any(children)

        for i in range(self.list.topLevelItemCount()):
            show(self.list.topLevelItem(i))

    def _on_reset(self, _project: Project) -> None:
        self._known_ids = set()
        self._select_new = False
        self.sync()

    CAMERA_TIP = "Add the camera: key its position, scale (zoom) and rotation on the timeline to pan and zoom"
    CAMERA_HAVE_TIP = "The project already has a camera (the first row): there is one per project"

    def _sync_camera_action(self) -> None:
        """Add object > Camera is off, with the reason as its tooltip, once the camera exists (ADR 0084)."""
        action = getattr(self, "add_camera_action", None)
        if action is not None:
            have = self.project.camera_layer is not None
            action.setEnabled(not have)
            action.setToolTip(self.CAMERA_HAVE_TIP if have else self.CAMERA_TIP)

    def update_buttons(self) -> None:
        self._sync_camera_action()
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
        self.parts_menu_action.setEnabled(self.part_button.isEnabled())

    # -- actions --------------------------------------------------------------------

    def add_object(self, type_name: str, position: tuple[float, float] | None = None) -> None:
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
        self._submit(partial(add_placed, spec=spec, t=self.playhead(), position=position), f"Add {type_name}")

    def add_camera(self) -> None:
        """Add the project's camera (ADR 0072); its keys are edited like any layer's."""
        self._select_new = True
        self._submit(edits.add_camera, "Add camera")

    def add_python_object(self, code: str | None = None) -> None:
        """A Python object (ADR 0051), from a template (the right triangle by default): made on the
        Code page, not the library."""
        code = python_object.STARTER if code is None else code
        spec = Spec(type=PYTHON_TYPE, params={"code": code})
        self.trust_code(code)  # the editor's own template
        self._select_new = True
        self._submit(partial(add_placed, spec=spec, t=self.playhead()), "Add Python object")

    def add_code_layers(
        self,
        layers: list[tuple[str, str, str]],
        *,
        appear: float | None = None,
        position: tuple[float, float] | None = None,
        trust: bool = False,
    ) -> None:
        """Add code as layers - (name, "Python" | "Code", code) each - as one undo step, selecting
        them. The code is untrusted (a placeholder, and it asks) unless ``trust``. P12."""
        specs = []
        for name, type_name, code in layers:
            if trust:
                self.trust_code(code)
            specs.append((Spec(type=type_name, params={"code": code}), name))
        self._select_new = "all" if len(specs) > 1 else True
        label = "Add Python object" if specs[0][0].type == PYTHON_TYPE else "Add code layer"
        self._submit(
            partial(
                add_many_placed,
                items=specs,
                t=self.playhead() if appear is None else appear,
                position=position,
                appear=appear,
            ),
            label if len(specs) == 1 else f"{label}s",
        )

    def duplicate_code_layer(
        self, layer_id: str, *, appear: float | None = None, position: tuple[float, float] | None = None
    ) -> None:
        """Another instance of a code layer or Python object, placed as dropped."""
        self._select_new = True
        self._submit(
            partial(duplicate_placed, layer_id=layer_id, position=position, appear=appear), "Duplicate"
        )

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

    def colour_characters(self, layer_id: str | None = None) -> bool:
        """Colour the glyphs of a Text, MathTex or Tex one by one (ADR 0055): the dialog asks, then
        ``edits.set_glyph_colours`` is one undo step. False when there was nothing to do."""
        layer_id = layer_id or self.selected_id()
        if not layer_id or layer_id not in {x.id for x in self.project.layers}:
            self.message.emit("Colour characters: select a Text, MathTex or Tex")
            return False
        layer = self.project.layer(layer_id)
        if layer.spec is None or layer.spec.type not in TEXT_TYPES:
            self.message.emit(f"Colour characters: {layer.label} is not a Text, MathTex or Tex")
            return False
        current = layer.spec.params.get(GLYPH_COLOURS)
        colours = self.ask_glyph_colours(layer_id, current)
        if colours is None or glyph_colours.normalised(colours) == glyph_colours.normalised(current):
            return False
        self._submit(
            partial(edits.set_glyph_colours, layer_id=layer_id, colours=colours), "Colour characters"
        )
        return True

    def pin_label(self, layer_id: str) -> bool:
        """Pin to... (ADR 0075): ask for the target, then ``edits.pin_label`` is one undo step."""
        if layer_id not in {x.id for x in self.project.layers}:
            return False
        request = self.ask_pin(layer_id)
        if request is None:
            return False
        op = partial(
            edits.pin_label,
            label_id=layer_id,
            target_id=request.target,
            anchor=request.anchor,
            follow_rotation=request.follow_rotation,
            follow_scale=request.follow_scale,
        )
        self._submit(op, "Pin label")
        return True

    def unpin_label(self, layer_id: str) -> None:
        """Unpin (ADR 0075): the label stays where it is drawn at the playhead."""
        position = self.unpin_position(layer_id)
        self._submit(partial(edits.unpin_label, label_id=layer_id, position=position), "Unpin label")

    def _ask_pin_dialog(self, layer_id: str) -> PinRequest | None:
        dialog = PinDialog(self.project, layer_id, self)
        return dialog.request() if dialog.exec() == QDialog.DialogCode.Accepted else None

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
        if layer is not None and layer.spec is not None and layer.spec.type in TEXT_TYPES:  # ADR 0055
            characters = menu.addAction("Colour Characters...", lambda: self.colour_characters(layer_id))
            characters.setToolTip("Colour its letters or symbols one by one, or as a gradient or a rainbow")
            if not layer.is_child:  # ADR 0075
                pin = menu.addAction("Pin to...", lambda: self.pin_label(layer_id))
                pin.setToolTip("Make it follow another object through every move, at a fixed offset")
                if layer.pin is not None:
                    unpin = menu.addAction("Unpin", lambda: self.unpin_label(layer_id))
                    unpin.setToolTip("Stop following; it stays where it is now")
            menu.addSeparator()
        if (
            layer is not None
            and shape.kind_problem(layer) is None
            and layer.spec.type not in plugins.SIMULATIONS
        ):
            freeze = menu.addAction("Freeze to Shape", lambda: self.freeze(layer_id))  # ADR 0052
            freeze.setToolTip("Plain vector data as drawn now: no code, no LaTeX (undo turns it back)")
            menu.addSeparator()
        if layer is not None and not layer.is_child:  # a part is drawn with its object
            chosen = self.selected_ids()
            picked = chosen if layer_id in chosen else [layer_id]
            extract = menu.addAction("Extract as Code", lambda: self.extract_code(picked))  # ADR 0076
            extract.setToolTip("Replace the selected objects with one code layer that draws the same")
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

    def _on_visibility_toggled(self, layer_id: str, visible: bool) -> None:
        if layer_id in {layer.id for layer in self.project.layers}:
            verb = "Show layer" if visible else "Hide layer"
            self._submit(partial(edits.update_layer, layer_id=layer_id, visible=visible), verb)

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
        dialog = EquationStepsDialog(
            start,
            self.builds,
            matching=self.project.morph_matching,
            parent=self,
        )
        return dialog.request() if dialog.exec() == QDialog.DialogCode.Accepted else None

    def _ask_part_dialog(self, parent_id: str) -> tuple[str, int] | None:
        dialog = PartDialog(self.project, parent_id, self)
        return dialog.key() if dialog.exec() == QDialog.DialogCode.Accepted else None
