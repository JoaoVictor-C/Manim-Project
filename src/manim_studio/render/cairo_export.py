"""Exact rendering through Manim's own Cairo camera, plus video export.

The frames are drawn by Cairo on the processor, by this process or by several (``farm``, ADR 0065), and
encoded by the graphics card when it has an encoder or by x264 (``encoders``); the pixels are the same either
way. A long export is rendered in segments kept in a work folder, so an interrupted one resumes (``resume``,
ADR 0081).
"""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from fractions import Fraction
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
from . import encoders, farm, resume
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
    fresh: bool = False,
) -> Exported:
    """Render ``project`` to ``out_path``; an existing file is replaced only by a complete video.

    Frames go to ``partial_path(out_path)``; on any error that file is deleted. An export of two segments
    or more (``options.segment_seconds``) is rendered in segments kept in ``resume.work_dir(out_path)`` and
    joined at the end: an export stopped part way resumes from the segments it finished, unless ``fresh``
    (ADR 0081); the folder is removed once the video is complete.
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
    work = None
    if resume.segmented(first, last, resume.segment_frames(options.segment_seconds, project.canvas.fps)):
        work = resume.work_dir(out_path)
        resume.sweep(out_path.parent, keep=work)
    try:
        if work is None:
            how = _encode(project, partial, progress, first, last, options)
        else:
            how = _encode_segments(project, partial, work, progress, first, last, options, fresh)
    except BaseException:
        partial.unlink(missing_ok=True)  # the work folder stays: the next export resumes from it
        raise
    exported = _finish(partial, out_path, replace_timeout)
    if work is not None:
        resume.discard(work)
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


def _open_video(
    out_path: Path,
    project: Project,
    encoder: encoders.Encoder,
    head: np.ndarray,
    with_sound: bool = True,
    container_format: str | None = None,
):
    """The file, its video stream (and sound stream) with ``head``, the first frame, already encoded: an
    encoder is opened by its first frame, so a card that cannot is found out here, before anything is
    written. A segment (ADR 0081) has no sound and is an MP4 whatever its name."""
    canvas = project.canvas
    container = av.open(str(out_path), mode="w", format=container_format)
    try:
        stream = container.add_stream(encoder.codec, rate=canvas.fps)
        stream.width = canvas.width_px
        stream.height = canvas.height_px
        stream.pix_fmt = encoder.pixel_format
        stream.options = dict(encoder.options)
        sound = _sound_stream(container, project) if with_sound else None
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
            if sound is not None:
                _mux_sound(container, sound, project, first, last)
    return encoder.label + (f", {workers} render processes" if workers > 1 else "")


def _sound_stream(container, project: Project):
    return container.add_stream("aac", rate=audio.RATE, layout="stereo") if project.audio else None


def _mux_sound(container, sound, project: Project, first: int, last: int) -> None:
    """The project's mix under frames ``[first, last)``, from the first frame's time (ADR 0034, B47)."""
    canvas = project.canvas
    # it depends on the sounds and the duration, not on size or fps; streamed in spans (B70)
    if first > 0 or last < round(canvas.duration * canvas.fps):
        start, stop = audio_bounds(first, last, canvas.fps)
    else:
        start, stop = 0, round(canvas.duration * audio.RATE)
    _encode_audio(container, sound, audio.mix_chunks(project, start, stop, AUDIO_SPAN))


# -- resumable exports: segments in a work folder, joined at the end (ADR 0081) ----------------


class _EncoderGoneError(Exception):
    """The encoder the finished segments were made with cannot be opened any more (a card's encoder)."""


def _encode_segments(
    project: Project,
    out_path: Path,
    work: Path,
    progress,
    first: int,
    last: int,
    options: RenderOptions,
    fresh: bool = False,
) -> str:
    """Render the segments of ``[first, last)`` missing from ``work`` and join them all into ``out_path`` with
    the sound; says what drew and encoded them (``Exported.how``)."""
    canvas = project.canvas
    total = last - first
    per = resume.segment_frames(options.segment_seconds, canvas.fps)
    trust = python_object.trusts_everything()
    state = None if fresh else resume.load(work)
    if state is not None and not resume.matches(state, project, options, trust, first, last, per):
        log.info("export: %s was made for another project or other options; starting again", work)
        state = None
    if state is None:
        resume.discard(work)
        state = resume.State(
            project=resume.project_key(project),
            options=resume.options_key(options, trust),
            first=first,
            last=last,
            segment_frames=per,
            fps=canvas.fps,
            audio=bool(project.audio),
        )
    else:
        resume.remove_temporary(work)
    plan = resume.spans(first, last, per)
    for index, a, b in plan:
        segment = state.segments.get(index)
        if segment is None:
            continue
        if (segment.first, segment.last) != (a, b) or not resume.intact(work, segment):
            log.warning("export: segment %d in %s is missing or changed; rendering it again", index, work)
            del state.segments[index]
    missing = [span for span in plan if span[0] not in state.segments]
    done = total - sum(b - a for _, a, b in missing)
    if state.segments:
        log.info("export: resuming %s, %d of %d segments done", work, len(state.segments), len(plan))
    resume.save(work, state)  # the folder says what it is for before its first segment
    workers = 1
    if missing:
        workers = farm.plan(options.jobs, total - done, canvas.width_px * canvas.height_px * 4)
        if workers > 1 and options.jobs is None and not farm_pays(project, missing[0][1], missing[-1][2]):
            workers = 1
        if state.codec:
            recorded = encoders.by_codec(state.codec, options.crf)
            chosen = [recorded] if recorded is not None else []
        else:
            chosen = encoders.candidates(
                options.encoder, options.crf, total, canvas.width_px, canvas.height_px, farming=workers > 1
            )
        if not chosen:
            return _encode_segments(project, out_path, work, progress, first, last, options, fresh=True)
        log.info(
            "export %s: %d of %d segments to render, %d render processes, encoders %s",
            out_path,
            len(missing),
            len(plan),
            workers,
            [e.label for e in chosen],
        )
        try:
            for run in _runs(missing):
                with contextlib.closing(rendered_frames(project, run[0][1], run[-1][2], workers)) as frames:
                    for index, a, b in run:
                        report = _reporter(progress, done, total)
                        encoder = _write_segment(project, work, state, (index, a, b), frames, chosen, report)
                        chosen = [encoder]
                        done += b - a
        except _EncoderGoneError as gone:
            log.warning("export: %s cannot encode here any more (%s); starting again", state.label, gone)
            return _encode_segments(project, out_path, work, progress, first, last, options, fresh=True)
    elif progress:
        progress(total, total)
    _join(project, work, state, plan, out_path, first, last)
    return state.label + (f", {workers} render processes" if workers > 1 else "")


def _reporter(progress, base: int, total: int) -> Callable[[int], None] | None:
    """Progress inside one segment: its ``k``-th frame is frame ``base + k`` of the export."""
    if progress is None:
        return None
    return lambda k: progress(base + k, total)


def _runs(spans: list[tuple[int, int, int]]) -> list[list[tuple[int, int, int]]]:
    """The spans in runs of consecutive frames (each run is drawn by one stream of frames)."""
    runs: list[list[tuple[int, int, int]]] = []
    for span in spans:
        if runs and runs[-1][-1][2] == span[1]:
            runs[-1].append(span)
        else:
            runs.append([span])
    return runs


def _write_segment(
    project: Project,
    work: Path,
    state: resume.State,
    span: tuple[int, int, int],
    frames: Iterator[tuple[int, np.ndarray]],
    chosen: list[encoders.Encoder],
    report: Callable[[int], None] | None,
) -> encoders.Encoder:
    """Encode frames ``[a, b)`` from ``frames`` as segment ``index``: into ``<name>.tmp``, renamed when
    complete and only then recorded in the state. Each segment is its own encoder session, so it starts with a
    key frame and refers to nothing outside it: the segments join without encoding again."""
    index, a, b = span
    name = f"segment_{index:04d}.mp4"
    tmp = work / f"{name}.tmp"
    _, head = next(frames)
    for position, encoder in enumerate(chosen):
        try:
            container, stream, _ = _open_video(tmp, project, encoder, head, False, "mp4")
        except ValueError as exc:  # PyAV's: the encoder will not open here
            if not encoder.hardware:
                raise
            if position + 1 == len(chosen):
                raise _EncoderGoneError(str(exc)) from exc
            fallback = chosen[position + 1].label
            log.warning("%s cannot encode here (%s); trying %s", encoder.label, exc, fallback)
            continue
        break
    try:
        with contextlib.closing(container):
            if report:
                report(1)
            for k in range(2, b - a + 1):
                _, rgba = next(frames)
                container.mux(stream.encode(av.VideoFrame.from_ndarray(rgba, format="rgba")))
                if report:
                    report(k)
            container.mux(stream.encode())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    path = work / name
    os.replace(tmp, path)
    state.segments[index] = resume.Segment(index, a, b, name, resume.file_sha256(path), path.stat().st_size)
    if not state.codec:
        state.codec, state.label = encoder.codec, encoder.label
    resume.save(work, state)
    return encoder


def _join(
    project: Project,
    work: Path,
    state: resume.State,
    plan: list[tuple[int, int, int]],
    out_path: Path,
    first: int,
    last: int,
) -> None:
    """Copy the segments' video, in order and with their times moved to their place, into ``out_path`` (no
    encoding: each starts with a key frame) and add the sound under the whole as a single-pass export does."""
    fps = project.canvas.fps
    container = av.open(str(out_path), mode="w")
    try:
        with contextlib.closing(container):
            video = sound = extradata = None
            for index, a, _ in plan:
                with av.open(str(work / state.segments[index].file)) as source:
                    stream = source.streams.video[0]
                    if video is None:
                        video = container.add_stream_from_template(stream)
                        extradata = stream.codec_context.extradata
                        sound = _sound_stream(container, project)
                    elif stream.codec_context.extradata != extradata:  # not the same encoder settings
                        resume.discard(work)
                        raise RuntimeError(
                            f"the segments in {work.name} were encoded differently and cannot be joined; "
                            "export again"
                        )
                    offset = round(Fraction(a - first, fps) / stream.time_base)
                    for packet in source.demux(stream):
                        if packet.dts is None:  # the demuxer's empty packet at the end
                            continue
                        packet.pts += offset
                        packet.dts += offset
                        packet.stream = video
                        container.mux(packet)
            if sound is not None:
                _mux_sound(container, sound, project, first, last)
    except BaseException:
        out_path.unlink(missing_ok=True)
        raise


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
