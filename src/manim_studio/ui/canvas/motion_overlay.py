"""The selected layer's motion path on the canvas (P3d, ADR 0026). Geometry only, no Qt.

``build`` turns a layer's position keys into world-space shapes: the path
through the keys (curved where tangents are set), a point per key and the
key's tangent handles. ``hit`` says which handle or key is under the cursor -
handles first, they sit on top. Position values map to world through the
layer's position frame ``(a, b)``: ``world = a @ value + b``.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import numpy as np

from ...core.model import motion_paths
from ...core.model.schema import Layer

SAMPLES_PER_SEGMENT = 32
SMOOTH_DEGREES = 1.0  # handles this close to opposite count as one smooth key


@dataclass(frozen=True)
class MotionKey:
    t: float
    point: np.ndarray  # world
    in_handle: np.ndarray | None  # world position of the handle's end
    out_handle: np.ndarray | None
    smooth: bool


@dataclass(frozen=True)
class MotionPath:
    layer_id: str
    keys: tuple[MotionKey, ...]
    polyline: np.ndarray  # (N, 2) world
    to_world: np.ndarray  # the linear part a, for tangents
    to_track: np.ndarray  # its inverse: world move -> change of a value or tangent


def is_smooth(in_tangent, out_tangent) -> bool:
    if in_tangent is None or out_tangent is None:
        return False
    a, b = np.asarray(in_tangent, float), np.asarray(out_tangent, float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-12 or nb < 1e-12:
        return False
    cos = float(np.dot(a, b) / (na * nb))
    return cos <= math.cos(math.radians(180 - SMOOTH_DEGREES))


def build(layer: Layer, a: np.ndarray, b: np.ndarray) -> MotionPath | None:
    track = layer.tracks.get("position") or []
    if len(track) < 2:
        return None

    def world(value) -> np.ndarray:
        return a @ np.asarray(value, float) + b

    keys = []
    for key in track:
        point = world(key.value)
        handle_in = point + a @ np.asarray(key.in_tangent) if key.in_tangent is not None else None
        handle_out = point + a @ np.asarray(key.out_tangent) if key.out_tangent is not None else None
        keys.append(
            MotionKey(key.t, point, handle_in, handle_out, is_smooth(key.in_tangent, key.out_tangent))
        )
    pieces = []
    for k0, k1 in itertools.pairwise(track):
        if k0.out_tangent is not None or k1.in_tangent is not None:
            controls = motion_paths.controls(k0.value, k0.out_tangent, k1.in_tangent, k1.value)
            local = motion_paths.bezier(controls, np.linspace(0, 1, SAMPLES_PER_SEGMENT))
        else:
            local = np.array([k0.value, k1.value], float)
        pieces.append(local @ a.T + b)
    return MotionPath(layer.id, tuple(keys), np.vstack(pieces), a, np.linalg.pinv(a))


def hit(path: MotionPath, point, grab: float) -> tuple[str, int] | None:
    """``("in" | "out" | "key", key index)`` within ``grab`` of ``point``; handles win."""
    point = np.asarray(point, float)
    for index, key in enumerate(path.keys):
        for side, handle in (("out", key.out_handle), ("in", key.in_handle)):
            if handle is not None and np.linalg.norm(handle - point) <= grab:
                return side, index
    for index, key in enumerate(path.keys):
        if np.linalg.norm(key.point - point) <= grab:
            return "key", index
    return None


def aligned(dragged: np.ndarray, opposite) -> tuple[float, float] | None:
    """The opposite handle of a smooth key after one is dragged: opposite direction, own length."""
    if opposite is None:
        return None
    norm = np.linalg.norm(dragged)
    if norm < 1e-12:
        return tuple(opposite)
    unit = dragged / norm
    length = float(np.linalg.norm(opposite))
    return (float(-unit[0] * length), float(-unit[1] * length))
