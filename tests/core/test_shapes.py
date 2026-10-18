"""Shape objects and freezing (P10.2, ADR 0052): an object turned into plain vector data.

A frozen object draws exactly the same pixels as the object it was - at every moment of its
clips, under any transform - but needs no code, no trust prompt and no LaTeX: a finished project
runs on a computer without them. Freezing is one undo step that keeps the layer's place, keys,
clips and lifetime; what cannot be frozen says why.
"""

from __future__ import annotations

import ast
import json
import shutil

import manim as m
import numpy as np
import pytest
from pydantic import ValidationError
from tests.core.test_python_export import assert_matches_editor, rendered
from tests.support import CANVAS, FRAMES, MATH, TEXT

from manim_studio import plugins
from manim_studio.core import adapter, edits, library, python_object, python_templates, shape
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.python_export import _exact, readable_problems, to_python
from manim_studio.core.schema import (
    Clip,
    Keyframe,
    Layer,
    Lifetime,
    PartKey,
    Project,
    Spec,
    Transform2D,
)
from manim_studio.render.cairo_export import make_camera, render_frame

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect x="5" y="5" width="40" height="40" fill="#f97316" stroke="#111827" stroke-width="2"/>
  <circle cx="70" cy="30" r="20" fill="#22d3ee"/>
  <path d="M10 90 C 30 50, 70 50, 90 90" fill="none" stroke="#a3e635" stroke-width="4"/>
</svg>"""
# Colours the renderer reads besides a plain fill: a gradient along one path (several rgbas,
# drawn as a cairo gradient along the sheen direction), a gradient across pieces, and a stroke
# width that differs from piece to piece, with a background stroke and round joints.
GRADIENT = """
def build(p):
    bar = Square(side_length=2).set_fill(opacity=0.8).set_color([RED, YELLOW, BLUE])
    bar.set_sheen_direction(RIGHT)
    dots = VGroup(*[Circle(radius=0.3).set_fill(opacity=1) for _ in range(4)]).arrange(RIGHT)
    dots.set_color_by_gradient(GREEN, PURPLE)
    lines = VGroup(*[Line(LEFT, RIGHT).set_stroke(width=2 + 3 * i) for i in range(3)]).arrange(DOWN)
    lines[1].set_stroke(BLUE, background=True, width=12)
    lines[2].joint_type = LineJointType.ROUND
    return VGroup(bar, dots, lines).arrange(RIGHT)
