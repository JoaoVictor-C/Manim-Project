"""Selecting and moving objects on the canvas (S3, ADR 0016).

``MoveTool`` turns canvas input into selection changes and edits:

* click: select the front-most object under the cursor (Alt+click: the next one
  behind the current selection); a click inside the selected object's box keeps
  it; a click on nothing clears the selection;
* drag: move the selected object, previewed live and recorded as one undo step
  ("Move layer"); Shift locks the dominant axis; Escape cancels;
* arrow keys: nudge 1 px (Shift: 10 px); a held key is one undo step.

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
    press: np.ndarray  # cursor at press, Manim units
    start: tuple[float, float]  # the position being edited, at press
    key_time: float | None  # the frame the key goes to; None = base position
    base: Project  # snapshot at press


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
        self._drag: _Drag | None = None
        self._pending: tuple[np.ndarray, bool] | None = None
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
        layers = self.canvas.evaluator.frame_layers(self.playhead())
        hits = hit_layers(layers, point, self.canvas.px_per_unit())
        current = self.selection.layer_id
        if modifiers & Qt.KeyboardModifier.AltModifier:
            if hits:  # cycle behind the current selection
                index = hits.index(current) + 1 if current in hits else 0
                self.selection.select_layer(hits[index % len(hits)])
            return
        if current is not None and self._inside_selected_box(point):
            target = current
        elif hits:
            target = hits[0]
        else:
            self.selection.clear()
            return
        self.selection.select_layer(target)
        self._start_drag(target, point)

    def move(self, pos: QPointF, modifiers: Qt.KeyboardModifier) -> None:
        if self._drag is None:
            return
        self._pending = (self.canvas.to_units(pos), bool(modifiers & Qt.KeyboardModifier.ShiftModifier))
        if not self._scheduled:
            self._scheduled = True
            QTimer.singleShot(0, self.apply_pending)

    def release(self) -> None:
        if self._drag is None:
            return
        self.apply_pending()
        self._drag = None
        self.document.commit_preview("Move layer")

    def cancel(self) -> None:
        if self._drag is not None:
            self._drag = None
            self._pending = None
            self.document.cancel_preview()

    def apply_pending(self) -> None:
        """Preview the latest cursor position (coalesced, as timeline drags are)."""
        self._scheduled = False
        if self._drag is None or self._pending is None:
            return
        point, constrain = self._pending
        self._pending = None
        delta = point - self._drag.press
        if constrain:
            delta[np.argmin(np.abs(delta))] = 0.0
        value = (self._drag.start[0] + float(delta[0]), self._drag.start[1] + float(delta[1]))
        self.document.preview(self._edit(self._drag.base, self._drag.layer_id, value, self._drag.key_time))

    # -- keyboard ------------------------------------------------------------------

    def wants_key(self, event: QKeyEvent) -> bool:
        return event.key() in ARROWS and self.selection.layer_id is not None and self._drag is None

    def key(self, event: QKeyEvent) -> bool:
        if event.key() == Qt.Key.Key_Escape and self._drag is not None:
            self.cancel()
            return True
        if not self.wants_key(event):
            return False
        layer = self.project.layer(self.selection.layer_id)
        step = NUDGE_SHIFT_PX if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else NUDGE_PX
        dx, dy = (d * step / self.canvas.px_per_unit() for d in ARROWS[event.key()])
        key_time = self._key_time(layer)
        x, y = self._position(layer, key_time)
        edit = self._edit(self.project, layer.id, (x + dx, y + dy), key_time)
        self.document.apply(edit, "Nudge layer", merge_key=("nudge", layer.id), merge=event.isAutoRepeat())
        return True

    # -- rules ---------------------------------------------------------------------

    def _start_drag(self, layer_id: str, point: np.ndarray) -> None:
        layer = self.project.layer(layer_id)
        if self._morph_playing(layer_id):
            self.message.emit("This object is morphing here: move the playhead outside the morph to move it.")
            return
        key_time = self._key_time(layer)
        start = self._position(layer, key_time)
        self._drag = _Drag(layer_id, point, start, key_time, self.project)
        self.document.begin_preview()

    def _key_time(self, layer: Layer) -> float | None:
        """None for base edits; else the playhead's frame, moving the playhead onto it."""
        if not layer.tracks.get("position"):
            return None
        fps = self.project.canvas.fps
        t = self.playhead()
        frame_t = round(t * fps) / fps
        if abs(frame_t - t) > 1e-9:
            self.seek(frame_t)
        return frame_t

    def _position(self, layer: Layer, key_time: float | None) -> tuple[float, float]:
        if key_time is None:
            return tuple(layer.base.position)
        return tuple(layer_transform(layer, key_time).position)

    @staticmethod
    def _edit(project: Project, layer_id: str, value, key_time: float | None) -> edits.Edit:
        if key_time is not None:
            return edits.set_key(project, layer_id, "position", key_time, value)
        base = project.layer(layer_id).base.model_dump()
        base["position"] = value
        return edits.update_layer(project, layer_id, base=base)

    def _morph_playing(self, layer_id: str) -> bool:
        t = self.playhead()
        for layer in self.project.layers:
            for clip in layer.clips:
                if clip.to_layer and layer_id in (layer.id, clip.to_layer) and clip.start <= t < clip.end:
                    return True
        return False

    def _inside_selected_box(self, point: np.ndarray) -> bool:
        outline = self.canvas.outline
        if outline is None or self.canvas.selected_layer != self.selection.layer_id:
            return False
        margin = 4.0 / self.canvas.px_per_unit()
        box = outline.bounds.adjusted(-margin, -margin, margin, margin)
        return box.contains(QPointF(float(point[0]), float(point[1])))
