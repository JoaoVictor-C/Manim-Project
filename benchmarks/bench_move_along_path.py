"""B38 — MoveAlongPath: exactness under scrubbing, cost per frame, what it moves.

Probes for P3c (motion along another layer's shape):

1. ``MoveAlongPath(dot, path)`` played in order vs scrubbed in a shuffled order,
   on a circle, a line and a 400-sample graph (max pixel diff);
2. cost of one ``interpolate`` per path (``point_from_proportion`` measures the
   path every call);
3. what it moves: the mobject's centre lands on the path point (checked), and
   whether a precomputed arc-length table makes a frame cheaper while giving the
   same point.

Run: ``python benchmarks/bench_move_along_path.py``.
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

import manim as m
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from manim_studio.core import adapter
from manim_studio.core.schema import Spec
from manim_studio.render.cairo_export import make_camera, render_frame
from support import CANVAS, FRAMES


def paths() -> dict[str, m.VMobject]:
    graph = adapter.build_child(Spec(type="Axes"), Spec(type="Graph", params={"expression": "sin(x)"}))
    return {"circle": m.Circle(radius=2), "line": m.Line(m.LEFT * 3, m.RIGHT * 3 + m.UP), "graph": graph}


def scrub_diff(path: m.VMobject) -> int:
    camera = make_camera(CANVAS)

    def make():
        anim = m.MoveAlongPath(m.Dot(radius=0.2, color=m.YELLOW), path)
        anim.begin()
        return anim

    played = make()
    reference = []
    for t in FRAMES:
        played.interpolate(t)
        reference.append(render_frame(camera, [path, played.mobject]))
    scrub = make()
    worst = 0
    for i in random.Random(0).sample(range(len(FRAMES)), len(FRAMES)):
        scrub.interpolate(FRAMES[i])
        worst = max(
            worst, int(np.abs(render_frame(camera, [path, scrub.mobject]).astype(int) - reference[i]).max())
        )
    return worst


def cost_ms(path: m.VMobject) -> float:
    anim = m.MoveAlongPath(m.Dot(), path)
    anim.begin()
    start = time.perf_counter()
    for i in range(200):
        anim.interpolate(i / 199)
    return (time.perf_counter() - start) / 200 * 1000


def table_point(path: m.VMobject):
    """Arc-length table once; then a frame is a search + one bezier evaluation."""
    curves = [path.get_nth_curve_function(i) for i in range(path.get_num_curves())]
    lengths = np.array([path.get_nth_curve_length(i) for i in range(path.get_num_curves())])
    cumulative = np.concatenate([[0], np.cumsum(lengths)])
    total = cumulative[-1]

    def point(alpha: float) -> np.ndarray:
        target = alpha * total
        i = min(int(np.searchsorted(cumulative, target, side="right")) - 1, len(curves) - 1)
        residue = (target - cumulative[i]) / lengths[i] if lengths[i] > 0 else 0.0
        return curves[i](residue)

    return point


def main() -> None:
    adapter.configure(Path(__file__).resolve().parents[1] / ".cache" / "manim")
    for name, path in paths().items():
        dot = m.Dot()
        anim = m.MoveAlongPath(dot, path, rate_func=m.linear)  # alpha = proportion
        anim.begin()
        anim.interpolate(0.37)
        on_path = np.abs(dot.get_center() - path.point_from_proportion(0.37)).max()
        point = table_point(path)
        start = time.perf_counter()
        for i in range(200):
            point(i / 199)
        table_ms = (time.perf_counter() - start) / 200 * 1000
        table_diff = max(
            np.abs(point(a) - path.point_from_proportion(a)).max() for a in np.linspace(0, 1, 50)
        )
        print(
            f"{name:7s} curves {path.get_num_curves():4d}  scrub diff {scrub_diff(path)}  "
            f"interpolate {cost_ms(path):6.2f} ms  table {table_ms:5.3f} ms (max diff {table_diff:.1e})  "
            f"centre on path {on_path:.1e}"
        )


if __name__ == "__main__":
    main()
