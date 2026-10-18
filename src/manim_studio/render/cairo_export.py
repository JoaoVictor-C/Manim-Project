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

from ..core import audio, subtitles
from ..core.code_frame import CodeFrame
from ..core.evaluator import Evaluator
from ..core.schema import Camera, Canvas, Project
from ..logging_config import get_logger
from .preview import PreviewView, keep_in_frame, scene_camera
from .options import (
    DEFAULT_CRF,
    RenderOptions,
    apply_options,
    audio_window,
    frame_window,
    window_cues,
)

log = get_logger(__name__)


def make_camera(canvas: Canvas, camera: Camera | None = None) -> m.Camera:
    """The export's camera: the whole video frame, seen from ``camera`` (ADR 0048; None or the
    default is Manim's 2D camera, as before)."""
    view = PreviewView(
        pixel_width=canvas.width_px,
        pixel_height=canvas.height_px,
        frame_width=canvas.frame_width,
        frame_height=canvas.frame_height,
        centre=(0.0, 0.0),
        background=canvas.background,
    )
    return scene_camera(view, camera)


def render_frame(
    camera: m.Camera, mobjects: Iterable[m.Mobject], overlay: Iterable[m.Mobject] = ()
) -> np.ndarray:
    """RGBA uint8 array of shape (height, width, 4).

    Code layer frames (ADR 0019) are painted by Cairo between runs of ordinary
    mobjects, so they keep their place in the stacking order. ``overlay`` (the
    evaluator's: burned-in subtitles) is drawn last and stays flat on the screen
    when the camera is turned (ADR 0048).
    """
    overlay = list(overlay)
    keep_in_frame(camera, overlay)
    camera.reset()
    run: list[m.Mobject] = []
    for mob in [*mobjects, *overlay]:
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


def frame_times(canvas: Canvas, first: int = 0, last: int | None = None) -> list[float]:
    """The times of frames ``[first, last)`` (all of them by default)."""
    n = round(canvas.duration * canvas.fps) if last is None else last
    return [i / canvas.fps for i in range(first, n)]


@dataclass(frozen=True)
class Exported:
    path: Path  # where the video is (the requested path, unless it was locked)
    warning: str | None = None


def partial_path(out_path: Path) -> Path:
    """Where frames are written until the video is complete (ADR 0017)."""
    return out_path.with_name(f"{out_path.stem}.partial{out_path.suffix}")


def export_video(
    project: Project,
    out_path: Path,
    progress=None,
    replace_timeout: float = 2.0,
    options: RenderOptions | None = None,
) -> Exported:
    """Render ``project`` to ``out_path``; an existing file is replaced only by a complete video.

    Frames go to ``partial_path(out_path)``; on any error that file is deleted.
    If ``out_path`` stays locked (open in a player on Windows) for
    ``replace_timeout`` seconds, the video is saved as ``<stem> (n)<suffix>``.
    ``options`` (ADR 0042) change the size, fps, frame range, quality and subtitles; an
    ``.srt`` is written beside the video unless they say ``subtitles="none"``.
    """
    options = options or RenderOptions()
    out_path = Path(out_path)
    if out_path.is_dir():
        raise IsADirectoryError(f"{out_path} is a folder, not a video file")
    project = apply_options(project, options)
    first, last = frame_window(project.canvas, options)  # before anything is written
    out_path.parent.mkdir(parents=True, exist_ok=True)
    partial = partial_path(out_path)
    try:
        _encode(project, partial, progress, first, last, options.crf)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    exported = _finish(partial, out_path, replace_timeout)
    cues = project.subtitles  # an .srt beside the video, burned in or not (ADR 0035)
    if cues and options.subtitles != "none":
        fps = project.canvas.fps
        if first > 0 or last < round(project.canvas.duration * fps):
            cues = window_cues(cues, first / fps, last / fps)
        if cues:
            exported.path.with_suffix(".srt").write_text(subtitles.write_srt(cues), encoding="utf-8")
    return exported


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


def _encode(
    project: Project,
    out_path: Path,
    progress=None,
    first: int = 0,
    last: int | None = None,
    crf: int = DEFAULT_CRF,
) -> None:
    """Encode frames ``[first, last)`` of ``project`` (options applied) and the sound under them."""
    canvas = project.canvas
    camera = make_camera(canvas, project.camera)
    evaluator = Evaluator(project)
    with av.open(str(out_path), mode="w") as container:
        stream = container.add_stream("libx264", rate=canvas.fps)
        stream.width = canvas.width_px
        stream.height = canvas.height_px
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": str(crf)}
        sound = container.add_stream("aac", rate=audio.RATE, layout="stereo") if project.audio else None
        times = frame_times(canvas, first, last)
        log.info(
            "export %s: %d frames %dx%d@%d",
            out_path,
            len(times),
            canvas.width_px,
            canvas.height_px,
            canvas.fps,
        )
        for i, t in enumerate(times):
            layers = [mob for _, mob in evaluator.frame_layers(t)]  # evaluator.frame(t), the subtitle apart
            rgba = render_frame(camera, layers, evaluator.overlay(t))
            frame = av.VideoFrame.from_ndarray(rgba[:, :, :3].copy(), format="rgb24")
            container.mux(stream.encode(frame))
            if progress:
                progress(i + 1, len(times))
        container.mux(stream.encode())
        if sound is not None:  # the project's mix, from the first frame's time (ADR 0034, B47)
            mix = audio.mix(project)  # it depends on the sounds and the duration, not on size or fps
            if first > 0 or first + len(times) < round(canvas.duration * canvas.fps):
                mix = audio_window(mix, first, first + len(times), canvas.fps)
            _encode_audio(container, sound, mix)


def _encode_audio(container, stream, samples: np.ndarray) -> None:
    resampler = av.AudioResampler(format=stream.codec_context.format.name, layout="stereo", rate=audio.RATE)
    frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(samples), format="fltp", layout="stereo")
    frame.sample_rate = audio.RATE
    frame.pts = 0
    for resampled in [*resampler.resample(frame), *resampler.resample(None)]:
        container.mux(stream.encode(resampled))
    container.mux(stream.encode())
