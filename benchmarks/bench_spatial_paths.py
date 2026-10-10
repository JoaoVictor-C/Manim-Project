"""B39 — curved position paths between keyframes: parameterisation, cost, compatibility.

A position segment from p0 to p1 with tangents (out of p0, into p1) is the cubic
Bezier p0, p0 + out, p1 + in, p1. Two ways to walk it with the key's eased time u:

* raw: B(u) - speed along the curve depends on the handles (bunching at bends);
* arc length: B(s(u)) with s chosen so the travelled length is u * total - the
  ease alone decides the speed, as for straight segments today.

Measured: speed unevenness of raw vs arc-length walking (max/min step length at
uniform u), position error of a table with N samples against a fine reference,
cost per sample (table cached per segment), and that zero tangents give exactly
today's linear interpolation.

Run: ``python benchmarks/bench_spatial_paths.py``.
"""

from __future__ import annotations

import time

import numpy as np


def bezier(p0, c0, c1, p1, u):
    u = np.asarray(u, float)[..., None]
    return (1 - u) ** 3 * p0 + 3 * (1 - u) ** 2 * u * c0 + 3 * (1 - u) * u**2 * c1 + u**3 * p1


def table(p0, c0, c1, p1, n):
    us = np.linspace(0, 1, n)
    pts = bezier(p0, c0, c1, p1, us)
    lengths = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    return us, lengths


def by_length(p0, c0, c1, p1, u, us, lengths):
    s = np.interp(u * lengths[-1], lengths, us)
    return bezier(p0, c0, c1, p1, s)


def main() -> None:
    p0, p1 = np.array([-4.0, -1.0]), np.array([3.0, 1.5])
    c0, c1 = p0 + np.array([4.0, 5.0]), p1 + np.array([-1.0, 3.0])  # a strong S bend
    uniform = np.linspace(0, 1, 61)
    raw = bezier(p0, c0, c1, p1, uniform)
    steps_raw = np.linalg.norm(np.diff(raw, axis=0), axis=1)
    fine_us, fine_lengths = table(p0, c0, c1, p1, 20001)
    reference = by_length(p0, c0, c1, p1, uniform, fine_us, fine_lengths)
    print(f"raw walking: step lengths max/min = {steps_raw.max() / steps_raw.min():.2f}")
    for n in (16, 32, 64, 128):
        us, lengths = table(p0, c0, c1, p1, n)
        walked = by_length(p0, c0, c1, p1, uniform, us, lengths)
        steps = np.linalg.norm(np.diff(walked, axis=0), axis=1)
        error = np.abs(walked - reference).max()
        start = time.perf_counter()
        for u in np.linspace(0, 1, 2000):
            by_length(p0, c0, c1, p1, u, us, lengths)
        per = (time.perf_counter() - start) / 2000 * 1e6
        build = time.perf_counter()
        for _ in range(200):
            table(p0, c0, c1, p1, n)
        build_us = (time.perf_counter() - build) / 200 * 1e6
        print(
            f"arc-length table n={n:3d}: steps max/min {steps.max() / steps.min():.3f}, "
            f"error {error:.1e} units, {per:.1f} us/sample, table {build_us:.0f} us"
        )
    flat = bezier(p0, p0, p1, p1, uniform)  # zero tangents
    us, lengths = table(p0, p0, p1, p1, 64)
    flat_by_length = by_length(p0, p0, p1, p1, uniform, us, lengths)
    linear = p0 + (p1 - p0) * uniform[:, None]
    print(f"zero tangents: raw vs linear {np.abs(flat - linear).max():.1e} (not linear in u!), "
          f"arc length vs linear {np.abs(flat_by_length - linear).max():.1e}")


if __name__ == "__main__":
    main()
