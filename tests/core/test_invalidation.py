"""Incremental invalidation (ADR 0008): after an edit, the cached evaluator must
render exactly like a freshly built one."""

from __future__ import annotations

import pytest

from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Clip, Layer, Project, Spec, Transform2D
from support import CANVAS, FRAMES, SQUARE, TEXT, assert_evaluators_agree


def _warm(evaluator: Evaluator) -> Evaluator:
    for t in FRAMES:
        evaluator.frame(t)  # fill every cache
    return evaluator


def test_clip_edit_matches_fresh_evaluator() -> None:
    layers = [
        Layer(id="a", spec=SQUARE, clips=[Clip(id="c", kind="Create", start=0.0, duration=0.6)]),
        Layer(id="b", spec=TEXT, clips=[Clip(id="w", kind="Write", start=0.2, duration=0.6)]),
    ]
    project = Project(canvas=CANVAS, layers=layers)
    evaluator = _warm(Evaluator(project))

    edited = project.model_copy(deep=True)
    edited.layers[0].clips[0] = Clip(id="c", kind="GrowFromCenter", start=0.3, duration=0.5)
    evaluator.invalidate(edited, {"a"})
    assert_evaluators_agree(evaluator, Evaluator(edited))


@pytest.mark.parametrize("transform_only", [False, True])
def test_morph_target_edit_refreshes_source(transform_only: bool) -> None:
    """Moving the morph TARGET must refresh the source layer's morph clip."""
    layers = [
        Layer(
            id="a", spec=SQUARE, clips=[Clip(id="m", kind="Transform", start=0.2, duration=0.6, to_layer="b")]
        ),
        Layer(
            id="b", spec=Spec(type="Circle", params={"radius": 1.0}), base=Transform2D(position=(-2.0, 0.0))
        ),
    ]
    project = Project(canvas=CANVAS, layers=layers)
    evaluator = _warm(Evaluator(project))

    edited = project.model_copy(deep=True)
    edited.layers[1].base = Transform2D(position=(2.5, 1.0), scale=0.5)
    evaluator.invalidate(edited, {"b"}, transform_only=transform_only)
    assert_evaluators_agree(evaluator, Evaluator(edited))


def test_transform_only_edit_keeps_active_clip() -> None:
    """A gizmo drag during an active Write must not need the clip rebuilt."""
    layer = Layer(id="a", spec=TEXT, clips=[Clip(id="w", kind="Write", start=0.0, duration=1.0)])
    project = Project(canvas=CANVAS, layers=[layer])
    evaluator = Evaluator(project)
    evaluator.frame(0.5)

    edited = project.model_copy(deep=True)
    edited.layers[0].base = Transform2D(position=(1.0, -1.0), rotation=30.0)
    evaluator.invalidate(edited, {"a"}, transform_only=True)
    assert_evaluators_agree(evaluator, Evaluator(edited))


def test_missing_checkpoints_drain() -> None:
    """Idle-time precompute (ADR 0009) visits every checkpoint exactly once."""
    clips = [Clip(id=str(i), kind="Indicate", start=i * 0.2, duration=0.2) for i in range(4)]
    project = Project(canvas=CANVAS, layers=[Layer(id="a", spec=SQUARE, clips=clips)])
    evaluator = Evaluator(project)
    assert len(evaluator.missing_checkpoints()) == 4
    while missing := evaluator.missing_checkpoints():
        evaluator.compute_checkpoint(*missing[0])
    assert evaluator.missing_checkpoints() == []
