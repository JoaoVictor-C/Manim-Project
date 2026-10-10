"""P3c acceptance: a dot runs along sin(x) (ADR 0025).

Axes from the library with a graph added through Parts > Add graph..., a Dot
from the library, and Add clip > Move > MoveAlongPath > the graph from the
timeline. The dot's centre is on the curve at sampled times, scrubbing shows
what playing shows, and the export shows what the editor shows.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import random

import av
import manim as m
import numpy as np
import pytest

pytest.importorskip("PySide6")

from manim_studio.core import adapter
from manim_studio.render.cairo_export import frame_times, make_camera, render_frame
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_p3b import add_graph
from ui.test_acceptance_v1 import menu_action, timeline_menu, wait_until

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # the export starts a real process


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def test_a_dot_runs_along_a_graph(window, qt_app, tmp_path) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    menu_action(window.layers.library_menu, "Axes").trigger()
    wait_until(qt_app, lambda: len(window.project.roots()) == 1)
    axes = window.project.roots()[0].id
    sine = add_graph(window, qt_app, axes, "sin(x)")
    menu_action(window.layers.library_menu, "Dot").trigger()
    wait_until(qt_app, lambda: len(window.project.roots()) == 2)
    dot = window.project.roots()[-1].id

    graph_name = window.project.layer(sine).name or sine
    menu_action(timeline_menu(window, dot, 0.0), "Add clip", "Move", "MoveAlongPath", graph_name).trigger()
    run = window.project.layer(dot).clips[0]
    assert run.params == {"path": sine}

    evaluator = window.evaluator
    curve = adapter.build_child(window.project.layer(axes).spec, window.project.layer(sine).spec)
    for alpha in (0.0, 0.25, 0.6, 0.95):
        t = run.start + alpha * run.duration
        centre = dict(evaluator.frame_layers(t))[dot].get_center()
        assert centre == pytest.approx(curve.point_from_proportion(m.smooth(alpha)), abs=1e-6), alpha
    after = dict(evaluator.frame_layers(run.end + 0.5))[dot].get_center()
    assert after == pytest.approx(curve.point_from_proportion(1.0), abs=1e-6)  # stays at the end

    # scrubbing in any order shows what playing in order shows
    project = window.project
    camera = make_camera(project.canvas)
    times = [i / project.canvas.fps for i in range(0, int(project.canvas.duration * project.canvas.fps), 2)]
    played = {t: render_frame(camera, evaluator.frame(t)) for t in times}
    shuffled = times[:]
    random.Random(6).shuffle(shuffled)
    for t in shuffled:
        assert np.array_equal(render_frame(camera, evaluator.frame(t)), played[t]), t

    # the export shows exactly what the editor shows
    window.show_export_dialog()
    dialog = window.export_dialog
    out = tmp_path / "p3c.mp4"
    dialog.path.setText(str(out))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=180)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    all_times = frame_times(project.canvas)
    for t in (run.start + 0.3, (run.start + run.end) / 2, run.end + 0.3):
        i = min(range(len(all_times)), key=lambda k: abs(all_times[k] - t))
        expected = render_frame(camera, evaluator.frame(all_times[i]))[:, :, :3].astype(int)
        assert np.abs(frames[i].astype(int) - expected).mean() < 3, t
