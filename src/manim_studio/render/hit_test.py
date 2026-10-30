"""Which layers are under a point on the canvas (S3, ADR 0016).

``hit_layers(layers, point, px_per_unit)`` takes ``Evaluator.frame_layers(t)``
and a point in Manim units, and returns the ids of every layer under it,
front-most first. The optional bounds mode also treats the object's bounding
rectangle as selectable, which helps with thin or hard-to-hit objects. Rules:

* only what is drawn counts: fill or stroke alpha must exceed ``VISIBLE_ALPHA``
  (an object at the first frame of its FadeIn has full geometry and alpha 0);
* Text, Tex and MathTex hit on their bounding box, so the holes of letters
  and the gaps between them still select the text;
* images hit on their (possibly rotated) rectangle;
* other vector objects hit inside a visibly filled area (nonzero winding, as
  Cairo and ``qt_paths`` fill it) or within ``max(tolerance, half the stroke
  width)`` of a visibly stroked curve. Both use the cubics flattened into short
  segments, in numpy. (``QPainterPath.contains`` was the plan, but it reports
  points on some horizontal lines through a shape as outside, e.g. the centre
  of a Manim square — ADR 0016.)

Measured: about 0.05 ms per click on the stress scene, at most ~1 ms (B21).
"""

from __future__ import annotations

from collections.abc import Sequence

import manim as m
import numpy as np

from ..core.code.code_frame import CodeFrame

VISIBLE_ALPHA = 0.02
TOLERANCE_PX = 4.0
_TEXT_CLASSES = (m.Text, m.SingleStringMathTex)
_SAMPLES = np.linspace(0.0, 1.0, 9)  # points per cubic when measuring distance to a stroke
_BERNSTEIN = np.stack(
    [(1 - _SAMPLES) ** 3, 3 * (1 - _SAMPLES) ** 2 * _SAMPLES, 3 * (1 - _SAMPLES) * _SAMPLES**2, _SAMPLES**3],
    axis=1,
)  # (samples, 4)
_STROKE_UNITS = 0.01  # Manim draws a stroke width w as w * 0.01 frame units wide (as qt_paths does)


def hit_layers(
    layers: Sequence[tuple[str, m.Mobject]],
    point: Sequence[float],
    px_per_unit: float,
    tolerance_px: float = TOLERANCE_PX,
    select_by_bounds: bool = False,
) -> list[str]:
    """Ids of layers under ``point`` (Manim units), front-most first.

    With ``select_by_bounds``, points inside a visible object's bounds count as
    hits too. This is intentionally an interaction option: the rendered pixels
    and precise hit-testing rules are unchanged.
    """
    p = np.asarray(point, dtype=float)[:2]
    tolerance = tolerance_px / px_per_unit
    return [
        layer_id
        for layer_id, mob in reversed(layers)
        if hits(mob, p, tolerance) or (select_by_bounds and within_bounds(mob, p, tolerance))
    ]


def within_bounds(mob: m.Mobject, p: np.ndarray, tolerance: float = 0.0) -> bool:
    """Whether ``p`` lies in the visible object's rectangular selection bounds."""
    if isinstance(mob, CodeFrame):
        alpha = mob.crop.pixels[..., 3]
        if mob.opacity <= VISIBLE_ALPHA or not alpha.size:
            return False
        if float(np.max(alpha)) * mob.opacity <= VISIBLE_ALPHA * 255:
            return False
        return _quad_hit(mob.points, p)
    if isinstance(mob, m.ImageMobject):
        return _image_hit(mob, p)
    family = [
        sub
        for sub in mob.family_members_with_points()
        if isinstance(sub, m.VMobject) and (_fill_visible(sub) or _stroke_visible(sub))
    ]
    if not family:
        return False
    lo, hi = bounds(family)
    return bool((p >= lo - tolerance).all() and (p <= hi + tolerance).all())


def hits(mob: m.Mobject, p: np.ndarray, tolerance: float) -> bool:
    if isinstance(mob, CodeFrame):
        return mob.hit(p)  # a code layer: on a visible pixel of its frame (ADR 0019)
    if isinstance(mob, m.ImageMobject):
        return _image_hit(mob, p)
    family = [sub for sub in mob.family_members_with_points() if isinstance(sub, m.VMobject)]
    if not family:
        return False
    lo, hi = bounds(family)
    if (p < lo - tolerance).any() or (p > hi + tolerance).any():
        return False
    if isinstance(mob, _TEXT_CLASSES):
        return any(_fill_visible(sub) or _stroke_visible(sub) for sub in family)
    for sub in family:
        if _fill_visible(sub) and _winding(sub, p) != 0:
            return True
        if _stroke_visible(sub):
            reach = max(tolerance, sub.get_stroke_width() * _STROKE_UNITS / 2)
            if _distance_to_curves(sub, p) <= reach:
                return True
    return False


