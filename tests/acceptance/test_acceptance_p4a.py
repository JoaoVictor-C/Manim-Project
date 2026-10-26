"""P4a acceptance: from the editor to a Manim file that renders the same video (ADR 0031).

A circle drawn on and a square indicated, built through the library and the
timeline, exported with File > Export Python... (readable) and rendered with
`manim render`; then keys are set on the square and the file is exported
again (still readable: the keys as data, G3a) and rendered; then the circle is
turned, so the export is the exact scene, saying why. Every video matches the
editor's frames.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess
import sys
from pathlib import Path

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")

from acceptance.test_acceptance_v1 import menu_action, timeline_menu, wait_until
from manim_studio.render.cairo_export import frame_times, make_camera, render_frame
from manim_studio.ui.main_window import MainWindow

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # renders with the Manim command line


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def manim_render(path: Path, scene: str) -> list[np.ndarray]:
    media = path.parent / "media"
    done = subprocess.run(
        [sys.executable, "-m", "manim", "render", str(path), scene, "--media_dir", str(media)],
        capture_output=True,
        text=True,
        cwd=path.parent,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    video = next(media.rglob(f"{scene}.mp4"))
    with av.open(str(video)) as container:
        return [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]


def assert_matches_editor(window, frames: list[np.ndarray]) -> None:
    project = window.project
    times = frame_times(project.canvas)
    assert len(frames) == len(times)
    camera = make_camera(project.canvas)
    for i, t in enumerate(times):
        ours = render_frame(camera, window.evaluator.frame(t))[:, :, :3].astype(int)
        assert np.abs(frames[i].astype(int) - ours).mean() < 1.5, t  # h264 noise (B43)


def test_export_python_both_ways_and_render_with_manim(window, qt_app, tmp_path) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    window.document.replace(
        window.project.model_copy(
            update={
                "canvas": window.project.canvas.model_copy(
                    update={"width_px": 320, "height_px": 180, "fps": 10, "duration": 3.0}
                )
            }
        )
    )
    menu_action(window.layers.library_menu, "Circle").trigger()
    menu_action(window.layers.library_menu, "Square").trigger()
    wait_until(qt_app, lambda: len(window.project.roots()) == 2)
    circle, square = (x.id for x in window.project.roots())
    window.selection.set(square)
    window.properties.fields["base.position"].commit((2.5, 0.5))
    menu_action(timeline_menu(window, circle, 0.0), "Add clip", "Appear / disappear", "Create").trigger()
    menu_action(timeline_menu(window, square, 1.2), "Add clip", "Emphasis", "Indicate").trigger()

    readable = tmp_path / "shapes.py"
    window.ask_python_path = lambda start: str(readable)
    menu_action(window.menuBar(), "File", "Export Python...").trigger()
    assert window.statusBar().currentMessage().endswith("readable Manim code")
    assert "manim_studio" not in readable.read_text(encoding="utf-8")
    assert_matches_editor(window, manim_render(readable, "Shapes"))

    window.seek(0.0)
    window.selection.set(square)
    window.properties.fields["keys.position"].commit(True)  # a key at 0 s
    window.seek(2.5)
    window.properties.fields["base.position"].commit((-2.5, -1.0))  # a key at 2.5 s
    keyed = tmp_path / "keyed" / "shapes keyed.py"
    keyed.parent.mkdir()
    window.ask_python_path = lambda start: str(keyed)
    menu_action(window.menuBar(), "File", "Export Python...").trigger()
    assert window.statusBar().currentMessage().endswith("readable Manim code")  # G3a: keys as data
    assert "manim_studio" not in keyed.read_text(encoding="utf-8")
    assert_matches_editor(window, manim_render(keyed, "ShapesKeyed"))

    window.selection.set(circle)
    window.properties.fields["base.rotation"].commit(30.0)  # its Create acts before the turn
    exact = tmp_path / "turned" / "shapes turned.py"
    exact.parent.mkdir()
    window.ask_python_path = lambda start: str(exact)
    menu_action(window.menuBar(), "File", "Export Python...").trigger()
    assert (
        "exact scene" in window.statusBar().currentMessage()
        and "turned or scaled" in window.statusBar().currentMessage()
    )
    assert_matches_editor(window, manim_render(exact, "ShapesTurned"))
