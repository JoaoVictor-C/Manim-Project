"""Editable animation recipes (ADR 0080): a sequence's animation applied to other layers as a new sequence
whose length, delay between layers and layer order stay editable."""

from __future__ import annotations

import json

import numpy as np
import pytest

from manim_studio.core.editing import library
from manim_studio.core.editing.edits import EditError
from manim_studio.core.editing.recipes import apply_recipe, make_recipe, recipe_parameters
from manim_studio.core.editing.sequences import (
    Members,
    make_sequence,
    member_layers,
    reparameterise_sequence,
    restagger_sequence,
    retime_sequence,
    span,
)
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Canvas, Clip, Keyframe, Layer, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame

SQUARE = {"fill": "#3b82f6", "fill_opacity": 0.8}
CIRCLE = {"stroke": "#f59e0b"}


def scene() -> Project:
    """``a`` and ``b`` animated (the source); ``c`` and ``d`` still (the targets)."""
    return Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=10.0),
        layers=[
            Layer(
                id="a",
                spec=Spec(type="Square", style=SQUARE),
                base=Transform2D(position=(-4.0, 2.0)),
                clips=[Clip(id="f", kind="FadeIn", start=1.0, duration=1.0)],
                tracks={"scale": [Keyframe(t=1.0, value=1.0), Keyframe(t=2.0, value=1.5)]},
            ),
            Layer(
                id="b",
                spec=Spec(type="Circle", style=CIRCLE),
                base=Transform2D(position=(-4.0, -2.0)),
                clips=[Clip(id="w", kind="Create", start=1.5, duration=1.0)],
            ),
            Layer(id="c", spec=Spec(type="Square", style=SQUARE), base=Transform2D(position=(2.0, 1.0))),
            Layer(id="d", spec=Spec(type="Circle", style=CIRCLE), base=Transform2D(position=(2.0, -1.5))),
            Layer(id="t", spec=Spec(type="Text", params={"text": "Hi"})),
        ],
    )


def grouped() -> Project:
    members = Members(clips=(("a", "f"), ("b", "w")), keys=(("a", "scale", 1.0), ("a", "scale", 2.0)))
    return make_sequence(scene(), "Pair", members).project


def pair_recipe() -> library.Recipe:
    project = grouped()
    return make_recipe(project, project.sequences[0].id, "Pop pair")


def clips_of(project: Project, layer_id: str) -> list[tuple[str, float, float]]:
    return [(c.kind, round(c.start, 6), round(c.duration, 6)) for c in project.layer(layer_id).clips]


def test_make_a_recipe_from_a_two_layer_sequence() -> None:
    recipe = pair_recipe()
    assert recipe.name == "Pop pair" and len(recipe.slots) == 2
    first, second = recipe.slots
    assert (first.offset, second.offset) == (0.0, 0.5)
    assert [(c.kinds, c.offset, c.duration) for c in first.clips] == [(["FadeIn"], 0.0, 1.0)]
    assert [(k.dt, k.value) for k in first.keys["scale"]] == [(0.0, 1.0), (1.0, 1.5)]
    assert [(c.kinds, c.offset) for c in second.clips] == [(["Create"], 0.0)] and not second.keys
    assert recipe.stagger == 0.5 and recipe.length is None
    assert recipe.natural_length == pytest.approx(1.5)
    assert "Pair" in recipe.description


def test_apply_to_two_other_layers_at_3_with_another_length_and_stagger() -> None:
    edit = apply_recipe(grouped(), pair_recipe(), ["c", "d"], 3.0, length=3.0, stagger=1.0)
    project = edit.project
    # each part stretched by one factor (2) so the whole lasts 3 s with the 1 s delay kept
    assert clips_of(project, "c") == [("FadeIn", 3.0, 2.0)]
    assert clips_of(project, "d") == [("Create", 4.0, 2.0)]
    assert [(k.t, k.value) for k in project.layer("c").tracks["scale"]] == [(3.0, 1.0), (5.0, 1.5)]
    seq = project.sequences[-1]
    assert (seq.name, seq.recipe) == ("Pop pair", "Pop pair")
    assert span(project, seq) == (3.0, 6.0)
    assert member_layers(project, seq) == ["c", "d"]
    assert recipe_parameters(project, seq.id) == (3.0, 1.0)
    assert clips_of(project, "a") == clips_of(grouped(), "a")  # the source is untouched


