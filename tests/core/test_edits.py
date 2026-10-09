"""Edit API and edit kinds (ADR 0013, ADR 0014)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from manim_studio.core import adapter, edits
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Clip, Easing, Keyframe, Layer, Project, Spec, Transform2D
from support import CANVAS, FRAMES, SQUARE, TEXT, assert_evaluators_agree

CIRCLE = Spec(type="Circle", params={"radius": 1.0})


def two_clip_project() -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(
                id="a",
                spec=TEXT,
                clips=[
                    Clip(id="w", kind="Write", start=0.0, duration=0.4),
                    Clip(id="i", kind="Indicate", start=0.5, duration=0.3),
                ],
            ),
            Layer(id="b", spec=SQUARE, clips=[Clip(id="g", kind="GrowFromCenter", start=0.2, duration=0.5)]),
        ],
    )


def morph_project(source_tracks=None, morph_start: float = 0.4) -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(
                id="a",
                spec=SQUARE,
                tracks=source_tracks or {},
                clips=[Clip(id="m", kind="Transform", start=morph_start, duration=0.4, to_layer="b")],
            ),
            Layer(id="b", spec=CIRCLE, base=Transform2D(position=(2.0, 0.5))),
        ],
    )


# -- edit functions -----------------------------------------------------------------


def test_move_returns_new_validated_snapshot_and_leaves_input_untouched() -> None:
    project = two_clip_project()
    edit = edits.move_clip(project, "a", "i", 0.6)
    assert edit.project.layer("a").clips[1].start == 0.6
    assert project.layer("a").clips[1].start == 0.5
    assert edit.kind == "timing"
    assert edit.layer_ids == {"a"}


def test_unchanged_layers_are_shared() -> None:
    project = two_clip_project()
    edit = edits.move_clip(project, "a", "i", 0.6)
    assert edit.project.layer("b") is project.layer("b")


def test_move_into_a_neighbour_raises() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        edits.move_clip(two_clip_project(), "a", "i", 0.3)


def test_trim_moves_one_edge_only() -> None:
    project = two_clip_project()
    right = edits.trim_clip(project, "a", "i", end=0.9).project.layer("a").clips[1]
    assert (right.start, right.end) == pytest.approx((0.5, 0.9))
    left = edits.trim_clip(project, "a", "i", start=0.45).project.layer("a").clips[1]
    assert (left.start, left.end) == pytest.approx((0.45, 0.8))


def test_trim_to_zero_length_raises() -> None:
    with pytest.raises(ValidationError):
        edits.trim_clip(two_clip_project(), "a", "i", end=0.5)


def test_unknown_layer_or_clip_raises_edit_error() -> None:
    with pytest.raises(edits.EditError, match="no layer"):
        edits.move_clip(two_clip_project(), "zz", "i", 0.1)
    with pytest.raises(edits.EditError, match="no clip"):
        edits.move_clip(two_clip_project(), "a", "zz", 0.1)


def test_project_rules_still_run_on_edits() -> None:
    """The edit path re-validates project-level rules (model_copy would skip them)."""
    with pytest.raises(ValidationError, match="after morph"):
        edits.update_layer(
            morph_project(),
            "a",
            clips=[
                Clip(id="m", kind="Transform", start=0.1, duration=0.3, to_layer="b"),
                Clip(id="f", kind="FadeOut", start=0.6, duration=0.2),
            ],
        )


# -- classification ------------------------------------------------------------------


def test_moving_a_morph_touches_both_partners() -> None:
    edit = edits.move_clip(morph_project(), "a", "m", 0.5)
    assert edit.kind == "timing"
    assert edit.layer_ids == {"a", "b"}


@pytest.mark.parametrize(
    ("change", "kind"),
    [
        (lambda p: edits.update_clip(p, "a", "i", duration=0.2), "timing"),
        (lambda p: edits.update_layer(p, "a", lifetime={"out": 0.9}), "timing"),
        (lambda p: edits.update_layer(p, "a", name="Title"), "timing"),
        (lambda p: edits.update_layer(p, "a", base=Transform2D(position=(1.0, 0.0))), "transform"),
        (lambda p: edits.update_layer(p, "a", tracks={"scale": [Keyframe(t=0, value=2.0)]}), "transform"),
        (lambda p: edits.update_clip(p, "a", "i", ease=Easing(name="linear")), "clip"),
        (lambda p: edits.update_clip(p, "a", "i", kind="Wiggle"), "clip"),
        (lambda p: edits.update_clip(p, "a", "i", params={"scale_factor": 1.5}), "clip"),
        (lambda p: edits.update_layer(p, "a", spec=SQUARE), "spec"),
    ],
)
def test_edit_kind_is_computed_from_the_diff(change, kind: str) -> None:
    assert change(two_clip_project()).kind == kind


def test_reordering_clips_by_start_times_is_a_clip_edit() -> None:
    """Same fields as a timing edit, but each clip's predecessor changes."""
    project = two_clip_project()
    swapped = edits.update_layer(
        project,
        "a",
        clips=[
            Clip(id="w", kind="Write", start=0.5, duration=0.4),
            Clip(id="i", kind="Indicate", start=0.0, duration=0.3),
        ],
    )
    assert swapped.kind == "clip"


