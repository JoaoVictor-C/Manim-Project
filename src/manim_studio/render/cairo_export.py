"""Exact rendering through Manim's own Cairo camera, plus video export.

The frames are drawn by Cairo on the processor, by this process or by several (``farm``, ADR 0065), and
encoded by the graphics card when it has an encoder or by x264 (``encoders``); the pixels are the same either
way.
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import av
import manim as m
import numpy as np

from ..core.code import python_object
from ..core.code.code_frame import CodeFrame
from ..core.engine import adapter
from ..core.engine.evaluator import Evaluator
from ..core.model.schema import Camera, Canvas, Project
from ..core.sound import audio, subtitles
from ..logging_config import get_logger
from . import encoders, farm
from .options import RenderOptions, apply_options, audio_bounds, frame_window, window_cues
from .preview import PreviewView, keep_in_frame, scene_camera

log = get_logger(__name__)

AUDIO_SPAN = 10 * audio.RATE  # the mix is encoded 10 s at a time (B70)


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
    camera: m.Camera, mobjects: Iterable[m.Mobject], overlay: Iterable[m.Mobject] = (), copy: bool = True
) -> np.ndarray:
    """RGBA uint8 array of shape (height, width, 4): a copy, or with ``copy=False`` the camera's own buffer
    (what the export reads at once; the next frame draws over it).

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
    return np.array(camera.pixel_array, copy=True) if copy else camera.pixel_array


def frame_times(canvas: Canvas, first: int = 0, last: int | None = None) -> list[float]:
    """The times of frames ``[first, last)`` (all of them by default)."""
    n = round(canvas.duration * canvas.fps) if last is None else last
    return [i / canvas.fps for i in range(first, n)]


@dataclass(frozen=True)
class Exported:
    path: Path  # where the video is (the requested path, unless it was locked)
    warning: str | None = None
    how: str = ""  # what drew and encoded it: "GPU (NVENC), 4 render processes"


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
        how = _encode(project, partial, progress, first, last, options)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    exported = _finish(partial, out_path, replace_timeout)
    exported = Exported(exported.path, exported.warning, how)
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


