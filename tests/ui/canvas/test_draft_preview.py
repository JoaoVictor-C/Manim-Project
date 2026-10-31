"""Draft preview (ADR 0070): heavy edits are drawn small and marked, and in full when the user pauses."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[Layer(id="a", spec=Spec(type="Square"))],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1300, 800)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


def wait_until(qt_app, condition, seconds: float = 3.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qt_app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def test_slow_renders_in_a_burst_make_a_draft_and_one_slow_render_does_not(window) -> None:
    canvas = window.canvas
    assert not canvas.draft
    canvas.from_cache = False
    canvas._last_render_at = 0.0
    canvas._note_render(200.0)  # alone: a click, not an interaction
    assert not canvas.draft
    canvas._note_render(200.0)  # again at once: a drag
    assert canvas.draft


def test_quick_renders_never_make_a_draft(window) -> None:
    canvas = window.canvas
    canvas.from_cache = False
    for _ in range(5):
        canvas._note_render(5.0)
    assert not canvas.draft


def test_frames_from_the_cache_are_never_drafts(window) -> None:
    canvas = window.canvas
    canvas.from_cache = True
    for _ in range(3):
        canvas._note_render(500.0)
    assert not canvas.draft


def test_a_draft_is_drawn_at_half_size(window) -> None:
    canvas = window.canvas
    full = canvas.preview_view().pixel_width
    canvas.draft = True
    assert canvas.preview_view().pixel_width == pytest.approx(full / 2, abs=1)
    canvas.draft = False
    assert canvas.preview_view().pixel_width == full


def test_after_a_pause_the_frame_is_drawn_in_full_again(window, qt_app) -> None:
    canvas = window.canvas
    full = canvas.preview_view().pixel_width
    canvas.from_cache = False
    canvas._note_render(200.0)
    canvas._note_render(200.0)
    assert canvas.draft
    assert wait_until(qt_app, lambda: not canvas.draft), "the draft was never replaced"
    assert canvas.preview_view().pixel_width == full and canvas._image is not None


def test_turning_it_off_leaves_a_draft_at_once(window) -> None:
    canvas = window.canvas
    canvas.draft = True
    window.draft_action.setChecked(False)
    assert not canvas.draft and not canvas.draft_enabled
    canvas.from_cache = False
    canvas._last_render_at = 0.0
    canvas._note_render(500.0)
    canvas._note_render(500.0)
    assert not canvas.draft
    window.draft_action.setChecked(True)
    assert canvas.draft_enabled


def test_the_badge_paints_and_the_choice_is_remembered(window) -> None:
    window.canvas.draft = True
    assert not window.canvas.grab().isNull()  # painting the badge raises nothing
    assert ("draft_preview", window.draft_action, True) in window._toggles()
