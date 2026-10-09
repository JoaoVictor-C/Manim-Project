"""Property tests over random projects (ADR 0002 purity, ADR 0008 invalidation).

Targeted tests check known cases; these generate many valid projects from a fixed
seed and assert the two contracts every project must satisfy:

1. frames do not depend on the order they are requested in;
2. an edit applied through ``invalidate`` renders like a freshly built evaluator.

Seeds are fixed so failures are reproducible: a failing case prints its seed.
"""

from __future__ import annotations

import random

import pytest

from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import (
    CLIP_KIND_INFO,
    Canvas,
    Clip,
    Easing,
    Keyframe,
    Layer,
    Project,
    Spec,
    Transform2D,
)
from manim_studio.render.cairo_export import make_camera, render_frame
from support import max_diff

CANVAS = Canvas(width_px=160, height_px=90, fps=8, duration=1.0)
TIMES = [i / CANVAS.fps for i in range(CANVAS.fps)]
SPECS = [
    Spec(type="Square", style={"fill": "#22c55e", "fill_opacity": 0.7}),
    Spec(type="Circle", params={"radius": 1.2}),
    Spec(type="Triangle", style={"fill": "#eab308", "fill_opacity": 0.5}),
    Spec(type="Text", params={"text": "Ab"}),
]
EASES = [
    None,
    Easing(name="linear"),
    Easing(name="there_and_back"),
    Easing(bezier=(0.34, 1.56, 0.64, 1.0)),
]
NON_MORPH = [k for k, v in CLIP_KIND_INFO.items() if v.category != "morph"]
MORPH = [k for k, v in CLIP_KIND_INFO.items() if v.category == "morph"]
SEEDS = range(12)


def random_project(rng: random.Random) -> Project:
    n_layers = rng.randint(1, 3)
    with_morph = rng.random() < 0.5  # decided first so layer 0 leaves room for it
    layers = []
    for i in range(n_layers):
        limit = CANVAS.duration - 0.3 if (with_morph and i == 0) else CANVAS.duration
        clips, t = [], round(rng.uniform(0, 0.2), 2)
        for j in range(rng.randint(0, 3)):
            duration = round(rng.uniform(0.15, 0.4), 2)
            if t + duration > limit:
                break
            clips.append(
                Clip(
                    id=f"c{j}", kind=rng.choice(NON_MORPH), start=t, duration=duration, ease=rng.choice(EASES)
                )
            )
            t = round(t + duration + rng.choice([0, 0, 0.1]), 2)
        tracks = {}
        if rng.random() < 0.5:
            tracks["position"] = [
                Keyframe(
                    t=0, value=(rng.uniform(-3, 3), rng.uniform(-1, 1)), ease=rng.choice(EASES) or Easing()
                ),
                Keyframe(t=1, value=(rng.uniform(-3, 3), rng.uniform(-1, 1))),
            ]
        if rng.random() < 0.3:
            tracks["opacity"] = [Keyframe(t=0, value=1.0), Keyframe(t=1, value=rng.uniform(0.2, 1))]
        layers.append(
            Layer(
                id=f"l{i}",
                spec=rng.choice(SPECS),
                base=Transform2D(scale=rng.uniform(0.6, 1.2), rotation=rng.uniform(-30, 30)),
                tracks=tracks,
                clips=clips,
            )
        )
    # Sometimes end the first layer with a morph into a new, clip-less layer (ADR 0005).
    first = layers[0]
    last_end = max((c.end for c in first.clips), default=0.0)
    if with_morph:
        morph = Clip(id="m", kind=rng.choice(MORPH), start=last_end, duration=0.3, to_layer="target")
        layers[0] = first.model_copy(update={"clips": [*first.clips, morph]})
        layers.append(Layer(id="target", spec=rng.choice(SPECS), base=Transform2D(position=(1.5, 0.5))))
    return Project.model_validate(Project(canvas=CANVAS, layers=layers).model_dump(by_alias=True))


def render_all(evaluator: Evaluator, order: list[float]) -> dict[float, object]:
    camera = make_camera(CANVAS)
    return {t: render_frame(camera, evaluator.frame(t)) for t in order}


@pytest.mark.parametrize("seed", SEEDS)
def test_frames_are_order_independent(seed: int) -> None:
    rng = random.Random(seed)
    project = random_project(rng)
    scrambled = render_all(Evaluator(project), [*TIMES, *rng.sample(TIMES, len(TIMES)), *reversed(TIMES)])
    camera = make_camera(CANVAS)
    for t in TIMES:
        fresh = render_frame(camera, Evaluator(project).frame(t))
        assert max_diff(scrambled[t], fresh) <= 1, f"seed={seed} t={t}"


@pytest.mark.parametrize("seed", SEEDS)
def test_random_edits_match_fresh_evaluator(seed: int) -> None:
    rng = random.Random(1000 + seed)
    project = random_project(rng)
    evaluator = Evaluator(project)
    render_all(evaluator, TIMES)  # warm every cache

    edited = project.model_copy(deep=True)
    layer = rng.choice(edited.layers)
    transform_only = rng.random() < 0.5 or not layer.clips
    if transform_only:
        layer.base = Transform2D(
            position=(rng.uniform(-2, 2), rng.uniform(-1, 1)), rotation=rng.uniform(-90, 90)
        )
    else:
        clip = rng.choice([c for c in layer.clips if c.info.category != "morph"] or layer.clips)
        shifted = clip.model_copy(update={"ease": rng.choice(EASES)})
        layer.clips = [shifted if c is clip else c for c in layer.clips]
    edited = Project.model_validate(edited.model_dump(by_alias=True))
    evaluator.invalidate(edited, {layer.id}, transform_only=transform_only)

    got = render_all(evaluator, TIMES)
    camera = make_camera(CANVAS)
    fresh = Evaluator(edited)
    for t in TIMES:
        assert max_diff(got[t], render_frame(camera, fresh.frame(t))) <= 1, f"seed={seed} t={t}"
