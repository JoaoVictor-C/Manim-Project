"""Part layers (B29): frame cost of an object with parts vs. the same object without.

``a^2 + b^2 = c^2`` at 1280x720@30 with Write; the tree adds Split terms, an
Indicate, a FadeOut and a keyed move on three parts. Caches are warmed by one
pass, then 120 frames are evaluated, and evaluated + rendered.
"""

from __future__ import annotations

import time
from pathlib import Path

from manim_studio.core.editing import edits
from manim_studio.core.engine import adapter
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model import parts
from manim_studio.core.model.schema import Canvas, Clip, Keyframe, Layer, Project, Spec
from manim_studio.render.cairo_export import make_camera, render_frame

adapter.configure(Path(__file__).resolve().parent.parent / ".cache" / "manim")


def main() -> None:
    canvas = Canvas(width_px=1280, height_px=720, fps=30, duration=4.0)
    text = r"a^2 + b^2 = c^2"
    root = Layer(
        id="eq",
        spec=Spec(type="MathTex", params={"text": text, "font_size": 96}),
        clips=[Clip(id="w", kind="Write", start=0, duration=1)],
    )
    plain = Project(canvas=canvas, layers=[root])
    tree = edits.add_parts(plain, "eq", parts.split_terms(text)).project
    tree = edits.add_clip(tree, "part-2", "Indicate", 1.0, 1.0).project
    tree = edits.add_clip(tree, "part-3", "FadeOut", 1.5, 1.0).project
    move = [Keyframe(t=1, value=(0, 0)), Keyframe(t=3, value=(0, 1))]
    tree = edits.update_layer(tree, "part-1", tracks={"position": move}).project
    camera = make_camera(canvas)
    times = [i / canvas.fps for i in range(120)]
    for label, project in (("plain", plain), ("tree", tree)):
        evaluator = Evaluator(project)
        for t in times:
            evaluator.frame(t)
        t0 = time.perf_counter()
        for t in times:
            evaluator.frame(t)
        evaluate_ms = (time.perf_counter() - t0) * 1000 / len(times)
        t0 = time.perf_counter()
        for t in times:
            render_frame(camera, evaluator.frame(t))
        total_ms = (time.perf_counter() - t0) * 1000 / len(times)
        print(f"{label}: evaluate {evaluate_ms:.2f} ms/frame, evaluate + render {total_ms:.2f} ms/frame")


if __name__ == "__main__":
    main()
