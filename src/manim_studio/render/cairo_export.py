"""Exact rendering through Manim's own Cairo camera, plus video export."""

from __future__ import annotations

import os
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import av
import manim as m
import numpy as np

from ..core import audio
from ..core.code_frame import CodeFrame
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
    """RGBA uint8 array of shape (height, width, 4).

    Code layer frames (ADR 0019) are painted by Cairo between runs of ordinary
    mobjects, so they keep their place in the stacking order.
    """
    camera.reset()
    run: list[m.Mobject] = []
    for mob in mobjects:
        if isinstance(mob, CodeFrame):
            if run:
                camera.capture_mobjects(run)
                run = []
            mob.paint(camera)
        else:
            run.append(mob)
    if run:
        camera.capture_mobjects(run)
    return np.array(camera.pixel_array, copy=True)


def frame_times(canvas: Canvas) -> list[float]:
    n = round(canvas.duration * canvas.fps)
    return [i / canvas.fps for i in range(n)]


@dataclass(frozen=True)
class Exported:
    path: Path  # where the video is (the requested path, unless it was locked)
    warning: str | None = None


def partial_path(out_path: Path) -> Path:
    """Where frames are written until the video is complete (ADR 0017)."""
    return out_path.with_name(f"{out_path.stem}.partial{out_path.suffix}")


def export_video(project: Project, out_path: Path, progress=None, replace_timeout: float = 2.0) -> Exported:
    """Render ``project`` to ``out_path``; an existing file is replaced only by a complete video.

    Frames go to ``partial_path(out_path)``; on any error that file is deleted.
    If ``out_path`` stays locked (open in a player on Windows) for
    ``replace_timeout`` seconds, the video is saved as ``<stem> (n)<suffix>``.
    """
    out_path = Path(out_path)
    if out_path.is_dir():
        raise IsADirectoryError(f"{out_path} is a folder, not a video file")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    partial = partial_path(out_path)
    try:
        _encode(project, partial, progress)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return _finish(partial, out_path, replace_timeout)


def _finish(partial: Path, out_path: Path, timeout: float) -> Exported:
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.replace(partial, out_path)
            return Exported(out_path)
        except PermissionError:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.1)
    n = 2
    while (alternative := out_path.with_name(f"{out_path.stem} ({n}){out_path.suffix}")).exists():
        n += 1
    os.replace(partial, alternative)
    log.warning("%s is in use; saved as %s", out_path, alternative)
    warning = f"{out_path.name} is in use (open in a player?); saved as {alternative.name}"
    return Exported(alternative, warning)


def _encode(project: Project, out_path: Path, progress=None) -> None:
    canvas = project.canvas
    camera = make_camera(canvas)
    evaluator = Evaluator(project)
    with av.open(str(out_path), mode="w") as container:
        stream = container.add_stream("libx264", rate=canvas.fps)
        stream.width = canvas.width_px
        stream.height = canvas.height_px
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "18"}
        sound = container.add_stream("aac", rate=audio.RATE, layout="stereo") if project.audio else None
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
        if sound is not None:  # the project's mix, aligned from 0 (ADR 0034, B47)
            _encode_audio(container, sound, audio.mix(project))


def _encode_audio(container, stream, samples: np.ndarray) -> None:
    resampler = av.AudioResampler(format=stream.codec_context.format.name, layout="stereo", rate=audio.RATE)
    frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(samples), format="fltp", layout="stereo")
    frame.sample_rate = audio.RATE
    frame.pts = 0
    for resampled in [*resampler.resample(frame), *resampler.resample(None)]:
        container.mux(stream.encode(resampled))
    container.mux(stream.encode())
