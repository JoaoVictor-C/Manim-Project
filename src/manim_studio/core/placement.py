"""Where a new object goes (GP, the golden path): not on top of the others.

The first object goes to the centre of the frame, as before. A new one goes below what is
already there, else above it, else beside it (right, then left) - the first spot where it
fits inside the frame with a small gap - and to the centre when nothing fits. Boxes are the
objects' drawings as built, placed by their transforms at a time (clips are ignored: this is
about where things *are*, not how they enter).
"""

from __future__ import annotations

import numpy as np

from . import adapter
from .schema import CODE_TYPES, CONNECTOR_TYPES, TRACE_TYPES, Project, Spec

GAP = 0.3  # Manim units between a new object and the others
SKIPPED = CODE_TYPES | CONNECTOR_TYPES | TRACE_TYPES  # drawn from other layers or the whole frame

Box = tuple[np.ndarray, np.ndarray]


def drawn_box(spec: Spec) -> Box | None:
    """The box of ``spec``'s drawing as built (centred on the origin), or None."""
    if spec.type in SKIPPED:
        return None
    try:
        mob = adapter.build_mobject(spec)
    except Exception:  # a placeholder-worthy object must not stop the add
        return None
    family = mob.family_members_with_points()
    if not family:
        return None
    points = np.vstack([sub.points[:, :2] for sub in family])
    return points.min(axis=0), points.max(axis=0)


def occupied(project: Project, t: float) -> list[Box]:
    """The world boxes of the objects (roots) at ``t``, by their transforms."""
    from .evaluator import _affine, layer_transform  # the evaluator's own placement rules

    boxes = []
    for layer in project.roots():
        if layer.spec is None:
            continue
        box = drawn_box(layer.spec)
        if box is None:
            continue
        a, b = _affine(layer_transform(layer, t))
        low, high = box
        corners = np.array([[low[0], low[1]], [high[0], low[1]], [high[0], high[1]], [low[0], high[1]]])
        world = corners @ a.T + b
        boxes.append((world.min(axis=0), world.max(axis=0)))
    return boxes


def _overlaps(a: Box, b: Box) -> bool:
    return bool((a[0] < b[1]).all() and (b[0] < a[1]).all())


def place(boxes: list[Box], size, frame: Box) -> tuple[float, float]:
    """Where the centre of a new object ``size`` (w, h) goes among ``boxes`` in ``frame``."""
    half = np.asarray(size, float) / 2
    frame_low, frame_high = (np.asarray(v, float) for v in frame)

    def fits(centre) -> bool:
        box = (centre - half, centre + half)
        inside = (box[0] >= frame_low - 1e-9).all() and (box[1] <= frame_high + 1e-9).all()
        return bool(inside and not any(_overlaps(box, other) for other in boxes))

    middle = np.zeros(2)
    if fits(middle):
        return 0.0, 0.0
    low = np.min([b[0] for b in boxes], axis=0)
    high = np.max([b[1] for b in boxes], axis=0)
    for centre in (
        np.array([0.0, low[1] - GAP - half[1]]),  # below
        np.array([0.0, high[1] + GAP + half[1]]),  # above
        np.array([high[0] + GAP + half[0], 0.0]),  # right
        np.array([low[0] - GAP - half[0], 0.0]),  # left
    ):
        if fits(centre):
            return round(float(centre[0]), 3), round(float(centre[1]), 3)
    return 0.0, 0.0


def position_for(project: Project, spec: Spec, t: float) -> tuple[float, float]:
    """Where a new object built from ``spec`` goes in ``project`` (seen at ``t``)."""
    box = drawn_box(spec)
    if box is None:
        return 0.0, 0.0
    size = box[1] - box[0]
    half = np.array([project.canvas.frame_width / 2, project.canvas.frame_height / 2])
    return place(occupied(project, t), size, (-half, half))