def test_defaults_are_the_recipe_as_made_and_the_order_is_the_layers_order() -> None:
    project = apply_recipe(grouped(), pair_recipe(), ["d", "c"], 0.0).project
    assert clips_of(project, "d") == [("FadeIn", 0.0, 1.0)]  # the first layer takes the first role
    assert clips_of(project, "c") == [("Create", 0.5, 1.0)]


def test_the_applied_recipe_draws_as_the_hand_built_animation() -> None:
    applied = apply_recipe(grouped(), pair_recipe(), ["c", "d"], 3.0, length=3.0, stagger=1.0).project
    by_hand = grouped()
    layers = []
    for layer in by_hand.layers:
        if layer.id == "c":
            layer = layer.model_copy(
                update={
                    "clips": [Clip(id="fadein-1", kind="FadeIn", start=3.0, duration=2.0)],
                    "tracks": {"scale": [Keyframe(t=3.0, value=1.0), Keyframe(t=5.0, value=1.5)]},
                }
            )
        elif layer.id == "d":
            layer = layer.model_copy(
                update={"clips": [Clip(id="create-1", kind="Create", start=4.0, duration=2.0)]}
            )
        layers.append(layer)
    by_hand = Project.model_validate({**by_hand.model_dump(by_alias=True), "layers": layers})
    assert by_hand.layer("c").lifetime == applied.layer("c").lifetime
    frames = []
    for t in (2.0, 3.5, 4.5, 5.5, 6.5):
        a = render_frame(make_camera(applied.canvas), Evaluator(applied).frame(t))
        b = render_frame(make_camera(by_hand.canvas), Evaluator(by_hand).frame(t))
        assert np.array_equal(a, b), t
        frames.append(a)
    assert not np.array_equal(frames[0], frames[2])  # the targets do move: the frames are not trivial


def test_a_one_role_recipe_repeats_over_any_number_of_layers() -> None:
    project = make_sequence(scene(), "Fade", Members(clips=(("a", "f"),))).project
    recipe = make_recipe(project, project.sequences[0].id, "Fade in")
    assert len(recipe.slots) == 1 and recipe.stagger is None
    applied = apply_recipe(project, recipe, ["c", "d", "t"], 1.0, stagger=0.5).project
    assert clips_of(applied, "c") == [("FadeIn", 1.0, 1.0)]
    assert clips_of(applied, "d") == [("FadeIn", 1.5, 1.0)]
    assert clips_of(applied, "t") == [("FadeIn", 2.0, 1.0)]
    with pytest.raises(EditError, match=r"b: Fade in does not fit at 2 s: .*overlap"):
        apply_recipe(project, recipe, ["c", "d", "b"], 1.0, stagger=0.5)


def test_parameters_can_be_changed_afterwards() -> None:
    project = apply_recipe(grouped(), pair_recipe(), ["c", "d"], 3.0, length=3.0, stagger=1.0).project
    seq_id = project.sequences[-1].id
    longer = reparameterise_sequence(project, seq_id, length=4.0, stagger=0.5).project
    assert clips_of(longer, "c") == [("FadeIn", 3.0, 3.5)]
    assert clips_of(longer, "d") == [("Create", 3.5, 3.5)]
    assert [k.t for k in longer.layer("c").tracks["scale"]] == [3.0, 6.5]
    assert recipe_parameters(longer, seq_id) == (pytest.approx(4.0), 0.5)
    together = restagger_sequence(project, seq_id, 0.0).project
    assert clips_of(together, "d") == [("Create", 3.0, 2.0)] and clips_of(together, "c") == [
        ("FadeIn", 3.0, 2.0)
    ]
    swapped = restagger_sequence(project, seq_id, 1.0, order=["d", "c"]).project
    assert clips_of(swapped, "d") == [("Create", 3.0, 2.0)] and clips_of(swapped, "c") == [
        ("FadeIn", 4.0, 2.0)
    ]
    assert [k.t for k in swapped.layer("c").tracks["scale"]] == [4.0, 6.0]
    assert swapped.sequences[-1].recipe == "Pop pair"
    assert retime_sequence(project, seq_id, 6.0).project.layer("d").clips[0].start == 5.0
    assert reparameterise_sequence(project, seq_id).project is project


