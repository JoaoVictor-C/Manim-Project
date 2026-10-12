"""Arrange (P6c.2, ADR 0043): align and distribute boxes. No Qt.

Boxes are axis-aligned ``(low, high)`` pairs in Manim units, one per selected
object (its drawing at the playhead). Each function returns how far to move each
object (world units); objects that need not move are left out.

* ``align`` - several objects line up on their common box's edge or centre; a
  single object lines up on the video frame's;
* ``distribute`` - three or more objects get equal gaps between them along an
  axis, the outermost two staying where they are.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

Alignment = Literal["left", "centre", "right", "bottom", "middle", "top"]
ALIGNMENTS: dict[Alignment, tuple[int, str]] = {  # the axis and which line of the box
    "left": (0, "low"),
    "centre": (0, "middle"),
    "right": (0, "high"),
    "bottom": (1, "low"),
    "middle": (1, "middle"),
    "top": (1, "high"),
}
EPSILON = 1e-9

Box = tuple[np.ndarray, np.ndarray]


def _line(box: Box, which: str, axis: int) -> float:
    low, high = box
    if which == "low":
        return float(low[axis])
    if which == "high":
        return float(high[axis])
    return float(low[axis] + high[axis]) / 2


def common_box(boxes) -> Box:
    lows = np.array([np.asarray(low, float)[:2] for low, _ in boxes])
    highs = np.array([np.asarray(high, float)[:2] for _, high in boxes])
    return lows.min(axis=0), highs.max(axis=0)


def align(boxes: dict[str, Box], how: Alignment, frame: Box | None = None) -> dict[str, np.ndarray]:
    """Moves lining every box up on ``how`` of their common box (of ``frame`` for one box)."""
    if not boxes:
        return {}
    axis, which = ALIGNMENTS[how]
    if len(boxes) == 1:
        if frame is None:
            return {}
        target = _line(frame, which, axis)
    else:
        target = _line(common_box(boxes.values()), which, axis)
    moves = {}
    for key, box in boxes.items():
        move = target - _line(box, which, axis)
        if abs(move) > EPSILON:
            delta = np.zeros(2)
            delta[axis] = move
            moves[key] = delta
    return moves


def distribute(boxes: dict[str, Box], axis: int) -> dict[str, np.ndarray]:
    """Moves giving three or more boxes equal gaps along ``axis`` (0: x, 1: y), in the order of
    their centres; the first and the last stay. Fewer than three: nothing moves."""
    if len(boxes) < 3:
        return {}
    order = sorted(boxes, key=lambda k: (_line(boxes[k], "middle", axis), k))
    sizes = {k: float(boxes[k][1][axis] - boxes[k][0][axis]) for k in order}
    start = float(boxes[order[0]][0][axis])
    end = float(boxes[order[-1]][1][axis])
    gap = (end - start - sum(sizes.values())) / (len(order) - 1)
    moves, edge = {}, start
    for key in order:
        move = edge - float(boxes[key][0][axis])
        if abs(move) > EPSILON:
            delta = np.zeros(2)
            delta[axis] = move
            moves[key] = delta
        edge += sizes[key] + gap
    return moves
