"""The camera gizmo of the Scene view (ADR 0083): the rectangle the camera layer sees. No Qt.

Unity's scene view draws a 2D camera as the rectangle it sees; so does the canvas in Scene view. The
rectangle is centred on the camera's position, turned by its rotation, and as big as the video frame
divided by its scale: its height is twice the camera's size (``evaluator.camera_size``) and its width
follows the canvas's aspect. Everything is in scene units (y up, degrees counter-clockwise).

* ``camera_box`` - the rectangle as a ``gizmo.Box``, corners bottom-left, bottom-right, top-right,
  top-left, so the rotate knob sits above its top edge as on any layer;
* ``part_at`` - what a press hits: the rotate knob, a corner (the size), the camera icon or the inside
  (moving it);
* ``size_from`` - the size after dragging a corner, about the centre.
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np

from ...core.model.schema import Canvas, Transform2D
from .gizmo import Box

ICON_PX = 18.0  # the camera icon drawn at the rectangle's top-left corner, outside it
SIZE_LIMITS = (0.01, 10_000.0)

Part = Literal["rotate", "size", "icon", "move"]


def camera_box(view: Transform2D, canvas: Canvas) -> Box:
    """The rectangle the camera sees at ``view`` (its position, scale and rotation in scene units)."""
    half = np.array([canvas.frame_width, canvas.frame_height]) / (2.0 * view.scale)
    local = np.array([[-half[0], -half[1]], [half[0], -half[1]], [half[0], half[1]], [-half[0], half[1]]])
    a = math.radians(view.rotation)
    c, s = math.cos(a), math.sin(a)
    turn = np.array([[c, -s], [s, c]])
    centre = np.asarray(view.position, float)
    return Box(local @ turn.T + centre, centre, view.rotation)


def icon_point(box: Box, offset: float) -> np.ndarray:
    """Where the camera icon sits: beyond the top-left corner, along the box's up direction."""
    return box.corners[3] + box.up * offset


def part_at(box: Box, p, grab: float, knob_offset: float, icon_offset: float, selected: bool) -> Part | None:
    """The part of the gizmo under ``p``. Only the icon is live while the camera is not selected: its inside
    is the scene, where clicks select objects."""
    p = np.asarray(p, float)
    if np.linalg.norm(p - icon_point(box, icon_offset)) <= max(grab, icon_offset * 0.75):
        return "icon"
    if not selected:
        return None
    if np.linalg.norm(p - box.knob(knob_offset)) <= grab:
        return "rotate"
    if (np.linalg.norm(box.corners - p, axis=1) <= grab).any():
        return "size"
    if box.contains(p):
        return "move"
    return None


def size_from(centre, start_point, point, start_size: float) -> float:
    """The size after dragging a corner from ``start_point`` to ``point``: the rectangle grows with the
    distance from its centre (a larger size sees more: the scene looks smaller)."""
    centre = np.asarray(centre, float)
    d0 = float(np.linalg.norm(np.asarray(start_point, float) - centre))
    d1 = float(np.linalg.norm(np.asarray(point, float) - centre))
    size = start_size * d1 / d0 if d0 > 1e-9 else start_size
    return min(max(size, SIZE_LIMITS[0]), SIZE_LIMITS[1])
