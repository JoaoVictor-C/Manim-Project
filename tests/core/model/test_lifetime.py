"""Layer lifetime (docs/project-format.md "Lifetime inference", ADR 0005).

Visibility is decided by the lifetime window, inferred from introducer/remover/
morph clips unless set explicitly. The lifetime gates everything, clips included.
"""

from __future__ import annotations

import pytest

from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Clip, Layer, Lifetime, Project, Spec

SQUARE = Spec(type="Square")
CIRCLE = Spec(type="Circle")


def visible(project: Project, layer_id: str, t: float) -> bool:
    """A layer is visible at t if the evaluator returns a mobject for it."""
    evaluator = Evaluator(project)
    layer = project.layer(layer_id)
    return evaluator._layer_at(layer, t) is not None


def test_layer_without_clips_is_always_visible() -> None:
    project = Project(layers=[Layer(id="a", spec=SQUARE)])
    assert visible(project, "a", 0.0) and visible(project, "a", 4.9)


def test_introducer_starts_the_lifetime() -> None:
    project = Project(
        layers=[Layer(id="a", spec=SQUARE, clips=[Clip(id="c", kind="Create", start=1, duration=1)])]
    )
    assert not visible(project, "a", 0.5)
    assert visible(project, "a", 1.0)
    assert visible(project, "a", 3.0)


def test_emphasis_first_clip_keeps_layer_visible_from_zero() -> None:
    project = Project(
        layers=[Layer(id="a", spec=SQUARE, clips=[Clip(id="c", kind="Indicate", start=2, duration=1)])]
    )
    assert visible(project, "a", 0.0)


def test_remover_ends_the_lifetime() -> None:
    clips = [
        Clip(id="c", kind="FadeIn", start=0, duration=1),
        Clip(id="o", kind="FadeOut", start=2, duration=1),
    ]
    project = Project(layers=[Layer(id="a", spec=SQUARE, clips=clips)])
    assert visible(project, "a", 2.5)
    assert not visible(project, "a", 3.0)
    assert not visible(project, "a", 4.0)


def test_morph_hands_off_between_layers() -> None:
    layers = [
        Layer(id="a", spec=SQUARE, clips=[Clip(id="m", kind="Transform", start=1, duration=1, to_layer="b")]),
        Layer(id="b", spec=CIRCLE),
    ]
    project = Project(layers=layers)
    assert visible(project, "a", 0.5) and not visible(project, "b", 0.5)
    assert visible(project, "a", 1.5) and not visible(project, "b", 1.5)  # the morph is drawn by "a"
    assert not visible(project, "a", 2.0) and visible(project, "b", 2.0)


def test_explicit_lifetime_overrides_inference() -> None:
    layer = Layer(
        id="a",
        spec=SQUARE,
        lifetime=Lifetime(in_=0.5, out=3.0),
        clips=[Clip(id="c", kind="Create", start=1, duration=1)],
    )
    project = Project(layers=[layer])
    assert not visible(project, "a", 0.4)
    assert visible(project, "a", 0.6)  # visible before its Create: shown in its pre-Create state
    assert not visible(project, "a", 3.0)


@pytest.mark.parametrize("t", [3.2, 3.6])
def test_lifetime_gates_clips_outside_it(t: float) -> None:
    """A clip placed after the explicit out-point must not bring the layer back."""
    layer = Layer(
        id="a",
        spec=SQUARE,
        lifetime=Lifetime(out=3.0),
        clips=[Clip(id="i", kind="Indicate", start=3.1, duration=0.8)],
    )
    assert not visible(Project(layers=[layer]), "a", t)


def test_frame_returns_only_visible_layers_in_z_order() -> None:
    layers = [
        Layer(id="back", spec=SQUARE),
        Layer(id="late", spec=CIRCLE, clips=[Clip(id="c", kind="FadeIn", start=2, duration=1)]),
        Layer(id="front", spec=Spec(type="Triangle")),
    ]
    evaluator = Evaluator(Project(layers=layers))
    assert len(evaluator.frame(1.0)) == 2
    assert len(evaluator.frame(2.5)) == 3
