"""P3b acceptance: plot sin(x), draw it, turn it into a parabola (ADR 0024).

Axes from the library, two graphs added through Parts > Add graph..., Create on
the first from the timeline and Turn into > Transform into the second. The
graphs ride on the axes, scrubbing shows what playing shows, and the export
shows what the editor shows.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import random

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")

from acceptance.test_acceptance_v1 import menu_action, timeline_menu, wait_until
from manim_studio.render.cairo_export import frame_times, make_camera, render_frame
from manim_studio.ui.main_window import MainWindow

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # the export starts a real process


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def add_graph(window, qt_app, axes: str, expression: str) -> str:
    before = {layer.id for layer in window.project.children(axes)}
    window.layers.select(axes)
    window.layers.ask_expression = lambda: expression
    window.layers.add_graph_action.trigger()
    wait_until(qt_app, lambda: len(window.project.children(axes)) == len(before) + 1)
    return next(layer.id for layer in window.project.children(axes) if layer.id not in before)


def test_plot_draw_and_morph_a_graph(window, qt_app, tmp_path) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    menu_action(window.layers.library_menu, "Axes").trigger()
    wait_until(qt_app, lambda: len(window.project.roots()) == 1)
    axes = window.project.roots()[0].id
    window.properties.fields["base.position"].commit((0.0, -0.3))
    sine = add_graph(window, qt_app, axes, "sin(x)")
    parabola = add_graph(window, qt_app, axes, "x**2/10 - 1")

    menu_action(timeline_menu(window, sine, 0.0), "Add clip", "Appear / disappear", "Create").trigger()
    create = window.project.layer(sine).clips[0]
    menu = timeline_menu(window, sine, create.end + 0.5)
    target_name = window.project.layer(parabola).name or parabola
    menu_action(menu, "Add clip", "Turn into", "Transform", target_name).trigger()
    morph = next(c for c in window.project.layer(sine).clips if c.to_layer == parabola)

    evaluator = window.evaluator
    assert [i for i, _ in evaluator.frame_layers(create.end + 0.1)] == [axes, sine]
    assert [i for i, _ in evaluator.frame_layers((morph.start + morph.end) / 2)] == [axes, sine]
    assert [i for i, _ in evaluator.frame_layers(morph.end + 0.1)] == [axes, parabola]
    # the graphs ride on the axes: moved by their position
    drawn = dict(evaluator.frame_layers(morph.end + 0.1))[parabola]
    assert drawn.get_bottom()[1] == pytest.approx(-0.3 - 1.0, abs=0.05)  # min of x^2/10 - 1 is -1

    # scrubbing in any order shows what playing in order shows
    project = window.project
    camera = make_camera(project.canvas)
    times = [i / project.canvas.fps for i in range(0, int(project.canvas.duration * project.canvas.fps), 2)]
    played = {t: render_frame(camera, evaluator.frame(t)) for t in times}
    shuffled = times[:]
    random.Random(5).shuffle(shuffled)
    for t in shuffled:
        assert np.array_equal(render_frame(camera, evaluator.frame(t)), played[t]), t

    # the export shows exactly what the editor shows
    window.show_export_dialog()
    dialog = window.export_dialog
    out = tmp_path / "p3b.mp4"
    dialog.path.setText(str(out))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=180)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    all_times = frame_times(project.canvas)
    for t in (create.start + 0.4, (morph.start + morph.end) / 2, morph.end + 0.2):
        i = min(range(len(all_times)), key=lambda k: abs(all_times[k] - t))
        expected = render_frame(camera, evaluator.frame(all_times[i]))[:, :, :3].astype(int)
        assert np.abs(frames[i].astype(int) - expected).mean() < 3, t
