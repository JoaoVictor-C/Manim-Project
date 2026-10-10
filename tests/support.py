"""Shared fixtures-as-constants and helpers for the test suite.

The core contract under test: a frame is a pure function of (project, t), and
it must equal what Manim's own sequential play loop renders.
"""

from __future__ import annotations

import numpy as np

from manim_studio.core import adapter
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import CLIP_KIND_INFO, Canvas, Clip, Easing, Layer, Project, Spec
from manim_studio.render.cairo_export import make_camera, render_frame

CANVAS = Canvas(width_px=320, height_px=180, fps=15, duration=1.0)
FRAMES = [i / CANVAS.fps for i in range(CANVAS.fps)]

SQUARE = Spec(type="Square", params={"side_length": 3}, style={"fill": "#3b82f6", "fill_opacity": 0.6})
CIRCLE = Spec(type="Circle", params={"radius": 1.5}, style={"fill": "#ef4444", "fill_opacity": 0.5})
TEXT = Spec(type="Text", params={"text": "Hi ok"})
MATH = Spec(type="MathTex", params={"text": r"e^{i\pi}+1=0"})


# Pixel tolerance: Cairo anti-aliasing may round differently by one level.
TOLERANCE = 1


def single_clip_project(kind: str, spec: Spec, ease: Easing | None = None) -> Project:
    clip = Clip(id="c", kind=kind, start=0.0, duration=1.0, ease=ease)
    return Project(canvas=CANVAS, layers=[Layer(id="a", spec=spec, clips=[clip])])


def sequential_reference(kind: str, spec: Spec, ease: Easing | None = None) -> list[np.ndarray]:
    """Frames exactly as ``Scene.play`` produces them: begin, interpolate in order."""
    camera = make_camera(CANVAS)
    mob = adapter.build_mobject(spec)
    anim = adapter.make_animation(kind, mob, ease, {})
    anim.begin()
    drawn = [mob, anim.mobject] if CLIP_KIND_INFO[kind].overlay else [anim.mobject]  # ADR 0022
    frames = []
    for t in FRAMES:
        anim.interpolate(t / 1.0)
        frames.append(render_frame(camera, drawn))
    return frames


def render_in_order(
    project: Project, order: list[int], fresh_each_frame: bool = False
) -> dict[int, np.ndarray]:
    """Render FRAMES[i] for i in ``order`` with one evaluator (or a new one per frame)."""
    camera = make_camera(CANVAS)
    evaluator = Evaluator(project)
    out = {}
    for i in order:
        if fresh_each_frame:
            evaluator = Evaluator(project)
        out[i] = render_frame(camera, evaluator.frame(FRAMES[i]))
    return out


def max_diff(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.abs(a.astype(int) - b.astype(int)).max())


def assert_frames_equal(reference: list[np.ndarray], got: dict[int, np.ndarray], label: str) -> None:
    for i, ref in enumerate(reference):
        diff = max_diff(ref, got[i])
        assert diff <= TOLERANCE, f"{label}: frame {i} differs by {diff}"


def assert_evaluators_agree(a: Evaluator, b: Evaluator) -> None:
    camera = make_camera(CANVAS)
    for t in FRAMES:
        diff = max_diff(render_frame(camera, a.frame(t)), render_frame(camera, b.frame(t)))
        assert diff <= TOLERANCE, f"t={t}: differs by {diff}"
