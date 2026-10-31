"""Parameter handles (P6c.1, ADR 0043): the pure geometry. No Qt.

The selected object shows round handles for its editable points and parameters -
a polygon's vertices, a circle's radius, a line's ends, a text's font size -
and dragging one edits that value exactly as its Properties field does, within
the same limits. Everything is in Manim units.

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

from ...core.engine import adapter
from ...core.model.schema import Spec

Mode = Literal["point", "delta", "ratio", "range", "anchored"]
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
    "RoundedRectangle": (("width", "delta", X, 2.0), ("height", "delta", Y, 2.0)),
    "Ellipse": (("width", "delta", X, 2.0), ("height", "delta", Y, 2.0)),
    "RightTriangle": (("side_length", "delta", X, 1.5),),
    "Star": (("outer_radius", "ratio", X, 1.0),),
    "RegularPolygram": (("radius", "ratio", X, 1.0),),
    "Arc": (("radius", "ratio", X, 1.0),),
    "Sector": (("radius", "ratio", X, 1.0),),
    "Annulus": (("outer_radius", "ratio", X, 1.0),),
    "AnnularSector": (("outer_radius", "ratio", X, 1.0),),
    "Text": (("font_size", "ratio", X, 1.0),),
    "MathTex": (("font_size", "ratio", X, 1.0),),
    "Tex": (("font_size", "ratio", X, 1.0),),
    "DecimalNumber": (("font_size", "ratio", X, 1.0),),
    "Axes": (("x_length", "delta", X, 2.0), ("y_length", "delta", Y, 2.0)),
    "NumberLine": (("length", "delta", X, 2.0),),
    "NumberPlane": (("x_length", "delta", X, 2.0), ("y_length", "delta", Y, 2.0)),
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
    point_control: bool = False  # a draggable geometry point, not a size or connector offset
    python_names: tuple[str, ...] | None = None  # Python object's point param or x/y PARAMS names
    label: str | None = None
    display_offset: tuple[float, float] | None = None  # visual clearance from the transform side handles
    point_whole: tuple[bool, bool] | None = None  # Python point coordinates declared as integer params
    point_minimum: tuple[float | None, float | None] | None = None
    point_maximum: tuple[float | None, float | None] | None = None
    range_end: int | None = None  # which end of an Axes range this handle edits
    minimum_span: float = 0.01
    reference: np.ndarray | None = None  # anchored value: its zero point in the object's frame
    unit: str = ""

    @property
    def world(self) -> np.ndarray:
        local = self.local if self.display_offset is None else self.local + self.display_offset
        return self.a @ local + self.b

    def to_local(self, world) -> np.ndarray:
        """A world point in this handle's frame (pinv: a layer scaled to 0 must not raise)."""
        return np.linalg.pinv(self.a) @ (np.asarray(world, float)[:2] - self.b)

    @property
    def title(self) -> str:
        title = self.label or {"side_length": "side", "outer_radius": "radius", "font_size": "size"}.get(
            self.param, self.param.replace("_offset", "").replace("_", " ")
        )
        return f"{title} ({self.unit})" if self.unit else title


def _param(type_name: str, name: str) -> adapter.Param:
    return next(p for p in adapter.MOBJECT_PARAMS[type_name] if p.name == name)


def supports_object_handles(spec: Spec) -> bool:
    """Whether the adapter builds this as a parameterized mobject or Python object."""
    return spec.type == "Python" or (
        (spec.type in adapter.MOBJECT_PARAMS or spec.type in adapter.plugins.TYPES)
        and spec.type not in adapter.CHILD_ONLY_TYPES
    )


def _point_params(spec: Spec) -> tuple[adapter.Param, ...]:
    """The true geometry points a built-in or plugin explicitly exposes as handles."""
    if spec.type in adapter.MOBJECT_PARAMS:
        return adapter.MOBJECT_PARAMS[spec.type]
    if spec.type in adapter.plugins.TYPES:
        return adapter.plugins.TYPES[spec.type].params
    return ()


def line_origin(spec: Spec, rest_points: np.ndarray) -> np.ndarray:
    """Where the parameter space's origin lies in a line's centred drawing: a parameter point
    ``p`` is drawn at ``p - line_origin``. ``rest_points``: the drawing's points (its own first)."""
    start = np.array(adapter.param_value(spec, _param(spec.type, "start"))[:2], float)
    end = np.array(adapter.param_value(spec, _param(spec.type, "end"))[:2], float)
    length = float(np.linalg.norm(end - start))
    unit = (end - start) / length if length > 1e-9 else np.zeros(2)
    buff = float(spec.params.get("buff", 0.25)) if spec.type == "Arrow" else 0.0
    return start + unit * buff - np.asarray(rest_points, float)[0, :2]  # Manim pulls the start in by buff


