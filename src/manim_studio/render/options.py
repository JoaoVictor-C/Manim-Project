"""Render options (P6b.5, ADR 0042): size, fps, range, quality and subtitles of one export.

No Qt and no Manim: the options are parsed from ``manim-studio render`` flags (or built by
the Deliver page), applied to a project by ``apply_options`` and turned into a frame
window by ``frame_window``. A range is the frame window ``[a, b)`` with
``a = round(start * fps)`` and ``b = round(end * fps)``; output frame ``k`` shows time
``(a + k) / fps``; the sound and the ``.srt`` are cut to the same window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..core.model.schema import Canvas, Cue, Project
from ..core.sound import audio

SUBTITLE_MODES = ("burn", "srt", "none")
ENCODERS = ("auto", "gpu", "cpu")  # what turns the frames into H.264 (ADR 0065)
MAX_JOBS = 32  # render processes an export may be told to use
DEFAULT_CRF = 18  # what exports used before options existed
QUALITIES: dict[str, int] = {"Draft": 28, "Standard": 23, "High": 18, "Archive": 12}
HEIGHT_PRESETS: dict[str, int] = {"480p": 480, "720p": 720, "1080p": 1080, "1440p": 1440, "2160p": 2160}
EPS = 1e-9


class OptionsError(ValueError):
    """The options cannot be rendered (an empty range, a bad size); the message is for the user."""


@dataclass(frozen=True)
class RenderOptions:
    """What differs from the project's own canvas in one export (None / default: as the project)."""

    width: int | None = None
    height: int | None = None
    fps: int | None = None
    start: float = 0.0
    end: float | None = None  # None: to the end of the scene
    crf: int = DEFAULT_CRF
    subtitles: str | None = None  # None: as the project (burn-in per its style, .srt always)
    encoder: str = "auto"  # "auto": the graphics card's encoder when there is one and the video is big enough
    jobs: int | None = None  # render processes; None: as many as pay; 1: this process alone (ADR 0065)

    def __post_init__(self) -> None:
        if (self.width is None) != (self.height is None):
            raise OptionsError("a size needs both a width and a height")
        if self.width is not None and (self.width < 2 or self.height < 2):
            raise OptionsError(f"size {self.width}x{self.height} is too small")
        if self.fps is not None and self.fps < 1:
            raise OptionsError("fps must be at least 1")
        if not 0 <= self.crf <= 51:
            raise OptionsError(f"quality (crf) must be between 0 and 51, not {self.crf}")
        if self.subtitles is not None and self.subtitles not in SUBTITLE_MODES:
            raise OptionsError(f"subtitles must be one of {', '.join(SUBTITLE_MODES)}")
        if self.encoder not in ENCODERS:
            raise OptionsError(f"encoder must be one of {', '.join(ENCODERS)}")
        if self.jobs is not None and not 1 <= self.jobs <= MAX_JOBS:
            raise OptionsError(f"jobs must be between 1 and {MAX_JOBS}, not {self.jobs}")

    def to_args(self) -> list[str]:
        """The ``manim-studio render`` flags that rebuild these options (defaults left out)."""
        args: list[str] = []
        if self.width is not None:
            args += ["--size", f"{self.width}x{self.height}"]
        if self.fps is not None:
            args += ["--fps", str(self.fps)]
        if self.start > EPS:
            args += ["--start", repr(self.start)]
        if self.end is not None:
            args += ["--end", repr(self.end)]
        if self.crf != DEFAULT_CRF:
            args += ["--crf", str(self.crf)]
        if self.subtitles is not None:
            args += ["--subtitles", self.subtitles]
        if self.encoder != "auto":
            args += ["--encoder", self.encoder]
        if self.jobs is not None:
            args += ["--jobs", str(self.jobs)]
        return args


