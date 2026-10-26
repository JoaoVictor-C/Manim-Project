"""B42 — objects on axes: build cost and drawing clips under scrubbing.

Probes for P3h (more child objects of Axes): a dot at axes coordinates, the
area under a graph (and between two), Riemann rectangles, axis labels and a
graph label, built with Manim's own Axes helpers on the editor's axes and
graph (``adapter.build_child``):

1. build time (cold, then again), leaf count;
2. Create, FadeIn and DrawBorderThenFill played in order vs scrubbed in a
   shuffled order (max pixel diff) and whether the drawing is visible.

Run: ``python benchmarks/bench_axes_objects.py``.
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

import manim as m
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from manim_studio.core.engine import adapter
from manim_studio.core.model.schema import Spec
from manim_studio.render.cairo_export import make_camera, render_frame
from support import CANVAS, FRAMES

AXES = Spec(type="Axes")


def builders(axes: m.Axes, sine: m.VMobject, parabola: m.VMobject) -> dict:
    return {
        "dot": lambda: m.Dot(axes.c2p(1.0, 0.5), radius=0.08),
        "area": lambda: axes.get_area(sine, x_range=(0.0, 3.0), color=m.BLUE, opacity=0.5),
        "area between": lambda: axes.get_area(sine, x_range=(-2.0, 2.0), bounded_graph=parabola, opacity=0.5),
        "riemann (dx 0.25)": lambda: axes.get_riemann_rectangles(sine, x_range=(0.0, 3.0), dx=0.25),
        "axis labels": lambda: axes.get_axis_labels(m.MathTex("x"), m.MathTex("y")),
        "graph label": lambda: axes.get_graph_label(sine, m.MathTex(r"\\sin x"), x_val=2.0),
    }


def scrub(mob: m.Mobject, cls) -> tuple[int, int]:
    camera = make_camera(CANVAS)
    played = cls(mob.copy())
    played.begin()
    reference = []
    for t in FRAMES:
        played.interpolate(t)
        reference.append(render_frame(camera, [played.mobject]))
    scrubbed = cls(mob.copy())
    scrubbed.begin()
    worst = 0
    for i in random.Random(0).sample(range(len(FRAMES)), len(FRAMES)):
        scrubbed.interpolate(FRAMES[i])
        diff = np.abs(render_frame(camera, [scrubbed.mobject]).astype(int) - reference[i]).max()
        worst = max(worst, int(diff))
    blank = render_frame(camera, [])
    return worst, int(np.abs(reference[-1].astype(int) - blank.astype(int)).max())


def main() -> None:
    adapter.configure(Path(__file__).resolve().parents[1] / ".cache" / "manim")
    axes = adapter.build_mobject(AXES)
    sine = adapter.build_child(AXES, Spec(type="Graph", params={"expression": "sin(x)"}))
    parabola = adapter.build_child(AXES, Spec(type="Graph", params={"expression": "x**2/10 - 1"}))
    # Manim's helpers read a graph's function (x -> point) and underlying function (x -> y).
    for graph, f in ((sine, np.sin), (parabola, lambda x: x**2 / 10 - 1)):
        graph.underlying_function = f
        graph.function = lambda x, f=f: axes.c2p(x, f(x))
        graph.t_min, graph.t_max = -5.0, 5.0
    for name, build in builders(axes, sine, parabola).items():
        start = time.perf_counter()
        mob = build()
        cold = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        build()
        again = (time.perf_counter() - start) * 1000
        results = []
        for cls in (m.Create, m.FadeIn, m.DrawBorderThenFill):
            try:
                worst, visible = scrub(mob, cls)
                results.append(f"{cls.__name__} {worst}/{visible}")
            except Exception as exc:
                results.append(f"{cls.__name__} error {type(exc).__name__}")
        leaves = len(mob.family_members_with_points())
        print(
            f"{name:18s} build {cold:6.1f} ms (again {again:5.1f}), {leaves:3d} leaves; scrub diff/visible: "
            + ", ".join(results)
        )


if __name__ == "__main__":
    main()
