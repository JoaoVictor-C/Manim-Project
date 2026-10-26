"""B68: the project camera (P7.5, ADR 0048) - the default path against the pre-P7.5 camera code,
and the cost of a turned camera, on the showcase project at 640x360.

Run: python benchmarks/bench_camera.py
"""

from __future__ import annotations

import time
from pathlib import Path

import manim as m
import numpy as np

from manim_studio.core.engine import adapter
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Camera, Project
from manim_studio.render.cairo_export import render_frame
from manim_studio.render.preview import PreviewView, preview_camera

ROOT = Path(__file__).resolve().parents[1]
REPEATS = 5


def old_camera(view: PreviewView) -> m.Camera:  # pre-P7.5 render.preview.preview_camera
    camera = m.Camera(
        pixel_width=view.pixel_width,
        pixel_height=view.pixel_height,
        frame_width=view.frame_width,
        frame_height=view.frame_height,
        background_color=m.ManimColor(view.background),
        background_opacity=1.0,
    )
    camera.frame_center = np.array([view.centre[0], view.centre[1], 0.0])
    return camera


def main() -> None:
    adapter.configure(ROOT / ".cache" / "manim")
    project = Project.model_validate_json((ROOT / "examples" / "showcase.json").read_text(encoding="utf-8"))
    evaluator = Evaluator(project)
    canvas = project.canvas
    view = PreviewView(640, 360, canvas.frame_width, canvas.frame_height, (0.0, 0.0), canvas.background)
    times = [float(t) for t in np.linspace(0.2, canvas.duration - 0.2, 12)]
    frames = {t: evaluator.frame(t) for t in times[:1]}  # warm the evaluator
    cameras = {
        "pre-P7.5 2D": old_camera(view),
        "default (2D)": preview_camera(view, project.camera),
        "phi 60": preview_camera(view, Camera(phi=60.0)),
        "phi 60, theta -45, gamma 10": preview_camera(view, Camera(phi=60.0, theta=-45.0, gamma=10.0)),
    }
    results = {name: [] for name in cameras}
    for _ in range(REPEATS):
        for t in times:
            frames = evaluator.frame(t)
            for name, camera in cameras.items():
                start = time.perf_counter()
                render_frame(camera, frames)
                results[name].append(time.perf_counter() - start)
    for name, values in results.items():
        median, p90 = np.median(values) * 1000, np.percentile(values, 90) * 1000
        print(f"{name:32s} median {median:5.2f} ms  p90 {p90:5.2f} ms")


if __name__ == "__main__":
    main()