def even(value: float) -> int:
    """The nearest even whole number, at least 2 (H.264 with 4:2:0 chroma needs even sizes)."""
    return max(2, 2 * math.floor(value / 2 + 0.5))  # halves go up: 161 -> 162


def parse_size(text: str) -> tuple[int, int]:
    """'1280x720' -> (1280, 720); the sides are made even."""
    try:
        width, height = (int(part) for part in text.lower().replace("*", "x").split("x"))
    except ValueError:
        raise OptionsError(f"size must look like 1280x720, not {text!r}") from None
    if width < 1 or height < 1:
        raise OptionsError(f"size {text!r} must be positive")
    return even(width), even(height)


def size_for_height(canvas: Canvas, height: int) -> tuple[int, int]:
    """``height`` pixels tall at the canvas's aspect ratio (both sides even)."""
    return even(height * canvas.width_px / canvas.height_px), even(height)


def preset_sizes(canvas: Canvas) -> dict[str, tuple[int, int]]:
    """480p ... 2160p at the canvas's aspect ratio."""
    return {name: size_for_height(canvas, height) for name, height in HEIGHT_PRESETS.items()}


def apply_options(project: Project, options: RenderOptions) -> Project:
    """The project as the export renders it: the size and fps of ``options``, subtitles burned or not.

    The scene's duration and ``frame_height`` stay, so the picture is framed as in the editor.
    """
    changes: dict = {}
    if options.width is not None:
        changes.update(width_px=even(options.width), height_px=even(options.height))
    if options.fps is not None:
        changes["fps"] = options.fps
    canvas = project.canvas.model_copy(update=changes) if changes else project.canvas
    style = project.subtitle_style
    if options.subtitles is not None:
        style = style.model_copy(update={"burn_in": options.subtitles == "burn"})
    return project.model_copy(update={"canvas": canvas, "subtitle_style": style})


def _frame(t: float, fps: int) -> int:
    """The frame a time falls on; halves go up (0.5 s at 5 fps is frame 3, not Python's 2)."""
    return math.floor(t * fps + 0.5 + EPS)


def frame_window(canvas: Canvas, options: RenderOptions) -> tuple[int, int]:
    """The frames ``[a, b)`` the export renders, on ``canvas`` (with the options' fps applied)."""
    fps = options.fps or canvas.fps
    total = round(canvas.duration * fps)
    if options.start < 0:
        raise OptionsError("the range cannot start before 0")
    if options.start >= canvas.duration - EPS:
        raise OptionsError(f"the range starts at {options.start:g} s, after the scene ends")
    first = _frame(options.start, fps)
    last = total if options.end is None else min(total, _frame(options.end, fps))
    if options.end is not None and options.end <= options.start + EPS:
        raise OptionsError("the range must end after it starts")
    if last <= first:
        raise OptionsError(f"the range is shorter than one frame at {fps} fps")
    return first, last


def window_cues(cues: list[Cue], t0: float, t1: float) -> list[Cue]:
    """The cues shown between ``t0`` and ``t1``, moved so ``t0`` is 0 and cut at both edges."""
    out: list[Cue] = []
    for cue in cues:
        start, end = max(cue.start, t0) - t0, min(cue.end, t1) - t0
        if end - start > EPS:
            out.append(cue.model_copy(update={"start": start, "end": end}))
    return out


def audio_bounds(first: int, last: int, fps: int) -> tuple[int, int]:
    """The samples of the mix under frames ``[first, last)``."""
    return round(first / fps * audio.RATE), round(last / fps * audio.RATE)


def audio_window(samples: np.ndarray, first: int, last: int, fps: int) -> np.ndarray:
    """The part of the mix under frames ``[first, last)``, padded with silence to the video's length."""
    start, stop = audio_bounds(first, last, fps)
    cut = samples[:, start:stop]
    missing = (stop - start) - cut.shape[1]
    if missing > 0:
        cut = np.pad(cut, ((0, 0), (0, missing)))
    return np.ascontiguousarray(cut)