"""


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("MANIM_STUDIO_TRUST_FILE", str(tmp_path / "trusted.json"))
    monkeypatch.setattr(python_object, "_trust_everything", True)  # build the sources
    adapter.forget_python_builds()
    yield
    adapter.forget_python_builds()


@pytest.fixture
def svg_path(tmp_path) -> str:
    path = tmp_path / "drawing.svg"
    path.write_text(SVG, encoding="utf-8")
    return str(path)


def python(code: str, values: dict | None = None) -> Spec:
    return Spec(type="Python", params={"code": code, **({"values": values} if values else {})})


def styled_circle() -> Spec:
    style = {"fill": "#ef4444", "fill_opacity": 0.5, "stroke": "#22c55e", "stroke_width": 7}
    return Spec(type="Circle", params={"radius": 1.5}, style=style)


def sources(svg_path: str) -> dict[str, Spec]:
    return {
        "circle": styled_circle(),
        "square": Spec(type="Square", params={"side_length": 3}),
        "text": TEXT,
        "math": MATH,
        "triangle": python(python_object.STARTER),
        "matrix": python(python_templates.MATRIX, {"rows": 2, "columns": 2, "values": "1,2;3,4"}),
        "svg": Spec(type="SVGMobject", params={"path": svg_path}),
        "gradient": python(GRADIENT),
        "axes": Spec(type="Axes", params={"x_length": 6.0, "y_length": 4.0}),
    }


def scene(spec: Spec, kind: str = "Create") -> Project:
    """The object moved, turned and scaled, drawn by a clip, then keyed: every frame differs."""
    layer = Layer(
        id="a",
        name="It",
        spec=spec,
        base=Transform2D(position=(0.5, -0.25), rotation=20.0, scale=0.8),
        tracks={"position": [Keyframe(t=0.6, value=(0.5, -0.25)), Keyframe(t=0.9, value=(-1.0, 0.5))]},
        lifetime=Lifetime(out=0.95),
        clips=[Clip(id="c", kind=kind, start=0.0, duration=0.5)],
    )
    return Project(canvas=CANVAS, layers=[layer])


def frozen(project: Project, layer_id: str = "a") -> Project:
    data = adapter.freeze_data(project.layer(layer_id).spec)
    return edits.freeze_layer(project, layer_id, data).project


def frames(project: Project) -> list[np.ndarray]:
    camera, evaluator = make_camera(CANVAS), Evaluator(project)
    return [render_frame(camera, evaluator.frame(t)) for t in FRAMES]


def assert_same_pixels(a: Project, b: Project, label: str) -> None:
    for i, (x, y) in enumerate(zip(frames(a), frames(b), strict=True)):
        assert np.array_equal(x, y), f"{label}: frame {i} differs by {np.abs(x.astype(int) - y).max()}"


# -- the same pixels ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["circle", "square", "text", "math", "triangle", "matrix", "svg", "gradient", "axes"]
)
def test_a_frozen_object_draws_the_same_pixels(name: str, svg_path: str) -> None:
    source = scene(sources(svg_path)[name], "Write" if name in ("text", "math", "matrix") else "Create")
    after = frozen(source)
    assert after.layer("a").spec.type == "Shape"
    assert any(frame.any() for frame in frames(after))
    assert_same_pixels(source, after, name)


@pytest.mark.parametrize("kind", ["FadeIn", "DrawBorderThenFill", "GrowFromCenter", "Indicate", "Wiggle"])
def test_other_clips_draw_the_same_pixels_too(kind: str) -> None:
    source = scene(python(GRADIENT), kind)
    assert_same_pixels(source, frozen(source), kind)


def test_the_data_keeps_what_the_renderer_reads(svg_path: str) -> None:
    built = adapter.build_mobject(python(GRADIENT))
    data = adapter.shape_data(built)
    leaves = built.family_members_with_points()
    assert len(data["shapes"]) == len(leaves)
    bar = data["shapes"][0]
    assert len(bar["fill"]) == 3 and bar["sheen_direction"] == [1.0, 0.0, 0.0]  # a gradient's stops
    assert len(data["shapes"][1]["fill"]) == 4  # one colour: [r, g, b, a]
    widths = [piece["stroke_width"] for piece in data["shapes"][-3:]]
    assert widths == [2.0, 5.0, 8.0]
    assert data["shapes"][-2]["background_width"] == 12.0 and "background" in data["shapes"][-2]
    assert data["shapes"][-1]["joint"] == "ROUND"
    assert all(len(p) == 2 for p in bar["points"])  # flat: z is 0
    rebuilt = adapter.shape_from_data(data["shapes"])
    for leaf, piece in zip(leaves, rebuilt.family_members_with_points(), strict=True):
        assert np.array_equal(leaf.points, piece.points)  # exactly, not approximately
        assert np.array_equal(leaf.get_fill_rgbas(), piece.get_fill_rgbas())
        assert np.array_equal(leaf.get_stroke_rgbas(), piece.get_stroke_rgbas())


def test_points_with_depth_keep_their_z() -> None:
    leaf = m.VMobject()
    leaf.set_points(np.array([[0, 0, 0], [1, 0, 0.5], [1, 1, 0], [0, 1, 0]], dtype=float))
    data = adapter.shape_data(leaf)
    assert data["shapes"][0]["points"][1] == [1.0, 0.0, 0.5]
    assert np.array_equal(
        adapter.shape_from_data(data["shapes"]).family_members_with_points()[0].points, leaf.points
    )


def test_it_survives_save_and_load_exactly(svg_path: str) -> None:
    after = frozen(scene(MATH, "Write"))
    loaded = Project.model_validate_json(after.model_dump_json(by_alias=True))
    assert loaded == after  # every float written exactly (repr precision)
    a = adapter.build_mobject(after.layer("a").spec)
    b = adapter.build_mobject(loaded.layer("a").spec)
    assert all(
        np.array_equal(x.points, y.points)
        for x, y in zip(a.family_members_with_points(), b.family_members_with_points(), strict=True)
    )


def test_its_size_is_measured(svg_path: str) -> None:
    """ADR 0052 records these: an equation is tens of KB, well under the limits."""
    for name in ("text", "math", "matrix"):
        data = adapter.freeze_data(sources(svg_path)[name])
        size = len(json.dumps(data))
        points = sum(len(piece["points"]) for piece in data["shapes"])
        assert size < 400_000 and points < 20_000, (name, size, points)


# -- freezing: one undo step that keeps the layer ----------------------------------------------------------


def test_freezing_keeps_the_layer_and_bakes_its_style() -> None:
    project = scene(styled_circle())
    edit = edits.freeze_layer(project, "a", adapter.freeze_data(project.layer("a").spec))
    old, new = project.layer("a"), edit.project.layer("a")
    assert edit.kind == "spec" and edit.layer_ids == frozenset({"a"})
    assert new.spec.style == {}  # the colours are in the data
    assert new.model_dump(exclude={"spec"}) == old.model_dump(exclude={"spec"})
    assert edits.classify(project, edit.project)[0] == "spec"


def test_a_text_named_by_its_words_keeps_that_name() -> None:
    project = Project(
        canvas=CANVAS, layers=[Layer(id="text-1", spec=TEXT), Layer(id="c", spec=Spec(type="Circle"))]
    )
    assert frozen(project, "text-1").layer("text-1").label == "Hi ok"
    assert frozen(project, "c").layer("c").name == ""  # named by its id: nothing to keep


def test_the_style_applies_on_top_only_when_set_and_themes_recolour_it() -> None:
    project = frozen(scene(styled_circle()))
    spec = project.layer("a").spec
    plain = adapter.build_mobject(spec).family_members_with_points()[0]
    assert plain.get_fill_color().to_hex().lower() == "#ef4444" and plain.get_stroke_width() == 7
    restyled = adapter.build_mobject(spec.model_copy(update={"style": {"fill": "#0000ff"}}))[0]
    assert restyled.get_fill_color().to_hex().lower() == "#0000ff"
    assert restyled.get_stroke_color().to_hex().lower() == "#22c55e"  # not set: the frozen colour
    lib = library.load_library([library.BUILTIN_FOLDER])
    themed = library.apply_theme(project, lib.themes[0]).project.layer("a").spec
    assert themed.style["fill"] == lib.themes[0].shape


def test_group_members_can_be_frozen() -> None:
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(id="a", spec=Spec(type="Circle"), base=Transform2D(position=(-1.0, 0.0))),
            Layer(id="b", spec=Spec(type="Square"), base=Transform2D(position=(1.0, 0.0))),
        ],
    )
    grouped = edits.group_layers(project, ["a", "b"]).project
    after = frozen(grouped, "a")
    assert after.layer("a").parent_id == grouped.layer("a").parent_id
    assert_same_pixels(grouped, after, "a group member")


def test_the_frame_caches_drop_the_old_drawing() -> None:
    project = scene(styled_circle())
    evaluator = Evaluator(project)
    before = render_frame(make_camera(CANVAS), evaluator.frame(0.7))
    edit = edits.freeze_layer(project, "a", adapter.freeze_data(project.layer("a").spec))
    recoloured = edits.update_layer(
        edit.project, "a", spec=edit.project.layer("a").spec.model_copy(update={"style": {"fill": "#0000ff"}})
    )
    evaluator.apply(edit)
    assert np.array_equal(render_frame(make_camera(CANVAS), evaluator.frame(0.7)), before)
    evaluator.apply(recoloured)
    after = render_frame(make_camera(CANVAS), evaluator.frame(0.7))
    assert not np.array_equal(after, before)  # the new spec was built, not a cached frame reused
    assert np.array_equal(after, render_frame(make_camera(CANVAS), Evaluator(recoloured.project).frame(0.7)))


# -- runs anywhere: no LaTeX, no code -----------------------------------------------------------------------


def test_a_frozen_equation_draws_without_latex(monkeypatch, tmp_path) -> None:
    """The user's other PC has no LaTeX: an equation frozen here still draws there."""
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(id="a", spec=MATH),
            Layer(
                id="b",
                spec=MATH,
                base=Transform2D(position=(0, 1)),
                clips=[Clip(id="w", kind="Write", start=0, duration=0.5)],
            ),
        ],
    )
    expected = frames(Project(canvas=CANVAS, layers=[project.layer("b")]))  # with LaTeX
    after = frozen(project, "b")
    # The other PC: no LaTeX on PATH and none of this one's compiled formulas (conftest restores both).
    monkeypatch.setenv("PATH", str(tmp_path))
    m.config.media_dir = str(tmp_path / "empty-cache")
    adapter._build_cached.cache_clear()
    adapter._shape_cached.cache_clear()
    assert shutil.which("latex") is None
    evaluator = Evaluator(after)
    drawn = dict(evaluator.frame_layers(0.75))
    assert isinstance(drawn["a"], m.DashedVMobject)  # not frozen: it needs LaTeX, a placeholder
    assert not isinstance(drawn["b"], m.DashedVMobject)
    assert set(evaluator.build_errors()) == {"a"} and "LaTeX" in evaluator.build_errors()["a"]
    lone = Project(canvas=CANVAS, layers=[after.layer("b")])
    assert all(np.array_equal(x, y) for x, y in zip(frames(lone), expected, strict=True))
    adapter._build_cached.cache_clear()  # nothing built without LaTeX stays for other tests


