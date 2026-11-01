"""Exports in a separate process (S4.2, ADR 0017), with the real renderer."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import av
import pytest

pytest.importorskip("PySide6")

from manim_studio import lifeline
from manim_studio.core.engine import adapter
from manim_studio.core.model.schema import Canvas, Clip, Layer, Project, Spec
from manim_studio.render.cairo_export import partial_path
from manim_studio.render.options import RenderOptions
from manim_studio.ui.deliver.export_job import ExportJob

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # starts real processes

CACHE = adapter.cache_dir()  # set by conftest (one per worker in parallel runs)


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
    events = {"progress": [], "finished": [], "failed": [], "stage": []}
    job.progress.connect(lambda *a: events["progress"].append((a, job.running)))
    job.stage.connect(events["stage"].append)
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


def test_the_export_says_what_drew_and_encoded_it(qt_app, tmp_path) -> None:
    job = ExportJob(project(), tmp_path / "v.mp4", CACHE, options=RenderOptions(jobs=1, encoder="cpu"))
    run(qt_app, job, lambda e, j: e["finished"] or e["failed"])
    assert job.how == "CPU (x264)"


def test_cancelling_an_export_drawn_by_render_processes_ends_them_all(qt_app, tmp_path) -> None:
    """ADR 0064 and 0065: nothing an export started outlives it, the render processes included."""
    out = tmp_path / "video.mp4"
    out.write_bytes(b"previous video")
    job = ExportJob(project(duration=60.0), out, CACHE, options=RenderOptions(jobs=2, encoder="cpu"))
    run(qt_app, job, lambda e, j: len(e["progress"]) >= 5)
    pid = int(job._process.processId())
    tree = [pid, *lifeline.descendants(pid)]
    assert len(tree) >= 3, f"expected the renderer and its render processes, found {tree}"
    job.cancel()
    assert lifeline.wait_gone(tree, timeout=15), "a render process outlived the cancelled export"
    assert out.read_bytes() == b"previous video" and not partial_path(out).exists()


def test_code_layers_are_announced_before_the_first_frame(qt_app, tmp_path) -> None:
    scene = "class A(Scene):\n    def construct(self):\n        self.add(Square())\n        self.wait(0.2)\n"
    code = Project(
        canvas=Canvas(width_px=160, height_px=90, fps=10, duration=1.0),
        layers=[
            Layer(id="one", spec=Spec(type="Code", params={"code": scene})),
            Layer(id="two", spec=Spec(type="Code", params={"code": scene.replace("0.2", "0.4")})),
        ],
    )
    fresh = tmp_path / "cache"  # (layers already in the shared cache would need no rendering)
    job = ExportJob(
        code, tmp_path / "v.mp4", fresh, trust_code=True, options=RenderOptions(jobs=2, encoder="cpu")
    )
    events = run(qt_app, job, lambda e, j: e["finished"] or e["failed"], timeout=120)
    assert events["failed"] == [] and events["finished"]
    stages = events["stage"]
    assert {t.split(" (")[0] for t in stages} == {"Rendering code layer one", "Rendering code layer two"}
    assert {t.rsplit("(", 1)[1] for t in stages} == {"1 of 2)", "2 of 2)"}  # counted as each one starts
    assert events["progress"][0][1], "the stages come before the frames"


def test_a_cancelled_long_export_resumes_and_fresh_starts_again(qt_app, tmp_path) -> None:
    """ADR 0081: the segments a cancel keeps are where the next export of it starts, unless it is fresh."""
    from manim_studio.render import resume

    out = tmp_path / "video.mp4"
    options = RenderOptions(jobs=1, encoder="cpu", segment_seconds=1)  # segments of 10 frames
    job = ExportJob(project(duration=60.0), out, CACHE, options=options)
    run(qt_app, job, lambda e, j: any(args[0] >= 25 for args, _ in e["progress"]))
    job.cancel()
    work = resume.work_dir(out)
    assert work.is_dir() and len(resume.load(work).segments) >= 2
    done = len(resume.load(work).segments)

    again = ExportJob(project(duration=60.0), out, CACHE, options=options)
    events = run(qt_app, again, lambda e, j: e["progress"] or e["failed"])
    assert events["stage"] and events["stage"][0].startswith(f"Resuming: {done} of 60 segments")
    assert events["progress"][0][0][0] == done * 10 + 1
    again.cancel()

    fresh = ExportJob(project(duration=60.0), out, CACHE, options=options, fresh=True)
    events = run(qt_app, fresh, lambda e, j: e["progress"] or e["failed"])
    assert events["progress"][0][0] == (1, 600) and not events["stage"]
    fresh.cancel()
