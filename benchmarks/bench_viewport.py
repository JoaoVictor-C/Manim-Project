"""B36 — what a re-framed preview camera costs (viewport zoom/pan, P3a).

The editor's canvas renders the frame letterboxed at widget size. With a zoomable
viewport the camera is re-framed (``frame_center``, ``frame_width``) and covers
the whole widget, so objects outside the video frame show. This measures the
stress scene (``bench_preview.stress_project``) per frame:

* letterboxed: the frame rect only (today), 806x453;
* whole widget: 806x598, same scale (letterbox bars become rendered pasteboard);
* zoomed 4x and 0.25x, whole widget;

and checks that a re-framed camera draws exactly what the full frame shows, cut
and scaled: zoom 2 about a point vs the matching crop of a 2x-resolution render.

Run: ``python benchmarks/bench_viewport.py``.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import manim as m
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_preview import stress_project
from manim_studio.core.engine import adapter
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.render.cairo_export import render_frame


def camera(width_px: int, height_px: int, frame_width: float, center=(0.0, 0.0)) -> m.Camera:
    cam = m.Camera(
        pixel_width=width_px,
        pixel_height=height_px,
        frame_width=frame_width,
        frame_height=frame_width * height_px / width_px,
        background_color=m.ManimColor("#000000"),
        background_opacity=1.0,
    )
    cam.frame_center = np.array([center[0], center[1], 0.0])
    return cam


def per_frame(cam: m.Camera, evaluator: Evaluator, times: list[float]) -> float:
    samples = []
    for t in times:
        mobs = [mob for _, mob in evaluator.frame_layers(t)]
        start = time.perf_counter()
        render_frame(cam, mobs)
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def main() -> None:
    adapter.configure(Path(__file__).resolve().parents[1] / ".cache" / "manim")
    project = stress_project()
    evaluator = Evaluator(project)
    fw = project.canvas.frame_width
    times = [i / 30 for i in range(0, 90, 3)]
    evaluator.frame(times[0])
    ppu = 806 / fw
    cases = {
        "letterboxed 806x453": camera(806, 453, fw),
        "whole widget 806x598": camera(806, 598, 806 / ppu),
        "zoom 4x 806x598": camera(806, 598, 806 / (ppu * 4), center=(1.0, 0.5)),
        "zoom 0.25x 806x598": camera(806, 598, 806 / (ppu * 0.25)),
    }
    for name, cam in cases.items():
        print(f"{name:24s} {per_frame(cam, evaluator, times):6.1f} ms / frame")

    # exactness: zoom 2 about (1, 0.5) vs the matching crop of a 2x render of the whole frame
    t = 1.0
    full = render_frame(camera(1612, 906, fw), [mob for _, mob in evaluator.frame_layers(t)])
    zoomed = render_frame(
        camera(806, 453, fw / 2, center=(1.0, 0.5)), [mob for _, mob in evaluator.frame_layers(t)]
    )
    px = 1612 / fw
    x0 = round(1612 / 2 + (1.0 - fw / 4) * px)
    y0 = round(906 / 2 - (0.5 + fw * 453 / 806 / 4) * px)
    crop = full[y0 : y0 + 453, x0 : x0 + 806]
    diff = np.abs(crop.astype(int) - zoomed.astype(int))
    print(f"zoom 2 vs crop of a 2x render: max {diff.max()}, mean {diff.mean():.3f}")


if __name__ == "__main__":
    main()
