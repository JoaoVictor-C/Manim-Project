"""B60 - canvas interaction: what live parameter handles and snapping guides cost.

1. A parameter handle drag edits the spec on every mouse move (a rectangle's width,
   a line's end, a circle's radius, a text's font size): the edit, the evaluator's
   invalidation and rebuild, and the frame, per move.
2. Snapping guides while moving an object: gathering the world boxes of every other
   object at the playhead and finding the nearest edge/centre within a radius.
3. Selecting several objects: moving 20 objects as one edit.

Run: ``python benchmarks/bench_handles.py``.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import numpy as np

from manim_studio.core.editing import edits
from manim_studio.core.engine import adapter
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame

ROOT = Path(__file__).resolve().parents[1]


def timed(step, repeat=30) -> float:
    samples = []
    for i in range(repeat):
        start = time.perf_counter()
        step(i)
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def main() -> None:
    adapter.configure(ROOT / ".cache" / "manim")
    layers = [
        Layer(
            id=f"s{i}",
            spec=Spec(type="Square"),
            base=Transform2D(position=(-6 + (i % 10) * 1.3, -3 + (i // 10) * 2.0)),
        )
        for i in range(20)
    ]
    layers += [
        Layer(id="r", spec=Spec(type="Rectangle", params={"width": 3.0, "height": 1.5})),
        Layer(id="l", spec=Spec(type="Line", params={"start": [-2, 0], "end": [2, 1]})),
        Layer(id="c", spec=Spec(type="Circle", params={"radius": 1.0})),
        Layer(id="t", spec=Spec(type="Text", params={"text": "Handles", "font_size": 48})),
    ]
    project = Project(canvas=Canvas(width_px=960, height_px=540), layers=layers)
    evaluator = Evaluator(project)
    camera = make_camera(project.canvas)
    render_frame(camera, evaluator.frame(0.0))
    state = {"project": project}

    def drag(layer_id, param, value_of):
        def step(i):
            layer = state["project"].layer(layer_id)
            spec = layer.spec.model_copy(update={"params": {**layer.spec.params, param: value_of(i)}})
            edit = edits.update_layer(state["project"], layer_id, spec=spec)
            evaluator.apply(edit)
            state["project"] = edit.project
            render_frame(camera, evaluator.frame(0.0))

        return step

    print(f"rectangle width per move: {timed(drag('r', 'width', lambda i: 3.0 + i * 0.01)):.1f} ms")
    print(f"line end per move: {timed(drag('l', 'end', lambda i: [2 + i * 0.01, 1])):.1f} ms")
    print(f"circle radius per move: {timed(drag('c', 'radius', lambda i: 1 + i * 0.01)):.1f} ms")
    text_ms = timed(drag("t", "font_size", lambda i: 48 + i % 3))
    print(f"text font size per move (cached glyphs): {text_ms:.1f} ms")

    def boxes(_):
        found = []
        for layer_id, mob in evaluator.frame_layers(0.0):
            points = np.vstack([s.points[:, :2] for s in mob.family_members_with_points()])
            low, high = points.min(axis=0), points.max(axis=0)
            found.append((layer_id, low, high, (low + high) / 2))
        xs = np.array([v for _, low, high, c in found for v in (low[0], high[0], c[0])])
        np.min(np.abs(xs - 0.37))

    print(f"snap candidates from {len(layers)} objects' boxes: {timed(boxes):.2f} ms")

    def move_many(i):
        p = state["project"]
        for k in range(20):
            layer = p.layer(f"s{k}")
            x, y = layer.base.position
            p = edits.update_layer(
                p, f"s{k}", base=layer.base.model_copy(update={"position": (x + 0.01, y)})
            ).project
        state["project"] = p

    print(f"move 20 objects (20 chained edits): {timed(move_many, repeat=10):.1f} ms")


if __name__ == "__main__":
    main()
