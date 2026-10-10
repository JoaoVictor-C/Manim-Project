"""Curved position paths between keys (P3d, ADR 0026). Pure numpy, no Manim.

A position segment from ``p0`` to ``p1`` whose keys carry tangents is the cubic
Bezier ``p0, p0 + out, p1 + in, p1``. It is walked by **arc length**: the key's
eased time ``u`` is the fraction of the length travelled, so the ease means
speed along the path as it does on straight segments (B39). An eased ``u``
outside [0, 1] continues along the end (or start) tangent by the overshoot
times the arc length.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

SAMPLES = 128  # B39: speed evenness 1.002, 1.6e-4 units off a fine table, 37 us to build
Vec = tuple[float, float]


def controls(p0: Vec, out0: Vec | None, in1: Vec | None, p1: Vec) -> tuple[float, ...]:
    """The four control points, flattened (hashable: the table cache key)."""
    a, b = np.asarray(p0, float), np.asarray(p1, float)
    c0 = a + np.asarray(out0 if out0 is not None else (0.0, 0.0), float)
    c1 = b + np.asarray(in1 if in1 is not None else (0.0, 0.0), float)
    return (*a, *c0, *c1, *b)


def bezier(points: tuple[float, ...], s) -> np.ndarray:
    p0, c0, c1, p1 = (np.array(points[i : i + 2]) for i in range(0, 8, 2))
    s = np.asarray(s, float)[..., None]
    return (1 - s) ** 3 * p0 + 3 * (1 - s) ** 2 * s * c0 + 3 * (1 - s) * s**2 * c1 + s**3 * p1


@lru_cache(maxsize=4096)
def _table(points: tuple[float, ...]) -> tuple[np.ndarray, np.ndarray]:
    """Bezier parameters and the cumulative length at each (pure: keyed by the control points)."""
    us = np.linspace(0.0, 1.0, SAMPLES)
    pts = bezier(points, us)
    lengths = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    return us, lengths


def parameter(points: tuple[float, ...], fraction: float) -> float:
    """The Bezier parameter at ``fraction`` of the arc length (fraction in [0, 1])."""
    us, lengths = _table(points)
    if lengths[-1] <= 0:
        return 0.0
    return float(np.interp(fraction * lengths[-1], lengths, us))


def length(points: tuple[float, ...]) -> float:
    return float(_table(points)[1][-1])


def point_at(p0: Vec, out0: Vec | None, in1: Vec | None, p1: Vec, u: float) -> Vec:
    """The position at eased time ``u`` on the curved segment."""
    points = controls(p0, out0, in1, p1)
    total = length(points)
    if total <= 0:
        return (float(points[0]), float(points[1]))
    if u < 0 or u > 1:  # an overshoot keeps going in the direction of travel
        end = u > 1
        direction = _end_direction(points, end)
        anchor = np.array(points[6:8] if end else points[0:2])
        travel = (u - 1) if end else u
        x, y = anchor + direction * travel * total
        return (float(x), float(y))
    x, y = bezier(points, parameter(points, u))
    return (float(x), float(y))


def _end_direction(points: tuple[float, ...], end: bool) -> np.ndarray:
    """Unit direction of travel at the start or the end of the curve."""
    p0, c0, c1, p1 = (np.array(points[i : i + 2]) for i in range(0, 8, 2))
    candidates = [p1 - c1, p1 - c0, p1 - p0] if end else [c0 - p0, c1 - p0, p1 - p0]
    for vector in candidates:
        norm = np.linalg.norm(vector)
        if norm > 1e-12:
            return vector / norm
    return np.zeros(2)


def split(p0: Vec, out0: Vec | None, in1: Vec | None, p1: Vec, fraction: float):
    """De Casteljau split at ``fraction`` of the arc length.

    Returns ``(out0', point, in_new, out_new, in1')``: the first key's new out
    tangent, the split point, the new key's in and out tangents, and the second
    key's new in tangent - together they draw exactly the same curve.
    """
    points = controls(p0, out0, in1, p1)
    s = parameter(points, fraction)
    a, b, c, d = (np.array(points[i : i + 2]) for i in range(0, 8, 2))
    ab, bc, cd = a + (b - a) * s, b + (c - b) * s, c + (d - c) * s
    abc, bcd = ab + (bc - ab) * s, bc + (cd - bc) * s
    mid = abc + (bcd - abc) * s

    def vec(v) -> Vec:
        return (float(v[0]), float(v[1]))

    return vec(ab - a), vec(mid), vec(abc - mid), vec(bcd - mid), vec(cd - d)
