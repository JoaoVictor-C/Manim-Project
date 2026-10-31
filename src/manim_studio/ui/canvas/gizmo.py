"""Transform handles: the pure geometry (P2a, ADR 0016/0018). No Qt.

Everything is in Manim units (y up, angles in degrees counter-clockwise), the
same space the evaluator places layers in: world = R(rotation) S(scale) local
+ position, turned about the layer's pivot (its anchor, ADR 0021).

* ``oriented_box`` — the box around a drawn object in the layer's own frame,
  so handles stay on the shape when it is rotated;
* ``scale_from`` / ``angle_delta`` — what a handle drag means;
* ``handle_at`` — which handle (if any) is under the cursor;
* ``Box.snap_points`` / ``nearest`` — where the pivot cross snaps (P2f).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

HANDLE_PX = 8.0  # corner squares, drawn size
GRAB_PX = 6.0  # how close the cursor must be to grab a handle
KNOB_OFFSET_PX = 24.0  # rotate knob distance beyond the top edge
MIN_BOX_PX = 12.0  # flat shapes (a horizontal line) still get a usable box
SCALE_LIMITS = (0.01, 100.0)
SHIFTS_ELSEWHERE = (  # status note after moving the anchor of a layer with keyed transforms
    "Anchor moved: with transform properties keyed, the object keeps its place at this frame only."
)
SCALE_SNAP = 0.1
ANGLE_SNAP = 15.0

Handle = Literal["scale", "scale_x", "scale_y", "rotate"]


@dataclass(frozen=True)
class Box:
    """A rectangle in the layer's frame: corners bottom-left, bottom-right, top-right, top-left."""

    corners: np.ndarray  # (4, 2) world units
    pivot: np.ndarray  # (2,)
    rotation: float  # degrees

    @property
    def up(self) -> np.ndarray:
        edge = self.corners[2] - self.corners[3]
        length = float(np.linalg.norm(edge))
        if length <= 1e-9:
            a = math.radians(self.rotation)
            return np.array([-math.sin(a), math.cos(a)])
        return np.array([-edge[1], edge[0]]) / length

    def knob(self, offset: float) -> np.ndarray:
        """The rotate knob: beyond the middle of the top edge, along the box's up direction."""
        top_middle = (self.corners[2] + self.corners[3]) / 2
        return top_middle + self.up * offset

    @property
    def centre(self) -> np.ndarray:
        return self.corners.mean(axis=0)

    def snap_points(self) -> np.ndarray:
        """Corners, edge midpoints and the centre: where the pivot cross snaps (9, 2)."""
        middles = (self.corners + np.roll(self.corners, -1, axis=0)) / 2
        return np.vstack([self.corners, middles, self.centre])

    def contains(self, p: np.ndarray, margin: float = 0.0) -> bool:
        basis = np.column_stack((self.corners[1] - self.corners[0], self.corners[3] - self.corners[0]))
        if abs(float(np.linalg.det(basis))) <= 1e-9:
            return False
        uv = np.linalg.solve(basis, np.asarray(p, float) - self.corners[0])
        limits = [margin / max(float(np.linalg.norm(basis[:, axis])), 1e-9) for axis in (0, 1)]
        return bool((-limits[0] <= uv[0] <= 1 + limits[0]) and (-limits[1] <= uv[1] <= 1 + limits[1]))


def oriented_box(points: np.ndarray, pivot, rotation: float, min_size: float = 0.0) -> Box:
    """The bounding box of ``points`` (N, 2) in the frame rotated by ``rotation`` about ``pivot``."""
    pivot = np.asarray(pivot, float)
    local = _rotate(np.asarray(points, float)[:, :2] - pivot, -rotation)
    lo, hi = local.min(axis=0), local.max(axis=0)
    for axis in (0, 1):  # give flat shapes some thickness so their handles do not overlap
        if hi[axis] - lo[axis] < min_size:
            middle = (hi[axis] + lo[axis]) / 2
            lo[axis], hi[axis] = middle - min_size / 2, middle + min_size / 2
    corners = np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]])
    return Box(_rotate(corners, rotation) + pivot, pivot, rotation)


