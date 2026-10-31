"""Snapping guides (P6c.1, ADR 0043): the pure geometry. No Qt.

While an object is moved (or a handle dragged), the left edge, centre and right
edge of its box snap to the edges and centres of the other objects' boxes and of
the video frame within a radius, and the same for bottom, middle and top; a guide
line shows each snap. Boxes are axis-aligned ``(low, high)`` pairs in Manim units.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

SNAP_PX = 6.0  # how close (screen pixels) an edge or centre must come to snap


@dataclass(frozen=True)
class Target:
    """A line something can snap to: ``value`` on one axis, from the box spanning ``span``
    on the other (the guide is drawn across both boxes)."""

    value: float
    span: tuple[float, float]


@dataclass(frozen=True)
class Targets:
    xs: tuple[Target, ...]  # vertical lines (x values)
    ys: tuple[Target, ...]  # horizontal lines (y values)


@dataclass(frozen=True)
class Snap:
    offset: np.ndarray  # (2,) add to the move
    guides: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)


def _lines(low, high) -> tuple[np.ndarray, np.ndarray]:
    """A box's snapping lines: (left, centre, right) and (bottom, middle, top)."""
    low, high = np.asarray(low, float), np.asarray(high, float)
    middle = (low + high) / 2
    return np.array([low[0], middle[0], high[0]]), np.array([low[1], middle[1], high[1]])


def targets(boxes, frame=None, lines=()) -> Targets:
    """What the moving box can snap to: every box's edges and centres, the frame's, and the
    layout guides (ADR 0074) in ``lines``: ``(axis, position)`` pairs, "x" a vertical line at
    x = position and "y" a horizontal one, drawn across the frame (or a unit when there is none)."""
    xs, ys = [], []
    for low, high in [*boxes, *([frame] if frame is not None else [])]:
        bx, by = _lines(low, high)
        xs += [Target(float(v), (float(low[1]), float(high[1]))) for v in bx]
        ys += [Target(float(v), (float(low[0]), float(high[0]))) for v in by]
    low, high = frame if frame is not None else ((-0.5, -0.5), (0.5, 0.5))
    for axis, position in lines:
        if axis == "x":
            xs.append(Target(float(position), (float(low[1]), float(high[1]))))
        else:
            ys.append(Target(float(position), (float(low[0]), float(high[0]))))
    return Targets(tuple(xs), tuple(ys))


def _nearest(values: np.ndarray, candidates: tuple[Target, ...], radius: float):
    """The smallest move (within ``radius``) putting one of ``values`` on a candidate."""
    best = None
    for value in values:
        for target in candidates:
            move = target.value - value
            if abs(move) <= radius and (best is None or abs(move) < abs(best[0]) - 1e-12):
                best = (move, target)
    return best


def snap(low, high, found: Targets, radius: float, axes=(True, True)) -> Snap:
    """How far to move the box ``(low, high)`` so an edge or centre lies on a target, per axis
    (``axes``: which ones may snap), and the guides to draw for the snapped box."""
    low, high = np.asarray(low, float), np.asarray(high, float)
    bx, by = _lines(low, high)
    offset = np.zeros(2)
    hits = [None, None]
    if axes[0]:
        hits[0] = _nearest(bx, found.xs, radius)
    if axes[1]:
        hits[1] = _nearest(by, found.ys, radius)
    for axis, hit in enumerate(hits):
        if hit is not None:
            offset[axis] = hit[0]
    low, high = low + offset, high + offset
    guides = []
    if hits[0] is not None:
        x = hits[0][1].value
        span = hits[0][1].span
        guides.append(((x, min(low[1], span[0])), (x, max(high[1], span[1]))))
    if hits[1] is not None:
        y = hits[1][1].value
        span = hits[1][1].span
        guides.append(((min(low[0], span[0]), y), (max(high[0], span[1]), y)))
    return Snap(offset, guides)


def box_of(points) -> tuple[np.ndarray, np.ndarray] | None:
    """The axis-aligned box of ``points`` (N, 2+), or None when there are none."""
    points = np.asarray(points, float)
    if not len(points):
        return None
    return points[:, :2].min(axis=0), points[:, :2].max(axis=0)
