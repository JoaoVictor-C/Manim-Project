"""B46 — simulated layers: what Manim's TracedPath draws on each frame, and what replay costs.

1. Manim's own play loop with a TracedPath following a dot (two plays and a
   wait): the trace on every rendered frame, compared with "a polyline through
   the dot's centre on every frame so far" (duplicates dropped).
2. Dissipating traces: how many points Manim keeps.
3. Costs: a traced point per frame, building and drawing a long trace, a
   simulation step, a drawing, a checkpoint copy.

Run: ``python benchmarks/bench_simulation.py``.
"""

from __future__ import annotations

import copy
import math
import statistics
import time

import manim as m
import numpy as np


def manim_frames(dissipating_time: float | None = None) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """(trace points, dot centre) on every frame Manim renders."""
    traces: list[np.ndarray] = []
    centres: list[np.ndarray] = []

    class Traced(m.Scene):
        def construct(self) -> None:
            dot = m.Dot(m.LEFT * 3)
            trace = m.TracedPath(dot.get_center, dissipating_time=dissipating_time)
            self.add(trace, dot)

            def render(scene, t, moving):
                traces.append(trace.points.copy())
                centres.append(dot.get_center().copy())

            self.renderer.render = render
            self.play(dot.animate.shift(m.RIGHT * 3 + m.UP * 2), run_time=1.0, rate_func=m.linear)
            self.play(m.MoveAlongPath(dot, m.Circle(radius=1.5).move_to(dot.get_center() + m.DOWN * 1.5)))
            self.wait(0.5)

    with m.tempconfig({"frame_rate": 10, "disable_caching": True, "dry_run": True}):
        Traced().render()
    return traces, centres


def corners(points: np.ndarray) -> np.ndarray:
    """Distinct consecutive points (a polyline drawn with add_line_to repeats its corners)."""
    if not len(points):
        return points
    keep = [0] + [i for i in range(1, len(points)) if not np.allclose(points[i], points[i - 1])]
    return points[keep]


def anchors(trace: np.ndarray) -> np.ndarray:
    """A trace's corners: the start and end of each of its curves."""
    return corners(np.vstack([trace[0::4], trace[-1:]])) if len(trace) else trace


def compare() -> None:
    traces, centres = manim_frames()
    same = 0
    for k, trace in enumerate(traces):
        ours, theirs = corners(np.array(centres[: k + 1])), anchors(trace)
        if theirs.shape == ours.shape and np.allclose(theirs, ours):
            same += 1
        elif same == k:
            print(f"  first difference at frame {k}: Manim {len(theirs)} corners, ours {len(ours)}")
    print(
        f"frames rendered by Manim: {len(traces)}; trace == polyline through the centre on frames 0..k: "
        f"{same}/{len(traces)}"
    )
    for seconds in (0.3, 1.0):
        traces, centres = manim_frames(seconds)
        kept = [len(anchors(t)) for t in traces]
        print(f"dissipating_time={seconds}: corners kept per frame {kept[:3]}...{kept[-8:]} (fps 10)")


def costs() -> None:
    from manim_studio.core import adapter
    from manim_studio.core.evaluator import Evaluator
    from manim_studio.core.schema import Canvas, Clip, Keyframe, Layer, Project, Spec
    from manim_studio.render.cairo_export import make_camera, render_frame

    canvas = Canvas(width_px=1280, height_px=720, fps=30, duration=10.0)
    ring = Layer(id="ring", spec=Spec(type="Circle", params={"radius": 2.5}))
    dot = Layer(
        id="dot",
        spec=Spec(type="Dot"),
        clips=[Clip(id="go", kind="MoveAlongPath", start=0.0, duration=10.0, params={"path": "ring"})],
        tracks={"rotation": [Keyframe(t=0, value=0.0), Keyframe(t=10, value=90.0)]},
    )
    project = Project(canvas=canvas, layers=[ring, dot])
    evaluator = Evaluator(project)
    times = [i / 30 for i in range(300)]
    evaluator.frame(0.0)
    start = time.perf_counter()
    points = []
    for t in times:
        local = evaluator._layer_at(dot, t)  # world mobject (probe: the centre is what is traced)
        points.append(local.get_center().copy())
    per_point = (time.perf_counter() - start) * 1000 / len(times)
    start = time.perf_counter()
    trace = m.VMobject(stroke_width=2).set_points_as_corners(np.array(points))
    build = (time.perf_counter() - start) * 1000
    camera = make_camera(canvas)
    samples = []
    for _ in range(5):
        start = time.perf_counter()
        render_frame(camera, [trace])
        samples.append((time.perf_counter() - start) * 1000)
    print(
        f"traced point (evaluate the target at a frame): {per_point:.2f} ms; trace of 300 corners: "
        f"build {build:.2f} ms, draw {statistics.median(samples):.1f} ms at 1280x720 "
        f"({adapter.MANIM_VERSION})"
    )

    def step(state, dt):  # a damped pendulum, RK4 (what a plugin simulation looks like)
        def f(theta, omega):
            return omega, -9.81 / 2.0 * math.sin(theta) - 0.1 * omega

        theta, omega = state
        k1 = f(theta, omega)
        k2 = f(theta + dt / 2 * k1[0], omega + dt / 2 * k1[1])
        k3 = f(theta + dt / 2 * k2[0], omega + dt / 2 * k2[1])
        k4 = f(theta + dt * k3[0], omega + dt * k3[1])
        return (
            theta + dt / 6 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0]),
            omega + dt / 6 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1]),
        )

    def draw(state):
        tip = 2.0 * np.array([math.sin(state[0]), -math.cos(state[0]), 0.0])
        return m.VGroup(m.Line(m.ORIGIN, tip), m.Circle(radius=0.2).move_to(tip).set_fill(opacity=1))

    state = (1.0, 0.0)
    start = time.perf_counter()
    for _ in range(3000):
        state = step(state, 1 / 30)
    per_step = (time.perf_counter() - start) * 1000 / 3000
    start = time.perf_counter()
    for _ in range(50):
        draw(state)
    per_draw = (time.perf_counter() - start) * 1000 / 50
    big = {"particles": np.zeros((2000, 4))}
    start = time.perf_counter()
    for _ in range(100):
        copy.deepcopy(big)
    per_copy = (time.perf_counter() - start) * 1000 / 100
    print(
        f"pendulum RK4 step {per_step * 1000:.1f} us; drawing {per_draw:.2f} ms; "
        f"checkpoint copy of 2000 particles {per_copy:.3f} ms"
    )
    for every in (15, 30, 60):
        print(
            f"  checkpoint every {every} frames: worst seek replays {every - 1} steps "
            f"({(every - 1) * per_step:.2f} ms for the pendulum)"
        )


if __name__ == "__main__":
    compare()
    costs()
