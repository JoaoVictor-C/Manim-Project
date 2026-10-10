"""Frames rendered ahead in the editor (P3f.3, ADR 0028), with a stand-in for the
preview process that renders in this process when told to deliver."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
import zlib

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal

from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Canvas, Clip, Layer, Lifetime, Project, Spec
from manim_studio.render.cairo_export import render_frame
from manim_studio.render.preview import preview_camera
from manim_studio.ui import main_window as mw
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

FPS = 10


class FakePreview(QObject):
    frame = Signal(int, int, int, bytes, int, int)
    failed = Signal(int)
    availableChanged = Signal(bool)  # noqa: N815 - the real client's Qt-style name

    def __init__(self) -> None:
        super().__init__()
        self.available = True
        self.project = None
        self.generation = 0
        self.view_id = 0
        self.view = None
        self.wanted: list[int] = []
        self.sent_projects = 0
        self.media_calls = 0
        self.stopped = False

    def send_project(self, project, generation):
        self.project, self.generation = project, generation
        self.sent_projects += 1

    def send_view(self, view_id, view):
        self.view_id, self.view = view_id, view

    def want(self, indices):
        self.wanted = list(indices)

    def media(self):
        self.media_calls += 1

    def stop(self):
        self.stopped = True

    def deliver(self, count: int | None = None, project=None, generation=None) -> None:
        """Render the wanted frames as the real process would (optionally from an older project)."""
        project = project or self.project
        generation = self.generation if generation is None else generation
        evaluator, camera = Evaluator(project), preview_camera(self.view)
        for index in list(self.wanted)[:count]:
            pixels = render_frame(camera, evaluator.frame(index / project.canvas.fps))
            h, w = pixels.shape[:2]
            self.frame.emit(self.view_id, generation, index, zlib.compress(pixels.tobytes(), 1), w, h)


def scene() -> Project:
    return Project(
        canvas=Canvas(width_px=320, height_px=180, fps=FPS, duration=3.0),
        layers=[
            Layer(id="early", spec=Spec(type="Circle"), lifetime=Lifetime(in_=0.0, out=1.0)),
            Layer(
                id="late",
                spec=Spec(type="Square"),
                clips=[Clip(id="in", kind="FadeIn", start=2.0, duration=0.5)],
            ),
        ],
    )


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    fakes: list[FakePreview] = []
    monkeypatch.setattr(
        mw, "make_preview", lambda cache_dir, parent: fakes.append(FakePreview()) or fakes[-1]
    )
    path = tmp_path / "ahead.json"
    path.write_text(scene().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(900, 700)
    win.show()
    win.load(path)
    qt_app.processEvents()
    win.fakes = fakes
    yield win
    win.close()


def live_pixels(window, t: float) -> np.ndarray:
    view = window.canvas.preview_view()
    return render_frame(preview_camera(view), window.evaluator.frame(t))


def shown(window) -> np.ndarray:
    image = window.canvas._image
    data = np.frombuffer(image.constBits(), np.uint8, image.sizeInBytes())
    return data.reshape(image.height(), image.width(), 4)


def wait(qt_app, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qt_app.processEvents()
        time.sleep(0.01)


def test_the_canvas_shows_kept_frames_equal_to_live_ones(window, qt_app) -> None:
    fake = window.fakes[0]
    assert fake.sent_projects == 1 and fake.view == window.canvas.preview_view()
    assert fake.wanted[:3] == [0, 1, 2]  # from the playhead
    fake.deliver()
    assert len(window.render_ahead.store) == 30
    for t in (0.5, 2.2):
        window.seek(t)
        assert window.canvas.from_cache, t
        assert np.array_equal(shown(window), live_pixels(window, t)), t
    window.seek(0.55)  # off the grid: live
    assert not window.canvas.from_cache
    assert "ahead 30/30" in window.time_label.text()


def test_the_outline_stays_on_kept_frames(window, qt_app) -> None:
    window.fakes[0].deliver()
    window.selection.set("late")
    window.seek(2.5)
    assert window.canvas.from_cache and window.canvas.outline is not None
    outline = window.canvas.outline.bounds
    window.render_ahead.store.invalidate_all()  # the same frame, live
    window.refresh()
    assert not window.canvas.from_cache and window.canvas.outline.bounds == outline


def test_an_edit_drops_only_the_frames_it_changes(window, qt_app) -> None:
    fake = window.fakes[0]
    fake.deliver()
    before = fake.project
    window.selection.set("late")
    window.properties.fields["params.side_length"].commit(3.0)
    store = window.render_ahead.store
    assert sorted(store.frames) == list(range(20))  # 2-3 s dropped at once, 0-2 s kept
    assert fake.sent_projects == 1  # not yet: sent after the edits settle
    fake.deliver(project=before, generation=1)  # an old render of the changed frames arrives late
    assert sorted(store.frames) == list(range(20))  # refused
    wait(qt_app, 0.3)
    assert fake.sent_projects == 2 and fake.project.layer("late").spec.params["side_length"] == 3.0
    fake.deliver()
    window.seek(2.5)
    assert window.canvas.from_cache and np.array_equal(shown(window), live_pixels(window, 2.5))


def test_a_new_view_clears_the_frames(window, qt_app) -> None:
    fake = window.fakes[0]
    fake.deliver()
    old_view = fake.view_id
    window.canvas.zoom(2.0)
    qt_app.processEvents()
    window.refresh()
    assert len(window.render_ahead.store) == 0 and fake.view_id != old_view
    fake.deliver(count=5)
    window.seek(0.2)
    assert window.canvas.from_cache and np.array_equal(shown(window), live_pixels(window, 0.2))


def test_a_finished_code_render_or_media_reload_drops_that_layers_frames(window, qt_app) -> None:
    fake = window.fakes[0]
    fake.deliver()
    window._on_code_rendered("early")
    assert sorted(window.render_ahead.store.frames) == list(range(10, 30))
    assert fake.sent_projects == 2  # with the newer generation its new frames need
    window.render_ahead.layers_changed({"late"}, media=True)
    assert sorted(window.render_ahead.store.frames) == list(range(10, 20)) and fake.media_calls == 1


def test_playback_uses_the_kept_frames(window, qt_app, monkeypatch) -> None:
    window.fakes[0].deliver()
    clock = [50.0]
    monkeypatch.setattr(mw.time, "perf_counter", lambda: clock[0])
    window.seek(0.0)
    window.play()
    for _ in range(5):
        clock[0] += 0.137
        window._on_play_tick()
        assert window.canvas.from_cache and abs(window.t * FPS - round(window.t * FPS)) < 1e-6
    window.pause()


def test_render_ahead_can_be_turned_off(window, qt_app) -> None:
    fake = window.fakes[0]
    fake.deliver()
    window.render_ahead_action.setChecked(False)
    assert fake.stopped and window.render_ahead is None and not window.canvas.from_cache
    window.render_ahead_action.setChecked(True)
    assert len(window.fakes) == 2 and window.fakes[1].sent_projects == 1
