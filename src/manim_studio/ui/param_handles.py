"""Parameter handles (P6c.1, ADR 0043): the pure geometry. No Qt.

The selected object shows a round handle per size it has - a rectangle's width
and height, a circle's radius, a line's ends, a text's font size - and dragging
one edits that parameter exactly as its Properties field does, within the same
limits. Everything is in Manim units.

A handle sits in a *frame*: ``world = a @ local + b``. For an object that is its
layer transform at the playhead (built objects are centred on the origin, so a
size grows about the object's centre); for a connector's end it is the frame of
the layer it points at, and ``local`` is the offset itself.

* ``object_handles`` / ``connector_handles`` - the handles an object shows;
* ``value_at`` - the parameter's value with the handle at a local point;
* ``line_origin`` - where a line's parameter space sits in its drawing (the
  drawing is re-centred, so dragging one end moves the layer to keep the other).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from ..core import adapter
from ..core.schema import Spec

Mode = Literal["point", "delta", "ratio"]
FONT_STEP = 4.0  # Shift: font sizes in steps of 4 points
POINT_STEP = 0.25  # Shift: connector offsets on a quarter-unit grid
LINE_TURN = 45.0  # Shift: a line end turns in steps of 45 degrees about the other end
X, Y = (1.0, 0.0), (0.0, 1.0)

# What each type's handles change: (param, mode, axis, factor). ``delta``: the value grows
# by ``factor`` times the move along ``axis`` (2: both sides move, about the centre);
# ``ratio``: the value scales with the handle's distance from the centre (text, stars).
SIZES: dict[str, tuple[tuple[str, Mode, tuple[float, float], float], ...]] = {
    "Circle": (("radius", "delta", X, 1.0),),
    "Dot": (("radius", "delta", X, 1.0),),
    "Square": (("side_length", "delta", X, 2.0),),
    "Rectangle": (("width", "delta", X, 2.0), ("height", "delta", Y, 2.0)),
    "Star": (("outer_radius", "ratio", X, 1.0),),
    "Text": (("font_size", "ratio", X, 1.0),),
    "MathTex": (("font_size", "ratio", X, 1.0),),
    "Tex": (("font_size", "ratio", X, 1.0),),
    "DecimalNumber": (("font_size", "ratio", X, 1.0),),
    "Axes": (("x_length", "delta", X, 2.0), ("y_length", "delta", Y, 2.0)),
    "SVGMobject": (("height", "delta", Y, 2.0),),
}
LINES = ("Line", "Arrow")


@dataclass(frozen=True, eq=False)
class ParamHandle:
    """One handle: where it is, what it changes and how."""

    param: str
    local: np.ndarray  # (2,) where it sits in its frame
    a: np.ndarray  # (2, 2) its frame -> world: world = a @ local + b
    b: np.ndarray  # (2,)
    start: float | tuple[float, float]  # the parameter's value now
    mode: Mode
    axis: np.ndarray  # sizes: the direction the value grows along (local)
    factor: float = 1.0
    step: float = 0.1  # Shift: values in steps of this
    whole: bool = False  # font sizes: whole points
    minimum: float | None = None
    maximum: float | None = None
    other: tuple[float, float] | None = None  # a line end: the other end's value (Shift turns about it)

    @property
    def world(self) -> np.ndarray:
        return self.a @ self.local + self.b

    def to_local(self, world) -> np.ndarray:
        """A world point in this handle's frame (pinv: a layer scaled to 0 must not raise)."""
        return np.linalg.pinv(self.a) @ (np.asarray(world, float)[:2] - self.b)

    @property
    def title(self) -> str:
        return {"side_length": "side", "outer_radius": "radius", "font_size": "size"}.get(
            self.param, self.param.replace("_offset", "").replace("_", " ")
        )


def _param(type_name: str, name: str) -> adapter.Param:
    return next(p for p in adapter.MOBJECT_PARAMS[type_name] if p.name == name)


def line_origin(spec: Spec, rest_points: np.ndarray) -> np.ndarray:
    """Where the parameter space's origin lies in a line's centred drawing: a parameter point
    ``p`` is drawn at ``p - line_origin``. ``rest_points``: the drawing's points (its own first)."""
    start = np.array(adapter.param_value(spec, _param(spec.type, "start"))[:2], float)
    end = np.array(adapter.param_value(spec, _param(spec.type, "end"))[:2], float)
    length = float(np.linalg.norm(end - start))
    unit = (end - start) / length if length > 1e-9 else np.zeros(2)
    buff = float(spec.params.get("buff", 0.25)) if spec.type == "Arrow" else 0.0
    return start + unit * buff - np.asarray(rest_points, float)[0, :2]  # Manim pulls the start in by buff


