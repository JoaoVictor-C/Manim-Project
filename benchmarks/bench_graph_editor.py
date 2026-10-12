"""B56 - the graph editor (P6b.2): what drawing and dragging curves costs with many keys.

A layer with every value keyed (position, scale, rotation, opacity: five curves) and
``KEYS`` keys per track, mixed eases, in the Animate page at 1600x1000:

1. sampling the five curves across the graph's width: the segment walk
   (``graph_model.curve_points``) against calling ``evaluator._sample`` at every sample
   (the alternative weighed in decision session 35);
2. a repaint after an edit (the curves resampled) and after a seek (only the playhead:
   the cached paths are stroked again);
3. one drag step: ``graph_model.drag_key`` on the drag's start snapshot plus
   ``Document.preview`` (the evaluator, the timeline, Properties and the graph follow).

Run: ``python benchmarks/bench_graph_editor.py``.
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for name in ("MANIM_STUDIO_PREVIEW", "MANIM_STUDIO_WORKER", "MANIM_STUDIO_AUDIO", "MANIM_STUDIO_CODE"):
    os.environ.setdefault(name, "0")

from PySide6.QtWidgets import QApplication  # noqa: E402

from manim_studio.core import adapter  # noqa: E402
from manim_studio.core.evaluator import _sample  # noqa: E402
from manim_studio.core.schema import Canvas, Easing, Keyframe, Layer, Project, Spec  # noqa: E402
from manim_studio.ui import graph_model, theme  # noqa: E402
from manim_studio.ui.main_window import MainWindow  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EASES = ["smooth", "linear", "ease_out_back", "ease_in_out_sine", "there_and_back"]


def scene(keys: int) -> Project:
    duration = keys * 0.1 + 1

    def track(value):
        return [
            Keyframe(t=i * 0.1, value=value(i), ease=Easing(name=EASES[i % len(EASES)])) for i in range(keys)
        ]

    return Project(
        canvas=Canvas(width_px=640, height_px=360, duration=duration),
        layers=[
            Layer(
                id="s",
                spec=Spec(type="Square"),
                tracks={
                    "position": track(lambda i: (i % 7 - 3.0, i % 5 - 2.0)),
                    "scale": track(lambda i: 1 + (i % 3) * 0.2),
                    "rotation": track(lambda i: (i % 11) * 15.0),
                    "opacity": track(lambda i: (i % 4) / 3),
                },
            )
        ],
    )


def best(fn, repeat: int = 7) -> float:
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    return min(times)


def main() -> None:
    adapter.configure(ROOT / ".cache" / "manim")
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app)
    header = ("keys", "walk ms", "per-sample ms", "repaint edit", "repaint seek", "drag step")
    print(" ".join(f"{h:>{w}}" for h, w in zip(header, (5, 8, 14, 13, 13, 10), strict=True)))
    for keys in (10, 50, 200, 1000):
        project = scene(keys)
        path = ROOT / ".cache" / f"bench_graph_{keys}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
        window = MainWindow()
        window.resize(1600, 1000)
        window.show()
        window.load(path)
        window.show_page("animate")
        window.selection.select_layer("s")
        app.processEvents()
        graph = window.pages.pages["animate"].graph
        graph.frame_all()
        layer = window.document.project.layer("s")
        rect = graph.plot_rect()
        t0, t1 = graph.t_of(rect.left()), graph.t_of(rect.right())
        step = graph.scale.seconds(2.0)

        def walk(layer=layer, t0=t0, t1=t1, step=step) -> None:
            for curve in graph_model.CURVES:
                graph_model.curve_points(layer, curve, t0, t1, step)

        def per_sample(layer=layer, t0=t0, t1=t1, step=step) -> None:
            for curve in graph_model.CURVES:
                track = layer.tracks.get(curve.prop, [])
                for t in graph_model.sample_times(layer, curve, t0, t1, step):
                    _sample(track, t, 0.0)

        def repaint_edit(graph=graph) -> None:
            graph._cache = type(graph._cache)()  # as after an edit: resample
            graph.repaint()

        def repaint_seek(graph=graph) -> None:
            graph.repaint()

        base = window.document.project
        steps = iter(range(10**6))

        def drag_step(base=base, graph=graph, window=window, steps=steps) -> None:
            i = next(steps)
            edit, _ = graph_model.drag_key(
                base,
                "s",
                graph_model.BY_NAME["x"],
                0.5,
                0.5 + (i % 2) * 0.03,
                1.0 + (i % 3) * 0.1,
                scale=graph.scale,
                playhead=0.0,
            )
            window.document.preview(edit)
            app.processEvents()

        walk_ms = best(walk)
        sample_ms = best(per_sample, 3)
        edit_ms = best(repaint_edit)
        seek_ms = best(repaint_seek)
        window.document.begin_preview()
        drag_ms = statistics.median([best(drag_step, 1) for _ in range(15)])
        window.document.cancel_preview()
        print(
            f"{keys:>5} {walk_ms:>8.2f} {sample_ms:>14.2f} {edit_ms:>13.2f} {seek_ms:>13.2f} {drag_ms:>10.2f}"
        )
        window.close()
        path.unlink()


if __name__ == "__main__":
    main()