def test_a_frozen_python_object_needs_no_code_and_no_trust(monkeypatch) -> None:
    project = scene(python(python_object.STARTER))
    after = frozen(project)
    monkeypatch.setattr(python_object, "_trust_everything", False)
    adapter.forget_python_builds()
    assert python_object.STARTER not in after.model_dump_json()
    assert "def build" not in after.model_dump_json()
    assert Evaluator(project).build_errors() == {"a": python_object.NOT_TRUSTED}
    assert Evaluator(after).build_errors() == {}
    monkeypatch.setattr(python_object, "_trust_everything", True)
    expected = frames(project)
    monkeypatch.setattr(python_object, "_trust_everything", False)
    assert all(np.array_equal(x, y) for x, y in zip(frames(after), expected, strict=True))


# -- what cannot be frozen, and why -------------------------------------------------------------------------


def refusal(project: Project, layer_id: str, data: dict | None = None) -> str:
    data = data or {
        "version": 1,
        "shapes": [{"points": [[0, 0]], "fill": [0, 0, 0, 0], "stroke": [1, 1, 1, 1], "stroke_width": 4}],
    }
    with pytest.raises(edits.EditError) as caught:
        edits.freeze_layer(project, layer_id, data)
    return str(caught.value)


def test_layers_of_kinds_that_cannot_be_frozen_say_why(tmp_path) -> None:
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(id="code", spec=Spec(type="Code", params={"code": adapter.CODE_STARTER})),
            Layer(id="img", spec=Spec(type="ImageMobject", params={"path": str(tmp_path / "x.png")})),
            Layer(id="dot", spec=Spec(type="Dot")),
            Layer(id="sq", spec=Spec(type="Square")),
            Layer(id="trace", spec=Spec(type="TracedPath", params={"target": "dot"})),
            Layer(id="link", spec=Spec(type="Connector", params={"source": "dot", "target": "sq"})),
            Layer(id="axes", spec=Spec(type="Axes")),
            Layer(id="graph", parent_id="axes", spec=Spec(type="Graph", params={"expression": "x"})),
            Layer(id="eq", spec=MATH),
            Layer(id="part", parent_id="eq", part=PartKey(tex="=")),
        ],
    )
    grouped = edits.group_layers(project, ["dot", "sq"], "pair").project
    group = next(x for x in grouped.layers if x.is_group).id
    for layer_id, message in (
        ("code", "code layer"),
        ("img", "an image is pixels"),
        ("trace", "traced path"),
        ("link", "connector"),
        ("axes", "objects on it"),
        ("graph", "drawn with its axes"),
        ("eq", "it has parts"),
        ("part", "a part draws pieces"),
        (group, "a group draws nothing"),
    ):
        assert message in refusal(grouped, layer_id), layer_id
        assert shape.freeze_problem(grouped, layer_id) is not None
    assert shape.kind_problem(grouped.layer("axes")) is None  # axes alone can be frozen
    assert shape.kind_problem(grouped.layer("eq")) is None  # an equation without parts can
    shaped = frozen(Project(canvas=CANVAS, layers=[Layer(id="a", spec=Spec(type="Circle"))]))
    assert "already a shape" in refusal(shaped, "a")
    assert "no layer" in refusal(shaped, "nope")


