"""S0 previewer smoke test (ADR 0006, 0009).

The previewer loads the demo, scrubs, and precomputes checkpoints.
"""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.ui.main_window import MainWindow

DEMO = Path(__file__).resolve().parents[2] / "examples" / "euler.json"


@pytest.mark.ui
def test_previewer_loads_scrubs_and_warms_checkpoints(qt_app) -> None:
    window = MainWindow()
    window.resize(960, 600)
    window.show()
    window.load(DEMO)
    for t in (0.0, 1.2, 5.0, 6.9, 3.0):
        window.seek(t)
        assert window.canvas._image is not None
        assert not window.canvas._image.isNull()
    while window.evaluator.missing_checkpoints():
        window._on_idle()
    window._on_idle()
    assert not window.idle_timer.isActive()
    window.close()
    qt_app.processEvents()


@pytest.fixture
def window(qt_app, tmp_path):
    project_file = tmp_path / "euler.json"
    project_file.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    win = MainWindow()
    win.resize(640, 400)
    win.show()
    win.load(project_file)
    yield win
    win.pause()
    win.close()
    qt_app.processEvents()


@pytest.mark.ui
def test_save_round_trips_the_project(window, tmp_path) -> None:
    from manim_studio.core.schema import Project

    target = tmp_path / "saved.json"
    window.path = target
    window.save()
    assert Project.model_validate_json(target.read_text(encoding="utf-8")) == window.project


@pytest.mark.ui
def test_invalid_project_shows_error_and_keeps_state(window, tmp_path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: shown.append(args[2]))
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"layers": [{"id": "a", "spec": {"type": "Square"}, "clips": [{"id": "c", '
        '"kind": "Explode", "start": 0, "duration": 1}]}]}',
        encoding="utf-8",
    )
    before = window.project
    window.load(bad)
    assert shown and "Explode" in shown[0]
    assert window.project is before


@pytest.mark.ui
def test_playback_follows_wall_clock_and_drops_frames(window, monkeypatch) -> None:
    """ADR 0009: playback time = elapsed wall-clock time, however slow frames are."""
    from manim_studio.ui import main_window as mw

    clock = [100.0]
    monkeypatch.setattr(mw.time, "perf_counter", lambda: clock[0])
    window.seek(1.0)
    window.play()
    clock[0] += 0.75  # one tick arrives late: no catch-up frames, just the current time
    window._on_play_tick()
    assert window.t == pytest.approx(1.75)
    clock[0] += 100  # past the end: stops at the last moment and pauses
    window._on_play_tick()
    assert window.t == pytest.approx(window.project.canvas.duration)
    assert not window.play_timer.isActive()


@pytest.mark.ui
def test_play_at_end_restarts_from_zero(window) -> None:
    window.seek(window.project.canvas.duration)
    window.play()
    assert window.t == 0.0
    window.pause()


@pytest.mark.ui
def test_step_moves_one_frame_and_pauses(window) -> None:
    window.seek(2.0)
    window.play()
    window.step(1)
    assert not window.play_timer.isActive()
    assert window.t == pytest.approx(2.0 + 1 / window.project.canvas.fps)
    window.step(-100)
    assert window.t == 0.0


@pytest.mark.ui
def test_half_resolution_halves_the_render(window) -> None:
    full = window.canvas._camera_size
    window._set_half_resolution(True)
    half = window.canvas._camera_size
    assert half[0] == pytest.approx(full[0] / 2, abs=1)
    window._set_half_resolution(False)
    assert window.canvas._camera_size == full
