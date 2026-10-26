"""Helpers where code runs (P13.2, ADR 0058): Python objects, code layers, the build worker, the CLI and
the exports import them; trust is per helper; every signature of code that may import one follows them.
"""

from __future__ import annotations

import json

import manim as m
import numpy as np
import pytest
from tests.core.engine.test_python_export import assert_matches_editor, rendered

from manim_studio import cli
from manim_studio.core.code import helpers, python_object
from manim_studio.core.code.code_cache import CodeCache, cache_key
from manim_studio.core.code.trust import TrustStore, code_of, default_path, label, project_code
from manim_studio.core.editing import edits
from manim_studio.core.engine import adapter, frame_cache, warm
from manim_studio.core.engine.evaluator import Evaluator, code_key
from manim_studio.core.engine.python_export import readable_problems, to_python
from manim_studio.core.model.schema import Canvas, Helper, Layer, Project, Spec
from manim_studio.processes import worker
from manim_studio.processes.code_runner import CodeError, Job, render_code

SIDES = (
    "def polygon_points(n, r):\n"
    "    import math\n"
    "    return [(r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n), 0)"
    " for k in range(n)]\n"
)
SHAPE = (
    "import sides\n"
    'PARAMS = {"n": (5, 3, 9)}\n'
    "def build(p):\n"
    "    return Polygon(*sides.polygon_points(p['n'], 2.0), color=YELLOW)\n"
)
CANVAS = Canvas(width_px=160, height_px=90, fps=10, duration=1.0)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    """An empty trust store of each test's own, no cached builds."""
    monkeypatch.setenv("MANIM_STUDIO_TRUST_FILE", str(tmp_path / "trusted.json"))
    monkeypatch.setattr(python_object, "_trust_everything", False)
    adapter.forget_python_builds()
    yield
    adapter.forget_python_builds()


def trust(*codes: str) -> None:
    TrustStore(default_path()).trust(codes)


def project(code: str = SHAPE, sides: str = SIDES, *more: Layer) -> Project:
    layer = Layer(id="shape", spec=Spec(type="Python", params={"code": code}))
    return Project(canvas=CANVAS, layers=[layer, *more], helpers=[Helper(name="sides", code=sides)])


def built(p: Project, layer_id: str = "shape") -> tuple[m.Mobject, str | None]:
    evaluator = Evaluator(p)
    layer = p.layer(layer_id)
    return evaluator.built(layer.spec), evaluator.build_errors().get(layer_id)


def points(mob: m.Mobject) -> np.ndarray:
    return np.concatenate([sub.points for sub in mob.family_members_with_points()])


# -- Python objects ------------------------------------------------------------------------------------------


def test_a_python_object_imports_a_trusted_helper() -> None:
    trust(SHAPE, SIDES)
    mob, problem = built(project())
    assert problem is None
    expected = m.Polygon(
        *[(2 * np.cos(2 * np.pi * k / 5), 2 * np.sin(2 * np.pi * k / 5), 0) for k in range(5)]
    )
    assert np.allclose(points(mob), points(expected.move_to(m.ORIGIN)))
    assert "sides" not in __import__("sys").modules  # the module is gone once built


def test_an_untrusted_helper_draws_the_placeholder_saying_so() -> None:
    trust(SHAPE)
    _, problem = built(project())
    assert problem == (
        "line 1: ImportError: helper 'sides' is not trusted yet: select it on the Code page and press Run"
    )
    trust(SIDES)  # trusted since: check_media notices, as for the object's own code
    p = project()
    evaluator = Evaluator(p)
    evaluator.built(p.layer("shape").spec)
    assert evaluator.build_errors() == {}


def test_trusting_a_helper_later_rebuilds_through_check_media() -> None:
    trust(SHAPE)
    p = project()
    evaluator = Evaluator(p)
    evaluator.frame(0.0)
    assert "not trusted" in evaluator.build_errors()["shape"]
    trust(SIDES)
    assert evaluator.check_media() == {"shape"}
    evaluator.frame(0.0)
    assert evaluator.build_errors() == {}


def test_an_error_inside_a_helper_names_the_helper_and_its_line() -> None:
    broken = "def polygon_points(n, r):\n    return undefined_name\n"
    trust(SHAPE, broken)
    p = project(sides=broken)
    problem = adapter.python_problem(p.layer("shape").spec, Evaluator(p).signature_of(p.layer("shape").spec))
    assert problem.message == "NameError: name 'undefined_name' is not defined"
    assert (problem.line, problem.where, problem.helper_line) == (4, "helper:sides", 2)
    assert str(problem) == "helper sides, line 2: NameError: name 'undefined_name' is not defined"


