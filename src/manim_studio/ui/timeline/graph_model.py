"""The graph editor's model (P6b.2): curves, value ranges, sampling, hits and drag rules - no Qt.

The Animate page draws the selected layer's keyed transform values over time. This module
holds everything that turns keys into curves and mouse positions into edits, so it can be
tested headless (decision session 35):

* ``CURVES`` - x and y (the two components of the position key), scale, rotation, opacity;
  ``curves_for`` offers only what the layer may key (a graph on axes: opacity, ADR 0024);
* ``value_range`` - each curve is normalised to the plot over its own range (its values,
  a minimum span, 10 % padding; opacity 0..1), because one shared axis would draw opacity
  flat beside rotation in degrees; ``ValueView`` is the shown window of that space;
* ``sample_track`` - ``evaluator._sample`` at many ascending times, walking the segments
  once (O(samples + keys)); ``curve_points`` adds the key times exactly;
* ``drag_key`` - one curve's key moved in time (``timeline.model.drag_keys`` on that track
  alone: the same snap points and frame clamp) and in value, built on the drag's start;
* ``add_key`` / ``delete_keys`` / ``set_segment_ease`` - the other edits, all through
  ``core.edits``, so undo comes for free.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from ...core.editing import edits
from ...core.engine import adapter
from ...core.model import motion_paths
from ...core.model.schema import Easing, Keyframe, Layer, Project, keyable_props
from .model import TimeScale, drag_keys, quantize, snap_candidates

PAD = 0.1  # of a curve's range, above and below
EPS = 1e-6  # s: a sample just before a key, where an ease may jump (there_and_back)
VALUE_DIGITS = 4  # dragged values are rounded to this many decimals
MIN_WINDOW, MAX_WINDOW = 0.01, 100.0  # how far the value window zooms


@dataclass(frozen=True)
class Curve:
    """One value drawn over time: a property, or one component of the position."""

    name: str
    prop: str  # the track
    index: int | None  # the component of a position value, None for a number
    label: str
    min_span: float  # the smallest range drawn (a flat curve sits in the middle)
    token: str  # its colour in ``theme.THEME``


CURVES: tuple[Curve, ...] = (
    Curve("x", "position", 0, "Position x", 1.0, "curve_x"),
    Curve("y", "position", 1, "Position y", 1.0, "curve_y"),
    Curve("scale", "scale", None, "Scale", 0.5, "curve_scale"),
    Curve("scale_x", "scale_x", None, "Width scale", 0.5, "curve_width"),
    Curve("scale_y", "scale_y", None, "Height scale", 0.5, "curve_height"),
    Curve("rotation", "rotation", None, "Rotation", 45.0, "curve_rotation"),
    Curve("opacity", "opacity", None, "Opacity", 1.0, "curve_opacity"),
)
BY_NAME: dict[str, Curve] = {curve.name: curve for curve in CURVES}


def curves_for(layer: Layer) -> list[Curve]:
    """The curves the layer may key (ADR 0024: a locked child keys opacity only)."""
    keyable = keyable_props(layer)
    return [curve for curve in CURVES if curve.prop in keyable]


def component(value: Any, curve: Curve) -> float:
    return float(value[curve.index]) if curve.index is not None else float(value)


def with_component(value: Any, curve: Curve, number: float) -> Any:
    """``value`` with ``curve``'s part replaced by ``number`` (the other component kept)."""
    if curve.index is None:
        return float(number)
    parts = [float(value[0]), float(value[1])]
    parts[curve.index] = float(number)
    return (parts[0], parts[1])


def clamp_value(curve: Curve, number: float) -> float:
    """A value the property can hold: opacity stays within 0..1."""
    if curve.prop == "opacity":
        return min(max(number, 0.0), 1.0)
    if curve.prop in ("scale_x", "scale_y"):
        return min(max(number, 0.01), 100.0)
    return number


