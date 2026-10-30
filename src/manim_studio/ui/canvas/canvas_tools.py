"""Selecting and moving objects on the canvas (S3, ADR 0016).

``MoveTool`` turns canvas input into selection changes and edits:

* click: select the front-most object under the cursor (Alt+click: the next one
  behind the current selection); a click inside the selected object's box keeps
  it; a click on nothing clears the selection;
* parts (P2c, ADR 0012): a click selects the whole object, as groups do in
  design tools; double-click selects the part under the cursor one level down,
  and once inside an object clicks pick its parts; Escape selects the parent;
* drag: move the selected object, previewed live and recorded as one undo step
  ("Move layer"); Shift locks the dominant axis; Escape cancels;
* arrow keys: nudge 1 px (Shift: 10 px); a held key is one undo step;
* handles (P2a): a corner scales uniformly about the layer's pivot (Shift: steps of
  10 %), a side changes width or height independently, the knob rotates about it (Shift: 15 degree steps);
* the motion path (P3d, ADR 0026): drag a key's square to move that key, a
  tangent handle to bend the path (a smooth key's other handle stays opposite,
  keeping its length; Alt moves one handle only); double-click a square to
  make the key smooth or straight;
* the pivot cross (P2f, ADR 0021): Ctrl+drag on it moves the anchor while the
  object stays put ("Move anchor"; Shift snaps to the box's corners, edge
  midpoints and centre); Ctrl+double-click centres the anchor. Without Ctrl a
  press on the cross moves the object: the cross sits on the middle of every
  new object, where people grab it.

The stopwatch rule decides what a move edits: a layer with position keyframes
gets a key at the playhead (snapped to the nearest frame first, so preview and
key agree); other layers get their base position changed. A layer whose morph
is playing at the playhead cannot be dragged — the morph would not follow the
cursor (B23).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent

from ...core.editing import edits
from ...core.engine.evaluator import layer_transform
from ...core.model.schema import Layer, Project
from ...render.hit_test import hit_layers
from ..session.document import Document
from ..session.selection import Selection
from . import motion_overlay, param_handles, snap_guides
from .canvas import CanvasWidget
from .gizmo import (
    GRAB_PX,
    KNOB_OFFSET_PX,
    SHIFTS_ELSEWHERE,
    angle_delta,
    handle_at,
    nearest,
    scale_axis_from,
    scale_from,
    snap_angle,
)

NUDGE_PX = 1.0
AUTO_KEY_PLACED = (
    "Auto-key: the object was placed. It animates once it has an entrance"
    " (a clip, or Appears at) and you edit it later."
)
NUDGE_SHIFT_PX = 10.0
ARROWS = {
    Qt.Key.Key_Left: (-1.0, 0.0),
    Qt.Key.Key_Right: (1.0, 0.0),
    Qt.Key.Key_Up: (0.0, 1.0),
    Qt.Key.Key_Down: (0.0, -1.0),
}


@dataclass
class _Drag:
    layer_id: str
    prop: str  # transform property, "anchor", or an interaction such as "param" or "marquee"
    press: np.ndarray  # cursor at press, Manim units
    start: object  # the property's value at press
    pivot: np.ndarray  # the world pivot: scaling and rotating happen about it
    key_time: float | None  # the frame a key goes to; None = base value (ADR 0016)
    base: Project  # snapshot at press
    to_local: np.ndarray  # world move -> change of position (a part under a scaled/rotated object)
    previous: np.ndarray | None = None  # rotation: last cursor point, to sum angle deltas
    turned: float = 0.0  # rotation: total angle swept so far
    to_anchor: np.ndarray | None = None  # anchor: world move of the pivot -> change of the anchor
    snaps: np.ndarray | None = None  # anchor: where Ctrl snaps the pivot (world)
    axis_matrix: np.ndarray | None = None  # independent resize: local axes at drag start
    key: motion_overlay.MotionKey | None = None  # motion path: the key (or its handle) dragged
    param: param_handles.ParamHandle | None = None  # a parameter handle (ADR 0043)
    origin: np.ndarray | None = None  # point edits: where the object's parameter space sat at press
    box: tuple[np.ndarray, np.ndarray] | None = None  # moves: the moved drawing's box at press (world)
    targets: snap_guides.Targets | None = None  # what moves and handles snap to (ADR 0043)
    group: list[tuple[str, float | None, tuple, np.ndarray]] = field(default_factory=list)  # the
    # other selected objects a move carries: (layer id, key time, position at press, to_local)
    toggle_out: str | None = None  # Shift+press on a selected object: a click (no move) deselects it
    moved: bool = False  # the cursor left the press point (a click is not a move)
    collapse: str | None = None  # a plain press on one of several: a click selects only it


VERBS = {
    "key": "Move key",
    "in": "Bend path",
    "out": "Bend path",
    "position": "Move layer",
    "scale": "Scale layer",
    "scale_x": "Resize width",
    "scale_y": "Resize height",
    "rotation": "Rotate layer",
    "anchor": "Move anchor",
    "param": "Resize layer",
    "group": "Move layers",
}
CLICK_PX = 3.0  # a press that moves less than this is a click
DEGREES = "\N{DEGREE SIGN}"


class MoveTool(QObject):
    message = Signal(str)  # refusals, for the status bar

    def __init__(
        self,
        canvas: CanvasWidget,
        document: Document,
        selection: Selection,
        playhead: Callable[[], float],
        seek: Callable[[float], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.canvas, self.document, self.selection = canvas, document, selection
        self.playhead, self.seek = playhead, seek
        self.auto_key: Callable[[], bool] = lambda: False  # Edit > Auto-key (ADR 0018)
        self.snapping = True  # View > Snap to Objects (ADR 0043); Alt turns it off while dragging
        self._drag: _Drag | None = None
        self._pending: tuple[np.ndarray, Qt.KeyboardModifier, QPointF] | None = None
        self._scheduled = False
        canvas.tool = self

    @property
    def project(self) -> Project:
        return self.document.project

    # -- mouse -------------------------------------------------------------------

    def press(self, pos: QPointF, modifiers: Qt.KeyboardModifier) -> None:
        if self._drag is not None or self.document.dragging:
            return
        point = self.canvas.to_units(pos)
        current = self.selection.layer_id
        alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
        if self.canvas.interaction_mode == "anchor":
            if current is not None:
                self._start_drag(current, "anchor", point)
            return
        if modifiers & Qt.KeyboardModifier.ControlModifier and self._cross_under(point):
            self._start_drag(current, "anchor", point)  # 1. Ctrl on the pivot cross
            return
        if current is not None and not alt and self._cross_under(point):
            self._start_drag(current, "position", point)  # the centre cross is the easy place to grab
            return
        param = None if alt else self._param_under(point)
        if param is not None:  # 2. a parameter handle: a size, a line's end (ADR 0043)
            self._start_param_drag(current, param, point)
            return
        handle = None if alt else self._handle_under(point)
        if handle is not None:  # 3. a corner or the knob of the selected layer
            self._start_drag(current, "rotation" if handle == "rotate" else handle, point)
            return
        motion = self._motion_under(point)
        if motion is not None and alt and motion[0] == "key":
            motion = None  # Alt+click on a key square still cycles; on a handle Alt breaks the pair
        if motion is not None:  # 3. the motion path's handles and keys (ADR 0026)
            self._start_motion_drag(current, *motion, point)
            return
        layers = self.canvas.evaluator.frame_layers(self.playhead())
        hits = hit_layers(
            layers,
            point,
            self.canvas.px_per_unit(),
            select_by_bounds=self.canvas.select_by_bounds,
        )
        if alt:
            if hits:  # cycle behind the current selection
                index = hits.index(current) + 1 if current in hits else 0
                self.selection.select_layer(hits[index % len(hits)])
            return
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        chosen = self.selection.layer_ids
        inside = self._inside_selection(point)
        if current is not None and self._inside_selected_box(point):  # 3. the selected box
            target = current
        elif inside is not None and not (hits and self._click_target(hits[0], None) not in chosen):
            target = inside  # 3b. inside one of several selected objects' boxes: they move together
        elif hits:  # 4. whatever is under the cursor (the object, unless inside it already)
            target = self._click_target(hits[0], None if shift or self.selection.many else current)
        else:  # 5. empty canvas: a selection rectangle (Shift: adding to the selection)
            if not shift:
                self.selection.clear()
            self._drag = _Drag(
                "", "marquee", point, tuple(self.selection.layer_ids), point, None, self.project, np.eye(2)
            )
            return
        toggle_out = collapse = None
        if shift and target in chosen:
            toggle_out = target  # a Shift+click takes it out; a Shift+drag moves them all
        elif shift:
            self.selection.set_layers([*chosen, target])  # Shift adds it (ADR 0043)
        elif target not in chosen or not self.selection.many:
            self.selection.select_layer(target)
        else:
            self.selection.set_layers(chosen, primary=target)
            collapse = target  # a drag moves them all; a click selects only it
        self._start_drag(target, "position", point)
        if self._drag is not None:
            self._drag.toggle_out, self._drag.collapse = toggle_out, collapse

    def double_click(
        self, pos: QPointF, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
    ) -> None:
        """Select one level deeper toward the part under the cursor (drill into an object).

        Ctrl+double-click on the selected layer's pivot cross centres the anchor instead.
        """
        if self._drag is not None:
            self.cancel()
        point = self.canvas.to_units(pos)
        if modifiers & Qt.KeyboardModifier.ControlModifier and self._cross_under(point):
            self._centre_anchor()
            return
        motion = self._motion_under(point)
        if motion is not None and motion[0] == "key":
            self._toggle_smooth(motion[1])
            return
        layers = self.canvas.evaluator.frame_layers(self.playhead())
        hits = hit_layers(
            layers,
            point,
            self.canvas.px_per_unit(),
            select_by_bounds=self.canvas.select_by_bounds,
        )
        if not hits:
            return
        chain = [hits[0], *(a.id for a in self.project.ancestors(hits[0]))]  # the part up to its object
        current = self.selection.layer_id
        if current in chain[1:]:
            target = chain[chain.index(current) - 1]
        else:
            target = chain[-2] if len(chain) > 1 else chain[0]
        self.selection.select_layer(target)

    def _click_target(self, hit: str, current: str | None) -> str:
        """Clicks select whole objects; inside a selected object's tree they select parts."""
        root = self.project.root_of(hit)
        selected = self.project.layer(current) if current is not None else None
        # Inside a group (ADR 0050), a click picks another of its objects, as inside an equation.
        in_group = selected is not None and selected.parent_id == root.id and root.is_group
        if current is None or current == root.id or not (selected.is_part or in_group):
            return root.id
        if self.project.root_of(current).id != root.id:
            return root.id
        # Inside this object: the part under the cursor at the depth of the current selection.
        chain = [hit, *(a.id for a in self.project.ancestors(hit))]
        depth = len(self.project.ancestors(current))
        return chain[max(0, len(chain) - 1 - depth)]

    def move(self, pos: QPointF, modifiers: Qt.KeyboardModifier) -> None:
        if self._drag is None:
            return
        if not self._drag.moved:
            moved = np.linalg.norm(self.canvas.to_units(pos) - self._drag.press) * self.canvas.px_per_unit()
            self._drag.moved = bool(moved >= CLICK_PX)
        self._pending = (self.canvas.to_units(pos), modifiers, QPointF(pos))
        if not self._scheduled:
            self._scheduled = True
            QTimer.singleShot(0, self.apply_pending)

    def release(self) -> None:
        if self._drag is None:
            return
        self.apply_pending()
        drag, self._drag = self._drag, None
        self.canvas.readout = None
        self.canvas.guides = []
        if drag.prop == "marquee":
            self._finish_marquee(drag)
            return
        if drag.toggle_out is not None and not drag.moved:
            self.document.cancel_preview()
            self.selection.toggle_layer(drag.toggle_out)
            return
        if drag.collapse is not None and not drag.moved:
            self.document.cancel_preview()
            self.selection.select_layer(drag.collapse)
            return
        verb = f"Change {drag.param.title}" if drag.param is not None else VERBS[drag.prop]
        if drag.group:
            verb = VERBS["group"]
        self.document.commit_preview(verb)
        if drag.prop == "position" and drag.key_time is None:
            layer = self.project.layer(drag.layer_id)
            runs = [c for c in layer.clips if c.info.category == "motion" and c.start <= self.playhead()]
            if runs:  # the path re-runs from the moved base: nothing moves after its start (ADR 0025)
                run = runs[-1]
                self.message.emit(
                    f"This object follows a path from {run.start:g} s: key its position to move it "
                    "after that, or move the path."
                )
        if drag.prop == "anchor" and edits.anchor_shifts_elsewhere(self.project.layer(drag.layer_id)):
            self.message.emit(SHIFTS_ELSEWHERE)

    def cancel(self) -> None:
        if self._drag is not None:
            marquee = self._drag.prop == "marquee"
            self._drag = None
            self._pending = None
            self.canvas.readout = None
            self.canvas.guides = []
            if marquee:
                self.canvas.marquee = None
                self.canvas.update()
                return
            self.document.cancel_preview()

    def apply_pending(self) -> None:
        """Preview the latest cursor position (coalesced, as timeline drags are)."""
        self._scheduled = False
        drag = self._drag
        if drag is None or self._pending is None:
            return
        point, modifiers, pos = self._pending
        self._pending = None
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        snapping = self.snapping and not modifiers & Qt.KeyboardModifier.AltModifier
        readout = None
        if drag.prop == "param":
            self._param_preview(drag, point, pos, shift, snapping)
            return
        if drag.prop == "marquee":
            drag.pivot = point  # the rectangle's other corner
            self.canvas.marquee = (drag.press, point)
            self.canvas.update()
            return
        if drag.prop in ("key", "in", "out"):
            alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
            self.document.preview(self._motion_edit(drag, point, alt))
            return
        if drag.prop == "anchor":
            target = drag.pivot + (point - drag.press)
            if shift:
                target = nearest(drag.snaps, target)
            delta = drag.to_anchor @ (target - drag.pivot)
            value = (drag.start[0] + float(delta[0]), drag.start[1] + float(delta[1]))
            self.canvas.readout = (pos, f"anchor {value[0]:.2f}, {value[1]:.2f}")
            self.document.preview(edits.set_anchor(drag.base, drag.layer_id, value, self.playhead()))
            return
        if drag.prop == "position":
            delta = point - drag.press
            free = (True, True)
            if shift:
                delta[np.argmin(np.abs(delta))] = 0.0
                free = (bool(delta[0]), bool(delta[1]))
            self.canvas.guides = []
            if snapping and drag.box is not None and drag.targets is not None:
                found = snap_guides.snap(
                    drag.box[0] + delta, drag.box[1] + delta, drag.targets, self._snap_radius(), free
                )
                delta = delta + found.offset
                self.canvas.guides = found.guides
            if drag.group:
                self.document.preview(self._group_edit(drag, delta))
                return
            delta = drag.to_local @ delta
            value = (drag.start[0] + float(delta[0]), drag.start[1] + float(delta[1]))
        elif drag.prop == "scale":
            value = scale_from(drag.pivot, drag.press, point, drag.start, snap=shift)
            readout = f"{value * 100:.0f} %"
        elif drag.prop in ("scale_x", "scale_y"):
            axis = 0 if drag.prop == "scale_x" else 1
            value = scale_axis_from(
                drag.pivot,
                drag.press,
                point,
                drag.axis_matrix if drag.axis_matrix is not None else np.eye(2),
                axis,
                drag.start,
                snap=shift,
            )
            readout = f"{value * 100:.0f} %"
        else:
            drag.turned += angle_delta(drag.pivot, drag.previous, point)
            drag.previous = point
            value = snap_angle(drag.start + drag.turned, shift)
            readout = f"{value:.0f}{DEGREES}"
        self.canvas.readout = (pos, readout) if readout else None
        self.document.preview(self._edit(drag.base, drag.layer_id, drag.prop, value, drag.key_time))

    # -- keyboard ------------------------------------------------------------------

    def wants_key(self, event: QKeyEvent) -> bool:
        return (
            self.selection.layer_id is not None
            and self._drag is None
            and (event.key() in ARROWS or event.key() == Qt.Key.Key_Delete)
        )

    def key(self, event: QKeyEvent) -> bool:
        if event.key() == Qt.Key.Key_Escape and self._drag is not None:
            self.cancel()
            return True
        current = self.selection.layer_id
        layer = self.project.layer(current) if current is not None else None
        in_group = (
            layer is not None and layer.parent_id is not None and self.project.layer(layer.parent_id).is_group
        )
        if event.key() == Qt.Key.Key_Escape and layer is not None and (layer.is_part or in_group):
            self.selection.select_layer(layer.parent_id)  # back out of a part, or of a group's object
            return True
        if event.key() == Qt.Key.Key_Delete and self.selection.layer_ids and self._drag is None:
            chosen = self.selection.layer_ids
            verb = "Delete layers" if len(chosen) > 1 else "Delete layer"
            self.document.apply(edits.remove_layers(self.project, chosen), verb)
            return True
        if not self.wants_key(event):
            return False
        step = NUDGE_SHIFT_PX if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else NUDGE_PX
        world = np.array(ARROWS[event.key()]) * step / self.canvas.px_per_unit()
        movers = self._movers(self.selection.layer_ids)
        edit = self.move_by({layer_id: world for layer_id in movers})
        if edit is None:
            return True
        verb = "Nudge layers" if len(movers) > 1 else "Nudge layer"
        merge_key = ("nudge", *movers)
        self.document.apply(edit, verb, merge_key=merge_key, merge=event.isAutoRepeat())
        return True

    # -- several objects (ADR 0043) ---------------------------------------------------

    def _movers(self, layer_ids) -> list[str]:
        """What moving ``layer_ids`` moves: their owners, without any whose ancestor moves too."""
        owners = list(dict.fromkeys(self._owner(i) for i in layer_ids if i in self._ids()))
        chosen = set(owners)
        return [i for i in owners if not {a.id for a in self.project.ancestors(i)} & chosen]

    def _ids(self) -> set[str]:
        return {layer.id for layer in self.project.layers}

    def move_by(self, moves: dict[str, np.ndarray], project: Project | None = None) -> edits.Edit | None:
        """One edit moving each layer by its world move, keyed where its position is keyed (or
        Auto-key is on) at the playhead's frame, its base otherwise (the stopwatch rule, ADR 0018).
        None when nothing moves."""
        base = project or self.project
        current = base
        for layer_id, world in moves.items():
            layer = current.layer(layer_id)
            key_time = self._key_time(layer, "position")
            at = key_time if key_time is not None else self.playhead()
            to_local = self.canvas.evaluator.layer_frame(layer, at)[2]
            dx, dy = (float(d) for d in to_local @ np.asarray(world, float))
            x, y = self._value(layer, "position", key_time)
            current = self._edit(current, layer_id, "position", (x + dx, y + dy), key_time).project
        if current is base:
            return None
        return edits.Edit(current, *edits.classify(base, current))

    def _group_edit(self, drag: _Drag, world: np.ndarray) -> edits.Edit:
        """The primary object and the others moved together by ``world`` (one preview)."""
        delta = drag.to_local @ world
        value = (drag.start[0] + float(delta[0]), drag.start[1] + float(delta[1]))
        current = self._edit(drag.base, drag.layer_id, "position", value, drag.key_time).project
        for layer_id, key_time, start, to_local in drag.group:
            d = to_local @ world
            moved = (start[0] + float(d[0]), start[1] + float(d[1]))
            current = self._edit(current, layer_id, "position", moved, key_time).project
        return edits.Edit(current, *edits.classify(drag.base, current))

    def _finish_marquee(self, drag: _Drag) -> None:
        """Select the objects the rectangle touches (added to those selected at press)."""
        self.canvas.marquee = None
        self.canvas.update()
        low = np.minimum(drag.press, drag.pivot)
        high = np.maximum(drag.press, drag.pivot)
        touched = []
        if np.linalg.norm(high - low) * self.canvas.px_per_unit() >= CLICK_PX:
            boxes: dict[str, tuple[np.ndarray, np.ndarray]] = {}
            for owner, mob in self.canvas.evaluator.frame_layers(self.playhead()):
                family = mob.family_members_with_points()
                if not family:
                    continue
                box = snap_guides.box_of(np.vstack([sub.points[:, :2] for sub in family]))
                root = self.project.root_of(owner).id
                old = boxes.get(root, box)
                boxes[root] = (np.minimum(old[0], box[0]), np.maximum(old[1], box[1]))
            touched = [
                layer.id
                for layer in self.project.roots()
                if layer.id in boxes
                and (boxes[layer.id][0] <= high).all()
                and (boxes[layer.id][1] >= low).all()
            ]
        self.selection.set_layers([*drag.start, *touched])

    # -- rules ---------------------------------------------------------------------

    def _owner(self, layer_id: str) -> str:
        """Who a gesture moves: a graph is locked to its axes, so they move (ADR 0024)."""
        layer = self.project.layer(layer_id)
        return layer.parent_id if layer.locked else layer_id

    def _start_drag(self, layer_id: str, prop: str, point: np.ndarray) -> None:
        layer_id = self._owner(layer_id)
        layer = self.project.layer(layer_id)
        if self._morph_playing(layer_id):
            self.message.emit("This object is morphing here: move the playhead outside the morph to edit it.")
            return
        key_time = None if prop == "anchor" else self._key_time(layer, prop)  # anchors are never keyed
        start = self._value(layer, prop, key_time)
        at = key_time if key_time is not None else self.playhead()
        pivot, _rotation, to_local = self.canvas.evaluator.layer_frame(layer, at)
        self._drag = _Drag(
            layer_id, prop, point, start, pivot, key_time, self.project, to_local, previous=point
        )
        if prop in ("scale_x", "scale_y"):
            self._drag.axis_matrix = self.canvas.evaluator.world_affine(layer, at)[0]
        if prop == "anchor":
            self._drag.to_anchor = self._to_anchor(layer, at, to_local)
            self._drag.snaps = self._selected_outline().snaps
        if prop == "position":
            others = [i for i in self._movers(self.selection.layer_ids) if i != layer_id]
            if self.selection.many and others:
                for other_id in others:
                    other = self.project.layer(other_id)
                    if self._morph_playing(other_id):
                        self._drag = None
                        self.message.emit(
                            "An object is morphing here: move the playhead outside the morph to edit it."
                        )
                        return
                    kt = self._key_time(other, "position")
                    other_at = kt if kt is not None else self.playhead()
                    self._drag.group.append(
                        (
                            other_id,
                            kt,
                            self._value(other, "position", kt),
                            self.canvas.evaluator.layer_frame(other, other_at)[2],
                        )
                    )
            self._drag.box, self._drag.targets = self._snapping_for([layer_id, *others])
        self.document.begin_preview()

    # -- parameter handles and snapping (ADR 0043) ---------------------------------

    def _param_under(self, point: np.ndarray) -> param_handles.ParamHandle | None:
        if self._selected_outline() is None:
            return None
        grab = GRAB_PX / self.canvas.px_per_unit()
        return param_handles.handle_under(self.canvas.param_handles, point, grab)

    def _start_param_drag(self, layer_id: str, handle: param_handles.ParamHandle, point: np.ndarray) -> None:
        if self._morph_playing(layer_id):
            self.message.emit("This object is morphing here: move the playhead outside the morph to edit it.")
            return
        layer = self.project.layer(layer_id)
        self._drag = _Drag(
            layer_id, "param", point, handle.start, handle.world, None, self.project, np.eye(2), param=handle
        )
        if handle.point_control:
            if layer.spec.type in param_handles.LINES:
                self._drag.origin = param_handles.line_origin(layer.spec, self.canvas.rest_points(layer.spec))
            else:
                self._drag.origin = self.canvas.rest_origin(layer.spec)
        self._drag.targets = self._snapping_for([layer_id])[1]
        self.document.begin_preview()

    def _param_preview(
        self, drag: _Drag, point: np.ndarray, pos: QPointF, shift: bool, snapping: bool
    ) -> None:
        """Preview a parameter handle at ``point``: its edge snaps (not with Shift, which steps)."""
        handle = drag.param
        world = handle.world + (point - drag.press)
        self.canvas.guides = []
        if snapping and drag.targets is not None and not shift:
            offset = np.asarray(handle.display_offset or (0.0, 0.0), float)
            value_point = world - handle.a @ offset
            found = snap_guides.snap(value_point, value_point, drag.targets, self._snap_radius())
            world = world + found.offset
            self.canvas.guides = found.guides
        value = param_handles.value_at(handle, handle.to_local(world), step=shift)
        spec = drag.base.layer(drag.layer_id).spec
        shift_by = np.zeros(2)
        if handle.python_names is not None:
            values = dict(spec.params.get("values") or {})
            for name, coordinate in zip(handle.python_names, value, strict=True):
                values[name] = coordinate
            moved = spec.model_copy(update={"params": {**spec.params, "values": values}})
        else:
            moved = spec.model_copy(update={"params": {**spec.params, handle.param: value}})
        if drag.origin is not None:  # recentering changes the drawing origin; keep other points still
            origin = (
                param_handles.line_origin(moved, self.canvas.rest_points(moved))
                if spec.type in param_handles.LINES
                else self.canvas.rest_origin(moved)
            )
            shift_by = handle.a @ (origin - drag.origin)
            parent_id = drag.base.layer(drag.layer_id).parent_id
            if parent_id is not None:
                parent_a, _parent_b = self.canvas.evaluator.world_affine(
                    drag.base.layer(parent_id), self.playhead()
                )
                shift_by = np.linalg.pinv(parent_a) @ shift_by
        shown = f"{value[0]:.2f}, {value[1]:.2f}" if isinstance(value, tuple) else f"{value:g}"
        self.canvas.readout = (pos, f"{handle.title} {shown}")
        if handle.python_names is not None:
            edit = edits.set_python_values(
                drag.base,
                drag.layer_id,
                dict(zip(handle.python_names, value, strict=True)),
                tuple(shift_by),
            )
        else:
            edit = edits.set_params(drag.base, drag.layer_id, {handle.param: value}, tuple(shift_by))
        self.document.preview(edit)

    def _snap_radius(self) -> float:
        return snap_guides.SNAP_PX / self.canvas.px_per_unit()

    def _snapping_for(self, layer_ids: list[str]):
        """The box of what a drag moves (world, at the playhead) and what it snaps to: the other
        objects' boxes (the other parts, inside its own object) and the video frame."""
        project = self.project
        moved = set(layer_ids) | {d.id for i in layer_ids for d in project.descendants(i)}
        follows = project.connectors_of(moved) | project.traces_of(moved)
        own_root = project.root_of(layer_ids[0]).id
        mine, others = [], {}
        for owner, mob in self.canvas.evaluator.frame_layers(self.playhead()):
            family = mob.family_members_with_points()
            if not family or owner in follows:
                continue
            box = snap_guides.box_of(np.vstack([sub.points[:, :2] for sub in family]))
            if owner in moved:
                mine.append(box)
                continue
            root = project.root_of(owner).id
            group = owner if root == own_root else root
            low, high = others.get(group, box)
            others[group] = (np.minimum(low, box[0]), np.maximum(high, box[1]))
        canvas = project.canvas
        half = np.array([canvas.frame_width / 2, canvas.frame_height / 2])
        targets = snap_guides.targets(list(others.values()), (-half, half))
        if not mine:
            return None, targets
        low = np.min([b[0] for b in mine], axis=0)
        high = np.max([b[1] for b in mine], axis=0)
        return (low, high), targets

    @staticmethod
    def _to_anchor(layer: Layer, t: float, to_local: np.ndarray) -> np.ndarray:
        """World move of the pivot -> change of the anchor: the parent's inverse, then the layer's."""
        tr = layer_transform(layer, t)
        angle = np.radians(tr.rotation)
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        own = rotation @ np.diag([tr.scale * tr.scale_x, tr.scale * tr.scale_y])
        return np.linalg.pinv(own) @ to_local  # pinv: a layer scaled to 0 must not raise

    def _centre_anchor(self) -> None:
        """Put the selected layer's anchor at the centre of its drawing's box."""
        layer = self.project.layer(self._owner(self.selection.layer_id))
        if self._morph_playing(layer.id):
            self.message.emit("This object is morphing here: move the playhead outside the morph to edit it.")
            return
        t = self.playhead()
        pivot, _rotation, to_local = self.canvas.evaluator.layer_frame(layer, t)
        delta = self._to_anchor(layer, t, to_local) @ (self._selected_outline().box.centre - pivot)
        anchor = (layer.base.anchor[0] + float(delta[0]), layer.base.anchor[1] + float(delta[1]))
        self.document.apply(edits.set_anchor(self.project, layer.id, anchor, t), "Centre anchor")
        if edits.anchor_shifts_elsewhere(self.project.layer(layer.id)):
            self.message.emit(SHIFTS_ELSEWHERE)

    def _key_time(self, layer: Layer, prop: str) -> float | None:
        """None for base edits; else the playhead's frame, moving the playhead onto it."""
        if not layer.tracks.get(prop) and not self.auto_key():
            return None
        if not layer.tracks.get(prop) and edits.auto_key_places(self.project, layer.id, self.playhead()):
            self.message.emit(AUTO_KEY_PLACED)  # nothing to animate yet: a base edit (P7.1)
            return None
        fps = self.project.canvas.fps
        t = self.playhead()
        frame_t = round(t * fps) / fps
        if abs(frame_t - t) > 1e-9:
            self.seek(frame_t)
        return frame_t

    @staticmethod
    def _value(layer: Layer, prop: str, key_time: float | None):
        """Where the gesture starts: the value at the key's frame when keyed, else the base."""
        if layer.tracks.get(prop) and key_time is not None:
            value = getattr(layer_transform(layer, key_time), prop)
        else:
            value = getattr(layer.base, prop)
        return tuple(value) if isinstance(value, (tuple, list)) else float(value)

    def _edit(self, project: Project, layer_id: str, prop: str, value, key_time: float | None) -> edits.Edit:
        at = key_time if key_time is not None else self.playhead()
        return edits.set_property(project, layer_id, prop, value, at, auto_key=key_time is not None)

    def _morph_playing(self, layer_id: str) -> bool:
        t = self.playhead()
        for layer in self.project.layers:
            for clip in layer.clips:
                if clip.to_layer and layer_id in (layer.id, clip.to_layer) and clip.start <= t < clip.end:
                    return True
        return False

    def _selected_outline(self):
        """The selected object's outline, while one object is selected (its handles)."""
        outline = self.canvas.outline
        if outline is None or self.canvas.selected_layer != self.selection.layer_id or self.selection.many:
            return None
        return outline

    def _handle_under(self, point: np.ndarray):
        outline = self._selected_outline()
        if outline is None:
            return None
        ppu = self.canvas.px_per_unit()
        layer = self.project.layer(self.selection.layer_id)
        independent = self.canvas.show_edit_handles and not layer.is_group
        return handle_at(
            outline.box, point, GRAB_PX / ppu, KNOB_OFFSET_PX / ppu, independent=independent
        )

    # -- the motion path (ADR 0026) ------------------------------------------------

    def _motion_under(self, point: np.ndarray):
        path = self.canvas.motion
        if path is None or path.layer_id != self.selection.layer_id:
            return None
        return motion_overlay.hit(path, point, GRAB_PX / self.canvas.px_per_unit())

    def _start_motion_drag(self, layer_id: str, part: str, index: int, point: np.ndarray) -> None:
        if self._morph_playing(layer_id):
            self.message.emit("This object is morphing here: move the playhead outside the morph to edit it.")
            return
        path = self.canvas.motion
        key = self.project.layer(layer_id).tracks["position"][index]
        start = key.value if part == "key" else (key.in_tangent if part == "in" else key.out_tangent)
        self._drag = _Drag(
            layer_id,
            part,
            point,
            tuple(start),
            path.keys[index].point,
            key.t,
            self.project,
            path.to_track,
            key=path.keys[index],
        )
        self.document.begin_preview()

    def _motion_edit(self, drag: _Drag, point: np.ndarray, alt: bool) -> edits.Edit:
        delta = drag.to_local @ (point - drag.press)
        moved = (drag.start[0] + float(delta[0]), drag.start[1] + float(delta[1]))
        if drag.prop == "key":
            return edits.set_key(drag.base, drag.layer_id, "position", drag.key_time, moved)
        key = next(
            k for k in drag.base.layer(drag.layer_id).tracks["position"] if abs(k.t - drag.key_time) < 1e-9
        )
        own, other = ("in_tangent", "out_tangent") if drag.prop == "in" else ("out_tangent", "in_tangent")
        values = {own: moved, other: getattr(key, other)}
        if drag.key.smooth and not alt:  # a smooth key stays smooth: the other handle turns, keeps its length
            values[other] = motion_overlay.aligned(np.asarray(moved), getattr(key, other))
        return edits.set_tangents(
            drag.base, drag.layer_id, drag.key_time, values["in_tangent"], values["out_tangent"]
        )

    def _toggle_smooth(self, index: int) -> None:
        layer = self.project.layer(self.selection.layer_id)
        key = layer.tracks["position"][index]
        try:
            if key.curved:
                self.document.apply(
                    edits.set_tangents(self.project, layer.id, key.t, None, None), "Straighten key"
                )
            else:
                self.document.apply(edits.smooth_key(self.project, layer.id, key.t), "Smooth key")
        except edits.EditError as exc:
            self.message.emit(str(exc))

    def _cross_under(self, point: np.ndarray) -> bool:
        """Whether ``point`` is on the selected layer's pivot cross."""
        outline = self._selected_outline()
        if outline is None:
            return False
        distance = np.linalg.norm(point - np.asarray(outline.anchor)) * self.canvas.px_per_unit()
        return bool(distance <= GRAB_PX)

    def _inside_selection(self, point: np.ndarray) -> str | None:
        """With several objects selected: the one whose box ``point`` is in, or None."""
        if not self.selection.many:
            return None
        found = list(self.canvas.other_outlines)
        if self.canvas.outline is not None:
            found.append((self.canvas.selected_layer, self.canvas.outline.path))
        margin = 4.0 / self.canvas.px_per_unit()
        for layer_id, path in reversed(found):
            box = path.boundingRect().adjusted(-margin, -margin, margin, margin)
            if box.contains(QPointF(float(point[0]), float(point[1]))):
                return layer_id
        return None

    def _inside_selected_box(self, point: np.ndarray) -> bool:
        outline = self._selected_outline()
        return outline is not None and outline.box.contains(point, margin=4.0 / self.canvas.px_per_unit())