def test_a_slow_helper_is_stopped_by_the_time_limit(monkeypatch) -> None:
    looping = "def polygon_points(n, r):\n    while True:\n        pass\n"
    trust(SHAPE, looping)
    monkeypatch.setattr(python_object, "TIME_LIMIT", 0.2)
    _, problem = built(project(sides=looping))
    assert "building took longer than 0.2 s" in problem and problem.startswith("helper sides, line ")


def test_editing_a_helper_rebuilds_the_object() -> None:
    trust(SHAPE, SIDES)
    p = project()
    evaluator = Evaluator(p)
    before = points(evaluator.frame(0.0)[0]).copy()
    doubled = SIDES.replace("return [(r", "return [(2 * r").replace(", r * math.sin", ", 2 * r * math.sin")
    trust(doubled)
    edit = edits.update_helper(p, "sides", code=doubled)
    assert edit.kind == "spec" and edit.layer_ids == {"shape"}
    evaluator.apply(edit)
    after = points(evaluator.frame(0.0)[0])
    assert not np.allclose(before, after)
    assert np.allclose(np.ptp(after, axis=0)[:2], 2 * np.ptp(before, axis=0)[:2], atol=1e-6)


# -- signatures ----------------------------------------------------------------------------------------------


def test_without_helpers_every_signature_is_what_it_was() -> None:
    code = "class A(Scene):\n    def construct(self):\n        self.add(Square())\n"
    layer = Layer(id="c", spec=Spec(type="Code", params={"code": code}))
    plain = Project(canvas=CANVAS, layers=[layer])
    old = cache_key(code, 160, 90, 10, CANVAS.frame_height, adapter.MANIM_VERSION)
    assert code_key(plain, layer) == old == Evaluator(plain).code_key(layer)
    spec = Spec(type="Python", params={"code": SHAPE})
    trust(SHAPE)
    assert adapter.media_signature(spec) == adapter.media_signature(spec, {}) == adapter.TRUSTED
    assert (
        warm.warm_key(spec)
        == warm.warm_key(spec, {})
        == json.dumps({"params": {"code": SHAPE}, "type": "Python"}, sort_keys=True)
    )


def test_editing_a_helper_changes_the_signatures_of_code_layers_and_python_objects() -> None:
    trust(SHAPE, SIDES)
    scene = Layer(id="scene", spec=Spec(type="Code", params={"code": "import sides\n"}))
    p = project(SHAPE, SIDES, scene)
    q = edits.update_helper(p, "sides", code=SIDES + "# edited\n").project
    assert code_key(p, p.layer("scene")) != code_key(q, q.layer("scene"))
    spec = p.layer("shape").spec
    assert adapter.media_signature(spec, helpers.sources(p)).startswith("trusted:")
    assert adapter.media_signature(spec, helpers.sources(p)) != adapter.media_signature(
        spec, helpers.sources(q)
    )
    assert warm.warm_key(spec, helpers.sources(p)) != warm.warm_key(spec, helpers.sources(q))
    described = edits.update_helper(p, "sides", description="regular polygons").project
    assert code_key(p, p.layer("scene")) == code_key(described, described.layer("scene"))


def test_trusting_a_helper_changes_a_python_objects_signature() -> None:
    trust(SHAPE)
    p = project()
    spec = p.layer("shape").spec
    before = adapter.media_signature(spec, helpers.sources(p))
    trust(SIDES)
    assert adapter.media_signature(spec, helpers.sources(p)) != before


def test_changed_spans_mark_the_code_that_may_import_a_helper() -> None:
    plain = Layer(id="sq", spec=Spec(type="Square"))
    scene = Layer(id="scene", spec=Spec(type="Code", params={"code": "x = 1\n"}))
    p = project(SHAPE, SIDES, plain, scene)
    q = edits.update_helper(p, "sides", code=SIDES + "# edited\n").project
    assert frame_cache.changed_layers(p, q) == {"shape", "scene"}
    assert frame_cache.changed_spans(p, q) == [(0.0, float("inf"))]  # alive to the end
    described = edits.update_helper(p, "sides", description="d").project
    assert frame_cache.changed_spans(p, described) == []
    no_code = Project(canvas=CANVAS, layers=[plain])
    added = edits.add_helper(no_code, "sides", SIDES).project
    assert frame_cache.changed_spans(no_code, added) == []


def test_needs_warm_rebuilds_python_objects_when_a_helper_changes() -> None:
    trust(SHAPE, SIDES, SIDES + "# edited\n")
    p = project()
    q = edits.update_helper(p, "sides", code=SIDES + "# edited\n").project
    keys = warm.needs_warm(p, q, set())
    assert len(keys) == 1
    (key,) = keys
    assert warm.key_spec(key) == Spec(type="Python", params={"code": SHAPE})
    assert warm.key_helpers(key) == ({"sides": SIDES + "# edited\n"}, ["sides"])
    assert warm.needs_warm(p, edits.update_helper(p, "sides", description="d").project, set()) == set()