def test_clips_that_need_the_object_type_refuse_naming_the_clip() -> None:
    text = Layer(
        id="t", spec=TEXT, clips=[Clip(id="letters", kind="AddTextLetterByLetter", start=0, duration=1)]
    )
    number = Layer(
        id="n",
        spec=Spec(type="DecimalNumber"),
        clips=[Clip(id="count", kind="ChangeDecimalToValue", start=0, duration=1, params={"value": 5.0})],
    )
    a = Layer(
        id="e1",
        spec=MATH,
        clips=[Clip(id="morph", kind="TransformMatchingTex", start=0, duration=1, to_layer="e2")],
    )
    b = Layer(id="e2", spec=Spec(type="MathTex", params={"text": r"e^{i\pi}=-1"}))
    project = Project(canvas=CANVAS, layers=[text, number, a, b])
    assert "AddTextLetterByLetter clip (letters) needs Text" in refusal(project, "t")
    assert "ChangeDecimalToValue clip (count) needs DecimalNumber" in refusal(project, "n")
    assert "TransformMatchingTex clip (morph) needs MathTex or Tex" in refusal(project, "e1")
    assert "e1's TransformMatchingTex clip (morph) turns it into this object" in refusal(project, "e2")
    plain = Layer(
        id="n", spec=Spec(type="DecimalNumber"), clips=[Clip(id="f", kind="FadeIn", start=0, duration=1)]
    )
    assert shape.freeze_problem(Project(layers=[plain]), "n") is None  # a number that does not count