def object_handles(spec: Spec, rest_points: np.ndarray, a, b) -> list[ParamHandle]:
    """The handles of an object built from ``spec``: ``rest_points`` (N, 2) is its drawing as
    built (centred on the origin, ``adapter.build_mobject``), ``a, b`` its layer transform."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    points = np.asarray(rest_points, float).reshape(-1, 2) if len(rest_points) else np.zeros((0, 2))
    if spec.type in LINES:
        if not len(points):
            return []
        origin = line_origin(spec, points)
        ends = {n: adapter.param_value(spec, _param(spec.type, n))[:2] for n in ("start", "end")}
        return [
            ParamHandle(
                name,
                np.array(value, float) - origin,
                a,
                b,
                (float(value[0]), float(value[1])),
                "point",
                np.zeros(2),
                other=tuple(float(v) for v in ends["end" if name == "start" else "start"]),
            )
            for name, value in ends.items()
        ]
    if spec.type not in SIZES or not len(points):
        return []
    low, high = points.min(axis=0), points.max(axis=0)
    out = []
    for name, mode, axis, factor in SIZES[spec.type]:
        param = _param(spec.type, name)
        along = 0 if axis == X else 1
        local = (low + high) / 2
        local[along] = high[along]  # the middle of the right (or top) edge
        if mode == "ratio" and abs(local[along]) < 1e-6:
            continue  # nothing drawn to measure against
        font = name == "font_size"
        out.append(
            ParamHandle(
                name,
                local,
                a,
                b,
                float(adapter.param_value(spec, param)),
                mode,
                np.array(axis, float),
                factor,
                step=FONT_STEP if font else max(param.step, 0.05),
                whole=font,
                minimum=param.minimum,
                maximum=param.maximum,
            )
        )
    return out


def connector_handles(spec: Spec, frames) -> list[ParamHandle]:
    """A connector's two ends: ``frames`` are ``(a, b)`` per end (source, target) with
    ``world = a @ offset + b``, or None for an end that is not drawn."""
    out = []
    for name, frame in zip(("source_offset", "target_offset"), frames, strict=True):
        if frame is None:
            continue
        value = adapter.param_value(spec, _param("Connector", name))[:2]
        out.append(
            ParamHandle(
                name,
                np.array(value, float),
                np.asarray(frame[0], float),
                np.asarray(frame[1], float),
                (float(value[0]), float(value[1])),
                "point",
                np.zeros(2),
                step=POINT_STEP,
            )
        )
    return out


def value_at(handle: ParamHandle, local, step: bool = False):
    """The parameter's value with ``handle`` dragged to ``local`` (its frame); ``step`` (Shift):
    sizes in steps, a line end turned in 45-degree steps about the other end, offsets on a grid."""
    local = np.asarray(local, float)
    if handle.mode == "point":
        value = np.asarray(handle.start, float) + (local - handle.local)
        if step and handle.other is not None:
            other = np.asarray(handle.other, float)
            arm = value - other
            angle = math.radians(round(math.degrees(math.atan2(arm[1], arm[0])) / LINE_TURN) * LINE_TURN)
            value = other + float(np.linalg.norm(arm)) * np.array([math.cos(angle), math.sin(angle)])
        elif step:
            value = np.round(value / handle.step) * handle.step
        return (round(float(value[0]), 4), round(float(value[1]), 4))
    if handle.mode == "delta":
        value = handle.start + handle.factor * float(np.dot(local - handle.local, handle.axis))
    else:
        reach = float(np.dot(handle.local, handle.axis))
        value = handle.start * float(np.dot(local, handle.axis)) / reach
    if step:
        value = round(value / handle.step) * handle.step
    value = float(round(value)) if handle.whole else round(value, 4)
    if handle.minimum is not None:
        value = max(value, handle.minimum)
    if handle.maximum is not None:
        value = min(value, handle.maximum)
    return value


def handle_under(handles: list[ParamHandle], p, grab: float) -> ParamHandle | None:
    """The handle within ``grab`` of the world point ``p`` (the nearest)."""
    p = np.asarray(p, float)[:2]
    near = [(float(np.linalg.norm(h.world - p)), i) for i, h in enumerate(handles)]
    near = [(d, i) for d, i in near if d <= grab]
    return handles[min(near)[1]] if near else None
