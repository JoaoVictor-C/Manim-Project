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

from manim_studio.core.editing import edits
from manim_studio.core.engine import adapter
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import (
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
NON_MORPH = [
    k for k, v in CLIP_KIND_INFO.items() if v.category not in ("morph", "motion")
]  # motion: 2 layers
MORPH = [
    k for k, v in CLIP_KIND_INFO.items() if v.category == "morph" and k != "TransformMatchingTex"
]  # TeX only
SEEDS = range(12)


def random_project(rng: random.Random) -> Project:
    n_layers = rng.randint(1, 3)
    with_morph = rng.random() < 0.5  # decided first so layer 0 leaves room for it
    layers = []
    for i in range(n_layers):
        limit = CANVAS.duration - 0.3 if (with_morph and i == 0) else CANVAS.duration
        spec = rng.choice(SPECS)
        kinds = [k for k in NON_MORPH if k in adapter.allowed_clip_kinds(spec.type)]
        clips, t = [], round(rng.uniform(0, 0.2), 2)
        for j in range(rng.randint(0, 3)):
            duration = round(rng.uniform(0.15, 0.4), 2)
            if t + duration > limit:
                break
            clips.append(
                Clip(id=f"c{j}", kind=rng.choice(kinds), start=t, duration=duration, ease=rng.choice(EASES))
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
                spec=spec,
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


def _gaps(layer: Layer, min_length: float = 0.15) -> list[tuple[float, float]]:
    """Free intervals on a lane where a clip may go (never after a morph)."""
    if any(c.info.category == "morph" for c in layer.clips):
        return []
    edges = [0.0, *(t for c in layer.clips for t in (c.start, c.end)), CANVAS.duration]
    pairs = zip(edges[::2], edges[1::2], strict=True)
    return [(lo, hi) for lo, hi in pairs if hi - lo >= min_length]


def random_edit(rng: random.Random, project: Project) -> edits.Edit:
    """One random edit through the public edit API, kept valid by construction."""
    layer = rng.choice(project.layers)
    movable = [c for c in layer.clips]
    ops = ["base", "add_layer", "move_layer"]
    if movable:
        ops += ["move", "trim", "ease", "remove_clip"]
    if _gaps(layer):
        ops.append("add_clip")
    if len(project.layers) > 1:
        ops.append("remove_layer")
    op = rng.choice(ops)
    if op == "base":
        base = Transform2D(position=(rng.uniform(-2, 2), rng.uniform(-1, 1)), rotation=rng.uniform(-90, 90))
        return edits.update_layer(project, layer.id, base=base)
    if op == "add_layer":
        return edits.add_layer(project, rng.choice(SPECS), index=rng.randint(0, len(project.layers)))
    if op == "move_layer":
        return edits.move_layer(project, layer.id, rng.randrange(len(project.layers)))
    if op == "remove_layer":
        return edits.remove_layer(project, layer.id)
    if op == "add_clip":
        lo, hi = rng.choice(_gaps(layer))
        duration = round(rng.uniform(0.1, hi - lo), 3)
        start = rng.uniform(lo, hi - duration)
        return edits.add_clip(
            project, layer.id, rng.choice(NON_MORPH), start, duration, ease=rng.choice(EASES)
        )
    index = rng.randrange(len(movable))
    clip = movable[index]
    if op == "remove_clip":
        return edits.remove_clip(project, layer.id, clip.id)
    lo = layer.clips[index - 1].end if index > 0 else 0.0
    hi = layer.clips[index + 1].start if index + 1 < len(layer.clips) else CANVAS.duration
    if op == "move":
        return edits.move_clip(project, layer.id, clip.id, rng.uniform(lo, hi - clip.duration))
    if op == "trim":
        end = rng.uniform(clip.start + 0.05, hi)
        return edits.trim_clip(project, layer.id, clip.id, end=end)
    return edits.update_clip(project, layer.id, clip.id, ease=rng.choice(EASES))


@pytest.mark.parametrize("seed", SEEDS)
def test_random_edits_match_fresh_evaluator(seed: int) -> None:
    """ADR 0013: applying an Edit with its computed kind renders like a rebuilt evaluator."""
    rng = random.Random(1000 + seed)
    project = random_project(rng)
    evaluator = Evaluator(project)
    render_all(evaluator, TIMES)  # warm every cache
    for _ in range(4):
        edit = random_edit(rng, project)
        evaluator.apply(edit)
        project = edit.project
        got = render_all(evaluator, TIMES)
        camera = make_camera(CANVAS)
        fresh = Evaluator(project)
        for t in TIMES:
            diff = max_diff(got[t], render_frame(camera, fresh.frame(t)))
            assert diff <= 1, f"seed={seed} kind={edit.kind} t={t}"