def keys(layer: Layer, curve: Curve) -> list[tuple[float, float]]:
    """``(t, value)`` of the curve's keys."""
    return [(key.t, component(key.value, curve)) for key in layer.tracks.get(curve.prop, [])]


def base_value(layer: Layer, curve: Curve) -> float:
    return component(getattr(layer.base, curve.prop), curve)


def value_range(layer: Layer, curve: Curve) -> tuple[float, float]:
    """The values drawn from the plot's bottom to its top: the keys' (or the base's) span,
    at least ``min_span``, padded by ``PAD``; opacity always shows 0..1."""
    if curve.prop == "opacity":
        lo, hi = 0.0, 1.0
    else:
        values = [v for _, v in keys(layer, curve)] or [base_value(layer, curve)]
        lo, hi = min(values), max(values)
        if hi - lo < curve.min_span:
            middle = (lo + hi) / 2
            lo, hi = middle - curve.min_span / 2, middle + curve.min_span / 2
    pad = (hi - lo) * PAD
    return lo - pad, hi + pad


def normalise(value: float, span: tuple[float, float]) -> float:
    lo, hi = span
    return (value - lo) / (hi - lo)


def denormalise(n: float, span: tuple[float, float]) -> float:
    lo, hi = span
    return lo + n * (hi - lo)


# -- sampling ---------------------------------------------------------------------------


def sample_track(track: Sequence[Keyframe], times: Sequence[float], default: Any) -> list[Any]:
    """``evaluator._sample(track, t, default)`` for each of ``times``, walking the segments once
    when the times ascend (the rule is the evaluator's: eases, bezier eases, curved paths)."""
    if not track:
        return [default] * len(times)
    first, last = track[0], track[-1]
    rates: dict[int, Any] = {}
    values: list[Any] = []
    i = 0
    for t in times:
        if t <= first.t:
            values.append(first.value)
            continue
        if t >= last.t:
            values.append(last.value)
            continue
        if t < track[i].t:
            i = 0  # the times went back
        while not (track[i].t <= t < track[i + 1].t):
            i += 1
        k0, k1 = track[i], track[i + 1]
        rate = rates.get(i)
        if rate is None:
            rate = rates[i] = adapter.rate_func(k0.ease)
        u = rate((t - k0.t) / (k1.t - k0.t))
        if k0.out_tangent is not None or k1.in_tangent is not None:  # a curved path (ADR 0026)
            values.append(motion_paths.point_at(k0.value, k0.out_tangent, k1.in_tangent, k1.value, u))
        elif isinstance(k0.value, tuple):
            values.append(tuple(a + (b - a) * u for a, b in zip(k0.value, k1.value, strict=True)))
        else:
            values.append(k0.value + (k1.value - k0.value) * u)
    return values


def sample_times(layer: Layer, curve: Curve, t0: float, t1: float, step: float) -> list[float]:
    """Times to draw the curve at: every ``step`` from ``t0`` to ``t1``, plus each key inside
    and the instant before it (where an ease that does not end at its target jumps)."""
    count = max(1, math.ceil((t1 - t0) / step))
    times = {t0 + (t1 - t0) * i / count for i in range(count + 1)}
    for key in layer.tracks.get(curve.prop, []):
        if t0 < key.t < t1:
            times.update((key.t, key.t - EPS))
    return sorted(times)


def curve_points(layer: Layer, curve: Curve, t0: float, t1: float, step: float) -> list[tuple[float, float]]:
    """``(t, value)`` along the curve between ``t0`` and ``t1`` (sampled every ``step`` s)."""
    times = sample_times(layer, curve, t0, t1, step)
    values = sample_track(layer.tracks.get(curve.prop, []), times, getattr(layer.base, curve.prop))
    return [(t, component(v, curve)) for t, v in zip(times, values, strict=True)]


def value_at(layer: Layer, curve: Curve, t: float) -> Any:
    """The property's whole value (a position for x and y) at ``t``, as the evaluator plays it."""
    return sample_track(layer.tracks.get(curve.prop, []), [t], getattr(layer.base, curve.prop))[0]


