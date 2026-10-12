"""B61 - preset thumbnails: what drawing a preset on a small square costs.

For every built-in preset: apply it to a square at t = 0 in a fresh 160x90 project,
then render 8 frames across the preset's run with the in-process evaluator and
Cairo - the first frame (clip activation included) and the rest separately.

Run: ``python benchmarks/bench_preset_thumbs.py``.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

from manim_studio.core import adapter, library
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.render.cairo_export import make_camera, render_frame

ROOT = Path(__file__).resolve().parents[1]
FRAMES = 8


def main() -> None:
    adapter.configure(ROOT / ".cache" / "manim")
    items = library.load_library()
    canvas = Canvas(width_px=160, height_px=90, fps=30, duration=3.0)
    firsts, rests, totals = [], [], []
    for preset in items.presets:
        base = Project(
            canvas=canvas,
            layers=[
                Layer(
                    id="s",
                    spec=Spec(
                        type="Square",
                        params={"side_length": 3.0},
                        style={"fill": "#3b82f6", "fill_opacity": 1.0},
                    ),
                )
            ],
        )
        start = time.perf_counter()
        project = library.apply_preset(base, "s", preset, 0.0).project
        layer = project.layer("s")
        end = max([c.end for c in layer.clips] + [k.t for t in layer.tracks.values() for k in t] + [0.5])
        evaluator = Evaluator(project)
        camera = make_camera(project.canvas)
        times = [end * i / (FRAMES - 1) * 0.999 for i in range(FRAMES)]
        t0 = time.perf_counter()
        render_frame(camera, evaluator.frame(times[0]))
        firsts.append((time.perf_counter() - t0) * 1000)
        t1 = time.perf_counter()
        for t in times[1:]:
            render_frame(camera, evaluator.frame(t))
        rests.append((time.perf_counter() - t1) * 1000 / (FRAMES - 1))
        totals.append((time.perf_counter() - start) * 1000)
    print(f"{len(items.presets)} presets")
    print(f"first frame: median {statistics.median(firsts):.1f} ms, max {max(firsts):.1f} ms")
    print(f"other frames: median {statistics.median(rests):.1f} ms, max {max(rests):.1f} ms")
    whole = statistics.median(totals)
    print(f"whole thumbnail ({FRAMES} frames): median {whole:.1f} ms, max {max(totals):.1f} ms")
    print(f"all presets: {sum(totals):.0f} ms")


if __name__ == "__main__":
    main()
