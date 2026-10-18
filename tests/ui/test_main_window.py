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
    """ADR 0009: playback time = elapsed wall-clock time, however slow frames are, shown on
    the export's frame grid (ADR 0028)."""
    from manim_studio.ui import main_window as mw

    clock = [100.0]
    monkeypatch.setattr(mw.time, "perf_counter", lambda: clock[0])
    window.seek(1.0)
    window.play()
    clock[0] += 0.75  # one tick arrives late: no catch-up frames, just the current time
    window._on_play_tick()
    fps = window.project.canvas.fps
    assert window.t == pytest.approx(int(1.75 * fps) / fps)  # the grid frame showing at 1.75 s
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
    full = window.canvas.preview_view()  # pixel size, and the world area it shows
    window._set_half_resolution(True)
    half = window.canvas.preview_view()
    assert half.pixel_width == pytest.approx(full.pixel_width / 2, abs=1)
    assert (half.frame_width, half.frame_height) == (full.frame_width, full.frame_height)  # same picture
    assert window.canvas._camera.pixel_width == half.pixel_width
    window._set_half_resolution(False)
    assert window.canvas.preview_view() == full


@pytest.mark.ui
def test_timeline_is_part_of_the_window(window) -> None:
    assert len(window.timeline.clip_items()) == sum(len(layer.clips) for layer in window.project.layers)
    window.seek(2.0)
    assert window.timeline.playhead == pytest.approx(2.0)


@pytest.mark.ui
def test_timeline_scrub_pauses_and_seeks(window) -> None:
    window.play()
    window.timeline.seekRequested.emit(4.0)
    assert not window.play_timer.isActive()
    assert window.t == pytest.approx(4.0)


@pytest.mark.ui
def test_timeline_drag_updates_canvas_and_undo(window) -> None:
    from manim_studio.core import edits
    from manim_studio.core.evaluator import Evaluator

    doc = window.document
    doc.begin_preview()
    doc.preview(edits.move_clip(doc.project, "eq1", "e1-write", 0.9))
    doc.commit_preview("Move clip")
    assert window.evaluator.project is doc.project
    assert window.timeline.clip_item("eq1", "e1-write").rect().x() == pytest.approx(
        window.timeline.scale.x(0.9)
    )
    fresh = Evaluator(doc.project)
    assert len(window.evaluator.frame(1.0)) == len(fresh.frame(1.0))
    doc.undo_stack.undo()
    assert window.timeline.clip_item("eq1", "e1-write").rect().x() == pytest.approx(
        window.timeline.scale.x(0.5)
    )


def test_the_start_hint_goes_once_a_project_is_open(qt_app, tmp_path) -> None:
    """GP: "Create a project..." stayed in the status bar after New and after opening a file."""
    from manim_studio.core.schema import Project
    from manim_studio.ui.main_window import START_HINT

    win = MainWindow()
    try:
        assert win.statusBar().currentMessage() == START_HINT
        win.new_project()
        assert win.statusBar().currentMessage() != START_HINT
        win.statusBar().showMessage(START_HINT)  # as at start
        path = tmp_path / "p.json"
        path.write_text(Project().model_dump_json(by_alias=True), encoding="utf-8")
        win.load(path)
        assert win.statusBar().currentMessage() != START_HINT
        win.statusBar().showMessage("Something else")
        win.new_project()
        assert win.statusBar().currentMessage() == "Something else"  # other messages stay
    finally:
        win.document.undo_stack.setClean()
        win.close()


@pytest.mark.ui
def test_an_exception_in_a_slot_is_logged_and_named_in_the_status_bar(window, caplog) -> None:
    """Qt only printed it (nobody saw it, no log): the user's session broke without a trace."""
    import logging

    from manim_studio.ui.main_window import report_exceptions

    hook = report_exceptions(window)
    try:
        raise ValueError("bad LaTeX")
    except ValueError as caught:
        exc = caught
        with caplog.at_level(logging.CRITICAL, logger="manim_studio"):
            logging.getLogger("manim_studio").propagate = True
            try:
                hook(type(exc), exc, exc.__traceback__)
            finally:
                logging.getLogger("manim_studio").propagate = False
    assert "ValueError: bad LaTeX" in window.statusBar().currentMessage()
    assert any(r.exc_info and r.exc_info[1] is exc for r in caplog.records)


@pytest.mark.ui
def test_a_frame_that_fails_to_draw_leaves_no_stale_picture(window, monkeypatch) -> None:
    """The last picture was kept and stretched to the canvas's new size: a squashed scene with
    stale objects. Now the canvas is empty and the exception goes on to the hook."""
    window.seek(1.0)
    assert window.canvas._image is not None

    def broken(t):
        raise RuntimeError("cannot draw")

    monkeypatch.setattr(window.evaluator, "frame_layers", broken)
    with pytest.raises(RuntimeError):
        window.canvas.render_at(1.5)
    assert window.canvas._image is None and window.canvas.outline is None


@pytest.mark.ui
def test_without_latex_the_editor_keeps_working(qt_app, tmp_path, monkeypatch) -> None:
    """The user's other PC: no LaTeX, so every MathTex build raised - in the idle pass, the
    canvas and selection - and the editor seemed broken. Now it shows a placeholder and says why."""
    import uuid

    from manim_studio.core.schema import Canvas, Clip, Layer, Project, Spec

    monkeypatch.setenv("PATH", str(tmp_path))  # no latex on PATH
    text = rf"x^2 + \text{{{uuid.uuid4().hex[:8]}}}"
    path = tmp_path / "tex.json"
    eq = Layer(
        id="eq",
        spec=Spec(type="MathTex", params={"text": text}),
        clips=[Clip(id="w", kind="Write", start=0.0, duration=1.0)],
    )
    project = Project(canvas=Canvas(duration=3.0), layers=[eq, Layer(id="c", spec=Spec(type="Circle"))])
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.show()
    win.load(path)
    for t in (0.5, 2.0):
        win.seek(t)
    while win.evaluator.missing_checkpoints():
        win._on_idle()
    win.selection.set("eq")
    win.seek(2.5)
    assert win.canvas._image is not None and win.canvas.outline is not None
    assert "LaTeX is not installed" in win.statusBar().currentMessage()
    win.close()
