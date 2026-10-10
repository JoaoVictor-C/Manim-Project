"""P3h acceptance: the area under a curve, built in the editor (ADR 0030).

Axes from the library, sin(x) through Parts > Add graph..., then Parts > Add to
axes: an area, Riemann rectangles, axis labels and a graph label; the area is
drawn on with DrawBorderThenFill and the rectangles fade in from the timeline.
Each object is what Manim's helper draws; scrubbing shows what playing shows;
the export shows what the editor shows.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import random

import av
import manim as m
import numpy as np
import pytest

pytestmark = [pytest.mark.ui, pytest.mark.slow, pytest.mark.latex]  # export process; TeX labels

pytest.importorskip("PySide6")

from manim_studio.core import adapter
from manim_studio.render.cairo_export import frame_times, make_camera, render_frame
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_p3b import add_graph
from ui.test_acceptance_v1 import menu_action, timeline_menu, wait_until


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def add_to_axes(window, qt_app, axes: str, label: str) -> str:
    before = {x.id for x in window.project.children(axes)}
    window.layers.select(axes)
    window.layers.update_buttons()
    menu_action(window.layers.part_button.menu(), "Add to axes", label).trigger()
    wait_until(qt_app, lambda: len(window.project.children(axes)) == len(before) + 1)
    return next(x.id for x in window.project.children(axes) if x.id not in before)


def test_the_area_under_a_curve(window, qt_app, tmp_path) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    menu_action(window.layers.library_menu, "Axes").trigger()
    wait_until(qt_app, lambda: len(window.project.roots()) == 1)
    axes = window.project.roots()[0].id
    sine = add_graph(window, qt_app, axes, "sin(x)")
    area = add_to_axes(window, qt_app, axes, "Area")
    rects = add_to_axes(window, qt_app, axes, "Riemann rectangles")
    labels = add_to_axes(window, qt_app, axes, "Axis labels")
    name = add_to_axes(window, qt_app, axes, "Graph label")
    project = window.project
    assert [project.layer(i).spec.params.get("graph") for i in (area, rects, name)] == [sine] * 3

    menu_action(
        timeline_menu(window, area, 0.0), "Add clip", "Appear / disappear", "DrawBorderThenFill"
    ).trigger()
    menu_action(timeline_menu(window, rects, 1.5), "Add clip", "Appear / disappear", "FadeIn").trigger()
    draw = window.project.layer(area).clips[0]

    # each object is Manim's helper on the same axes and curve
    a = adapter.build_mobject(window.project.layer(axes).spec)
    curve = adapter.build_child(window.project.layer(axes).spec, window.project.layer(sine).spec)
    later = dict(window.evaluator.frame_layers(3.0))
    expected_area = a.get_area(curve, x_range=(0.0, 2.0))
    assert np.allclose(later[area].family_members_with_points()[0].points, expected_area.points, atol=1e-6)
    expected_rects = a.get_riemann_rectangles(curve, x_range=(0.0, 3.0), dx=0.25)
    assert len(later[rects].family_members_with_points()) == len(expected_rects.family_members_with_points())
    x_label, y_label = (sub.get_center() for sub in a.get_axis_labels(m.MathTex("x"), m.MathTex("y")))
    drawn_labels = later[labels].family_members_with_points()
    assert drawn_labels[0].get_center() == pytest.approx(x_label, abs=0.05)
    assert drawn_labels[-1].get_center() == pytest.approx(y_label, abs=0.05)
    assert later[name].get_center()[0] > a.c2p(2.0, 0)[0]  # up and right of the curve at x = 2

    # the area is drawn on: invisible at its start, there at its end
    camera = make_camera(window.project.canvas)

    def area_pixels(t: float) -> np.ndarray:
        return render_frame(camera, [mob for i, mob in window.evaluator.frame_layers(t) if i == area])

    blank = render_frame(camera, [])
    assert np.abs(area_pixels(draw.start + 0.01).astype(int) - blank).max() < 60
    assert np.abs(area_pixels(draw.end + 0.1).astype(int) - blank).max() > 60

    # scrubbing in any order shows what playing in order shows
    evaluator = window.evaluator
    project = window.project
    times = [i / project.canvas.fps for i in range(0, int(project.canvas.duration * project.canvas.fps), 3)]
    played = {t: render_frame(camera, evaluator.frame(t)) for t in times}
    shuffled = times[:]
    random.Random(13).shuffle(shuffled)
    for t in shuffled:
        assert np.array_equal(render_frame(camera, evaluator.frame(t)), played[t]), t

    # the export shows exactly what the editor shows
    window.show_export_dialog()
    dialog = window.export_dialog
    out = tmp_path / "p3h.mp4"
    dialog.path.setText(str(out))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=180)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    all_times = frame_times(project.canvas)
    for t in (draw.start + 0.5, 1.8, 3.0):
        i = min(range(len(all_times)), key=lambda k: abs(all_times[k] - t))
        expected = render_frame(camera, evaluator.frame(all_times[i]))[:, :, :3].astype(int)
        assert np.abs(frames[i].astype(int) - expected).mean() < 3, t