def affine_box(points: np.ndarray, pivot, a, b, min_size: float = 0.0) -> Box:
    """The bounds of world ``points`` in a layer's local axes, carried by an arbitrary affine map."""
    pivot = np.asarray(pivot, float)
    a, b = np.asarray(a, float), np.asarray(b, float)
    local = (np.asarray(points, float)[:, :2] - b) @ np.linalg.pinv(a).T
    lo, hi = local.min(axis=0), local.max(axis=0)
    for axis in (0, 1):
        reach = float(np.linalg.norm(a[:, axis]))
        if (hi[axis] - lo[axis]) * reach < min_size and reach > 1e-9:
            middle = (hi[axis] + lo[axis]) / 2
            half = min_size / (2 * reach)
            lo[axis], hi[axis] = middle - half, middle + half
    corners = np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]])
    world = corners @ a.T + b
    rotation = math.degrees(math.atan2(a[1, 0], a[0, 0]))
    return Box(world, pivot, rotation)


def handle_at(box: Box, p, grab: float, knob_offset: float, independent: bool = True) -> Handle | None:
    """The knob, corner or (when enabled) side midpoint within ``grab`` of ``p``."""
    p = np.asarray(p, float)
    if np.linalg.norm(p - box.knob(knob_offset)) <= grab:
        return "rotate"
    if (np.linalg.norm(box.corners - p, axis=1) <= grab).any():
        return "scale"
    if independent:
        middles = (
            (box.corners[0] + box.corners[1]) / 2,
            (box.corners[1] + box.corners[2]) / 2,
            (box.corners[2] + box.corners[3]) / 2,
            (box.corners[3] + box.corners[0]) / 2,
        )
        for index, middle in enumerate(middles):
            if np.linalg.norm(p - middle) <= grab:
                return "scale_y" if index in (0, 2) else "scale_x"
    return None


def nearest(points: np.ndarray, p) -> np.ndarray:
    """The row of ``points`` closest to ``p``."""
    return points[int(np.argmin(np.linalg.norm(points - np.asarray(p, float), axis=1)))]


def scale_from(pivot, start_point, point, start_scale: float, snap: bool = False) -> float:
    """Uniform scale after dragging a corner from ``start_point`` to ``point``."""
    pivot = np.asarray(pivot, float)
    d0 = float(np.linalg.norm(np.asarray(start_point, float) - pivot))
    d1 = float(np.linalg.norm(np.asarray(point, float) - pivot))
    scale = start_scale * (d1 / d0) if d0 > 1e-9 else start_scale
    if snap:
        scale = round(scale / SCALE_SNAP) * SCALE_SNAP
    return min(max(scale, SCALE_LIMITS[0]), SCALE_LIMITS[1])


def scale_axis_from(
    pivot, start_point, point, frame, axis: int, start_scale: float, snap: bool = False
) -> float:
    """Resize one local axis from a side handle, about the layer pivot."""
    pivot = np.asarray(pivot, float)
    inverse = np.linalg.pinv(np.asarray(frame, float))
    start = float((inverse @ (np.asarray(start_point, float) - pivot))[axis])
    current = float((inverse @ (np.asarray(point, float) - pivot))[axis])
    value = start_scale * current / start if abs(start) > 1e-9 else start_scale
    if snap:
        value = round(value / SCALE_SNAP) * SCALE_SNAP
    return min(max(value, SCALE_LIMITS[0]), SCALE_LIMITS[1])


def angle_delta(pivot, previous, point) -> float:
    """Signed angle in degrees from ``previous`` to ``point`` around ``pivot``, in (-180, 180].

    Summing successive deltas follows the cursor through any number of turns.
    """
    pivot = np.asarray(pivot, float)
    a = np.asarray(previous, float) - pivot
    b = np.asarray(point, float) - pivot
    if np.linalg.norm(a) < 1e-9 or np.linalg.norm(b) < 1e-9:
        return 0.0
    return math.degrees(math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1]))


def snap_angle(angle: float, snap: bool) -> float:
    return round(angle / ANGLE_SNAP) * ANGLE_SNAP if snap else angle


def _rotate(v: np.ndarray, degrees: float) -> np.ndarray:
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    return np.asarray(v, float) @ np.array([[c, s], [-s, c]])