def test_only_what_is_drawn_can_be_frozen(monkeypatch, tmp_path) -> None:
    missing = Spec(type="SVGMobject", params={"path": str(tmp_path / "gone.svg")})
    with pytest.raises(ValueError, match=r"placeholder \(file not found"):
        adapter.freeze_data(missing)
    with pytest.raises(ValueError, match="no installed plugin"):
        adapter.freeze_data(Spec(type="NoSuchPlugin"))
    monkeypatch.setattr(python_object, "_trust_everything", False)
    with pytest.raises(ValueError, match="code not trusted yet"):
        adapter.freeze_data(python(python_object.STARTER))
    monkeypatch.setattr(python_object, "_trust_everything", True)
    with pytest.raises(ValueError, match="NameError"):
        adapter.freeze_data(python("def build(p):\n    return nope\n"))
    # No LaTeX and none of this computer's compiled formulas (conftest restores both).
    monkeypatch.setenv("PATH", str(tmp_path))
    m.config.media_dir = str(tmp_path / "empty-cache")
    adapter._build_cached.cache_clear()
    with pytest.raises(ValueError, match=r"cannot be built here \(LaTeX is not installed"):
        adapter.freeze_data(MATH)
    adapter._build_cached.cache_clear()


def test_a_simulation_cannot_be_frozen(monkeypatch) -> None:
    monkeypatch.setitem(plugins.SIMULATIONS, "Fake", object())
    with pytest.raises(ValueError, match="simulation"):
        adapter.freeze_data(Spec(type="Fake"))


def test_a_drawing_too_big_is_refused(monkeypatch) -> None:
    big = m.VGroup(*[m.Circle() for _ in range(10)])
    monkeypatch.setattr(shape, "MAX_POINTS", 100)
    with pytest.raises(ValueError, match="a shape may hold 100"):
        adapter.shape_data(big)
    monkeypatch.setattr(shape, "MAX_POINTS", 300_000)
    monkeypatch.setattr(shape, "MAX_BYTES", 1000)
    with pytest.raises(ValueError, match="MB; a shape may take"):
        adapter.shape_data(big)


