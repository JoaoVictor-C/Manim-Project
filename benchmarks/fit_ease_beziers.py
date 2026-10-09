"""Fit a cubic bezier to each named ease the panel offers (P2b, B27).

Prints the max vertical error over 41 curve samples and the fitted
(x1, y1, x2, y2). Re-run after a Manim upgrade to refresh
``adapter.EASE_BEZIER_FITS`` (entries over 0.025 are left out).
"""

from __future__ import annotations

import itertools
import time

import numpy as np

from manim_studio.core import adapter
from manim_studio.core.schema import Easing

S = np.linspace(0, 1, 41)
B = np.stack([3 * (1 - S) ** 2 * S, 3 * (1 - S) * S**2, S**3], 1)  # coefficients for P1, P2, P3=(1,1)


def curve(p):  # p (...,4) -> x(s), y(s)
    x = B[:, 0] * p[..., None, 0] + B[:, 1] * p[..., None, 2] + B[:, 2]
    y = B[:, 0] * p[..., None, 1] + B[:, 1] * p[..., None, 3] + B[:, 2]
    return x, y


def error(rate, p):
    x, y = curve(p)
    r = np.vectorize(rate)(np.clip(x, 0, 1))
    return np.abs(r - y).max(axis=-1)


def fit(rate):

    xs = np.linspace(0, 1, 11)
    ys = np.linspace(-0.5, 1.5, 21)
    grid = np.array(list(itertools.product(xs, ys, xs, ys)))
    errs = error(rate, grid)
    best = grid[errs.argmin()]
    e = errs.min()
    for scale in (0.05, 0.02, 0.008, 0.003):
        d = np.array(list(itertools.product(*[np.linspace(-scale, scale, 5)] * 4)))
        cand = best + d
        cand[:, 0] = cand[:, 0].clip(0, 1)
        cand[:, 2] = cand[:, 2].clip(0, 1)
        errs = error(rate, cand)
        if errs.min() < e:
            best, e = cand[errs.argmin()], errs.min()
    return best, e


t0 = time.time()
for name in adapter.EASE_NAMES:
    rate = adapter.rate_func(Easing(name=name))
    p, e = fit(rate)
    print(f"{name:<18} max error {e:.4f}  bezier {np.round(p, 3).tolist()}")
print(f"total {time.time() - t0:.1f} s")
