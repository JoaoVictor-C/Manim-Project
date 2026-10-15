"""P6b.5 acceptance: the Deliver page queues two exports with different sizes and ranges, runs them
one after another in the real export process, both files are right, and the Python scene is saved.

Done when you can queue two exports, both files come out right (frame count, size, picture,
subtitles), editing while they render changes neither, and the scene is saved as Python.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")

from manim_studio.core import adapter, edits
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.python_export import to_python
from manim_studio.core.schema import Canvas, Clip, Cue, Layer, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.render_queue import Status

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # starts real processes


def make_project() -> Project:
    project = Project(
        canvas=Canvas(width_px=160, height_px=90, fps=10, duration=2.0),
        layers=[
            Layer(
                id="sq",
                spec=Spec(type="Square", style={"fill": "#3b82f6", "fill_opacity": 1}),
                clips=[Clip(id="c", kind="FadeIn", start=0, duration=1.0)],
            )
        ],
        subtitles=[
            Cue(id="s1", start=0.2, end=0.8, text="one"),
            Cue(id="s2", start=1.2, end=1.8, text="two"),
        ],
    )
    for t, name in ((0.5, "from"), (1.5, "to")):
        project = edits.add_marker(project, t, name).project
    return project


def wait_until(qt_app, condition, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        qt_app.processEvents()
        time.sleep(0.01)


def decode(path) -> tuple[list[np.ndarray], float]:
    with av.open(str(path)) as container:
        rate = float(container.streams.video[0].average_rate)
        return [f.to_ndarray(format="rgb24") for f in container.decode(video=0)], rate


def test_two_queued_exports_render_right_and_the_python_scene_is_saved(qt_app, tmp_path) -> None:
    path = tmp_path / "scene.json"
    snapshot = make_project()
    path.write_text(snapshot.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.show()
    win.load(path)
    win.show_page("deliver")
    page = win.pages.pages["deliver"]
    try:
        # job 1: a custom size and a lower frame rate, the whole scene
        page.path.setText(str(tmp_path / "out" / "small.mp4"))
        page.size.setCurrentIndex(page.size.findData("custom"))
        page.width.setValue(128)
        page.height.setValue(72)
        page.fps.setValue(5)
        first = page.add_to_queue()
        # job 2: the project's own size, between the two markers, draft quality, subtitles only as .srt
        page.size.setCurrentIndex(page.size.findData("project"))
        page.fps.setValue(10)
        page.range.setCurrentIndex(page.range.findData("markers"))
        page.quality.setCurrentIndex(page.quality.findData(28))
        page.subtitles.setCurrentIndex(page.subtitles.findData("srt"))
        page.path.setText(str(tmp_path / "out" / "between.mp4"))
        second = page.add_to_queue()
        assert first is not None and second is not None and len(page.queue.jobs) == 2

        # edit while they render: neither export may show it
        page.start_queue()
        assert first.status is Status.RENDERING and second.status is Status.QUEUED
        moved = edits.update_layer(win.project, "sq", base=Transform2D(position=(3.0, 0.0)))
        win.document.apply(moved, "Move layer")
        wait_until(qt_app, lambda: not page.queue.active and not page.queue.busy)
        assert (first.status, second.status) == (Status.DONE, Status.DONE), (first.message, second.message)
        assert page.status_text(first) == "Done"

        small, rate = decode(first.result)
        assert len(small) == 10 and small[0].shape == (72, 128, 3) and rate == 5.0  # 2 s at 5 fps
        assert first.result.with_suffix(".srt").exists()  # srt follows the default "burned in"

        between, rate = decode(second.result)
        assert len(between) == 10 and between[0].shape == (90, 160, 3) and rate == 10.0  # 0.5 s to 1.5 s
        camera, evaluator = make_camera(snapshot.canvas), Evaluator(snapshot)
        for k in (0, 9):  # the picture is the scene at (5 + k) / 10 s, as it was when queued
            expected = render_frame(camera, evaluator.frame((5 + k) / 10))[..., :3].astype(int)
            assert np.abs(between[k].astype(int) - expected).mean() < 8, f"frame {k}"
        centre = between[9][45, 80].astype(int)  # the square is still in the middle: the edit came later
        assert centre[2] > centre[0] + 50
        srt = second.result.with_suffix(".srt").read_text(encoding="utf-8")
        assert "00:00:00,000 --> 00:00:00,300" in srt and "00:00:00,700 --> 00:00:01,000" in srt
        # burned in (job 1) draws the cue at 0.4 s; srt only (job 2) draws nothing at 0.6 s
        band = slice(-12, None)
        assert np.abs(small[2][band].astype(int) - small[0][band].astype(int)).max() > 60  # the text
        assert np.abs(between[1][band].astype(int) - between[5][band].astype(int)).max() < 40
        assert page.queue.queued == [] and not list((tmp_path / "out").glob("*.partial.*"))

        # the Python scene
        saved = tmp_path / "my_scene.py"
        win.ask_python_path = lambda start: str(saved)
        page.python_save.click()
        code = saved.read_text(encoding="utf-8")
        expected = to_python(win.project, "MyScene", str(adapter.cache_dir() / "code"))
        assert code == expected.code  # the preview shows this same scene under the project's name
        compile(code, str(saved), "exec")
        assert "class MyScene(" in code
        assert page.python_kind.text().startswith(("Readable", "Exact"))
    finally:
        win.ask_stop_export = lambda: "stop"
        win.close()
