"""Presets, themes and the library files (P5e.1, ADR 0039).

A preset is applied whole at the playhead or refused with a reason; its keys are
relative to the layer's transform and never change what was drawn before the
playhead; kinds fall back to what the object accepts. A theme recolours by kind.
Library files are versioned; bad ones are skipped with a message.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from manim_studio.core import edits, library
from manim_studio.core.edits import EditError
from manim_studio.core.evaluator import Evaluator, layer_transform
from manim_studio.core.library import Preset, Theme, apply_preset, apply_theme, load_library
from manim_studio.core.schema import Canvas, Clip, Keyframe, Layer, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=6.0)
BUILTINS = load_library([library.BUILTIN_FOLDER])


def preset(name: str) -> Preset:
    return next(p for p in BUILTINS.presets if p.name == name)


def scene(*layers: Layer) -> Project:
    return Project(canvas=CANVAS, layers=list(layers) or [Layer(id="s", spec=Spec(type="Square"))])


def frame(project: Project, t: float) -> np.ndarray:
    return render_frame(make_camera(project.canvas), Evaluator(project).frame(t))


# -- the built-in library ---------------------------------------------------------------------------------


def test_the_built_ins_load_without_problems() -> None:
    assert BUILTINS.problems == []
    for category in library.CATEGORIES:
        assert len(BUILTINS.presets_in(category)) >= 4, category
    assert [t.name for t in BUILTINS.themes] == ["Blueprint", "Chalkboard", "Manim", "Midnight", "Paper"]
    names = [p.name for p in BUILTINS.presets]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("name", [p.name for p in BUILTINS.presets])
def test_every_built_in_preset_applies_to_a_shape_and_keeps_the_past(name) -> None:
    square = Layer(id="s", spec=Spec(type="Square"), base=Transform2D(position=(1.0, 0.5), scale=1.5))
    before = scene(square)
    edit = apply_preset(before, "s", preset(name), 2.0)
    after = edit.project
    assert len(after.layer("s").clips) == len(preset(name).clips)
    enters = bool(after.layer("s").clips) and after.layer("s").clips[0].info.introducer
    empty = Project(canvas=CANVAS)
    for t in (0.0, 1.0, 1.9):  # before the playhead: as it was, or not there yet (an entrance)
        assert np.array_equal(frame(empty if enters else before, t), frame(after, t)), t
    assert edit.layer_ids == frozenset({"s"})


def test_typewriter_writes_letters_on_text_and_strokes_elsewhere() -> None:
    text = Layer(id="t", spec=Spec(type="Text", params={"text": "Hi"}))
    assert apply_preset(scene(text), "t", preset("Typewriter"), 0).project.layer("t").clips[0].kind == (
        "AddTextLetterByLetter"
    )
    assert apply_preset(scene(), "s", preset("Typewriter"), 0).project.layer("s").clips[0].kind == "Write"


def test_a_preset_no_kind_of_which_fits_is_refused(tmp_path) -> None:
    path = tmp_path / "p.png"
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(path)
    image = Layer(id="i", spec=Spec(type="ImageMobject", params={"path": str(path)}))
    with pytest.raises(EditError, match="Typewriter cannot be used on an image"):
        apply_preset(scene(image), "i", preset("Typewriter"), 0)
    assert apply_preset(scene(image), "i", preset("Fade in"), 0).project.layer("i").clips[0].kind == "FadeIn"
    assert apply_preset(scene(image), "i", preset("Wiggle"), 0).project.layer("i").clips[0].kind == "Indicate"


def test_params_go_only_to_the_kind_that_knows_them() -> None:
    clips = apply_preset(scene(), "s", preset("Circle it (round)"), 0).project.layer("s").clips
    assert clips[0].params == {"shape": "circle"}
    custom = Preset(
        name="Odd",
        category="emphasis",
        clips=[
            {"kinds": ["AddTextLetterByLetter", "Indicate"], "duration": 1, "params": {"shape": "circle"}}
        ],
    )
    assert apply_preset(scene(), "s", custom, 0).project.layer("s").clips[0].params == {}


def test_keys_are_relative_to_the_layer_and_the_past_is_held() -> None:
    square = Layer(id="s", spec=Spec(type="Square"), base=Transform2D(position=(1.0, 1.0), scale=2.0))
    project = apply_preset(scene(square), "s", preset("Pop in"), 1.0).project
    track = project.layer("s").tracks["scale"]
    assert [(round(k.t, 6), round(k.value, 6)) for k in track] == [
        (0.9, 2.0),
        (1.0, 1.2),
        (1.2, 2.24),  # 1.25 s lands on frame 12 (round half to even)
        (1.4, 2.0),
    ]
    drift = apply_preset(scene(square), "s", preset("Drift up"), 1.0).project.layer("s").tracks["position"]
    assert [(k.t, k.value) for k in drift] == [
        (1.0, (1.0, 1.0)),
        (3.0, (1.0, 1.5)),
    ]  # starts where it is: no hold
    assert drift[0].ease.name == "linear"


def test_keys_follow_earlier_keys_and_replace_keys_on_the_same_frames() -> None:
    moving = Layer(
        id="s",
        spec=Spec(type="Square"),
        tracks={"scale": [Keyframe(t=0.0, value=1.0), Keyframe(t=1.0, value=3.0)]},
    )
    project = apply_preset(scene(moving), "s", preset("Pulse"), 1.0).project
    track = project.layer("s").tracks["scale"]
    assert [(k.t, round(k.value, 6)) for k in track] == [(0.0, 1.0), (1.0, 3.0), (1.2, 3.45), (1.5, 3.0)]
    again = apply_preset(project, "s", preset("Pulse"), 1.0).project.layer("s").tracks["scale"]
    assert [k.t for k in again] == [k.t for k in track]  # same frames: replaced, not doubled


def test_at_the_start_no_hold_key_is_needed() -> None:
    track = apply_preset(scene(), "s", preset("Pop in"), 0.0).project.layer("s").tracks["scale"]
    assert track[0].t == 0.0 and track[0].value == pytest.approx(0.6)


def test_refused_when_it_does_not_fit() -> None:
    busy = Layer(
        id="s", spec=Spec(type="Square"), clips=[Clip(id="i", kind="Indicate", start=1.0, duration=1.0)]
    )
    with pytest.raises(EditError, match=r"Fade in does not fit at 0\.8 s"):
        apply_preset(scene(busy), "s", preset("Fade in"), 0.8)
    with pytest.raises(EditError, match="the scene ends at 6 s"):
        apply_preset(scene(), "s", preset("Drift up"), 5.0)
    with pytest.raises(EditError, match="no layer"):
        apply_preset(scene(), "zz", preset("Fade in"), 0)


def test_a_graph_on_axes_only_fades() -> None:
    axes = Layer(id="ax", spec=Spec(type="Axes"))
    graph = Layer(id="g", parent_id="ax", spec=Spec(type="Graph", params={"expression": "x"}))
    project = scene(axes, graph)
    with pytest.raises(
        EditError, match="Pop in cannot be used on a graph on axes: only its opacity can change"
    ):
        apply_preset(project, "g", preset("Pop in"), 0)
    assert apply_preset(project, "g", preset("Fade in"), 0).project.layer("g").clips[0].kind == "FadeIn"


def test_a_preset_applies_to_a_part() -> None:
    from manim_studio.core.schema import PartKey

    tex = Layer(id="m", spec=Spec(type="MathTex", params={"text": "a+b"}))
    part = Layer(id="p", parent_id="m", part=PartKey(tex="b"))
    project = apply_preset(scene(tex, part), "p", preset("Pulse"), 1.0).project
    assert [k.value for k in project.layer("p").tracks["scale"]] == pytest.approx([1.0, 1.15, 1.0])


# -- preset files -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"name": "x", "category": "entrance"}, "no clips and no keys"),
        (
            {"name": "x", "category": "entrance", "clips": [{"kinds": ["Transform"], "duration": 1}]},
            "needs another",
        ),
        (
            {"name": "x", "category": "entrance", "clips": [{"kinds": ["Teleport"], "duration": 1}]},
            "unknown clip",
        ),
        ({"name": "x", "category": "motion", "keys": {"position": [{"dt": 0, "value": 1.0}]}}, "offsets"),
        ({"name": "x", "category": "motion", "keys": {"scale": [{"dt": 0, "value": [1, 2]}]}}, "numbers"),
        ({"name": "x", "category": "sideways", "clips": [{"kinds": ["FadeIn"], "duration": 1}]}, "category"),
    ],
)
def test_invalid_presets_are_refused(data, message) -> None:
    with pytest.raises(ValueError, match=message):
        library.item_from_json({"format": library.FORMAT, "version": 1, "kind": "preset", **data})


def test_bad_files_are_skipped_with_a_message(tmp_path) -> None:
    good = Theme(name="Mine", background="#000000", text="#ffffff", shape="#ff0000", accent="#00ff00")
    library.save_item(good, tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    newer = {**library.item_to_json(good), "version": 99, "name": "Future"}
    (tmp_path / "newer.json").write_text(json.dumps(newer), encoding="utf-8")
    (tmp_path / "other.json").write_text(json.dumps({"hello": 1}), encoding="utf-8")
    loaded = load_library([tmp_path])
    assert [t.name for t in loaded.themes] == ["Mine"]
    assert sorted(p.split(":")[0] for p in loaded.problems) == ["broken.json", "newer.json", "other.json"]
    assert any("newer Manim Studio" in p for p in loaded.problems)
    assert any("not a Manim Studio library file" in p for p in loaded.problems)


def test_user_items_replace_built_ins_of_the_same_name(tmp_path, monkeypatch) -> None:
    mine = Preset(name="Fade in", category="entrance", clips=[{"kinds": ["FadeIn"], "duration": 2.0}])
    library.save_item(mine, tmp_path)
    monkeypatch.setenv("MANIM_STUDIO_LIBRARY", str(tmp_path))
    assert library.user_folder() == tmp_path
    loaded = load_library()
    fades = [p for p in loaded.presets if p.name == "Fade in"]
    assert len(fades) == 1 and fades[0].clips[0].duration == 2.0
    assert len(loaded.presets) == len(BUILTINS.presets)


def test_a_layers_animation_saves_as_a_preset_and_replays_elsewhere(tmp_path) -> None:
    layer = Layer(
        id="s",
        spec=Spec(type="Square"),
        base=Transform2D(position=(2.0, 0.0)),
        clips=[
            Clip(id="a", kind="FadeIn", start=1.0, duration=0.5, params={"shift": "UP"}),
            Clip(id="b", kind="Indicate", start=2.0, duration=0.5),
        ],
        tracks={"position": [Keyframe(t=1.5, value=(2.0, 0.0)), Keyframe(t=2.5, value=(3.0, 1.0))]},
    )
    saved = library.preset_from_layer(layer, "Mine", "entrance")
    assert [(c.kinds, c.offset) for c in saved.clips] == [(["FadeIn"], 0.0), (["Indicate"], 1.0)]
    assert [(k.dt, k.value) for k in saved.keys["position"]] == [(0.5, (0.0, 0.0)), (1.5, (1.0, 1.0))]
    path = library.save_item(saved, tmp_path)
    again = library.item_from_json(json.loads(path.read_text(encoding="utf-8")))
    assert again == saved
    target = Layer(id="t", spec=Spec(type="Circle"), base=Transform2D(position=(-1.0, -1.0)))
    project = apply_preset(scene(target), "t", again, 3.0).project
    assert [(c.kind, c.start, c.params) for c in project.layer("t").clips] == [
        ("FadeIn", 3.0, {"shift": "UP"}),
        ("Indicate", 4.0, {}),
    ]
    assert [k.value for k in project.layer("t").tracks["position"]] == [(-1.0, -1.0), (0.0, 0.0)]
    with pytest.raises(EditError, match="no clips or keys"):
        library.preset_from_layer(Layer(id="e", spec=Spec(type="Dot")), "Empty", "exit")


# -- themes ----------------------------------------------------------------------------------------------


def themed_scene() -> Project:
    return scene(
        Layer(id="t", spec=Spec(type="Text", params={"text": "Hi"})),
        Layer(id="s", spec=Spec(type="Square", style={"fill_opacity": 0.5})),
        Layer(id="ax", spec=Spec(type="Axes")),
        Layer(id="g", parent_id="ax", spec=Spec(type="Graph", params={"expression": "x"})),
        Layer(id="c", spec=Spec(type="Code", params={"code": ""})),
    )


def test_a_theme_recolours_everything_by_kind() -> None:
    paper = next(t for t in BUILTINS.themes if t.name == "Paper")
    edit = apply_theme(themed_scene(), paper)
    project = edit.project
    assert project.canvas.background == paper.background
    assert project.layer("t").spec.style == {"fill": paper.text}
    assert project.layer("s").spec.style == {"fill_opacity": 0.5, "fill": paper.shape, "stroke": paper.shape}
    assert project.layer("ax").spec.style == {"stroke": paper.text}
    assert project.layer("g").spec.style == {"stroke": paper.accent}
    assert project.layer("c").spec.style == {}  # code draws itself
    assert edit.kind == "spec"


def test_a_theme_on_a_selection_leaves_the_rest() -> None:
    paper = next(t for t in BUILTINS.themes if t.name == "Paper")
    project = apply_theme(themed_scene(), paper, {"g"}).project  # a graph: its axes and graphs
    assert project.canvas.background == CANVAS.background
    assert project.layer("g").spec.style == {"stroke": paper.accent}
    assert project.layer("ax").spec.style == {"stroke": paper.text}
    assert project.layer("t").spec.style == {} and project.layer("s").spec.style == {"fill_opacity": 0.5}


def test_theme_colours_are_validated() -> None:
    with pytest.raises(ValueError, match="not a colour"):
        Theme(name="Bad", background="black", text="#fff", shape="#fff", accent="#fff")


def test_applying_returns_a_valid_project_the_evaluator_draws() -> None:
    project = apply_preset(scene(), "s", preset("Bounce"), 1.0).project
    evaluator = Evaluator(project)
    centre = [dict(evaluator.frame_layers(t))["s"].get_center()[1] for t in (1.0, 1.25, 1.5)]
    assert centre[1] > centre[0] + 0.5 and abs(centre[2] - centre[0]) < 1e-6
    assert layer_transform(project.layer("s"), 0.5).position == (0.0, 0.0)
    assert edits.classify(scene(), project)[0] == "transform"


# -- templates (P5e.2) --------------------------------------------------------------------------------------


def template(name: str) -> library.Template:
    return next(t for t in BUILTINS.templates if t.name == name)


def needs_latex(name: str) -> list:
    return [pytest.mark.latex] if name in ("Equation reveal", "Counter") else []


@pytest.mark.parametrize(
    "name", [pytest.param(t.name, marks=needs_latex(t.name)) for t in BUILTINS.templates]
)
def test_every_built_in_template_inserts_and_draws(name) -> None:
    before = scene()
    pasted = library.insert_template(before, template(name), 1.0)
    project = pasted.edit.project
    added = [x for x in project.layers if x.id not in {"s"}]
    assert len(added) == len(template(name).layers) and pasted.selected == added[0].id
    assert min(c.start for x in added for c in x.clips) == pytest.approx(1.0)
    evaluator = Evaluator(project)
    drawn = {layer_id for layer_id, _ in evaluator.frame_layers(3.5)}
    assert {x.id for x in added if x.parent_id is None} <= drawn


def test_a_template_is_inserted_with_fresh_ids_and_its_references_follow() -> None:
    once = library.insert_template(scene(), template("Callout"), 0.0).edit.project
    twice = library.insert_template(once, template("Callout"), 2.0).edit.project
    connectors = [x for x in twice.layers if x.spec.type == "Connector"]
    assert len(connectors) == 2 and len({x.id for x in twice.layers}) == len(twice.layers)
    for arrow in connectors:
        source, target = twice.layer(arrow.spec.params["source"]), twice.layer(arrow.spec.params["target"])
        assert (source.spec.type, target.spec.type) == ("Rectangle", "Dot")
    assert connectors[0].spec.params["source"] != connectors[1].spec.params["source"]


def test_a_template_past_the_end_is_refused() -> None:
    with pytest.raises(EditError, match="Title card needs until"):
        library.insert_template(scene(), template("Title card"), 5.5)


def test_an_object_saves_as_a_template_from_time_zero(tmp_path) -> None:
    axes = Layer(
        id="ax",
        name="Plot",
        spec=Spec(type="Axes"),
        clips=[Clip(id="c", kind="Create", start=2.0, duration=1)],
    )
    graph = Layer(
        id="g",
        parent_id="ax",
        spec=Spec(type="Graph", params={"expression": "x**2/4"}),
        clips=[Clip(id="w", kind="Create", start=3.0, duration=1)],
    )
    saved = library.template_from(scene(axes, graph), "g", "My plot")  # a member picks its object
    assert [x.id for x in saved.layers] == ["ax", "g"]
    assert [x.clips[0].start for x in saved.layers] == [0.0, 1.0]
    path = library.save_item(saved, tmp_path)
    again = library.item_from_json(json.loads(path.read_text(encoding="utf-8")))
    inserted = library.insert_template(scene(), again, 0.5).edit.project
    plot = next(x for x in inserted.layers if x.spec.type == "Axes")
    assert plot.name == "Plot" and plot.clips[0].start == 0.5
    assert inserted.children(plot.id)[0].clips[0].start == 1.5


def test_an_object_tied_to_others_cannot_be_a_template() -> None:
    square = Layer(id="a", spec=Spec(type="Square"))
    dot = Layer(id="b", spec=Spec(type="Dot"))
    link = Layer(id="link", spec=Spec(type="Connector", params={"source": "a", "target": "b"}))
    with pytest.raises(EditError, match="refers to layers outside it"):
        library.template_from(scene(square, dot, link), "link", "Arrow")


def test_a_template_file_must_stand_on_its_own() -> None:
    link = {"id": "l", "spec": {"type": "Connector", "params": {"source": "a", "target": "b"}}}
    data = {"format": library.FORMAT, "version": 1, "kind": "template", "name": "Bad", "layers": [link]}
    with pytest.raises(ValueError, match="is missing"):
        library.item_from_json(data)


def test_rotation_keys_turn_from_where_the_object_is() -> None:
    turned = Layer(id="s", spec=Spec(type="Square"), base=Transform2D(rotation=30.0))
    track = apply_preset(scene(turned), "s", preset("Spin"), 0.0).project.layer("s").tracks["rotation"]
    assert [k.value for k in track] == [30.0, 390.0]
