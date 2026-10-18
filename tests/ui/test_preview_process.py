"""The preview render process as a real subprocess (P3f.2, ADR 0028).

Its frames must be the canvas's frames bit for bit; it follows project
generations and views; it restarts after a crash and gives up on a frame that
kills it every time.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import time
import zlib

import numpy as np
import pytest

pytest.importorskip("PySide6")

from manim_studio.core import adapter
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Camera, Canvas, Clip, Layer, Project, Spec
from manim_studio.render.cairo_export import render_frame
from manim_studio.render.preview import PreviewView, preview_camera
from manim_studio.ui.preview_client import MAX_FAILED_STARTS, PreviewProcess

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # starts real processes

VIEW = PreviewView(
    pixel_width=320,
    pixel_height=200,
    frame_width=16.0,
    frame_height=10.0,
    centre=(0.5, -0.25),
    background="#101010",
)


def project(colour: str = "#38bdf8") -> Project:
    return Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=1.0),
        layers=[
            Layer(
                id="c",
                spec=Spec(type="Circle", params={"radius": 2.0}, style={"stroke": colour}),
                clips=[Clip(id="w", kind="Create", start=0.0, duration=1.0)],
            ),
            Layer(
                id="t", spec=Spec(type="Square"), clips=[Clip(id="s", kind="Wiggle", start=0.2, duration=0.6)]
            ),
        ],
    )


def wait_for(qt_app, condition, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        qt_app.processEvents()
        time.sleep(0.01)


@pytest.fixture
def frames(qt_app):
    process = PreviewProcess(adapter.cache_dir())
    got: dict[tuple[int, int, int], np.ndarray] = {}

    def keep(view_id, generation, index, data, width, height):
        got[(view_id, generation, index)] = np.frombuffer(zlib.decompress(data), np.uint8).reshape(
            height, width, 4
        )

    process.frame.connect(keep)
    yield process, got
    process.stop()


def live(proj: Project, view: PreviewView, index: int) -> np.ndarray:
    return render_frame(preview_camera(view, proj.camera), Evaluator(proj).frame(index / proj.canvas.fps))


def test_its_frames_are_the_canvas_frames(qt_app, frames) -> None:
    process, got = frames
    process.send_project(project(), 1)
    process.send_view(1, VIEW)
    process.want([3, 0, 7, 9])
    wait_for(qt_app, lambda: len(got) == 4)
    assert sorted(got) == [(1, 1, i) for i in (0, 3, 7, 9)]
    for (_, _, index), pixels in got.items():
        assert np.array_equal(pixels, live(project(), VIEW, index)), index


def test_it_follows_generations_and_views(qt_app, frames) -> None:
    process, got = frames
    process.send_project(project(), 1)
    process.send_view(1, VIEW)
    process.want([5])
    wait_for(qt_app, lambda: (1, 1, 5) in got)
    red = project("#ef4444")
    process.send_project(red, 2)
    wider = PreviewView(**{**VIEW.to_json(), "frame_width": 20.0, "centre": (0.0, 0.0)})
    process.send_view(2, wider)
    process.want([5])
    wait_for(qt_app, lambda: (2, 2, 5) in got)
    assert np.array_equal(got[(2, 2, 5)], live(red, wider, 5))
    assert not np.array_equal(got[(2, 2, 5)], got[(1, 1, 5)])


def test_it_restarts_after_a_crash_and_catches_up(qt_app, frames) -> None:
    process, got = frames
    process.send_project(project(), 1)
    process.send_view(1, VIEW)
    wait_for(qt_app, lambda: process.ready)
    first = process.pid
    process._process.kill()
    wait_for(qt_app, lambda: process.ready and process.pid != first)
    process.want([2])  # the restarted process got the project and the view again
    wait_for(qt_app, lambda: (1, 1, 2) in got)
    assert np.array_equal(got[(1, 1, 2)], live(project(), VIEW, 2))


def test_it_gives_up_when_it_keeps_dying(qt_app, tmp_path) -> None:
    dies = tmp_path / "dies.py"
    dies.write_text("import json,sys\nprint(json.dumps({'ready': True}), flush=True)\nsys.stdin.readline()\n")
    process = PreviewProcess(adapter.cache_dir(), program=sys.executable, args=[str(dies)])
    try:
        for _ in range(MAX_FAILED_STARTS):
            wait_for(qt_app, lambda: process.ready, timeout=20)
            process.want([0])  # it reads one line and exits
            wait_for(qt_app, lambda: not process.ready, timeout=20)
        wait_for(qt_app, lambda: not process.available, timeout=20)
    finally:
        process.stop()


def test_it_draws_a_turned_camera_and_follows_it(qt_app, frames) -> None:
    """P7.5 (ADR 0048): the process builds the project's camera, and a new one on a camera edit."""
    process, got = frames
    turned = project().model_copy(update={"camera": Camera(phi=60.0, theta=-60.0)})
    process.send_project(turned, 1)
    process.send_view(1, VIEW)
    process.want([5])
    wait_for(qt_app, lambda: (1, 1, 5) in got)
    assert np.array_equal(got[(1, 1, 5)], live(turned, VIEW, 5))
    assert not np.array_equal(got[(1, 1, 5)], live(project(), VIEW, 5))
    process.send_project(project(), 2)  # back to the flat view, the same framing
    process.want([5])
    wait_for(qt_app, lambda: (1, 2, 5) in got)
    assert np.array_equal(got[(1, 2, 5)], live(project(), VIEW, 5))
