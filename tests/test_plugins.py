"""The plugin API (P4b.1, ADR 0032).

A plugin registers object types; they appear in the library and Properties,
build in every process and animate like built-in objects. A plugin that fails
to load is skipped with a reason; an object that cannot be built - a failing,
impure or missing plugin - draws the placeholder and says why.
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

import manim as m
import numpy as np
import pytest
from tests.support import CANVAS, assert_frames_equal, render_in_order, sequential_reference

from manim_studio import plugins
from manim_studio.core.engine import adapter, warm
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.engine.python_export import readable_problems, to_python
from manim_studio.core.model.schema import Clip, Layer, Project, Spec
from manim_studio.plugins import ObjectType, Param, Voice, VoiceError, VoiceProvider


def pendulum(params: dict) -> m.VMobject:
    tip = np.array(params["tip"])
    return m.VGroup(m.Line(m.ORIGIN, tip), m.Dot(tip, radius=params["bob"]))


PENDULUM = ObjectType(
    "Pendulum",
    pendulum,
    params=(Param("tip", "point", (1.0, -2.0)), Param("bob", "float", 0.2, minimum=0.01, maximum=2.0)),
    section="Physics",
    label="Simple pendulum",
)


@pytest.fixture(autouse=True)
def _restore_plugins():
    """Each test starts and ends with the plugins it found (none, in tests: conftest)."""
    types = set(plugins.TYPES)
    kept = [
        plugins.loaded,
        plugins.problems,
        plugins.manifests,
        plugins.pending,
        plugins.approved,
        plugins.approvals,
    ]
    before = [dict(d) for d in kept]
    library = list(adapter.LIBRARY)
    yield
    for name in set(plugins.TYPES) - types:
        plugins.unregister(name)
    for d, old in zip(kept, before, strict=True):
        d.clear()
        d.update(old)
    assert library == adapter.LIBRARY


@pytest.fixture(autouse=True)
def _restore_voices():
    """Voice providers a test added go away with it (ADR 0060)."""
    before = set(plugins.VOICES)
    yield
    for name in set(plugins.VOICES) - before:
        plugins.unregister(f"voice:{name}")


def provider(name: str = "anna") -> VoiceProvider:
    return VoiceProvider(name, "Anna", lambda: [Voice("a", "A")], lambda text, voice, rate, out: None)


def test_the_built_in_voice_providers_need_no_plugin() -> None:
    providers = plugins.voice_providers()
    assert {"sapi", "edge"} <= set(providers)
    assert providers["edge"].online and not providers["sapi"].online
    assert providers["edge"].extension == ".mp3" and providers["sapi"].extension == ".wav"


def test_a_voice_provider_is_registered_by_name() -> None:
    plugins.register(provider("anna-2_b"))
    assert "anna-2_b" in plugins.VOICES
    for bad in ("Anna", "1anna", "an na", "", "voice:x"):
        with pytest.raises(ValueError, match="not a valid voice provider name"):
            plugins.register(provider(bad))
    with pytest.raises(ValueError, match="already taken"):
        plugins.register(provider("anna-2_b"))
    with pytest.raises(ValueError, match="already taken"):
        plugins.register(provider("edge"))  # a plugin cannot shadow a built-in one


def test_a_plugin_file_can_add_a_voice_provider_and_is_credited_with_it(monkeypatch, tmp_path) -> None:
    source = (
        "from manim_studio.plugins import Voice, VoiceProvider, register\n"
        "register(VoiceProvider('lena', 'Lena', lambda: [Voice('l', 'L')], lambda t, v, r, o: None))\n"
    )
    path = _write(tmp_path, "lena_voice.py", source)
    monkeypatch.setenv("MANIM_STUDIO_PLUGINS", str(tmp_path))
    plugins.load_plugins()
    assert plugins.loaded[str(path)] == ["voice:lena"]
    assert plugins.VOICES["lena"].label == "Lena"


def test_a_plugin_that_fails_after_adding_a_voice_adds_nothing(monkeypatch, tmp_path) -> None:
    source = (
        "from manim_studio.plugins import Voice, VoiceProvider, register\n"
        "register(VoiceProvider('half', 'Half', lambda: [], lambda t, v, r, o: None))\n"
        "raise ImportError('needs a model')\n"
    )
    path = _write(tmp_path, "half_voice.py", source)
    monkeypatch.setenv("MANIM_STUDIO_PLUGINS", str(tmp_path))
    plugins.load_plugins()
    assert "half" not in plugins.VOICES
    assert plugins.problems[str(path)] == "ImportError: needs a model"


def test_unregistering_a_voice_provider_forgets_it() -> None:
    plugins.register(provider("gone"))
    plugins.unregister("voice:gone")
    assert "gone" not in plugins.VOICES


def test_a_voice_error_says_whether_to_try_again() -> None:
    assert VoiceError("busy", retryable=True).retryable
    assert not VoiceError("no").retryable
    assert str(VoiceError("busy")) == "busy"


def test_the_plugins_dialog_lists_voice_providers(monkeypatch, tmp_path) -> None:
    from manim_studio.ui.shell import plugins_dialog

    source = (
        "from manim_studio.plugins import Voice, VoiceProvider, register\n"
        "register(VoiceProvider('dlg', 'Dlg', lambda: [], lambda t, v, r, o: None))\n"
    )
    _write(tmp_path, "dlg_voice.py", source)
    monkeypatch.setenv("MANIM_STUDIO_PLUGINS", str(tmp_path))
    plugins.load_plugins()
    assert "adds: voices: dlg" in plugins_dialog.report()


def test_a_registered_type_joins_the_library_and_properties() -> None:
    plugins.register(PENDULUM)
    assert ("Physics", ("Pendulum",)) in adapter.LIBRARY
    assert adapter.LIBRARY_LABELS["Pendulum"] == "Simple pendulum"
    assert [p.name for p in adapter.MOBJECT_PARAMS["Pendulum"]] == ["tip", "bob"]
    assert adapter.allowed_clip_kinds("Pendulum") == adapter.allowed_clip_kinds("Square")  # vector object
    plugins.register(ObjectType("Spring", pendulum, PENDULUM.params, section="Physics"))
    assert ("Physics", ("Pendulum", "Spring")) in adapter.LIBRARY


def test_unregister_removes_every_trace() -> None:
    before = list(adapter.LIBRARY)
    plugins.register(PENDULUM)
    plugins.unregister("Pendulum")
    assert before == adapter.LIBRARY
    assert "Pendulum" not in adapter.MOBJECT_TYPES and "Pendulum" not in adapter.MOBJECT_PARAMS
    assert "Pendulum" not in plugins.TYPES and "Pendulum" not in adapter.LIBRARY_LABELS


@pytest.mark.parametrize(("name", "message"), [("Circle", "already taken"), ("two words", "not a valid")])
def test_a_type_name_must_be_new_and_an_identifier(name: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        plugins.register(ObjectType(name, pendulum))


def test_build_gets_every_default_and_is_centred_and_styled() -> None:
    seen: list[dict] = []

    def build(params: dict) -> m.VMobject:
        seen.append(params)
        return pendulum(params)

    plugins.register(ObjectType("Pendulum", build, PENDULUM.params))
    spec = Spec(type="Pendulum", params={"bob": 0.5, "extra": "kept"}, style={"stroke": "#ff0000"})
    mob = adapter.build_mobject(spec)
    assert seen[0] == {"tip": [1.0, -2.0, 0.0], "bob": 0.5, "extra": "kept"}
    assert np.allclose(mob.get_center(), 0.0)
    assert m.color_to_rgb(mob[0].get_stroke_color()) == pytest.approx([1.0, 0.0, 0.0])
    assert adapter.build_problem(spec) is None


def _placeholder_says(spec: Spec, message: str) -> None:
    assert isinstance(adapter.build_mobject(spec), m.DashedVMobject)
    problem = adapter.build_problem(spec)
    assert problem is not None and message in problem, problem


def test_a_failing_build_draws_the_placeholder_and_says_why() -> None:
    def broken(params: dict) -> m.VMobject:
        raise RuntimeError("no gravity today")

    plugins.register(ObjectType("Broken", broken))
    _placeholder_says(Spec(type="Broken"), "the Broken plugin failed: RuntimeError: no gravity today")


def test_a_plugin_must_return_a_vector_object() -> None:
    plugins.register(ObjectType("Raster", lambda params: m.ImageMobject(np.zeros((4, 4, 3), np.uint8))))
    _placeholder_says(Spec(type="Raster"), "must return a VMobject, not ImageMobject")


def test_a_plugin_that_draws_differently_each_time_is_refused() -> None:
    plugins.register(ObjectType("Jitter", lambda params: m.Dot([random.random(), 0, 0])))
    _placeholder_says(Spec(type="Jitter"), "draws differently each time")


def test_a_pure_plugin_is_built_twice_only_once_per_type() -> None:
    calls: list[dict] = []

    def counted(params: dict) -> m.VMobject:
        calls.append(params)
        return pendulum(params)

    plugins.register(ObjectType("Pendulum", counted, PENDULUM.params))
    adapter.build_mobject(Spec(type="Pendulum"))
    adapter.build_mobject(Spec(type="Pendulum", params={"bob": 0.3}))
    adapter.build_mobject(Spec(type="Pendulum", params={"bob": 0.3}))  # cached
    assert len(calls) == 3


def test_a_missing_plugin_is_reported_per_layer() -> None:
    project = Project(
        canvas=CANVAS,
        layers=[Layer(id="tea", spec=Spec(type="Teapot")), Layer(id="sq", spec=Spec(type="Square"))],
    )
    evaluator = Evaluator(project)
    assert evaluator.build_errors() == {"tea": "no installed plugin provides Teapot"}
    assert len(evaluator.frame(0.0)) == 2  # the frame still draws, with a placeholder


@pytest.mark.parametrize("kind", ["FadeIn", "Create", "Wiggle"])
def test_a_plugin_object_animates_like_a_built_in_one(kind: str) -> None:
    plugins.register(PENDULUM)
    spec = Spec(type="Pendulum", style={"stroke": "#22d3ee"})
    clip = Clip(id="c", kind=kind, start=0.0, duration=1.0)
    project = Project(canvas=CANVAS, layers=[Layer(id="a", spec=spec, clips=[clip])])
    expected = sequential_reference(kind, spec)
    n = len(expected)
    order = random.Random(5).sample(range(n), n)
    assert_frames_equal(expected, render_in_order(project, order, fresh_each_frame=True), kind)


def test_a_python_export_of_a_plugin_object_is_exact() -> None:
    plugins.register(PENDULUM)
    project = Project(canvas=CANVAS, layers=[Layer(id="p", name="Swing", spec=Spec(type="Pendulum"))])
    assert readable_problems(project) == ["Swing: a plugin object"]
    assert not to_python(project, "Swing").readable


def test_slow_types_wait_for_the_build_worker() -> None:
    plugins.register(PENDULUM)
    plugins.register(ObjectType("Formula", pendulum, PENDULUM.params, slow=True))
    assert warm.warm_key(Spec(type="Pendulum")) is None
    assert warm.warm_key(Spec(type="Formula", params={"bob": 1})) != warm.warm_key(Spec(type="Formula"))
    assert warm.key_spec(warm.warm_key(Spec(type="Formula", params={"bob": 1}))) == Spec(
        type="Formula", params={"bob": 1}
    )


GOOD = """
import manim as m
from manim_studio.plugins import ObjectType, Param, register
register(ObjectType("Ring{n}", lambda p: m.Circle(radius=p["r"]), params=(Param("r", "float", 1.0),)))
"""


def _write(folder: Path, name: str, code: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(code, encoding="utf-8")
    return path


def test_plugin_folders_load_in_order_and_skip_a_broken_file(tmp_path, monkeypatch) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    _write(first, "b_ring.py", GOOD.format(n=2))
    _write(first, "a_ring.py", GOOD.format(n=1))
    half = GOOD.format(n="Half") + "raise ImportError('needs scipy')\n"  # registers, then fails
    broken = _write(first, "c_broken.py", half)
    clash = _write(second, "ring_again.py", GOOD.format(n=1))
    empty = _write(second, "nothing.py", "x = 1\n")
    _write(second, "notes.txt", "not a plugin")
    monkeypatch.setenv("MANIM_STUDIO_PLUGINS", f"{first}{os.pathsep}{second}")
    assert plugins.folders() == [first, second]
    plugins.load_plugins()
    assert list(plugins.TYPES) == ["Ring1", "Ring2"]  # sorted by file name
    assert plugins.loaded[str(first / "a_ring.py")] == ["Ring1"]
    assert plugins.loaded[str(empty)] == []
    assert plugins.problems[str(broken)] == "ImportError: needs scipy"
    assert str(broken) not in plugins.loaded and "RingHalf" not in adapter.MOBJECT_TYPES  # nothing half-added
    assert "already taken" in plugins.problems[str(clash)]
    assert isinstance(adapter.build_mobject(Spec(type="Ring2", params={"r": 2.0})), m.Circle)


def test_the_default_folder_is_in_the_home_directory(monkeypatch) -> None:
    monkeypatch.delenv("MANIM_STUDIO_PLUGINS")
    assert plugins.folders() == [Path.home() / ".manim-studio" / "plugins"]


class _Entry:
    def __init__(self, name: str, target) -> None:
        self.name, self._target = name, target

    def load(self):
        return self._target


def test_entry_points_load_first_sorted_by_name(monkeypatch, tmp_path) -> None:
    order: list[str] = []

    def adds(name: str):
        def setup() -> None:
            order.append(name)
            plugins.register(ObjectType(name, pendulum, PENDULUM.params))

        return setup

    def fails() -> None:
        raise RuntimeError("bad install")

    entries = [_Entry("zeta", adds("Zeta")), _Entry("alpha", adds("Alpha")), _Entry("oops", fails)]
    monkeypatch.setattr(plugins.importlib.metadata, "entry_points", lambda group: entries)
    monkeypatch.setenv("MANIM_STUDIO_PLUGINS", str(_write(tmp_path, "late.py", GOOD.format(n=9)).parent))
    plugins.load_plugins()
    assert order == ["Alpha", "Zeta"] and list(plugins.TYPES)[-1] == "Ring9"
    assert plugins.loaded["entry point alpha"] == ["Alpha"]
    assert plugins.problems["entry point oops"] == "RuntimeError: bad install"


def test_the_public_api_reexports_the_editors_param() -> None:
    assert plugins.Param is adapter.Param
    with pytest.raises(AttributeError):
        _ = plugins.Nope


# -- manifests, compatibility and permissions (ADR 0078) ------------------------------------------------


def _manifest(folder: Path, stem: str, **fields) -> Path:
    path = folder / f"{stem}.plugin.json"
    path.write_text(json.dumps({"name": stem, "version": "1.0", **fields}), encoding="utf-8")
    return path


@pytest.fixture
def approvals_file(monkeypatch, tmp_path) -> Path:
    path = tmp_path / "approvals" / "plugin-approvals.json"
    monkeypatch.setenv("MANIM_STUDIO_PLUGIN_APPROVALS", str(path))
    return path


def test_a_plugin_without_a_manifest_still_loads_marked_unknown(
    monkeypatch, tmp_path, approvals_file
) -> None:
    path = _write(tmp_path, "legacy.py", GOOD.format(n=31))
    monkeypatch.setenv("MANIM_STUDIO_PLUGINS", str(tmp_path))
    plugins.load_plugins()
    assert plugins.loaded[str(path)] == ["Ring31"]
    assert plugins.manifests[str(path)] is None and str(path) not in plugins.pending
    assert not approvals_file.exists()  # nothing to approve, nothing written


def test_a_plugin_with_a_manifest_waits_for_approval_then_loads(
    monkeypatch, tmp_path, approvals_file
) -> None:
    path = _write(tmp_path, "ring.py", GOOD.format(n=32))
    _manifest(tmp_path, "ring", author="Ada", permissions=["reads_project"])
    monkeypatch.setenv("MANIM_STUDIO_PLUGINS", str(tmp_path))
    plugins.load_plugins()
    assert str(path) not in plugins.loaded and "Ring32" not in plugins.TYPES  # its code never ran
    assert plugins.pending[str(path)].permissions == ("reads_project",)
    plugins.approve(str(path))
    assert str(path) not in plugins.pending and plugins.approved[str(path)].author == "Ada"
    stored = json.loads(approvals_file.read_text(encoding="utf-8"))["approved"][str(path)]
    assert stored["version"] == "1.0" and stored["permissions"] == ["reads_project"]
    plugins.load_plugins()  # the next start
    assert plugins.loaded[str(path)] == ["Ring32"] and plugins.manifests[str(path)].name == "ring"


def test_a_plugin_asking_for_more_is_asked_about_again(monkeypatch, tmp_path, approvals_file) -> None:
    path = _write(tmp_path, "grow.py", GOOD.format(n=33))
    _manifest(tmp_path, "grow", permissions=["ui"])
    monkeypatch.setenv("MANIM_STUDIO_PLUGINS", str(tmp_path))
    plugins.load_plugins()
    plugins.approve(str(path))
    _manifest(tmp_path, "grow", version="1.1", permissions=["ui"])  # an update asking nothing more
    plugins.load_plugins()
    assert plugins.loaded[str(path)] == ["Ring33"]
    plugins.unregister("Ring33")
    _manifest(tmp_path, "grow", version="2.0", permissions=["network", "ui"])
    plugins.load_plugins()
    assert plugins.pending[str(path)].version == "2.0"
    from manim_studio import plugin_manifest

    assert plugin_manifest.new_permissions(plugins.approvals[str(path)], plugins.pending[str(path)]) == (
        "network",
    )


def test_an_incompatible_plugin_is_not_loaded_and_says_what_it_needs(
    monkeypatch, tmp_path, approvals_file
) -> None:
    path = _write(tmp_path, "future.py", "raise SystemExit('must never run')\n")
    _manifest(tmp_path, "future", requires=">=99.0")
    monkeypatch.setenv("MANIM_STUDIO_PLUGINS", str(tmp_path))
    monkeypatch.setattr("manim_studio.__version__", "0.3.0")
    plugins.load_plugins()
    assert plugins.problems[str(path)] == "incompatible: needs >=99.0 (this is Manim Studio 0.3.0)"
    assert str(path) not in plugins.pending and str(path) not in plugins.loaded


def test_a_broken_manifest_marks_the_plugin_broken_without_stopping_the_others(
    monkeypatch, tmp_path, approvals_file
) -> None:
    bad = _write(tmp_path, "a_bad.py", "raise SystemExit('must never run')\n")
    _manifest(tmp_path, "a_bad", permissions=["telepathy"])
    worse = _write(tmp_path, "b_worse.py", "raise SystemExit('must never run')\n")
    (tmp_path / "b_worse.plugin.json").write_text("{oops", encoding="utf-8")
    fine = _write(tmp_path, "c_fine.py", GOOD.format(n=34))
    monkeypatch.setenv("MANIM_STUDIO_PLUGINS", str(tmp_path))
    plugins.load_plugins()
    assert plugins.problems[str(bad)].startswith("broken manifest: unknown permission telepathy")
    assert plugins.problems[str(worse)].startswith("broken manifest: b_worse.plugin.json is not valid JSON")
    assert plugins.loaded[str(fine)] == ["Ring34"]


def test_an_entry_point_manifest_is_found_beside_its_module_without_importing_it(
    monkeypatch, tmp_path, approvals_file
) -> None:
    (tmp_path / "ms_probe_pkg").mkdir()
    (tmp_path / "ms_probe_pkg" / "__init__.py").write_text(
        "raise SystemExit('never imported')\n", encoding="utf-8"
    )
    (tmp_path / "ms_probe_pkg" / "plugin.json").write_text(
        '{"name": "Probe", "version": "2"}', encoding="utf-8"
    )
    (tmp_path / "ms_probe_single.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    entry = _Entry("probe", lambda: None)
    entry.module = "ms_probe_pkg.setup"
    assert plugins._entry_point_manifest(entry) == tmp_path / "ms_probe_pkg" / "plugin.json"
    entry.module = "ms_probe_single"
    assert plugins._entry_point_manifest(entry) == tmp_path / "ms_probe_single.plugin.json"
    monkeypatch.setattr(plugins.importlib.metadata, "entry_points", lambda group: [entry])
    entry.module = "ms_probe_pkg"
    monkeypatch.setenv("MANIM_STUDIO_PLUGINS", str(tmp_path / "none"))
    plugins.load_plugins()
    assert plugins.pending["entry point probe"].name == "Probe"