def test_what_is_not_vector_paths_is_refused() -> None:
    with pytest.raises(ValueError, match="draws nothing"):
        adapter.shape_data(m.VGroup())
    with pytest.raises(ValueError, match="not all vector paths"):
        adapter.shape_data(m.Group(m.Circle(), m.PMobject().add_points([[0, 0, 0]])))


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"version": 2, "shapes": []}, "version 2 is not supported"),
        ({"version": 1, "shapes": []}, "needs its pieces"),
        ({"version": 1, "shapes": [], "code": "x"}, "unknown params"),
        ({"version": 1, "shapes": [{"points": [[0, 0]]}]}, "missing"),
        (
            {
                "version": 1,
                "shapes": [
                    {
                        "points": [[0, 0]],
                        "fill": [0, 0, 0, 0],
                        "stroke": [0, 0, 0, 1],
                        "stroke_width": 1,
                        "x": 1,
                    }
                ],
            },
            "unknown keys",
        ),
        (
            {
                "version": 1,
                "shapes": [
                    {
                        "points": [[0, 0], [1, 2, 3]],
                        "fill": [0, 0, 0, 0],
                        "stroke": [0, 0, 0, 1],
                        "stroke_width": 1,
                    }
                ],
            },
            "points must be",
        ),
        (
            {
                "version": 1,
                "shapes": [
                    {"points": [["a", "b"]], "fill": [0, 0, 0, 0], "stroke": [0, 0, 0, 1], "stroke_width": 1}
                ],
            },
            "points must be",
        ),
        (
            {
                "version": 1,
                "shapes": [
                    {
                        "points": [[0, float("nan")]],
                        "fill": [0, 0, 0, 0],
                        "stroke": [0, 0, 0, 1],
                        "stroke_width": 1,
                    }
                ],
            },
            "points must be",
        ),
        (
            {
                "version": 1,
                "shapes": [
                    {"points": [[0, 0]], "fill": [0, 0, 2, 0], "stroke": [0, 0, 0, 1], "stroke_width": 1}
                ],
            },
            "fill must be",
        ),
        (
            {
                "version": 1,
                "shapes": [
                    {"points": [[0, 0]], "fill": [0, 0, 0, 0], "stroke": [0, 0, 0, 1], "stroke_width": -1}
                ],
            },
            "stroke_width must be",
        ),
        (
            {
                "version": 1,
                "shapes": [
                    {
                        "points": [[0, 0]],
                        "fill": [0, 0, 0, 0],
                        "stroke": [0, 0, 0, 1],
                        "stroke_width": 1,
                        "joint": "WOBBLY",
                    }
                ],
            },
            "joint must be",
        ),
    ],
)
def test_the_file_format_is_checked(params: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Layer(id="s", spec=Spec(type="Shape", params=params))


def test_it_is_a_vector_object_for_clips_and_not_a_plugin_name() -> None:
    kinds = adapter.allowed_clip_kinds("Shape")
    assert {"Create", "Write", "FadeIn", "DrawBorderThenFill", "Transform"} <= set(kinds)
    assert "AddTextLetterByLetter" not in kinds and "ChangeDecimalToValue" not in kinds
    assert "Shape" not in [t for _, types in adapter.LIBRARY for t in types]
    with pytest.raises(ValueError, match="already taken"):
        plugins.register(plugins.ObjectType(name="Shape", build=lambda p: m.Circle()))


# -- Python export ---------------------------------------------------------------------------------------


def exported() -> Project:
    triangle = Layer(
        id="tri",
        name="Triangle",
        spec=python(python_object.STARTER, {"side": 2.5}),
        base=Transform2D(position=(1.0, 0.5)),
        clips=[Clip(id="c", kind="Create", start=0.0, duration=0.6)],
    )
    words = Layer(id="words", name="Words", spec=TEXT, base=Transform2D(position=(-2.0, -1.0)))
    project = Project(canvas=CANVAS, layers=[triangle, words])
    project = frozen(project, "tri")
    project = frozen(project, "words")
    spec = project.layer("words").spec
    return edits.update_layer(
        project, "words", spec=spec.model_copy(update={"style": {"fill": "#facc15"}})
    ).project


def test_the_readable_export_writes_the_data_and_a_helper(monkeypatch) -> None:
    project = exported()
    assert readable_problems(project) == []
    monkeypatch.setattr(python_object, "_trust_everything", False)  # nothing to trust any more
    export = to_python(project, "Frozen")
    assert export.readable
    assert export.code.count("def shape_from_data(shapes):") == 1
    assert "TRIANGLE_SHAPES = [" in export.code and "WORDS_SHAPES = [" in export.code
    assert "triangle = shape_from_data(TRIANGLE_SHAPES)" in export.code
    assert "def build" not in export.code and "manim_studio" not in export.code
    namespace: dict = {}
    exec(compile(export.code, "<export>", "exec"), namespace)
    built = namespace["shape_from_data"](namespace["WORDS_SHAPES"])
    ours = adapter.build_mobject(Spec(type="Shape", params=project.layer("words").spec.params))
    for x, y in zip(built.family_members_with_points(), ours.family_members_with_points(), strict=True):
        assert np.array_equal(x.points, y.points)
        assert np.array_equal(x.get_fill_rgbas(), y.get_fill_rgbas())


def test_the_exact_export_carries_shapes_exactly() -> None:
    project = exported()
    code = _exact(project, "Frozen", ["forced"], None)
    tree = ast.parse(code)
    data = next(
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "PROJECT"
    )
    assert Project.model_validate_json(data) == project


@pytest.mark.slow
def test_the_readable_export_renders_what_the_editor_shows(tmp_path) -> None:
    project = exported()
    export = to_python(project, "Frozen")
    assert export.readable
    assert_matches_editor(project, rendered(export.code, "Frozen", tmp_path))
