"""The export health report (ADR 0066): what is slow or will not work, found before exporting."""

from __future__ import annotations

import numpy as np
import pytest

from manim_studio import cli
from manim_studio.core.code.code_cache import CodeCache
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Canvas, Layer, Lifetime, Project, Spec
from manim_studio.processes import export_health as health
from manim_studio.render import encoders, resources
from manim_studio.render.options import RenderOptions

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=20.0)
CODE = "class Scene1(Scene):\n    def construct(self):\n        self.wait(1)\n"


def project_with(*layers: Layer) -> Project:
    return Project(canvas=CANVAS, layers=list(layers))


def code_layer(name: str, code: str = CODE, seconds: float = 20.0) -> Layer:
    return Layer(
        id=name, spec=Spec(type="Code", params={"code": code}), lifetime=Lifetime(in_=0.0, out=seconds)
    )


def titles(report: health.Report) -> list[str]:
    return [f.title for f in report.findings]


def cached(tmp_path, project: Project, layer_id: str) -> None:
    evaluator = Evaluator(project, CodeCache(tmp_path / "code"))
    writer = evaluator.code_cache.writer(
        evaluator.code_key(project.layer(layer_id)), CANVAS.width_px, CANVAS.height_px, CANVAS.fps
    )
    writer.add(np.zeros((CANVAS.height_px, CANVAS.width_px, 4), np.uint8))
    writer.finish()


def test_a_plain_project_has_only_the_encoder_line(tmp_path) -> None:
    square = Layer(id="s", spec=Spec(type="Square"))
    report = health.check(project_with(square), RenderOptions(), tmp_path)
    assert [f.severity for f in report.findings] == [health.INFO]
    assert report.worst == health.INFO and report.frames == 200


def test_a_code_layer_to_render_costs_its_scene_time_and_runners_share_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(resources, "cores", lambda: 64)
    monkeypatch.setattr(resources, "available_memory", lambda: 64 * 2**30)
    layers = [code_layer(name, CODE.replace("Scene1", f"S{name}")) for name in "abcd"]
    report = health.check(project_with(*layers), RenderOptions(), tmp_path, trust_code=True)
    (finding,) = [f for f in report.findings if "code layer" in f.title]
    assert finding.severity == health.WARNING and finding.title.startswith("4 code layer")
    one_layer = 20.0 * health.CODE_SECONDS_PER_SECOND
    assert finding.seconds == pytest.approx(one_layer)  # four runners: the longest layer is what is left


def test_without_trust_code_layers_are_placeholders_not_work(tmp_path) -> None:
    report = health.check(project_with(code_layer("a")), RenderOptions(), tmp_path, trust_code=False)
    (finding,) = [f for f in report.findings if "placeholder" in f.title]
    assert finding.seconds == 0.0 and "not rendered" in finding.detail


def test_a_cached_code_layer_is_not_reported(tmp_path) -> None:
    project = project_with(code_layer("a"))
    cached(tmp_path, project, "a")
    report = health.check(project, RenderOptions(), tmp_path, trust_code=True)
    assert not [t for t in titles(report) if "code layer" in t]


def test_layers_with_the_same_code_count_once(tmp_path) -> None:
    report = health.check(
        project_with(code_layer("a"), code_layer("b")), RenderOptions(), tmp_path, trust_code=True
    )
    assert any(t.startswith("1 code layer") for t in titles(report))


def test_latex_objects_are_counted_against_the_cache(tmp_path) -> None:
    tex = [Layer(id=f"t{i}", spec=Spec(type="MathTex", params={"text": f"x^{i}"})) for i in range(3)]
    report = health.check(project_with(*tex), RenderOptions(), tmp_path)
    assert any("3 LaTeX object(s); the cache holds 0" in t for t in titles(report))
    (tmp_path / "Tex").mkdir()
    for i in range(3):
        (tmp_path / "Tex" / f"{i}.svg").write_text("<svg/>")
    assert not any("LaTeX" in t for t in titles(health.check(project_with(*tex), RenderOptions(), tmp_path)))


def test_the_cards_h264_limit_is_reported_and_obeyed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(encoders, "gpu_listed", lambda: True)
    assert [e.codec for e in encoders.candidates("gpu", 18, 500, 3840, 2160)] == ["h264_nvenc", "libx264"]
    assert [e.codec for e in encoders.candidates("gpu", 18, 500, 7680, 4320)] == ["libx264"]
    report = health.check(
        project_with(Layer(id="s", spec=Spec(type="Square"))),
        RenderOptions(width=7680, height=4320, encoder="gpu"),
        tmp_path,
    )
    assert any("card cannot be used" in t for t in titles(report))
    assert any("Above 4K" in t for t in titles(report))


def test_the_measured_frame_cost_becomes_a_time(tmp_path) -> None:
    square = Layer(id="s", spec=Spec(type="Square"))
    report = health.check(project_with(square), RenderOptions(jobs=1), tmp_path, frame_seconds=0.05)
    (drawing,) = [f for f in report.findings if f.title == "Drawing the frames"]
    assert drawing.seconds == pytest.approx(0.05 * 200)  # one process: no division
    assert report.seconds == pytest.approx(10.0)


def test_little_disk_space_is_a_warning_and_none_at_all_a_problem(tmp_path, monkeypatch) -> None:
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    square = project_with(Layer(id="s", spec=Spec(type="Square")))
    monkeypatch.setattr(health.shutil, "disk_usage", lambda _p: usage(10**12, 0, 1000))
    report = health.check(square, RenderOptions(), tmp_path, tmp_path / "out.mp4")
    assert report.worst == health.PROBLEM
    monkeypatch.setattr(health.shutil, "disk_usage", lambda _p: usage(10**12, 0, 10**9))
    assert health.check(square, RenderOptions(), tmp_path, tmp_path / "out.mp4").worst == health.WARNING
    monkeypatch.setattr(health.shutil, "disk_usage", lambda _p: usage(10**12, 0, 10**12))
    assert health.check(square, RenderOptions(), tmp_path, tmp_path / "out.mp4").worst == health.INFO


def test_findings_come_worst_first_then_longest_first(tmp_path) -> None:
    layers = [code_layer("a"), Layer(id="t", spec=Spec(type="MathTex", params={"text": "x"}))]
    report = health.check(project_with(*layers), RenderOptions(), tmp_path, trust_code=True)
    severities = [f.severity for f in report.findings]
    assert severities == sorted(severities, key=[health.PROBLEM, health.WARNING, health.INFO].index)


def test_clock_and_lines_read_well() -> None:
    assert [health.clock(s) for s in (4, 59.6, 61, 3725)] == ["4 s", "1 min 00 s", "1 min 01 s", "1 h 02 min"]
    report = health.Report((health.Finding(health.WARNING, "Slow", "because", 90.0),), 10, 90.0)
    assert report.lines() == ["! Slow (~1 min 30 s)", "    because"]


def test_the_cli_check_prints_the_report_and_renders_nothing(tmp_path, capsys) -> None:
    source = tmp_path / "p.json"
    source.write_text(
        project_with(Layer(id="s", spec=Spec(type="Square"))).model_dump_json(by_alias=True), encoding="utf-8"
    )
    out = tmp_path / "out.mp4"
    assert cli.main(["render", str(source), str(out), "--cache-dir", str(tmp_path / "c"), "--check"]) == 0
    printed = capsys.readouterr().out
    assert "200 frames" in printed and "Drawing the frames" in printed
    assert not out.exists()