def test_most_severe_kind_wins() -> None:
    project = two_clip_project()
    new = edits.update_layer(edits.move_clip(project, "a", "i", 0.6).project, "b", spec=CIRCLE).project
    assert edits.classify(project, new) == ("spec", frozenset({"a", "b"}))


def test_identical_snapshots_classify_as_no_change() -> None:
    project = two_clip_project()
    assert edits.classify(project, project) == ("timing", frozenset())


# -- evaluator: timing edits keep caches ---------------------------------------------


@pytest.fixture
def count_begins(monkeypatch):
    """Spy on adapter.make_animation: every call is a Manim begin() to come."""
    calls = []
    real = adapter.make_animation

    def spy(kind, *args, **kwargs):
        calls.append(kind)
        return real(kind, *args, **kwargs)

    monkeypatch.setattr(adapter, "make_animation", spy)
    return calls


def _warm(evaluator: Evaluator) -> Evaluator:
    for t in FRAMES:
        evaluator.frame(t)
    return evaluator


def test_timing_edits_never_rebuild_animations(count_begins) -> None:
    project = two_clip_project()
    evaluator = _warm(Evaluator(project))
    count_begins.clear()
    for start in (0.55, 0.6, 0.65, 0.7):
        edit = edits.move_clip(project, "a", "i", start)
        evaluator.apply(edit)
        project = edit.project
        _warm(evaluator)
    assert count_begins == []
    assert_evaluators_agree(evaluator, Evaluator(project))


def test_clip_edits_do_rebuild(count_begins) -> None:
    project = two_clip_project()
    evaluator = _warm(Evaluator(project))
    count_begins.clear()
    edit = edits.update_clip(project, "a", "i", ease=Easing(name="linear"))
    evaluator.apply(edit)
    _warm(evaluator)
    assert "Indicate" in count_begins
    assert_evaluators_agree(evaluator, Evaluator(edit.project))


def test_static_morph_moves_without_rebuilding(count_begins) -> None:
    project = morph_project()
    evaluator = _warm(Evaluator(project))
    count_begins.clear()
    edit = edits.move_clip(project, "a", "m", 0.5)
    evaluator.apply(edit)
    _warm(evaluator)
    assert count_begins == []
    assert_evaluators_agree(evaluator, Evaluator(edit.project))


@pytest.mark.parametrize(("start", "rebuilds"), [(0.5, False), (0.1, True)], ids=["settled", "mid-motion"])
def test_keyframed_morph_rebuilds_only_when_baked_transforms_change(count_begins, start, rebuilds) -> None:
    """Source moves over 0-0.3 s: moving the morph within the settled region reuses it."""
    tracks = {"position": [Keyframe(t=0.0, value=(-2.0, 0.0)), Keyframe(t=0.3, value=(0.0, 0.0))]}
    project = morph_project(tracks, morph_start=0.4)
    evaluator = _warm(Evaluator(project))
    count_begins.clear()
    edit = edits.move_clip(project, "a", "m", start)
    evaluator.apply(edit)
    _warm(evaluator)
    assert ("Transform" in count_begins) is rebuilds
    assert_evaluators_agree(evaluator, Evaluator(edit.project))


def test_transform_edit_of_morph_target_rebuilds_the_morph(count_begins) -> None:
    project = morph_project()
    evaluator = _warm(Evaluator(project))
    count_begins.clear()
    edit = edits.update_layer(project, "b", base=Transform2D(position=(-2.0, -1.0)))
    assert edit.kind == "transform"
    evaluator.apply(edit)
    _warm(evaluator)
    assert count_begins == ["Transform"]
    assert_evaluators_agree(evaluator, Evaluator(edit.project))


def test_undo_of_a_timing_edit_is_a_timing_edit() -> None:
    """ADR 0013: swapping snapshots back classifies the same way, so undo is cheap too."""
    project = two_clip_project()
    edit = edits.move_clip(project, "a", "i", 0.62)
    assert edits.classify(edit.project, project) == (edit.kind, edit.layer_ids)


# -- structure: layers and clips (S2.1) ----------------------------------------------


def test_add_layer_goes_on_top_with_a_free_id() -> None:
    project = two_clip_project()
    edit = edits.add_layer(project, Spec(type="MathTex", params={"text": "x"}))
    assert [layer.id for layer in edit.project.layers] == ["a", "b", "mathtex-1"]
    assert edit.kind == "clip" and edit.layer_ids == {"mathtex-1"}
    again = edits.add_layer(edit.project, Spec(type="MathTex"), index=0)
    assert [layer.id for layer in again.project.layers] == ["mathtex-2", "a", "b", "mathtex-1"]


