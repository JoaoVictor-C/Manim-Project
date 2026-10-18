"""Python objects (P10.1, ADR 0051): an object built by the user's own Manim code.

The code declares ``PARAMS`` (read without running it) and ``build(p)``; it runs only when
trusted, twice on first use (it must be pure), stopped by a time limit; whatever goes wrong
draws the placeholder with the reason and the line. Once built it is an object like any other:
centred, styled on top, transformed, animated, grouped, themed, exported as readable Manim.
"""

from __future__ import annotations

import math
import random
import time

import manim as m
import numpy as np
import pytest
from pydantic import ValidationError
from tests.support import CANVAS, FRAMES, assert_frames_equal, render_in_order

from manim_studio.core import adapter, edits, library, python_object, warm
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.python_export import readable_problems, to_python
from manim_studio.core.python_object import CodeProblem, PyParam, read_params
from manim_studio.core.schema import Clip, Layer, PartKey, Project, Spec, Transform2D
from manim_studio.core.trust import TrustStore, project_code
from manim_studio.render.cairo_export import make_camera, render_frame

STARTER = python_object.STARTER


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    """Each test starts with an empty trust store of its own and no cached builds."""
    monkeypatch.setenv("MANIM_STUDIO_TRUST_FILE", str(tmp_path / "trusted.json"))
    monkeypatch.setattr(python_object, "_trust_everything", False)
    adapter.forget_python_builds()
    yield
    adapter.forget_python_builds()


@pytest.fixture
def trusted(monkeypatch):
    monkeypatch.setattr(python_object, "_trust_everything", True)


def python(code: str = STARTER, values: dict | None = None, style: dict | None = None) -> Spec:
    params = {"code": code} if values is None else {"code": code, "values": values}
    return Spec(type="Python", params=params, style=style or {})


def code(body: str, params: str = "") -> str:
    return f"{params}\ndef build(p):\n{body}\n"


def hand_built(angle: float = 30.0, side: float = 3.0) -> m.VMobject:
    """The starter's right triangle, written out in Manim by hand."""
    height = side * math.tan(math.radians(angle))
    size = 0.12 * min(side, height)
    triangle = m.Polygon(m.ORIGIN, m.RIGHT * side, m.UP * height)
    mark = m.VGroup(
        m.Line(m.RIGHT * size, m.RIGHT * size + m.UP * size), m.Line(m.RIGHT * size + m.UP * size, m.UP * size)
    )
    return m.VGroup(triangle, mark).move_to(m.ORIGIN)


def points(mob: m.Mobject) -> np.ndarray:
    return np.concatenate([sub.points for sub in mob.family_members_with_points()])


# -- PARAMS, read without running the code -------------------------------------------------------------


def test_params_are_typed_by_their_defaults() -> None:
    source = 'PARAMS = {"angle": 30.0, "n": 3, "show": True, "label": "ab", "colour": "#ff0000", "c": "#abc"}'
    assert read_params(source) == (
        PyParam("angle", "float", 30.0),
        PyParam("n", "int", 3),
        PyParam("show", "bool", True),
        PyParam("label", "text", "ab"),
        PyParam("colour", "colour", "#ff0000"),
        PyParam("c", "colour", "#abc"),
    )


def test_numbers_may_have_limits() -> None:
    params = read_params('PARAMS = {"angle": (30.0, 5.0, 85.0), "n": (3, 1, 12), "x": (1, 0.5, 2)}')
    assert params == (
        PyParam("angle", "float", 30.0, 5.0, 85.0),
        PyParam("n", "int", 3, 1, 12),
        PyParam("x", "float", 1.0, 0.5, 2.0),
    )


def test_code_without_params_has_none_and_the_code_is_never_run() -> None:
    assert read_params("raise SystemExit('ran!')\ndef build(p):\n    return Circle()\n") == ()