# -- the view ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValueView:
    """Normalised values -> y pixels: ``n1`` at ``top``, ``n0`` at ``top + height``.

    Every curve's range maps to 0..1, so one window serves them all; zooming and panning
    move the window (Ctrl+wheel, middle drag)."""

    top: float = 0.0
    height: float = 100.0
    n0: float = 0.0
    n1: float = 1.0

    def y(self, n: float) -> float:
        return self.top + (self.n1 - n) / (self.n1 - self.n0) * self.height

    def n(self, y: float) -> float:
        return self.n1 - (y - self.top) / self.height * (self.n1 - self.n0)

    def zoomed(self, factor: float, anchor_y: float) -> ValueView:
        """Zoom by ``factor`` keeping the value under ``anchor_y`` where it is."""
        anchor = self.n(anchor_y)
        span = min(max((self.n1 - self.n0) / factor, MIN_WINDOW), MAX_WINDOW)
        fraction = (anchor_y - self.top) / self.height  # 0 at the top
        n1 = anchor + fraction * span
        return ValueView(self.top, self.height, n1 - span, n1)

    def panned(self, dy: float) -> ValueView:
        """Move the window by ``dy`` pixels (down: lower values come into view... and up)."""
        shift = dy / self.height * (self.n1 - self.n0)
        return ValueView(self.top, self.height, self.n0 + shift, self.n1 + shift)

    def resized(self, top: float, height: float) -> ValueView:
        return ValueView(top, height, self.n0, self.n1)


def frame_times(layer: Layer | None, curves: Iterable[Curve], duration: float) -> tuple[float, float]:
    """The time span F shows: the curves' keys with 5 % on each side, or the scene when
    they span less than a second."""
    times = [t for curve in curves if layer is not None for t, _ in keys(layer, curve)]
    if not times or max(times) - min(times) < 1.0:
        return 0.0, duration
    lo, hi = min(times), max(times)
    pad = (hi - lo) * 0.05
    return lo - pad, hi + pad


def nice_step(units_per_px: float, min_px: float = 60.0) -> float:
    """A 1, 2 or 5 times a power of ten step leaving at least ``min_px`` between grid lines."""
    target = abs(units_per_px) * min_px
    if target <= 0 or not math.isfinite(target):
        return 1.0
    power = 10 ** math.floor(math.log10(target))
    for multiple in (1, 2, 5, 10):
        if multiple * power >= target:
            return multiple * power
    return 10 * power


def ticks(lo: float, hi: float, step: float) -> list[float]:
    """Multiples of ``step`` within ``lo..hi``."""
    first = math.ceil(lo / step)
    return [i * step for i in range(first, math.floor(hi / step) + 1)]


# -- hits -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Point:
    """A key as drawn: its curve, time and pixel position."""

    curve: str
    t: float
    x: float
    y: float


def nearest_point(points: Iterable[Point], x: float, y: float, radius: float) -> Point | None:
    """The point closest to ``(x, y)`` within ``radius`` pixels (in both directions)."""
    near = [
        (math.hypot(p.x - x, p.y - y), p) for p in points if abs(p.x - x) <= radius and abs(p.y - y) <= radius
    ]
    return min(near, key=lambda pair: pair[0])[1] if near else None


def distance_to_polyline(polyline: Sequence[tuple[float, float]], x: float, y: float) -> float:
    """Pixels from ``(x, y)`` to the nearest segment of ``polyline``."""
    best = math.inf
    for (ax, ay), (bx, by) in itertools.pairwise(polyline):
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        f = 0.0 if length2 == 0 else min(max(((x - ax) * dx + (y - ay) * dy) / length2, 0.0), 1.0)
        best = min(best, math.hypot(ax + f * dx - x, ay + f * dy - y))
    if len(polyline) == 1:
        best = math.hypot(polyline[0][0] - x, polyline[0][1] - y)
    return best