def test_new_ids_take_the_smallest_free_number() -> None:
    project = Project(canvas=CANVAS, layers=[Layer(id="circle-2", spec=CIRCLE)])
    assert edits.new_layer_id(project, "Circle") == "circle-1"
    assert edits.new_layer_id(edits.add_layer(project, CIRCLE).project, "Circle") == "circle-3"
    assert edits.new_clip_id(two_clip_project().layer("a"), "FadeIn") == "fadein-1"


def test_remove_layer_also_removes_the_morph_into_it() -> None:
    """F6: deleting a morph target must not leave a dangling to_layer (one undo step)."""
    edit = edits.remove_layer(morph_project(), "b")
    assert [layer.id for layer in edit.project.layers] == ["a"]
    assert edit.project.layer("a").clips == []
    assert edit.layer_ids == {"a", "b"}
    assert edit.kind == "clip"


def test_remove_morph_source_frees_the_target() -> None:
    edit = edits.remove_layer(morph_project(), "a")
    assert edit.project.lifetime("b") == (0.0, float("inf"))


def test_move_layer_is_a_cheap_reorder() -> None:
    project = two_clip_project()
    edit = edits.move_layer(project, "b", 0)
    assert [layer.id for layer in edit.project.layers] == ["b", "a"]
    assert (edit.kind, edit.layer_ids) == ("timing", frozenset())
    assert edits.move_layer(project, "a", 99).project.layers[-1].id == "a"  # clamped to the front


def test_reorder_changes_draw_order_without_rebuilding(count_begins) -> None:
    project = two_clip_project()
    evaluator = _warm(Evaluator(project))
    count_begins.clear()
    edit = edits.move_layer(project, "b", 0)
    evaluator.apply(edit)
    assert count_begins == []
    assert_evaluators_agree(evaluator, Evaluator(edit.project))


def test_add_and_remove_clip() -> None:
    project = two_clip_project()
    edit = edits.add_clip(project, "b", "FadeOut", 0.8, 0.2, ease=Easing(name="linear"))
    clips = edit.project.layer("b").clips
    assert [c.id for c in clips] == ["g", "fadeout-1"]
    assert edit.kind == "clip" and edit.layer_ids == {"b"}
    removed = edits.remove_clip(edit.project, "b", "fadeout-1")
    assert removed.project == project


def test_add_clip_rules_are_validated() -> None:
    project = morph_project()
    with pytest.raises(ValidationError, match="overlap"):
        edits.add_clip(two_clip_project(), "a", "FadeIn", 0.3, 0.3)
    with pytest.raises(ValidationError, match="after morph"):
        edits.add_clip(project, "a", "FadeOut", 0.9, 0.05)
    with pytest.raises(ValidationError, match="two morphs"):
        edits.add_clip(
            edits.add_layer(project, SQUARE).project, "square-1", "Transform", 0, 0.2, to_layer="b"
        )
    with pytest.raises(ValidationError, match="needs to_layer"):
        edits.add_clip(project, "b", "Transform", 0.0, 0.2)


def test_add_morph_clip_gives_the_target_a_lifetime() -> None:
    project = edits.add_layer(two_clip_project(), CIRCLE).project
    edit = edits.add_clip(project, "b", "Transform", 0.8, 0.2, to_layer="circle-1")
    assert edit.layer_ids == {"b", "circle-1"}
    assert edit.project.lifetime("circle-1")[0] == pytest.approx(1.0)


def test_remove_unknown_things_raises_edit_error() -> None:
    with pytest.raises(edits.EditError):
        edits.remove_layer(two_clip_project(), "zz")
    with pytest.raises(edits.EditError):
        edits.remove_clip(two_clip_project(), "a", "zz")
    with pytest.raises(edits.EditError):
        edits.move_layer(two_clip_project(), "zz", 0)
    with pytest.raises(edits.EditError):
        edits.add_clip(two_clip_project(), "zz", "FadeIn", 0, 0.1)


def test_structural_edits_through_the_evaluator_match_a_fresh_one() -> None:
    project = two_clip_project()
    evaluator = _warm(Evaluator(project))
    steps = [
        lambda p: edits.add_layer(p, CIRCLE, index=1),
        lambda p: edits.add_clip(p, "circle-1", "GrowFromCenter", 0.1, 0.3),
        lambda p: edits.add_clip(p, "b", "Transform", 0.7, 0.2, to_layer="circle-1"),
        lambda p: edits.remove_clip(p, "a", "w"),
        lambda p: edits.move_layer(p, "a", 2),
        lambda p: edits.remove_layer(p, "circle-1"),
    ]
    for step in steps:
        edit = step(project)
        evaluator.apply(edit)
        project = edit.project
        _warm(evaluator)
        assert_evaluators_agree(evaluator, Evaluator(project))
