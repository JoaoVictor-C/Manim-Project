"""Video export and the CLI (ADR 0002: export uses the same evaluator as preview)."""

from __future__ import annotations

import json

import av
import numpy as np
import pytest

from manim_studio import cli
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Canvas, Clip, Layer, Project, Spec
from manim_studio.render.cairo_export import export_video, frame_times, make_camera, render_frame

TINY = Canvas(width_px=160, height_px=90, fps=10, duration=0.5, background="#202020")
PROJECT = Project(
    canvas=TINY,
    layers=[
        Layer(
            id="a",
            spec=Spec(type="Square", params={"side_length": 4}, style={"fill": "#3b82f6", "fill_opacity": 1}),
            clips=[Clip(id="c", kind="GrowFromCenter", start=0, duration=0.5)],
        )
    ],
)


def _decode(path) -> list[np.ndarray]:
    with av.open(str(path)) as container:
        return [frame.to_ndarray(format="rgb24") for frame in container.decode(video=0)]


def test_frame_times_cover_duration() -> None:
    assert frame_times(TINY) == pytest.approx([0.0, 0.1, 0.2, 0.3, 0.4])


def test_export_writes_every_frame_matching_the_evaluator(tmp_path) -> None:
    out = export_video(PROJECT, tmp_path / "nested" / "out.mp4")
    frames = _decode(out)
    assert len(frames) == 5
    assert frames[0].shape == (90, 160, 3)

    camera, evaluator = make_camera(TINY), Evaluator(PROJECT)
    for t, decoded in zip(frame_times(TINY), frames, strict=True):
        expected = render_frame(camera, evaluator.frame(t))[:, :, :3].astype(int)
        # H.264 + yuv420p chroma subsampling: compare on average, not per pixel.
        assert np.abs(decoded.astype(int) - expected).mean() < 4, f"t={t}"


def test_export_reports_progress(tmp_path) -> None:
    calls = []
    export_video(PROJECT, tmp_path / "p.mp4", progress=lambda done, total: calls.append((done, total)))
    assert calls == [(i, 5) for i in range(1, 6)]


def test_cli_render(tmp_path, capsys) -> None:
    project_file = tmp_path / "p.json"
    project_file.write_text(PROJECT.model_dump_json(by_alias=True), encoding="utf-8")
    out = tmp_path / "out.mp4"
    assert cli.main(["render", str(project_file), str(out)]) == 0
    assert len(_decode(out)) == 5
    assert "wrote" in capsys.readouterr().out


def test_cli_render_invalid_project_reports_error(tmp_path, capsys) -> None:
    data = json.loads(PROJECT.model_dump_json(by_alias=True))
    data["layers"][0]["clips"][0]["kind"] = "Explode"
    project_file = tmp_path / "bad.json"
    project_file.write_text(json.dumps(data), encoding="utf-8")
    assert cli.main(["render", str(project_file), str(tmp_path / "x.mp4")]) == 2
    err = capsys.readouterr().err
    assert "Explode" in err and "Traceback" not in err


def test_cli_render_missing_file(tmp_path, capsys) -> None:
    assert cli.main(["render", str(tmp_path / "nope.json"), str(tmp_path / "x.mp4")]) == 2
    assert "nope.json" in capsys.readouterr().err


def test_cli_requires_a_command(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2