def bounds(family: Sequence[m.Mobject]) -> tuple[np.ndarray, np.ndarray]:
    points = np.concatenate([sub.points[:, :2] for sub in family])
    return points.min(axis=0), points.max(axis=0)


def _fill_visible(sub: m.VMobject) -> bool:
    alphas = sub.get_fill_opacities()
    return len(alphas) > 0 and float(np.max(alphas)) > VISIBLE_ALPHA


def _stroke_visible(sub: m.VMobject) -> bool:
    alphas = sub.get_stroke_opacities()
    return sub.get_stroke_width() > 0 and len(alphas) > 0 and float(np.max(alphas)) > VISIBLE_ALPHA


def _segments(sub: m.VMobject, closed: bool) -> tuple[np.ndarray, np.ndarray]:
    """The curves as straight segments (each cubic in 8); ``closed`` adds each subpath's closing edge."""
    points = sub.points[:, :2]
    starts, ends = [], []
    for first, last in sub.get_subpath_split_indices_from_points(sub.points, n_dims=2):
        n = (int(last) - int(first)) // 4
        if n == 0:
            continue
        controls = points[int(first) : int(first) + n * 4].reshape(n, 4, 2)
        curve = np.einsum("sk,nkd->nsd", _BERNSTEIN, controls)  # (n, samples, 2)
        starts.append(curve[:, :-1].reshape(-1, 2))
        ends.append(curve[:, 1:].reshape(-1, 2))
        if closed:  # Cairo fills an open subpath as if it were closed
            starts.append(curve[-1:, -1])
            ends.append(curve[:1, 0])
    if not starts:
        empty = np.zeros((0, 2))
        return empty, empty
    return np.concatenate(starts), np.concatenate(ends)


def _winding(sub: m.VMobject, p: np.ndarray) -> int:
    """Nonzero winding number of the filled subpaths around ``p``."""
    a, b = _segments(sub, closed=True)
    upward = (a[:, 1] <= p[1]) & (b[:, 1] > p[1])
    downward = (b[:, 1] <= p[1]) & (a[:, 1] > p[1])
    crossing = upward | downward
    if not crossing.any():
        return 0
    a, b = a[crossing], b[crossing]
    # Which side of the edge a->b the point is on; left of an upward edge counts +1.
    side = (b[:, 0] - a[:, 0]) * (p[1] - a[:, 1]) - (p[0] - a[:, 0]) * (b[:, 1] - a[:, 1])
    up = upward[crossing]
    return int(np.sum(up & (side > 0)) - np.sum(~up & (side < 0)))


def _distance_to_curves(sub: m.VMobject, p: np.ndarray) -> float:
    """Distance from ``p`` to the object's curves."""
    a, b = _segments(sub, closed=False)
    if len(a) == 0:
        return float("inf")
    ab = b - a
    length2 = (ab * ab).sum(axis=1)
    length2[length2 == 0] = 1.0
    u = np.clip(((p - a) * ab).sum(axis=1) / length2, 0.0, 1.0)
    return float(np.min(np.linalg.norm(a + ab * u[:, None] - p, axis=1)))


def _image_hit(image: m.ImageMobject, p: np.ndarray) -> bool:
    """Inside the image's rectangle (corners UL, UR, DL, DR; may be rotated) and visible."""
    if float(np.max(image.pixel_array[..., 3])) / 255.0 <= VISIBLE_ALPHA:
        return False
    return _quad_hit(image.points, p)


def _quad_hit(points: np.ndarray, p: np.ndarray) -> bool:
    """Inside the affine rectangle with corners UL, UR, DL, DR (or CodeFrame crop)."""
    ul, ur, dl = (points[i, :2] for i in (0, 1, 2))
    basis = np.column_stack([ur - ul, dl - ul])
    if abs(np.linalg.det(basis)) < 1e-12:
        return False
    a, b = np.linalg.solve(basis, p - ul)
    return 0.0 <= a <= 1.0 and 0.0 <= b <= 1.0