@pytest.mark.parametrize(
    ("source", "line", "message"),
    [
        ("x = 2\nPARAMS = {'a': x}", 2, "plain values only"),
        ("PARAMS = dict(a=1)", 1, "plain values only"),
        ("PARAMS = [1, 2]", 1, "must be a dict"),
        ("PARAMS = {'a b': 1}", 1, "not a valid parameter name"),
        ("PARAMS = {'a': (1, 2)}", 1, "(default, minimum, maximum)"),
        ("PARAMS = {'a': (5.0, 0.0, 1.0)}", 1, "is not from"),
        ("PARAMS = {'a': [1]}", 1, "not a parameter type"),
        ("\n\ndef build(p:\n    pass", 3, "SyntaxError"),
    ],
)
def test_params_that_cannot_be_read_say_why_and_where(source: str, line: int, message: str) -> None:
    with pytest.raises(CodeProblem) as caught:
        read_params(source)
    assert caught.value.line == line
    assert message in caught.value.message


def test_values_must_fit_the_declared_parameters() -> None:
    source = code("    return Circle()", 'PARAMS = {"r": (1.0, 0.5, 3.0), "n": 2, "on": True, "c": "#ff0000"}')
    Layer(id="a", spec=python(source, {"r": 2.0, "n": 5, "on": False, "c": "#00ff00"}))  # fine
    for values, message in (
        ({"r": 9.0}, "from 0.5 to 3"),
        ({"r": "big"}, "a number"),
        ({"n": 2.5}, "whole number"),
        ({"on": 1}, "True or False"),
        ({"c": "red"}, "colour"),
        ({"zzz": 1}, "no parameter 'zzz'"),
    ):
        with pytest.raises(ValidationError, match=message):
            Layer(id="a", spec=python(source, values))


def test_the_spec_is_checked_but_unreadable_code_is_accepted() -> None:
    with pytest.raises(ValidationError, match="longer than 64 KB"):
        Layer(id="a", spec=python("#" * (python_object.MAX_CODE + 1)))
    with pytest.raises(ValidationError, match="unknown params"):
        Layer(id="a", spec=Spec(type="Python", params={"code": STARTER, "radius": 1}))
    with pytest.raises(ValidationError, match="needs its code"):
        Layer(id="a", spec=Spec(type="Python"))
    Layer(id="a", spec=python("def build(p:", {"anything": 1}))  # the error shows at its line instead


def test_new_code_keeps_the_values_that_still_fit() -> None:
    new = 'PARAMS = {"angle": (30.0, 5.0, 60.0), "label": "x"}'
    kept = python_object.kept_values(new, {"angle": 45.0, "side": 4.0, "label": "ab"})
    assert kept == {"angle": 45.0, "label": "ab"}  # side is gone
    assert python_object.kept_values(new, {"angle": 80.0}) == {}  # out of the new range
    assert python_object.kept_values("PARAMS = {", {"angle": 1}) == {"angle": 1}  # unreadable: kept


def test_build_gets_the_defaults_overridden_by_the_values() -> None:
    assert python_object.call_values(STARTER, {"side": 5}) == {"angle": 30.0, "side": 5.0}


# -- building --------------------------------------------------------------------------------------------


def test_the_starter_builds_the_hand_built_triangle_centred(trusted) -> None:
    mob = adapter.build_mobject(python())
    assert adapter.build_problem(python()) is None
    assert np.allclose(mob.get_center(), 0.0)
    assert np.allclose(points(mob), points(hand_built()))


def test_values_override_the_defaults(trusted) -> None:
    mob = adapter.build_mobject(python(values={"angle": 50.0, "side": 2.0}))
    assert np.allclose(points(mob), points(hand_built(50.0, 2.0)))


