"""Drag-step cost through the edit API (ADR 0013, S1 plan).

Each step = ``edits.move_clip`` + ``Evaluator.apply`` + evaluate + Cairo render at
960x540, on the stress scene plus a morph between two MathTex layers.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

from bench_preview import stress_project
from manim_studio.core.editing import edits
from manim_studio.core.engine import adapter
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Clip, Keyframe, Layer, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame

ROOT = Path(__file__).resolve().parent.parent
adapter.configure(ROOT / ".cache" / "manim")

EQ_A = Spec(type="MathTex", params={"text": r"\sum_{n=1}^\infty \frac1{n^2}=\frac{\pi^2}6", "font_size": 48})
EQ_B = Spec(type="MathTex", params={"text": r"\int_0^1 x^2\,dx=\tfrac13", "font_size": 48})


def scene(keyframed_source: bool) -> Project:
    base = stress_project()
    tracks = {}
    if keyframed_source:
        tracks = {"position": [Keyframe(t=0, value=(-3.0, 0.0)), Keyframe(t=1.0, value=(0.0, 0.0))]}
    layers = [
        *base.layers,
        Layer(
            id="ma",
            spec=EQ_A,
            tracks=tracks,
            clips=[Clip(id="m", kind="TransformMatchingShapes", start=2.0, duration=1.0, to_layer="mb")],
        ),
        Layer(id="mb", spec=EQ_B, base=Transform2D(position=(0, -2.5))),
    ]
    return Project(canvas=base.canvas, layers=layers)


def drag(project: Project, layer_id: str, clip_id: str, starts: list[float], playhead_offset: float) -> float:
    evaluator, camera = Evaluator(project), make_camera(project.canvas)
    render_frame(camera, evaluator.frame(starts[0] + playhead_offset))  # warm
    samples = []
    for start in starts:
        t0 = time.perf_counter()
        edit = edits.move_clip(project, layer_id, clip_id, start)
        evaluator.apply(edit)
        render_frame(camera, evaluator.frame(start + playhead_offset))
        samples.append((time.perf_counter() - t0) * 1000)
        project = edit.project
    return statistics.median(samples[1:])


def main() -> None:
    steps = [round(0.02 * i, 2) for i in range(12)]
    print(f"Write clip drag            {drag(scene(False), 'l1', 'w1', steps, 1.5):6.1f} ms/step")
    morph = [2.0 + s for s in steps[:8]]
    print(f"morph drag, static         {drag(scene(False), 'ma', 'm', morph, 0.5):6.1f} ms/step")
    print(f"morph drag, settled keys   {drag(scene(True), 'ma', 'm', morph, 0.5):6.1f} ms/step")
    mid = [0.3 + s for s in steps[:8]]
    print(f"morph drag, mid-motion     {drag(scene(True), 'ma', 'm', mid, 0.5):6.1f} ms/step")


if __name__ == "__main__":
    main()
