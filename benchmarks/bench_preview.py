"""Phase 0 preview benchmark: can scrubbing stay under 33 ms/frame?

Stress scene from DESIGN.md: 20 MathTex layers, 3 concurrent Write clips,
10 keyframed layers, rendered at 960x540. Reports per-stage timings.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

from PySide6.QtGui import QGuiApplication

from manim_studio.core import adapter
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Canvas, Clip, Keyframe, Layer, Project, Spec, Transform2D
from manim_studio.render import qt_paths
from manim_studio.render.cairo_export import make_camera, render_frame

ROOT = Path(__file__).resolve().parent.parent  # Manim is configured in main(): tests import this module

FORMULAS = [
    r"e^{i\pi}+1=0",
    r"\int_0^1 x^2\,dx=\tfrac13",
    r"a^2+b^2=c^2",
    r"\sum_{n=1}^\infty \frac1{n^2}=\frac{\pi^2}6",
    r"\nabla\cdot E=\frac{\rho}{\varepsilon_0}",
    r"F=ma",
    r"\det(A-\lambda I)=0",
    r"\lim_{x\to0}\frac{\sin x}x=1",
    r"E=mc^2",
    r"\binom{n}{k}=\frac{n!}{k!(n-k)!}",
]


def stress_project() -> Project:
    canvas = Canvas(width_px=960, height_px=540, fps=30, duration=4.0)
    layers = []
    for i in range(20):
        col, row = i % 4, i // 4
        tracks = {}
        if i % 2 == 0:  # 10 keyframed layers
            tracks = {
                "position": [
                    Keyframe(t=0, value=(-5 + col * 3.3, 3 - row * 1.5)),
                    Keyframe(t=4, value=(-4.5 + col * 3.3, 2.6 - row * 1.5)),
                ],
                "rotation": [Keyframe(t=0, value=0.0), Keyframe(t=4, value=10.0)],
            }
        clips = [Clip(id=f"w{i}", kind="Write", start=0.0, duration=3.0)] if i < 3 else []
        layers.append(
            Layer(
                id=f"l{i}",
                spec=Spec(type="MathTex", params={"text": FORMULAS[i % len(FORMULAS)], "font_size": 30}),
                base=Transform2D(position=(-5 + col * 3.3, 3 - row * 1.5)),
                tracks=tracks,
                clips=clips,
            )
        )
    return Project(canvas=canvas, layers=layers)


def timed(fn, *args):
    start = time.perf_counter()
    result = fn(*args)
    return result, (time.perf_counter() - start) * 1000


def report(name: str, samples: list[float]) -> None:
    p90 = sorted(samples)[int(len(samples) * 0.9)]
    print(f"{name:<28} median {statistics.median(samples):7.1f} ms   p90 {p90:7.1f} ms")


def main() -> None:
    adapter.configure(ROOT / ".cache" / "manim")
    app = QGuiApplication(sys.argv)  # noqa: F841 - QPainter needs an application
    project = stress_project()
    evaluator = Evaluator(project)
    camera = make_camera(project.canvas)
    w, h = project.canvas.width_px, project.canvas.height_px

    print("warm-up (LaTeX compile, first build)...")
    evaluator.frame(0.0)

    times = [i / 30 for i in range(0, 120, 3)]
    eval_ms, qt_ms, cairo_ms = [], [], []
    for t in times:
        mobs, ms = timed(evaluator.frame, t)
        eval_ms.append(ms)
        _, ms = timed(qt_paths.render_image, project.canvas, mobs, w, h)
        qt_ms.append(ms)
        _, ms = timed(render_frame, camera, mobs)
        cairo_ms.append(ms)

    report("evaluate (Manim state)", eval_ms)
    report("draw: QPainter preview", qt_ms)
    report("draw: Cairo (export path)", cairo_ms)
    report("total preview frame", [a + b for a, b in zip(eval_ms, qt_ms, strict=True)])


if __name__ == "__main__":
    main()
