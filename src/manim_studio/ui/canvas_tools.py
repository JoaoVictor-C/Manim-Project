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
* handles (P2a): a corner scales about the layer's pivot (Shift: steps of
  10 %), the knob rotates about it (Shift: 15 degree steps);
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
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent

from ..core import edits
from ..core.evaluator import layer_transform
from ..core.schema import Layer, Project
from ..render.hit_test import hit_layers
from .canvas import CanvasWidget
from .document import Document
from .gizmo import (
    GRAB_PX,
    KNOB_OFFSET_PX,
    SHIFTS_ELSEWHERE,
    angle_delta,
    handle_at,
    nearest,
    scale_from,
    snap_angle,
)
from .selection import Selection

NUDGE_PX = 1.0
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
    prop: str  # "position", "scale", "rotation" or "anchor"
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


VERBS = {
    "position": "Move layer",
    "scale": "Scale layer",
    "rotation": "Rotate layer",
    "anchor": "Move anchor",
}
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
        if modifiers & Qt.KeyboardModifier.ControlModifier and self._cross_under(point):
            self._start_drag(current, "anchor", point)  # 1. Ctrl on the pivot cross
            return
        handle = None if alt else self._handle_under(point)
        if handle is not None:  # 2. a handle of the selected layer
            self._start_drag(current, "scale" if handle == "scale" else "rotation", point)
            return
        layers = self.canvas.evaluator.frame_layers(self.playhead())
        hits = hit_layers(layers, point, self.canvas.px_per_unit())
        if alt:
            if hits:  # cycle behind the current selection
                index = hits.index(current) + 1 if current in hits else 0
                self.selection.select_layer(hits[index % len(hits)])
            return
        if current is not None and self._inside_selected_box(point):  # 3. the selected box
            target = current
        elif hits:  # 4. whatever is under the cursor (the object, unless inside it already)
            target = self._click_target(hits[0], current)
        else:  # 5. empty canvas
            self.selection.clear()
            return
        self.selection.select_layer(target)
        self._start_drag(target, "position", point)

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
        layers = self.canvas.evaluator.frame_layers(self.playhead())
        hits = hit_layers(layers, point, self.canvas.px_per_unit())
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
        if current is None or current == root.id or not self.project.layer(current).is_part:
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
        self.document.commit_preview(VERBS[drag.prop])
        if drag.prop == "anchor" and edits.anchor_shifts_elsewhere(self.project.layer(drag.layer_id)):
            self.message.emit(SHIFTS_ELSEWHERE)

    def cancel(self) -> None:
        if self._drag is not None:
            self._drag = None
            self._pending = None
            self.canvas.readout = None
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
        readout = None
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
            if shift:
                delta[np.argmin(np.abs(delta))] = 0.0
            delta = drag.to_local @ delta
            value = (drag.start[0] + float(delta[0]), drag.start[1] + float(delta[1]))
        elif drag.prop == "scale":
            value = scale_from(drag.pivot, drag.press, point, drag.start, snap=shift)
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
        return event.key() in ARROWS and self.selection.layer_id is not None and self._drag is None

    def key(self, event: QKeyEvent) -> bool:
        if event.key() == Qt.Key.Key_Escape and self._drag is not None:
            self.cancel()
            return True
        current = self.selection.layer_id
        if event.key() == Qt.Key.Key_Escape and current is not None and self.project.layer(current).is_part:
            self.selection.select_layer(self.project.layer(current).parent_id)  # back out of a part
            return True
        if not self.wants_key(event):
            return False
        layer = self.project.layer(self._owner(self.selection.layer_id))
        step = NUDGE_SHIFT_PX if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else NUDGE_PX
        world = np.array(ARROWS[event.key()]) * step / self.canvas.px_per_unit()
        dx, dy = (float(d) for d in self.canvas.evaluator.layer_frame(layer, self.playhead())[2] @ world)
        key_time = self._key_time(layer, "position")
        x, y = self._value(layer, "position", key_time)
        edit = self._edit(self.project, layer.id, "position", (x + dx, y + dy), key_time)
        self.document.apply(edit, "Nudge layer", merge_key=("nudge", layer.id), merge=event.isAutoRepeat())
        return True

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
        if prop == "anchor":
            self._drag.to_anchor = self._to_anchor(layer, at, to_local)
            self._drag.snaps = self._selected_outline().snaps
        self.document.begin_preview()

    @staticmethod
    def _to_anchor(layer: Layer, t: float, to_local: np.ndarray) -> np.ndarray:
        """World move of the pivot -> change of the anchor: the parent's inverse, then the layer's."""
        tr = layer_transform(layer, t)
        angle = np.radians(tr.rotation)
        own = tr.scale * np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
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
        outline = self.canvas.outline
        if outline is None or self.canvas.selected_layer != self.selection.layer_id:
            return None
        return outline

    def _handle_under(self, point: np.ndarray):
        outline = self._selected_outline()
        if outline is None:
            return None
        ppu = self.canvas.px_per_unit()
        return handle_at(outline.box, point, GRAB_PX / ppu, KNOB_OFFSET_PX / ppu)

    def _cross_under(self, point: np.ndarray) -> bool:
        """Whether ``point`` is on the selected layer's pivot cross."""
        outline = self._selected_outline()
        if outline is None:
            return False
        distance = np.linalg.norm(point - np.asarray(outline.anchor)) * self.canvas.px_per_unit()
        return bool(distance <= GRAB_PX)

    def _inside_selected_box(self, point: np.ndarray) -> bool:
        outline = self._selected_outline()
        return outline is not None and outline.box.contains(point, margin=4.0 / self.canvas.px_per_unit())