# -- trust ---------------------------------------------------------------------------------------------------


def test_trust_lists_helpers_by_their_own_hash(tmp_path) -> None:
    p = project()
    assert project_code(p) == {"shape": SHAPE, "helper:sides": SIDES}
    store = TrustStore(tmp_path / "store.json")
    assert store.untrusted(p) == ["shape", "helper:sides"]
    store.trust([SIDES])
    assert store.untrusted(p) == ["shape"]
    renamed = edits.rename_helper(p, "sides", "polygon_sides").project  # the helper's code is the same
    assert store.untrusted(renamed) == ["shape"]
    assert code_of(p, "helper:sides") == SIDES and code_of(p, "shape") == SHAPE
    assert label(p, "helper:sides") == "helper sides" and label(p, "shape") == "shape"


def test_trust_carries_to_code_a_rename_rewrote(tmp_path) -> None:
    store = TrustStore(tmp_path / "store.json")
    store.trust([SHAPE])
    edit = edits.rename_helper(project(), "sides", "polygon_sides")
    store.carry(edit.rewritten)
    assert store.untrusted(edit.project) == ["helper:polygon_sides"]


# -- the build worker ----------------------------------------------------------------------------------------


def test_the_worker_builds_with_the_helpers_it_is_sent(monkeypatch) -> None:
    trust(SHAPE, SIDES)
    monkeypatch.setattr(python_object, "TIME_LIMIT", 0.3)
    looping = "def polygon_points(n, r):\n    while True:\n        pass\n"
    spec = {"type": "Python", "params": {"code": SHAPE}}
    answer = worker.reply(
        {"id": 1, "spec": spec, "helpers": {"sides": looping}, "trusted_helpers": ["sides"]}
    )
    assert not answer["ok"] and "building took longer than 0.3 s" in answer["error"]
    fine = worker.reply({"id": 2, "spec": spec, "helpers": {"sides": SIDES}, "trusted_helpers": ["sides"]})
    assert fine["ok"]
    trust(looping)
    key = warm.warm_key(Spec.model_validate(spec), {"sides": looping})  # inside the spec, as the key is
    assert not worker.reply({"id": 3, "spec": json.loads(key)})["ok"]


# -- code layers ---------------------------------------------------------------------------------------------

SCENE = (
    "from sides import polygon_points\n"
    "class A(Scene):\n"
    "    def construct(self):\n"
    "        self.add(Polygon(*polygon_points(4, 2.0)))\n"
)


def job(code: str, sides: str, trusted: tuple[str, ...] = ("sides",)) -> Job:
    return Job("k", code, 160, 90, 10, 8.0, (("sides", sides),), trusted)


def test_a_code_layer_imports_a_helper(tmp_path) -> None:
    cache = CodeCache(tmp_path)
    assert render_code(job(SCENE, SIDES), cache) == 1
    assert cache.open("k").crop(0) is not None
    assert "sides" not in __import__("sys").modules


def test_a_code_layer_error_in_a_helper_says_where(tmp_path) -> None:
    broken = "def polygon_points(n, r):\n    x = 1\n    return 1 / 0\n"
    with pytest.raises(CodeError) as caught:
        render_code(job(SCENE, broken), CodeCache(tmp_path))
    error = caught.value
    assert (error.line, error.where, error.helper_line) == (4, "helper:sides", 3)
    message = error.message()
    assert message["traceback"].count("line ") >= 2 and "polygon_points" in message["traceback"]
    assert {k: v for k, v in message.items() if k != "traceback"} == {
        "error": "ZeroDivisionError: division by zero",
        "line": 4,
        "type": "ZeroDivisionError",
        "where": "helper:sides",
        "helper_line": 3,
    }
    with pytest.raises(CodeError, match="helper 'sides' is not trusted yet") as untrusted:
        render_code(job(SCENE, SIDES, trusted=()), CodeCache(tmp_path))
    assert untrusted.value.line == 1


def test_a_job_round_trips_and_one_without_helpers_reads_as_before() -> None:
    plain = Job("k", "x", 1, 2, 3, 8.0)
    assert json.loads(plain.to_json()) == {
        "key": "k",
        "code": "x",
        "width": 1,
        "height": 2,
        "fps": 3,
        "frame_height": 8.0,
    }
    assert Job.from_json(plain.to_json()) == plain
    rich = job(SCENE, SIDES)
    assert Job.from_json(rich.to_json()) == rich
    assert hash(rich)  # still a value
    assert CodeError("x", 2).message() == {
        "error": "x",
        "line": 2,
        "type": "",
        "where": "code",
        "traceback": "",
    }


