"""Export dialog (S4.3-S4.4, ADR 0017) — and the S4 acceptance test.

S4 is done when you can export from the UI without freezing it: the export
runs in another process while the editor keeps taking edits, reports progress,
can be cancelled without harming an existing video, and quitting asks first.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QCloseEvent, QKeySequence

from manim_studio.core.editing import edits
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Canvas, Clip, Layer, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame
from manim_studio.ui.main_window import MainWindow

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # starts real processes


def project(duration: float = 1.0) -> Project:
    return Project(
        canvas=Canvas(width_px=160, height_px=90, fps=10, duration=duration),
        layers=[
            Layer(
                id="sq",
                spec=Spec(type="Square", style={"fill": "#3b82f6", "fill_opacity": 1}),
                clips=[Clip(id="c", kind="FadeIn", start=0, duration=0.5)],
            )
        ],
    )


@pytest.fixture
def window(qt_app, tmp_path):
    def make(duration: float = 1.0) -> MainWindow:
        path = tmp_path / "scene.json"
        path.write_text(project(duration).model_dump_json(by_alias=True), encoding="utf-8")
        win = MainWindow()
        win.show()
        win.load(path)
        windows.append(win)
        return win

    windows: list[MainWindow] = []
    yield make
    for win in windows:
        win.close()


def wait_until(qt_app, condition, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        qt_app.processEvents()
        time.sleep(0.01)


def export_action(win: MainWindow):
    menu = next(a.menu() for a in win.menuBar().actions() if a.text() == "&File")
    return next(a for a in menu.actions() if a.text() == "&Export Video...")


def test_the_menu_opens_the_dialog_with_a_default_path(window, tmp_path) -> None:
    win = window()
    action = export_action(win)
    assert action.shortcut() == QKeySequence("Ctrl+E")
    action.trigger()
    assert win.export_dialog.isVisible()
    assert win.export_dialog.path.text() == str(tmp_path / "out" / "scene.mp4")


def test_export_runs_while_editing_and_renders_the_scene_as_it_was(window, qt_app, tmp_path) -> None:
    """S4 acceptance: the editor keeps working during the export; later edits are not exported."""
    win = window()
    exported_project = win.project
    export_action(win).trigger()
    dialog = win.export_dialog
    out = tmp_path / "video.mp4"
    dialog.path.setText(str(out))
    dialog.export_button.click()
    assert dialog.running and not dialog.export_button.isEnabled()

    # keep editing while the renderer works
    edit = edits.update_layer(win.project, "sq", base=Transform2D(position=(3.0, 0.0)))
    win.document.apply(edit, "Move layer")
    win.seek(0.7)
    assert win.project.layer("sq").base.position == (3.0, 0.0)

    wait_until(qt_app, lambda: not dialog.running)
    assert dialog.status.text() == f"Exported to {out} - CPU (x264)"  # and how it was made (ADR 0065)
    assert dialog.open_button.isEnabled()
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    assert len(frames) == 10
    # the last frame shows the square where it was when Export was pressed (centre), not at x=3
    expected = render_frame(make_camera(exported_project.canvas), Evaluator(exported_project).frame(0.9))[
        ..., :3
    ]
    moved = render_frame(make_camera(win.project.canvas), Evaluator(win.project).frame(0.9))[..., :3]
    error = np.abs(frames[-1].astype(int) - expected.astype(int)).mean()
    assert error < np.abs(frames[-1].astype(int) - moved.astype(int)).mean()
    assert error < 8  # video compression noise only


def test_cancel_keeps_an_existing_video(window, qt_app, tmp_path) -> None:
    win = window(duration=60.0)
    out = tmp_path / "video.mp4"
    out.write_bytes(b"previous video")
    win.show_export_dialog()
    dialog = win.export_dialog
    dialog.path.setText(str(out))
    dialog.start()
    wait_until(qt_app, lambda: dialog.bar.maximum() > 1)  # rendering frames
    assert "Rendering frame" in dialog.status.text()
    dialog.cancel_button.click()
    assert not dialog.running
    assert "Cancelled" in dialog.status.text()
    assert out.read_bytes() == b"previous video"
    assert dialog.export_button.isEnabled()


def test_quitting_during_an_export_asks_first(window, qt_app, tmp_path, monkeypatch) -> None:
    win = window(duration=60.0)
    win.show_export_dialog()
    dialog = win.export_dialog
    dialog.path.setText(str(tmp_path / "video.mp4"))
    dialog.start()
    monkeypatch.setattr(win, "ask_stop_export", lambda: "cancel")
    event = QCloseEvent()
    win.closeEvent(event)
    assert not event.isAccepted() and dialog.running
    monkeypatch.setattr(win, "ask_stop_export", lambda: "stop")
    event = QCloseEvent()
    win.closeEvent(event)
    assert event.isAccepted() and not dialog.running
    assert not (tmp_path / "video.partial.mp4").exists()


def test_errors_are_shown(window, qt_app, tmp_path) -> None:
    win = window()
    win.show_export_dialog()
    dialog = win.export_dialog
    folder = tmp_path / "taken.mp4"
    folder.mkdir()
    dialog.path.setText(str(folder))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running)
    assert dialog.status.text().startswith("Export failed:")
    assert "folder" in dialog.status.text()


def test_export_needs_a_project(qt_app) -> None:
    win = MainWindow()
    win.show_export_dialog()
    assert win.export_dialog is None
    win.close()