def segment_start(layer: Layer, curve: Curve, t: float) -> float | None:
    """The time of the key that starts the curve's segment around ``t`` (its ease shapes it),
    or None before the first key and after the last."""
    times = [key.t for key in layer.tracks.get(curve.prop, [])]
    for t0, t1 in itertools.pairwise(times):
        if t0 <= t < t1:
            return t0
    return None


# -- edits ------------------------------------------------------------------------------


def key_at(layer: Layer, curve: Curve, t: float, fps: int) -> Keyframe | None:
    return next((key for key in layer.tracks.get(curve.prop, []) if abs(key.t - t) < 0.5 / fps), None)


def drag_key(
    project: Project,
    layer_id: str,
    curve: Curve,
    t: float,
    proposed_t: float,
    proposed_value: float,
    *,
    scale: TimeScale,
    playhead: float,
    snapping: bool = True,
) -> tuple[edits.Edit, float]:
    """The snapshot after dragging ``curve``'s key at ``t`` to ``(proposed_t, proposed_value)``,
    built on ``project`` (the drag's start, never the last preview), and the key's new time.

    The time follows the timeline's rule for that one track (snap, frame grid, more than a
    frame from its neighbours); the value replaces only this curve's component (opacity is
    clamped to 0..1). x and y share the position key, so either moves both in time."""
    layer = project.layer(layer_id)
    canvas = project.canvas
    key = key_at(layer, curve, t, canvas.fps)
    if key is None:
        raise edits.EditError(f"layer {layer_id!r} has no {curve.prop} key at {t:g} s")
    alone = layer.model_copy(update={"tracks": {curve.prop: layer.tracks[curve.prop]}})
    candidates = snap_candidates(project, playhead, exclude=[("key", layer_id, key.t)])
    new_t = drag_keys(
        alone,
        key.t,
        proposed_t,
        duration=canvas.duration,
        fps=canvas.fps,
        scale=scale,
        candidates=candidates,
        snapping=snapping,
    )
    result = project
    if abs(new_t - key.t) >= 0.5 / canvas.fps:
        result = edits.retime_keys(result, layer_id, key.t, new_t, props=[curve.prop]).project
        new_t = quantize(new_t, canvas.fps)
    else:
        new_t = key.t
    number = round(clamp_value(curve, proposed_value), VALUE_DIGITS)
    value = with_component(key.value, curve, number)
    if value != key.value:
        result = edits.set_key(result, layer_id, curve.prop, new_t, value).project
    kind, layer_ids = edits.classify(project, result)
    return edits.Edit(result, kind, layer_ids), new_t


def add_key(project: Project, layer_id: str, curve: Curve, t: float) -> edits.Edit:
    """A key on ``curve``'s property at the frame of ``t``, holding the value the evaluator
    plays there, so adding it changes no frame (an untracked property starts its track)."""
    layer = project.layer(layer_id)
    t = min(max(quantize(t, project.canvas.fps), 0.0), project.canvas.duration)
    return edits.set_key(project, layer_id, curve.prop, t, value_at(layer, curve, t))


def delete_keys(project: Project, layer_id: str, t: float, props: Iterable[str] | None) -> edits.Edit:
    """Remove the keys at ``t`` of ``props`` (every property when None)."""
    return edits.remove_keys(project, layer_id, t, props=props)


def set_segment_ease(project: Project, layer_id: str, curve: Curve, t: float, ease: Easing) -> edits.Edit:
    """The ease of ``curve``'s segment starting at ``t`` (only that property's key)."""
    return edits.set_key_ease(project, layer_id, t, ease, props=[curve.prop])


def ease_choices() -> list[Easing]:
    """The eases offered on a segment: the named ones, then the bezier presets."""
    named = [Easing(name=name) for name in adapter.EASE_NAMES]
    return named + [Easing(name=None, bezier=b) for b in adapter.BEZIER_PRESETS.values()]