def test_an_error_is_the_placeholder_with_its_line(trusted) -> None:
    spec = python(code("    size = 2\n    return Square(side_length=size) + nothing"))
    assert adapter.build_problem(spec) == "line 4: NameError: name 'nothing' is not defined"
    problem = adapter.python_problem(spec)
    assert (problem.line, problem.message) == (4, "NameError: name 'nothing' is not defined")
    assert isinstance(adapter.build_mobject(spec), m.DashedVMobject)
    evaluator = Evaluator(Project(canvas=CANVAS, layers=[Layer(id="a", spec=spec)]))
    assert evaluator.frame(0.0)  # drawn, not raised
    assert evaluator.build_errors() == {"a": "line 4: NameError: name 'nothing' is not defined"}


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("def make(p):\n    return Circle()\n", "must define build(p)"),
        (code("    return 3"), "must return a Manim VMobject"),
        (code("    return ImageMobject(np.zeros((4, 4, 3), dtype=np.uint8))"), "not ImageMobject"),
        (code("    raise SystemExit"), "SystemExit"),
        ("x = 1\ny = 2\n1/0\n", "line 3: ZeroDivisionError"),
    ],
)
def test_code_that_builds_no_object_says_why(trusted, source: str, message: str) -> None:
    assert message in adapter.build_problem(python(source))


def test_code_that_draws_differently_each_time_is_refused(trusted) -> None:
    source = "import random\n" + code("    return Circle(radius=random.random() + 0.5)")
    assert "draws differently each time" in adapter.build_problem(python(source))
    seeded = "import random\n" + code("    random.seed(1)\n    return Circle(radius=random.random() + 0.5)")
    assert adapter.build_problem(python(seeded)) is None


def test_an_endless_loop_is_stopped_by_the_time_limit(trusted, monkeypatch) -> None:
    monkeypatch.setattr(python_object, "TIME_LIMIT", 0.3)
    started = time.perf_counter()
    problem = adapter.python_problem(python(code("    while True:\n        x = 1")))
    assert time.perf_counter() - started < 5
    assert problem.line in (3, 4)  # the while or its body
    assert problem.message.startswith("building took longer than 0.3 s")
    assert adapter.python_timed_out(python(code("    while True:\n        x = 1"))) == str(problem)
    # an endless loop calling Manim, that catches every Exception, is stopped too
    caught = code("    while True:\n        try:\n            Circle()\n        except Exception:\n            pass")
    assert adapter.python_problem(python(caught)).message.startswith("building took longer than")


def test_untrusted_code_is_not_run_and_is_the_placeholder_until_trusted(tmp_path) -> None:
    marker = tmp_path / "ran.txt"
    source = f"open({str(marker)!r}, 'w').close()\n" + STARTER
    project = Project(canvas=CANVAS, layers=[Layer(id="a", spec=python(source))])
    evaluator = Evaluator(project)
    assert isinstance(dict(evaluator.frame_layers(0.0))["a"], m.DashedVMobject)
    assert evaluator.build_errors() == {"a": python_object.NOT_TRUSTED}
    assert warm.warm_key(project.layers[0].spec) is None  # the build worker never runs it either
    assert not marker.exists()
    TrustStore().trust([source])  # the user agreed (the open prompt, Apply, --trust-code)
    assert evaluator.check_media() == {"a"}  # rebuilt, like a file changed on disk
    assert evaluator.build_errors() == {}
    assert np.allclose(points(dict(evaluator.frame_layers(0.0))["a"]), points(hand_built()))
    assert marker.exists()
    assert warm.warm_key(project.layers[0].spec) is not None


def test_the_trust_prompt_and_export_cover_python_objects() -> None:
    project = Project(layers=[Layer(id="a", spec=python()), Layer(id="c", spec=Spec(type="Circle"))])
    assert project_code(project) == {"a": STARTER}
    assert TrustStore().untrusted(project) == ["a"]


def test_new_code_is_built_first_by_the_worker_once_with_its_defaults(trusted) -> None:
    key = warm.warm_key(python(values={"side": 2.0}))
    assert key == warm.warm_key(python(values={"side": 5.0}))  # values never wait again
    assert warm.key_spec(key) == Spec(type="Python", params={"code": STARTER})