def object_handles(
    spec: Spec, rest_points: np.ndarray, *frame, a=None, b=None, origin=None, built=None
) -> list[ParamHandle]:
    """The handles of an object built from ``spec``: ``rest_points`` (N, 2) is its drawing as
    built (centred on the origin), ``origin`` its pre-centre position in parameter space, and
    ``a, b`` its layer transform. Accept the original ``(a, b)`` call shape as well."""
    if frame:
        if a is not None or b is not None or origin is not None or built is not None:
            raise TypeError("pass the object frame either positionally or by keyword")
        if len(frame) == 2:  # earlier callers without the pre-centre origin
            a, b = frame
        elif len(frame) == 3:
            origin, a, b = frame
        elif len(frame) == 4:
            origin, a, b, built = frame
        else:
            raise TypeError("object_handles expects (a, b), (origin, a, b), or (origin, a, b, built)")
    if a is None or b is None:
        raise TypeError("the object frame needs both a and b")
    if origin is None:
        origin = np.zeros(2)
    a, b = np.asarray(a, float), np.asarray(b, float)
    origin = np.asarray(origin, float)[:2]
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
                point_control=True,
            )
            for name, value in ends.items()
        ]
    out = []
    if spec.type == "Python":
        from ...core.code import python_object

        code = str(spec.params.get("code", ""))
        values = python_object.call_values(code, dict(spec.params.get("values") or {}))
        for declared in python_object.read_handles(code):
            if declared.point is not None:
                start = tuple(float(coordinate) for coordinate in values[declared.point])
                names = (declared.point,)
                minimum = (declared.point_minimum, declared.point_minimum)
                maximum = (declared.point_maximum, declared.point_maximum)
                whole = (False, False)
            else:
                start = (float(values[declared.x]), float(values[declared.y]))
                names = (declared.x, declared.y)
                minimum = (declared.x_minimum, declared.y_minimum)
                maximum = (declared.x_maximum, declared.y_maximum)
                whole = (declared.x_kind == "int", declared.y_kind == "int")
            out.append(
                ParamHandle(
                    declared.label,
                    np.asarray(start, float) - origin,
                    a,
                    b,
                    start,
                    "point",
                    np.zeros(2),
                    step=declared.step,
                    point_control=True,
                    python_names=names,
                    label=declared.label,
                    point_whole=whole,
                    point_minimum=minimum,
                    point_maximum=maximum,
                    unit=declared.unit,
                )
            )
    else:
        for param in _point_params(spec):
            if param.kind != "point" or not param.point_handle:
                continue
            value = tuple(float(v) for v in adapter.param_value(spec, param)[:2])
            out.append(
                ParamHandle(
                    param.name,
                    np.asarray(value, float) - origin,
                    a,
                    b,
                    value,
                    "point",
                    np.zeros(2),
                    step=POINT_STEP,
                    point_control=True,
                    label=param.title,
                    point_minimum=(param.minimum, param.minimum),
                    point_maximum=(param.maximum, param.maximum),
                )
            )
    if spec.type == "Axes" and built is not None:
        out.extend(_axes_handles(spec, built, a, b))
    if spec.type not in SIZES or not len(points):
        return out
    low, high = points.min(axis=0), points.max(axis=0)
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