# -- the CLI -------------------------------------------------------------------------------------------------


def test_the_cli_warns_about_untrusted_helpers_objects_import() -> None:
    trust(SHAPE)
    unused = Helper(name="unused", code="X = 1\n")
    p = project().model_copy(update={"helpers": [*project().helpers, unused]})
    assert cli._untrusted_objects(p) == [
        "helper 'sides' is not trusted: Python objects importing it are drawn as a placeholder "
        "(pass --trust-code to run its code)"
    ]
    python_object.trust_everything()
    try:
        assert cli._untrusted_objects(p) == []
        assert built(project())[1] is None  # --trust-code trusts helpers too
    finally:
        python_object.trust_everything(False)


@pytest.mark.slow
def test_render_trust_code_runs_code_layers_that_import_helpers(tmp_path, capsys) -> None:
    scene = Layer(id="scene", spec=Spec(type="Code", params={"code": SCENE}))
    p = Project(canvas=CANVAS, layers=[scene], helpers=[Helper(name="sides", code=SIDES)])
    path = tmp_path / "p.json"
    path.write_text(p.model_dump_json(by_alias=True), encoding="utf-8")
    cache = tmp_path / "cache"
    args = ["render", str(path), str(tmp_path / "a.mp4"), "--cache-dir", str(cache), "--trust-code"]
    assert cli.main(args) == 0
    assert "warning" not in capsys.readouterr().err
    assert len([d for d in (cache / "code").iterdir() if not d.name.startswith(".")]) == 1


# -- exports -------------------------------------------------------------------------------------------------


def chained() -> Project:
    """A Python object importing a helper that imports another."""
    radius = "RADIUS = 2.0\n"
    sides = "from radius import RADIUS\n" + SIDES.replace("(n, r)", "(n, r=RADIUS)")
    code = SHAPE.replace("p['n'], 2.0", "p['n']")
    layer = Layer(id="shape", spec=Spec(type="Python", params={"code": code, "values": {"n": 6}}))
    unused = Helper(name="unused", code="raise SystemExit('never imported')\n")
    return Project(
        canvas=CANVAS,
        layers=[layer],
        helpers=[Helper(name="sides", code=sides), Helper(name="radius", code=radius), unused],
    )


def test_the_readable_export_registers_the_helpers_it_imports_before_its_code() -> None:
    p = chained()
    trust(*(h.code for h in p.helpers), p.layer("shape").spec.params["code"])
    assert readable_problems(p) == []
    export = to_python(p, "Sides")
    assert export.readable
    code = export.code
    assert code.index("_register_helper('radius'") < code.index("_register_helper('sides'")
    assert code.index("_register_helper('sides'") < code.index("def _build_shape(p):")
    assert "unused" not in code
    names: dict = {}
    exec(code.split("class Sides(Scene):")[0], names)  # the module part: helpers, then the builder
    mob = names["_build_shape"]({"n": 6})
    ours = Evaluator(p).built(p.layer("shape").spec)
    assert np.allclose(points(mob.move_to(m.ORIGIN)), points(ours))
    for name in ("radius", "sides"):
        __import__("sys").modules.pop(name, None)


def test_the_exact_export_carries_the_helpers_in_its_project() -> None:
    p = chained()
    scene = Layer(id="scene", spec=Spec(type="Code", params={"code": SCENE}))
    p = p.model_copy(update={"layers": [*p.layers, scene]})
    export = to_python(p, "Exact")
    assert not export.readable
    embedded = export.code.split("PROJECT = r'''")[1].split("'''")[0]
    assert Project.model_validate_json(embedded).helpers == p.helpers


def test_a_helper_literal_reads_like_code_and_is_exact() -> None:
    from manim_studio.core.engine.python_export import _source_literal

    latex = 'TEX = r"\\frac{a}{b}"\n'
    assert _source_literal(latex) == f"r'''{latex}'''"
    for tricky in ("x = '''a'''\n", "s = 'a\\\\'\n", "x = 1", "a = '\\n'\r\nb = 2\r\n"):
        literal = _source_literal(tricky)
        assert eval(literal) == tricky.replace("\r\n", "\n") + ("" if tricky.endswith("\n") else "\n")


@pytest.mark.slow
def test_readable_code_with_helpers_renders_what_the_editor_shows(tmp_path) -> None:
    p = chained()
    trust(*(h.code for h in p.helpers), p.layer("shape").spec.params["code"])
    export = to_python(p, "Sides")
    assert export.readable
    assert_matches_editor(p, rendered(export.code, "Sides", tmp_path))