def test_refusals_say_why() -> None:
    project, recipe = grouped(), pair_recipe()
    with pytest.raises(EditError, match="animates 2 layers: select 2"):
        apply_recipe(project, recipe, ["c"], 0.0)
    with pytest.raises(EditError, match="select the layers"):
        apply_recipe(project, recipe, [], 0.0)
    with pytest.raises(EditError, match="chosen twice"):
        apply_recipe(project, recipe, ["c", "c"], 0.0)
    with pytest.raises(EditError, match="delays between layers alone"):
        apply_recipe(project, recipe, ["c", "d"], 0.0, length=0.5, stagger=1.0)
    with pytest.raises(EditError, match="one frame"):
        apply_recipe(project, recipe, ["c", "d"], 0.0, length=0.05, stagger=0.0)
    with pytest.raises(EditError, match="below 0 s"):
        apply_recipe(project, recipe, ["c", "d"], 0.0, stagger=-1.0)
    with pytest.raises(EditError, match="no layer"):
        apply_recipe(project, recipe, ["c", "zz"], 0.0)
    with pytest.raises(EditError, match="order must list"):
        reparameterise_sequence(project, project.sequences[0].id, stagger=1.0, order=["a"])
    text = Project(
        canvas=scene().canvas,
        layers=[
            Layer(
                id="t",
                spec=Spec(type="Text", params={"text": "Hi"}),
                clips=[Clip(id="l", kind="AddTextLetterByLetter", start=0.0, duration=1.0)],
            ),
            Layer(id="c", spec=Spec(type="Square")),
        ],
    )
    text = make_sequence(text, "Type", Members(clips=(("t", "l"),))).project
    typed = make_recipe(text, text.sequences[0].id, "Type")
    with pytest.raises(EditError, match="c: Type cannot be used on a Square"):
        apply_recipe(text, typed, ["c"], 0.0)
    with pytest.raises(EditError, match="a recipe needs a name"):
        make_recipe(text, text.sequences[0].id, "  ")


def test_the_scene_grows_to_hold_the_recipe() -> None:
    edit = apply_recipe(grouped(), pair_recipe(), ["c", "d"], 9.0)
    assert clips_of(edit.project, "d") == [("Create", 9.5, 1.0)]
    assert edit.project.canvas.duration == pytest.approx(10.5)


def test_round_trip_of_the_recipe_file(tmp_path) -> None:
    recipe = pair_recipe()
    path = library.save_item(recipe, tmp_path)
    assert path.name == "recipe-Pop pair.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert (data["format"], data["kind"], len(data["slots"])) == ("manim-studio-library", "recipe", 2)
    loaded = library.load_library([tmp_path])
    assert loaded.recipes == [recipe] and not loaded.problems
    assert library.item_from_json(library.item_to_json(recipe)) == recipe
    bad = {**library.item_to_json(recipe), "slots": [{"offset": 0.0}]}
    with pytest.raises(ValueError, match="no clips and no keys"):
        library.item_from_json(bad)


def test_the_project_file_names_the_recipe_and_files_without_one_save_as_before() -> None:
    project = apply_recipe(grouped(), pair_recipe(), ["c", "d"], 3.0).project
    data = json.loads(project.model_dump_json(by_alias=True))
    assert [s.get("recipe") for s in data["sequences"]] == [None, "Pop pair"]
    assert "recipe" not in data["sequences"][0]
    assert Project.model_validate(data) == project
