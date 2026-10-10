"""B34 — the anchor (pivot) model and its compensation, checked numerically.

Convention (ADR 0021): world(p) = A (p - P) + P + position, A = R(rotation) S(scale),
P = anchor (objects) or rest centre + anchor (parts).

Checks, over random transforms:

1. anchor (0, 0) is the old transform A p + position;
2. moving the anchor from a to a' and adding (I - A)(a - a') to position leaves
   the image of every point unchanged;
3. the world pivot a + position stays where it is under any rotation and scale;
4. with keyed rotation, the same rigid offset applied at one time is wrong at
   another (the documented limit).

Run: ``python benchmarks/bench_anchor.py``.
"""

from __future__ import annotations

import math

import numpy as np

CASES = 1000


def linear(rotation: float, scale: float) -> np.ndarray:
    a = math.radians(rotation)
    return scale * np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])


def world(points: np.ndarray, rotation: float, scale: float, position, anchor) -> np.ndarray:
    a = linear(rotation, scale)
    anchor = np.asarray(anchor, float)
    return (points - anchor) @ a.T + anchor + np.asarray(position, float)


def main() -> None:
    rng = np.random.default_rng(34)
    worst = {"identity": 0.0, "compensated": 0.0, "pivot": 0.0}
    for _ in range(CASES):
        points = rng.normal(size=(20, 2)) * 3
        rotation, scale = rng.uniform(-360, 360), rng.uniform(0.1, 4)
        position, a0, a1 = rng.normal(size=(3, 2)) * 2
        old = points @ linear(rotation, scale).T + position
        worst["identity"] = max(worst["identity"], np.abs(world(points, rotation, scale, position, (0, 0)) - old).max())
        before = world(points, rotation, scale, position, a0)
        moved = position + (np.eye(2) - linear(rotation, scale)) @ (a0 - a1)
        after = world(points, rotation, scale, moved, a1)
        worst["compensated"] = max(worst["compensated"], np.abs(after - before).max())
        other = rng.uniform(-360, 360), rng.uniform(0.1, 4)
        pivot = world(a1[None, :], *other, moved, a1)[0]
        worst["pivot"] = max(worst["pivot"], np.abs(pivot - (a1 + moved)).max())
    for name, value in worst.items():
        print(f"{name:12s} max error {value:.1e}")

    # The limit: rotation keyed 0 -> 90 over t in [0, 2]; the anchor moves at t = 1.
    points = np.array([[0.0, 0.0], [0.0, -3.0]])
    a0, a1 = np.array([0.0, -1.5]), np.zeros(2)
    offset = (np.eye(2) - linear(45, 1)) @ (a0 - a1)
    at_1 = np.abs(world(points, 45, 1, offset, a1) - world(points, 45, 1, (0, 0), a0)).max()
    at_0 = np.abs(world(points, 0, 1, offset, a1) - world(points, 0, 1, (0, 0), a0)).max()
    print(f"keyed rotation: exact at the edit time ({at_1:.1e}), off by {at_0:.2f} units at t = 0")


if __name__ == "__main__":
    main()
