"""Preset thumbnails (P6d.3, ADR 0044): a preset drawn on a square by the in-process evaluator.

Each preset is applied to a square in a small project (160x90) and a few frames across its
run are rendered with the same Cairo camera as the exports, so a thumbnail shows exactly
what the preset does. Eight frames cost about 2 ms (B61), so the presets browser draws all
of them when it opens; the frames are kept per preset (its JSON and the background), so an
edited preset is drawn again and an unchanged one never is. No Qt here: the browser turns
the arrays into pixmaps.
"""

from __future__ import annotations

import numpy as np

from ..core import library
from ..core.edits import EditError
from ..core.evaluator import Evaluator
from ..core.schema import Canvas, Layer, Project, Spec
from ..logging_config import get_logger
from .cairo_export import make_camera, render_frame

log = get_logger(__name__)

WIDTH, HEIGHT = 160, 90
FRAMES = 8  # across the preset's run, first and last included
STILL = FRAMES // 2  # the frame a card shows at rest: in the middle of the run
MIN_SPAN = 0.5  # s: a run that is only one key still gets a visible stretch
SQUARE_FILL = "#3b82f6"  # the drawing's own colour, as Manim renders it (not a chrome colour)
LAYER_ID = "square"

_cache: dict[tuple[str, str], list[np.ndarray]] = {}


def span(preset: library.Preset) -> float:
    """How long the preset runs from its start, in seconds (at least ``MIN_SPAN``)."""
    ends = [c.offset + c.duration for c in preset.clips]
    ends += [k.dt for track in preset.keys.values() for k in track]
    return max([*ends, MIN_SPAN])


def frame_times(preset: library.Preset) -> list[float]:
    """The ``FRAMES`` times, from 0 to just before the end of the run, that a thumbnail shows."""
    end = span(preset)
    return [end * i / (FRAMES - 1) * 0.999 for i in range(FRAMES)]


def thumb_project(preset: library.Preset, background: str) -> Project:
    """A 160x90 project with a square and ``preset`` applied to it at 0 s (``EditError`` when the
    preset cannot be drawn on a square)."""
    canvas = Canvas(
        width_px=WIDTH,
        height_px=HEIGHT,
        fps=30,
        duration=span(preset) + 1.0,
        background=background,
    )
    square = Layer(
        id=LAYER_ID,
        spec=Spec(
            type="Square",
            params={"side_length": 3.0},
            style={"fill": SQUARE_FILL, "fill_opacity": 1.0},
        ),
    )
    return library.apply_preset(Project(canvas=canvas, layers=[square]), LAYER_ID, preset, 0.0).project


def render_thumbnail(preset: library.Preset, background: str) -> list[np.ndarray]:
    """The ``FRAMES`` RGBA frames (height x width x 4, uint8) of ``preset``, drawn now; none when
    it cannot be drawn on a square."""
    try:
        project = thumb_project(preset, background)
    except EditError as exc:
        log.info("no thumbnail for %s: %s", preset.name, exc)
        return []
    evaluator = Evaluator(project)
    camera = make_camera(project.canvas)
    return [render_frame(camera, evaluator.frame(t)) for t in frame_times(preset)]


def thumbnails(preset: library.Preset, background: str) -> list[np.ndarray]:
    """``render_thumbnail``, kept per preset content and background."""
    key = (preset.model_dump_json(), background)
    if key not in _cache:
        _cache[key] = render_thumbnail(preset, background)
    return _cache[key]


def clear_cache() -> None:
    _cache.clear()


def cache_size() -> int:
    return len(_cache)
