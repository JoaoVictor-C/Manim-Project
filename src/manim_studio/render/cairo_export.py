"""Exact rendering through Manim's own Cairo camera, plus video export."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import av
import manim as m
import numpy as np

from ..core.evaluator import Evaluator
from ..core.schema import Canvas, Project
from ..logging_config import get_logger

log = get_logger(__name__)


def make_camera(canvas: Canvas) -> m.Camera:
    return m.Camera(
        pixel_width=canvas.width_px,
        pixel_height=canvas.height_px,
        frame_width=canvas.frame_width,
        frame_height=canvas.frame_height,
        background_color=m.ManimColor(canvas.background),
        background_opacity=1.0,
    )


def render_frame(camera: m.Camera, mobjects: Iterable[m.Mobject]) -> np.ndarray:
    """RGBA uint8 array of shape (height, width, 4)."""
    camera.reset()
    camera.capture_mobjects(list(mobjects))
    return np.array(camera.pixel_array, copy=True)


def frame_times(canvas: Canvas) -> list[float]:
    n = round(canvas.duration * canvas.fps)
    return [i / canvas.fps for i in range(n)]


def export_video(project: Project, out_path: Path, progress=None) -> Path:
    canvas = project.canvas
    camera = make_camera(canvas)
    evaluator = Evaluator(project)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(out_path), mode="w") as container:
        stream = container.add_stream("libx264", rate=canvas.fps)
        stream.width = canvas.width_px
        stream.height = canvas.height_px
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "18"}
        times = frame_times(canvas)
        log.info(
            "export %s: %d frames %dx%d@%d",
            out_path,
            len(times),
            canvas.width_px,
            canvas.height_px,
            canvas.fps,
        )
        for i, t in enumerate(times):
            rgba = render_frame(camera, evaluator.frame(t))
            frame = av.VideoFrame.from_ndarray(rgba[:, :, :3].copy(), format="rgb24")
            container.mux(stream.encode(frame))
            if progress:
                progress(i + 1, len(times))
        container.mux(stream.encode())
    return out_path