def _axes_handles(spec: Spec, built, a: np.ndarray, b: np.ndarray) -> list[ParamHandle]:
    """Range endpoints and grid spacing controls, positioned from the built coordinate system."""
    x0, x1 = (float(v) for v in adapter.param_value(spec, _param("Axes", "x_range"))[:2])
    y0, y1 = (float(v) for v in adapter.param_value(spec, _param("Axes", "y_range"))[:2])
    if x1 <= x0 or y1 <= y0:
        return []

    def at(x: float, y: float) -> np.ndarray:
        return np.asarray(built.c2p(x, y), float)[:2]

    # Keep endpoint handles on the visible axis when zero falls outside a configured range.
    axis_y = min(max(0.0, y0), y1)
    axis_x = min(max(0.0, x0), x1)
    x_range = (x0, x1)
    y_range = (y0, y1)
    x_length = max(float(adapter.param_value(spec, _param("Axes", "x_length"))), 1e-9)
    y_length = max(float(adapter.param_value(spec, _param("Axes", "y_length"))), 1e-9)
    out = []
    for name, values, endpoint, axis, local, span, length, label in (
        ("x_range", x_range, 0, X, at(x0, axis_y), x1 - x0, x_length, "x min"),
        ("x_range", x_range, 1, X, at(x1, axis_y), x1 - x0, x_length, "x max"),
        ("y_range", y_range, 0, Y, at(axis_x, y0), y1 - y0, y_length, "y min"),
        ("y_range", y_range, 1, Y, at(axis_x, y1), y1 - y0, y_length, "y max"),
    ):
        out.append(
            ParamHandle(
                name,
                local,
                a,
                b,
                values,
                "range",
                np.asarray(axis, float),
                span / length,
                step=0.5,
                minimum=-1000.0,
                maximum=1000.0,
                range_end=endpoint,
                label=label,
            )
        )

    # Grid handles sit one interval from the origin and read spacing from that fixed origin.
    # They are hidden when the interval lies outside the visible axes; the Properties fields remain available.
    x_grid_step = float(adapter.param_value(spec, _param("Axes", "grid_x_step")))
    if (
        adapter.param_value(spec, _param("Axes", "grid_x")) == "yes"
        and x0 <= 0 <= x1
        and 0 < x_grid_step <= x1
    ):
        out.append(
            ParamHandle(
                "grid_x_step",
                at(x_grid_step, axis_y),
                a,
                b,
                x_grid_step,
                "anchored",
                np.asarray(X, float),
                (x1 - x0) / x_length,
                step=0.1,
                minimum=0.01,
                maximum=1000.0,
                reference=at(0.0, axis_y),
                label="vertical spacing",
            )
        )

    y_grid_step = float(adapter.param_value(spec, _param("Axes", "grid_y_step")))
    if (
        adapter.param_value(spec, _param("Axes", "grid_y")) == "yes"
        and y0 <= 0 <= y1
        and 0 < y_grid_step <= y1
    ):
        out.append(
            ParamHandle(
                "grid_y_step",
                at(axis_x, y_grid_step),
                a,
                b,
                y_grid_step,
                "anchored",
                np.asarray(Y, float),
                (y1 - y0) / y_length,
                step=0.1,
                minimum=0.01,
                maximum=1000.0,
                reference=at(axis_x, 0.0),
                label="horizontal spacing",
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
    if handle.display_offset is not None:
        local = local - np.asarray(handle.display_offset, float)
    if handle.mode == "point":
        value = np.asarray(handle.start, float) + (local - handle.local)
        if step and handle.other is not None:
            other = np.asarray(handle.other, float)
            arm = value - other
            angle = math.radians(round(math.degrees(math.atan2(arm[1], arm[0])) / LINE_TURN) * LINE_TURN)
            value = other + float(np.linalg.norm(arm)) * np.array([math.cos(angle), math.sin(angle)])
        elif step:
            value = np.round(value / handle.step) * handle.step
        if handle.point_whole is not None:
            value = np.array(
                [round(v) if whole else v for v, whole in zip(value, handle.point_whole, strict=True)]
            )
        if handle.point_minimum is not None:
            value = np.array(
                [
                    max(v, low) if low is not None else v
                    for v, low in zip(value, handle.point_minimum, strict=True)
                ]
            )
        if handle.point_maximum is not None:
            value = np.array(
                [
                    min(v, high) if high is not None else v
                    for v, high in zip(value, handle.point_maximum, strict=True)
                ]
            )
        return (round(float(value[0]), 4), round(float(value[1]), 4))
    if handle.mode == "range":
        if handle.range_end is None:
            return handle.start
        values = list(handle.start)
        end = handle.range_end
        value = values[end] + handle.factor * float(np.dot(local - handle.local, handle.axis))
        if step:
            value = round(value / handle.step) * handle.step
        if handle.minimum is not None:
            value = max(value, handle.minimum)
        if handle.maximum is not None:
            value = min(value, handle.maximum)
        other = values[1 - end]
        if end == 0:
            value = min(value, other - handle.minimum_span)
        else:
            value = max(value, other + handle.minimum_span)
        values[end] = round(float(value), 4)
        return (values[0], values[1])
    if handle.mode == "anchored":
        if handle.reference is None:
            return handle.start
        value = float(np.dot(local - handle.reference, handle.axis)) * handle.factor
        if step:
            value = round(value / handle.step) * handle.step
    elif handle.mode == "delta":
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