def farm_pays(project: Project, first: int, last: int) -> bool:
    """Would render processes finish this export sooner? They take a few seconds to start and each builds the
    scene for itself, so a short or light export is done before they are of use: three frames spread over the
    range are drawn here (each twice, the second time is the steady cost) and the whole is estimated."""
    canvas = project.canvas
    camera = make_camera(canvas, project.camera)
    evaluator = Evaluator(project)
    costs = []
    for k in (1, 2, 3):
        t = (first + (last - first) * k // 4) / canvas.fps
        for _ in range(2):
            started = time.perf_counter()
            layers = [mob for _, mob in evaluator.frame_layers(t)]
            render_frame(camera, layers, evaluator.overlay(t), copy=False)
            took = time.perf_counter() - started
        costs.append(took)
    estimate = sorted(costs)[1] * (last - first)
    log.info("export: a frame takes about %.0f ms here, %.0f s in all", sorted(costs)[1] * 1000, estimate)
    return estimate >= farm.MIN_SECONDS


def rendered_frames(
    project: Project, first: int, last: int, workers: int = 1
) -> Iterator[tuple[int, np.ndarray]]:
    """``(frame, RGBA array)`` for frames ``[first, last)`` in order, each array valid until the next is asked
    for. ``workers`` > 1 draws them in that many render processes (``farm``, ADR 0065); if one stops, this
    process goes on from the frame it was at, so a failure is reported with its own traceback."""
    resume = first
    if workers > 1:
        pool = None
        try:
            pool = farm.Farm(
                project,
                first,
                last,
                workers,
                adapter.cache_dir(),
                trust_code=python_object.trusts_everything(),
            )
            yield from pool.frames()
            return
        except (farm.FarmError, OSError) as failure:  # OSError: no processes or no shared memory
            resume = pool.next_frame if pool is not None else first
            log.warning("render processes failed (%s); drawing from frame %d here", failure, resume)
        finally:
            if pool is not None:
                pool.close()
    canvas = project.canvas
    camera = make_camera(canvas, project.camera)
    evaluator = Evaluator(project)
    for i in range(resume, last):
        t = i / canvas.fps
        layers = [mob for _, mob in evaluator.frame_layers(t)]  # evaluator.frame(t), the subtitle apart
        yield i, render_frame(camera, layers, evaluator.overlay(t), copy=False)


def _open_video(out_path: Path, project: Project, encoder: encoders.Encoder, head: np.ndarray):
    """The file, its video stream (and sound stream) with ``head``, the first frame, already encoded: an
    encoder is opened by its first frame, so a card that cannot is found out here, before anything is
    written."""
    canvas = project.canvas
    container = av.open(str(out_path), mode="w")
    try:
        stream = container.add_stream(encoder.codec, rate=canvas.fps)
        stream.width = canvas.width_px
        stream.height = canvas.height_px
        stream.pix_fmt = encoder.pixel_format
        stream.options = dict(encoder.options)
        sound = container.add_stream("aac", rate=audio.RATE, layout="stereo") if project.audio else None
        container.mux(stream.encode(av.VideoFrame.from_ndarray(head, format="rgba")))
    except BaseException:
        with contextlib.suppress(Exception):
            container.close()
        out_path.unlink(missing_ok=True)
        raise
    return container, stream, sound


def _encode(
    project: Project,
    out_path: Path,
    progress=None,
    first: int = 0,
    last: int | None = None,
    options: RenderOptions | None = None,
) -> str:
    """Encode frames ``[first, last)`` of ``project`` (options applied) and the sound under them; says what
    drew and encoded them (``Exported.how``)."""
    options = options or RenderOptions()
    canvas = project.canvas
    if last is None:
        last = round(canvas.duration * canvas.fps)
    total = last - first
    workers = farm.plan(options.jobs, total, canvas.width_px * canvas.height_px * 4)
    if workers > 1 and options.jobs is None and not farm_pays(project, first, last):
        workers = 1
    chosen = encoders.candidates(
        options.encoder, options.crf, total, canvas.width_px, canvas.height_px, farming=workers > 1
    )
    log.info(
        "export %s: %d frames %dx%d@%d, %d render processes, encoders %s",
        out_path,
        total,
        canvas.width_px,
        canvas.height_px,
        canvas.fps,
        workers,
        [e.label for e in chosen],
    )
    with contextlib.closing(rendered_frames(project, first, last, workers)) as frames:
        _, head = next(frames)
        for position, encoder in enumerate(chosen):
            try:
                container, stream, sound = _open_video(out_path, project, encoder, head)
            except ValueError as exc:  # PyAV's: an encoder that will not open (FFmpegError) or is not there
                if not encoder.hardware:
                    raise  # x264 is the last resort: its failure is the export's
                log.warning(
                    "%s cannot encode here (%s); trying %s", encoder.label, exc, chosen[position + 1].label
                )
                continue
            break
        with contextlib.closing(container):
            if progress:
                progress(1, total)
            for done, (_, rgba) in enumerate(frames, 2):
                container.mux(stream.encode(av.VideoFrame.from_ndarray(rgba, format="rgba")))
                if progress:
                    progress(done, total)
            container.mux(stream.encode())
            if sound is not None:  # the project's mix, from the first frame's time (ADR 0034, B47)
                # it depends on the sounds and the duration, not on size or fps; streamed in spans (B70)
                if first > 0 or first + total < round(canvas.duration * canvas.fps):
                    start, stop = audio_bounds(first, first + total, canvas.fps)
                else:
                    start, stop = 0, round(canvas.duration * audio.RATE)
                _encode_audio(container, sound, audio.mix_chunks(project, start, stop, AUDIO_SPAN))
    return encoder.label + (f", {workers} render processes" if workers > 1 else "")


def _encode_audio(container, stream, samples: np.ndarray | Iterable[np.ndarray]) -> None:
    """Encode the sound, given whole or in consecutive pieces: the pieces are frames with
    consecutive timestamps, which the encoder cuts into its own frames as it cut the whole."""
    resampler = av.AudioResampler(format=stream.codec_context.format.name, layout="stereo", rate=audio.RATE)
    pts = 0
    for piece in [samples] if isinstance(samples, np.ndarray) else samples:
        frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(piece), format="fltp", layout="stereo")
        frame.sample_rate = audio.RATE
        frame.pts = pts
        pts += piece.shape[1]
        for resampled in resampler.resample(frame):
            container.mux(stream.encode(resampled))
    for resampled in resampler.resample(None):
        container.mux(stream.encode(resampled))
    container.mux(stream.encode())