def test_the_style_applies_on_top_only_when_set(trusted) -> None:
    blue = code("    return Square().set_stroke(BLUE, width=8)")
    plain = adapter.build_mobject(python(blue))
    assert plain.get_stroke_color() == m.BLUE and plain.get_stroke_width() == 8
    styled = adapter.build_mobject(python(blue, style={"fill": "#ff0000", "fill_opacity": 1.0}))
    assert styled.get_fill_color().to_hex().lower() == "#ff0000" and styled.get_fill_opacity() == 1.0
    assert styled.get_stroke_color() == m.BLUE  # what was not set stays the code's


def test_m_np_and_math_are_there(trusted) -> None:
    source = code("    return m.Circle(radius=float(np.sqrt(4)) * math.cos(0))")
    assert adapter.build_mobject(python(source)).width == pytest.approx(4.0)


def test_children_are_refused() -> None:
    root = Layer(id="t", spec=python())
    with pytest.raises(ValidationError, match="parts are only supported on MathTex and Tex"):
        Project(layers=[root, Layer(id="p", parent_id="t", part=PartKey(tex="a"))])
    with pytest.raises(ValidationError, match="cannot be a child of Python"):
        Project(layers=[root, Layer(id="g", parent_id="t", spec=Spec(type="Graph", params={"expression": "sin(x)"}))])


# -- an object like any other --------------------------------------------------------------------------


def test_a_create_clip_draws_what_manim_draws_for_the_hand_built_triangle(trusted) -> None:
    project = Project(
        canvas=CANVAS,
        layers=[Layer(id="a", spec=python(), clips=[Clip(id="c", kind="Create", start=0.0, duration=1.0)])],
    )
    camera = make_camera(CANVAS)
    mob = hand_built()
    anim = adapter.make_animation("Create", mob, None, {})
    anim.begin()
    expected = []
    for t in FRAMES:
        anim.interpolate(t)
        expected.append(render_frame(camera, [anim.mobject]))
    order = random.Random(3).sample(range(len(FRAMES)), len(FRAMES))
    assert_frames_equal(expected, render_in_order(project, order), "Create on a Python object")


def test_it_is_transformed_and_keyed_like_any_object(trusted) -> None:
    layer = Layer(
        id="a",
        spec=python(),
        base=Transform2D(position=(1.0, -0.5), rotation=30.0, scale=0.5),
        clips=[Clip(id="f", kind="FadeIn", start=0.0, duration=0.5)],
    )
    evaluator = Evaluator(Project(canvas=CANVAS, layers=[layer]))
    drawn = dict(evaluator.frame_layers(0.9))["a"]
    expected = hand_built().scale(0.5, about_point=m.ORIGIN).rotate(30 * m.DEGREES, about_point=m.ORIGIN)
    expected.shift([1.0, -0.5, 0.0])
    assert np.allclose(points(drawn), points(expected), atol=1e-6)


def test_a_group_of_python_objects(trusted) -> None:
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(id="a", spec=python(), base=Transform2D(position=(-2.0, 0.0))),
            Layer(id="b", spec=python(values={"side": 2.0}), base=Transform2D(position=(2.0, 0.0))),
        ],
    )
    grouped = edits.group_layers(project, ["a", "b"], "pair").project
    drawn = dict(Evaluator(grouped).frame_layers(0.5))
    assert np.allclose(drawn["a"].get_center(), [-2.0, 0.0, 0.0])  # grouping moves nothing
    assert np.allclose(points(drawn["b"]), points(hand_built(30.0, 2.0).shift([2.0, 0.0, 0.0])))
    group = next(x for x in grouped.layers if x.is_group)
    x, y = group.base.position
    moved = edits.update_layer(grouped, group.id, base={"position": (x, y + 1.0)}).project
    drawn = dict(Evaluator(moved).frame_layers(0.5))
    assert np.allclose(drawn["a"].get_center(), [-2.0, 1.0, 0.0])  # carried by the group
    assert np.allclose(drawn["b"].get_center(), [2.0, 1.0, 0.0])


