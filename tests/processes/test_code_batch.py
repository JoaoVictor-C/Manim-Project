"""Code layers rendered side by side for an export (ADR 0065): the same frames, the same errors, any order."""

from __future__ import annotations

import pytest

from manim_studio import cli
from manim_studio.core.code.code_cache import CodeCache
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.processes import code_batch
from manim_studio.processes.code_runner import CodeError, Job, render_code
from manim_studio.render import resources


def scene(name: str, waits: float = 0.3) -> str:
    body = f"        self.add(Square())\n        self.wait({waits})\n"
    return f"class {name}(Scene):\n    def construct(self):\n{body}"


def job(key: str, code: str) -> Job:
    return Job(key=key, code=code, width=160, height=90, fps=10, frame_height=8.0)


# -- how many runners ---------------------------------------------------------------------


def test_one_layer_or_one_runner_is_rendered_in_this_process() -> None:
    assert code_batch.plan(None, 1) == 1
    assert code_batch.plan(1, 7) == 1
    assert code_batch.plan(None, 0) == 1


def test_a_number_asked_for_is_honoured_up_to_the_layers() -> None:
    assert code_batch.plan(3, 7) == 3
    assert code_batch.plan(8, 3) == 3


def test_auto_follows_the_cores_and_the_free_memory(monkeypatch) -> None:
    monkeypatch.setattr(resources, "cores", lambda: 64)
    monkeypatch.setattr(resources, "available_memory", lambda: 64 * 2**30)
    assert code_batch.plan(None, 7) == code_batch.MAX_AUTO
    assert code_batch.plan(None, 2) == 2
    monkeypatch.setattr(
        resources, "available_memory", lambda: 4 * code_batch.RUNNER_BYTES
    )  # half: two runners
    assert code_batch.plan(None, 7) == 2
    monkeypatch.setattr(resources, "cores", lambda: 4)  # a third of the cores: one
    monkeypatch.setattr(resources, "available_memory", lambda: 64 * 2**30)
    assert code_batch.plan(None, 7) == 1


# -- real runners ---------------------------------------------------------------------------


@pytest.mark.slow
def test_layers_rendered_in_several_runners_are_the_layers_rendered_in_one(tmp_path) -> None:
    jobs = [("a", job("ka", scene("A", 0.3))), ("b", job("kb", scene("B", 0.5)))]
    started = []
    assert code_batch.render_all(jobs, tmp_path / "side", 2, started.append) == {}
    assert sorted(started) == ["a", "b"]
    for _, one in jobs:  # the same layers, drawn here
        render_code(one, CodeCache(tmp_path / "alone" / "code"))
    side, alone = CodeCache(tmp_path / "side" / "code"), CodeCache(tmp_path / "alone" / "code")
    for key in ("ka", "kb"):
        a, b = side.open(key), alone.open(key)
        assert a is not None and a.frame_count == b.frame_count and a.duration == b.duration
        assert all((a.crop(i).pixels == b.crop(i).pixels).all() for i in range(a.frame_count))
    assert side.open("kb").duration > side.open("ka").duration  # and they are the two different scenes


@pytest.mark.slow
def test_a_layer_that_fails_is_reported_with_its_line_and_the_others_still_render(tmp_path) -> None:
    bad = "class Bad(Scene):\n    def construct(self):\n        self.add(Square())\n        nonsense_name\n"
    jobs = [("bad", job("kb", bad)), ("good", job("kg", scene("Good")))]
    failures = code_batch.render_all(jobs, tmp_path, 2)
    assert list(failures) == ["bad"]
    error = failures["bad"]
    assert isinstance(error, CodeError) and error.line == 4 and error.error_type == "NameError"
    assert CodeCache(tmp_path / "code").open("kg") is not None
    assert CodeCache(tmp_path / "code").open("kb") is None  # nothing half-written is left behind


@pytest.mark.slow
def test_the_longest_scene_starts_first(tmp_path) -> None:
    short, long = scene("S", 0.1), scene("L", 0.1) + "# " + "x" * 200 + "\n"
    order = []
    code_batch.render_all([("short", job("ks", short)), ("long", job("kl", long))], tmp_path, 1, order.append)
    assert order == ["long", "short"]


# -- the export's use of it ---------------------------------------------------------------------


@pytest.fixture
def manim_cache(tmp_path):
    """Manim pointed at a cache of this test's own; put back where it was after."""
    from manim_studio.core.engine import adapter

    before = adapter.cache_dir()
    adapter.configure(tmp_path / "cache")
    yield tmp_path / "cache"
    adapter.configure(before)


def project_of(**codes: str) -> Project:
    return Project(
        canvas=Canvas(width_px=160, height_px=90, fps=10, duration=1.0),
        layers=[
            Layer(id=name, spec=Spec(type="Code", params={"code": code})) for name, code in codes.items()
        ],
    )


@pytest.mark.slow
def test_the_export_renders_every_missing_layer_and_equal_code_once(manim_cache, capsys) -> None:
    project = project_of(a=scene("A"), b=scene("B", 0.5), twin=scene("A"))
    cache = manim_cache
    assert cli._render_code_layers(project, True, "text", 2) == []
    out = capsys.readouterr().out
    assert out.count("rendering code layer") == 2  # a and b; twin has a's code and waits for it
    assert len([d for d in (cache / "code").iterdir() if not d.name.startswith(".")]) == 2


@pytest.mark.slow
def test_a_failed_layer_is_a_warning_for_every_layer_with_that_code(tmp_path) -> None:
    broken = "class Bad(Scene):\n    def construct(self):\n        nonsense_name\n"
    project = project_of(x=broken, y=broken, ok=scene("Ok"))
    from manim_studio.core.engine import adapter

    adapter.configure(tmp_path / "cache")
    warnings = cli._render_code_layers(project, True, "json", 2)
    assert sorted(w.split(" failed")[0] for w in warnings) == ["code layer 'x'", "code layer 'y'"]
    assert all("(line 3)" in w and "nonsense_name" in w for w in warnings)


def test_untrusted_layers_are_left_alone_whatever_the_runner_count(manim_cache) -> None:
    warnings = cli._render_code_layers(project_of(a=scene("A"), b=scene("B")), False, "json", 4)
    assert len(warnings) == 2 and all("pass --trust-code" in w for w in warnings)
