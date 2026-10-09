"""Exports in a separate process (S4.2, ADR 0017), with the real renderer."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
from pathlib import Path

import av
import pytest

pytest.importorskip("PySide6")

from manim_studio.core.schema import Canvas, Clip, Layer, Project, Spec
from manim_studio.render.cairo_export import partial_path
from manim_studio.ui.export_job import ExportJob

pytestmark = pytest.mark.ui

CACHE = Path(__file__).resolve().parents[2] / ".cache" / "manim"


def project(duration: float = 1.0) -> Project:
    return Project(
        canvas=Canvas(width_px=160, height_px=90, fps=10, duration=duration),
        layers=[
            Layer(
                id="a",
                spec=Spec(type="Square", style={"fill": "#3b82f6", "fill_opacity": 1}),
                clips=[Clip(id="c", kind="FadeIn", start=0, duration=duration)],
            )
        ],
    )


def run(qt_app, job: ExportJob, until, timeout: float = 60.0) -> dict:
    events = {"progress": [], "finished": [], "failed": []}
    job.progress.connect(lambda *a: events["progress"].append((a, job.running)))
    job.finished.connect(lambda *a: events["finished"].append(a))
    job.failed.connect(lambda m: events["failed"].append(m))
    job.start()
    deadline = time.monotonic() + timeout
    while not until(events, job):
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out: {events}")
        qt_app.processEvents()
        time.sleep(0.01)
    return events


def exports_dir_files() -> set[str]:
    return {p.name for p in (CACHE / "exports").glob("*.json")} if (CACHE / "exports").exists() else set()


def test_export_reports_progress_while_running_then_the_path(qt_app, tmp_path) -> None:
    before = exports_dir_files()
    out = tmp_path / "video.mp4"
    job = ExportJob(project(), out, CACHE)
    events = run(qt_app, job, lambda e, j: e["finished"] or e["failed"])
    assert events["failed"] == []
    assert events["finished"] == [(str(out), "")]
    frames = [args for args, _ in events["progress"]]
    assert frames[0] == (1, 10) and frames[-1] == (10, 10)
    assert all(running for _, running in events["progress"])  # live, not all at the end
    with av.open(str(out)) as container:
        assert sum(1 for _ in container.decode(video=0)) == 10
    assert exports_dir_files() == before  # the snapshot file is gone
    assert not job.running


def test_cancel_kills_the_render_and_keeps_the_old_video(qt_app, tmp_path) -> None:
    out = tmp_path / "video.mp4"
    out.write_bytes(b"previous video")
    job = ExportJob(project(duration=60.0), out, CACHE)  # 600 frames
    events = run(qt_app, job, lambda e, j: len(e["progress"]) >= 3)
    job.cancel()
    assert not job.running
    assert out.read_bytes() == b"previous video"
    assert not partial_path(out).exists()
    qt_app.processEvents()
    assert events["finished"] == [] and events["failed"] == []


def test_a_failing_render_reports_its_error(qt_app, tmp_path) -> None:
    out = tmp_path / "is-a-directory.mp4"
    out.mkdir()
    job = ExportJob(project(), out, CACHE)
    events = run(qt_app, job, lambda e, j: e["finished"] or e["failed"])
    assert events["finished"] == []
    assert events["failed"] and "cannot write" in events["failed"][0]
    assert "folder" in events["failed"][0]
    assert not partial_path(out).exists()