def test_it_morphs_into_another_object(trusted) -> None:
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(
                id="a",
                spec=python(),
                clips=[Clip(id="t", kind="Transform", start=0.0, duration=1.0, to_layer="b")],
            ),
            Layer(id="b", spec=Spec(type="Circle")),
        ],
    )
    evaluator = Evaluator(project)
    for t in FRAMES:
        evaluator.frame(t)


def test_themes_and_presets_apply(trusted) -> None:
    project = Project(canvas=CANVAS, layers=[Layer(id="a", spec=python())])
    lib = library.load_library([library.BUILTIN_FOLDER])
    themed = library.apply_theme(project, lib.themes[0]).project
    style = themed.layer("a").spec.style
    assert style["fill"] == lib.themes[0].shape and style["stroke"] == lib.themes[0].shape
    assert adapter.build_problem(themed.layer("a").spec) is None
    for preset in lib.presets:
        try:
            result = library.apply_preset(themed, "a", preset, 0.0).project
        except edits.EditError:
            continue  # a preset for other kinds of object (e.g. letter by letter on text)
        for t in (0.0, 0.5):
            Evaluator(result).frame(t)


# -- Python export (ADR 0031) ---------------------------------------------------------------------------


def exported() -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(
                id="tri",
                name="Triangle",
                spec=python(values={"side": 2.5}, style={"stroke": "#ff0000"}),
                base=Transform2D(position=(1.0, 0.5)),
                clips=[Clip(id="c", kind="Create", start=0.0, duration=0.6)],
            ),
            Layer(id="tri2", name="Small", spec=python(values={"angle": 60.0, "side": 1.0})),
        ],
    )


def test_the_readable_export_writes_the_code_once_as_a_function(trusted) -> None:
    project = exported()
    assert readable_problems(project) == []
    export = to_python(project, "Proof")
    assert export.readable
    assert export.code.count('"""A right triangle') == 1  # the code once, for both objects
    assert "def _build_triangle(p):" in export.code and "TRIANGLE_PARAMS = {" in export.code
    assert 'triangle = _build_triangle({"angle": 30.0, "side": 2.5})' in export.code
    assert 'small = _build_triangle({"angle": 60.0, "side": 1.0})' in export.code
    assert "def build(" not in export.code and "\nPARAMS" not in export.code
    namespace: dict = {}
    exec(compile(export.code, "<export>", "exec"), namespace)  # a file Manim can import
    built = namespace["_build_triangle"]({"angle": 30.0, "side": 2.5})
    assert np.allclose(points(built.move_to(m.ORIGIN)), points(hand_built(30.0, 2.5)))


def test_untrusted_code_is_still_written_out_but_errors_make_it_exact(trusted, monkeypatch) -> None:
    broken = exported().model_copy(update={"layers": [Layer(id="x", spec=python(code("    return nope")))]})
    assert readable_problems(broken) == ["x: line 3: NameError: name 'nope' is not defined"]
    assert not to_python(broken, "Broken").readable
    monkeypatch.setattr(python_object, "_trust_everything", False)
    assert readable_problems(exported()) == []  # not run here; the file is the user's


def test_codes_that_would_replace_each_others_names_make_it_exact(trusted) -> None:
    helper = "def mark():\n    return Dot()\n" + code("    return mark()")
    other = "def mark():\n    return Square()\n" + code("    return VGroup(mark(), Circle())")
    project = Project(layers=[Layer(id="a", spec=python(helper)), Layer(id="b", spec=python(other))])
    assert readable_problems(project) == ["b: its code defines 'mark', as a's does"]
    shadow = Project(layers=[Layer(id="a", spec=python("Circle = 3\n" + code("    return Square()")))])
    assert readable_problems(shadow) == ["a: its code defines 'Circle', a name Manim uses"]
