"""Random-access evaluation must equal Manim's sequential play loop (ADR 0002, 0007).

A timeline editor requests frames shuffled, reversed and repeated; every frame
must still match what ``Scene.play`` renders when played straight through.
"""

from __future__ import annotations

import random

import pytest

from manim_studio.core.engine import adapter
from manim_studio.core.model.schema import CLIP_KIND_INFO, SMART_MORPHS, Clip, Easing, Layer, Project
from manim_studio.render.cairo_export import make_camera, render_frame
from support import (
    CANVAS,
    CIRCLE,
    FRAMES,
    MATH,
    SQUARE,
    TEXT,
    assert_frames_equal,
    render_in_order,
    sequential_reference,
    single_clip_project,
)

NON_MORPH = [
    k for k, v in CLIP_KIND_INFO.items() if v.category not in ("morph", "motion")
]  # motion: test_paths.py
MORPH = [
    k for k, v in CLIP_KIND_INFO.items() if v.category == "morph" and k != "TransformMatchingTex"
]  # TeX only: test_matching_tex.py


@pytest.mark.parametrize("spec", [SQUARE, TEXT], ids=lambda s: s.type)
@pytest.mark.parametrize("kind", NON_MORPH)
def test_single_clip_random_access(kind: str, spec) -> None:
    if kind not in adapter.allowed_clip_kinds(spec.type):
        pytest.skip(f"{kind} is not offered on {spec.type}")
    project = single_clip_project(kind, spec)
    reference = sequential_reference(kind, spec)
    n = len(FRAMES)
    shuffled = random.Random(0).sample(range(n), n)
    scrub = list(range(n)) + list(reversed(range(n))) + shuffled

    assert_frames_equal(reference, render_in_order(project, shuffled, fresh_each_frame=True), "fresh")
    assert_frames_equal(reference, render_in_order(project, scrub), "reused")


@pytest.mark.latex
@pytest.mark.parametrize("kind", ["Write", "FadeIn", "Indicate", "Create"])
def test_mathtex_random_access(kind: str) -> None:
    project = single_clip_project(kind, MATH)
    reference = sequential_reference(kind, MATH)
    order = random.Random(1).sample(range(len(FRAMES)), len(FRAMES))
    assert_frames_equal(reference, render_in_order(project, order), "mathtex")


@pytest.mark.parametrize("params", [{}, {"match": "classic"}, {"match": "smart"}], ids=str)
@pytest.mark.parametrize("kind", MORPH)
def test_morph_random_access(kind: str, params: dict) -> None:
    if params and params.get("match") and kind not in SMART_MORPHS:
        pytest.skip(f"{kind} has no matching choice")
    clip = Clip(id="m", kind=kind, start=0, duration=1, to_layer="b", params=params)
    layers = [Layer(id="a", spec=SQUARE, clips=[clip]), Layer(id="b", spec=CIRCLE)]
    project = Project(canvas=CANVAS, layers=layers)

    camera = make_camera(CANVAS)
    anim = adapter.make_animation(
        kind, adapter.build_mobject(SQUARE), None, params, adapter.build_mobject(CIRCLE)
    )
    anim.begin()
    reference = []
    for t in FRAMES:
        anim.interpolate(t)
        reference.append(render_frame(camera, [anim.mobject]))

    order = random.Random(2).sample(range(len(FRAMES)), len(FRAMES))
    assert_frames_equal(reference, render_in_order(project, order), kind)


def test_checkpoint_chain_matches_sequential() -> None:
    """Three clips in a row: jumping into the last one must replay the earlier ones."""
    clips = [
        Clip(id="1", kind="Create", start=0.0, duration=0.4),
        Clip(id="2", kind="Indicate", start=0.4, duration=0.3),
        Clip(id="3", kind="FadeOut", start=0.7, duration=0.3),
    ]
    project = Project(canvas=CANVAS, layers=[Layer(id="a", spec=SQUARE, clips=clips)])

    camera = make_camera(CANVAS)
    mob = adapter.build_mobject(SQUARE)
    reference = []
    for clip in clips:
        anim = adapter.make_animation(clip.kind, mob, None, {})
        anim.begin()
        for t in FRAMES:
            if clip.start <= t < clip.end:
                anim.interpolate((t - clip.start) / clip.duration)
                reference.append(render_frame(camera, [anim.mobject]))
        anim.finish()
        mob = anim.mobject

    order = list(reversed(range(len(FRAMES))))
    assert_frames_equal(reference, render_in_order(project, order), "chain")


EXTREME_EASES = {
    "back-out": Easing(bezier=(0.34, 1.56, 0.64, 1.0)),
    "anticipate": Easing(bezier=(0.6, -0.6, 0.7, 1.0)),
    "there-and-back": Easing(name="there_and_back"),
    "rush-into": Easing(name="rush_into"),
}


@pytest.mark.parametrize("ease", EXTREME_EASES, ids=str)
@pytest.mark.parametrize("kind", ["Create", "Write", "FadeIn", "GrowFromCenter", "Indicate", "Uncreate"])
def test_extreme_easing_random_access(kind: str, ease: str) -> None:
    """ADR 0007: overshooting curves are clamped, and frames stay order-independent."""
    project = single_clip_project(kind, TEXT, EXTREME_EASES[ease])
    reference = sequential_reference(kind, TEXT, EXTREME_EASES[ease])
    order = random.Random(5).sample(range(len(FRAMES)), len(FRAMES))
    assert_frames_equal(reference, render_in_order(project, order), f"{kind}/{ease}")


def test_frame_layers_names_what_frame_draws() -> None:
    """S3.1: frame(t) is frame_layers(t) without the ids; a morph belongs to its source."""
    from manim_studio.core.engine.evaluator import Evaluator
    from support import CIRCLE, SQUARE

    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(
                id="a",
                spec=SQUARE,
                clips=[Clip(id="m", kind="Transform", start=0.2, duration=0.4, to_layer="b")],
            ),
            Layer(id="b", spec=CIRCLE),
            Layer(id="c", spec=CIRCLE, lifetime={"in": 0.5}),
        ],
    )
    evaluator = Evaluator(project)
    assert [i for i, _ in evaluator.frame_layers(0.1)] == ["a"]
    assert [i for i, _ in evaluator.frame_layers(0.4)] == ["a"]  # morphing: drawn by the source
    assert [i for i, _ in evaluator.frame_layers(0.8)] == ["b", "c"]
    for t in FRAMES:
        assert [id(m) for m in evaluator.frame(t)] == [id(m) for _, m in evaluator.frame_layers(t)]
