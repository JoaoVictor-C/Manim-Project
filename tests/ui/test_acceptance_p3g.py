"""P3g acceptance: graphs animate with their axes; a shape turns along a curve (ADR 0029).

Axes from the library with sin(x) added through Parts > Add graph..., one Create
on the axes from the timeline (it draws the graph too) and an Indicate later (it
scales the whole figure); a triangle rides the graph with Turn: along set in
Properties and turns with it. Scrubbing shows what playing shows and the export
shows what the editor shows.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math
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


def pixels(window, t: float, layer_ids: set[str]) -> np.ndarray:
    camera = make_camera(window.project.canvas)
    return render_frame(camera, [mob for i, mob in window.evaluator.frame_layers(t) if i in layer_ids])


def test_graphs_animate_with_their_axes_and_a_shape_turns_along_one(window, qt_app, tmp_path) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    menu_action(window.layers.library_menu, "Axes").trigger()
    wait_until(qt_app, lambda: len(window.project.roots()) == 1)
    axes = window.project.roots()[0].id
    sine = add_graph(window, qt_app, axes, "sin(x)")
    menu_action(timeline_menu(window, axes, 0.0), "Add clip", "Appear / disappear", "Create").trigger()
    create = window.project.layer(axes).clips[0]
    menu_action(timeline_menu(window, axes, create.end + 0.5), "Add clip", "Emphasis", "Indicate").trigger()
    indicate = window.project.layer(axes).clips[1]

    # the axes' Create draws the graph too - after the axes, as Manim's Create(VGroup(axes, graph))
    blank = pixels(window, 0.0, {sine})
    half = pixels(window, create.start + create.duration * 0.985, {sine})  # last of the group's leaves
    full = pixels(window, create.end + 0.1, {sine})
    assert np.abs(half.astype(int) - blank).max() > 50  # drawing
    assert not np.array_equal(half, full)  # not yet complete

    # Indicate on the axes scales the graph with them
    rest = dict(window.evaluator.frame_layers(create.end + 0.1))[sine]
    width_at_rest = rest.width
    peak = dict(window.evaluator.frame_layers(indicate.start + indicate.duration / 2))[sine]
    assert peak.width > width_at_rest * 1.1

    # a triangle rides the curve, turning with it
    menu_action(window.layers.library_menu, "Triangle").trigger()
    wait_until(qt_app, lambda: len(window.project.roots()) == 2)
    car = window.project.roots()[-1].id
    window.properties.fields["base.scale"].commit(0.3)
    graph_name = window.project.layer(sine).name or sine
    menu_action(timeline_menu(window, car, 0.0), "Add clip", "Move", "MoveAlongPath", graph_name).trigger()
    run = window.project.layer(car).clips[0]
    window.selection.set(car, run.id)
    qt_app.processEvents()
    window.properties.fields["clip.params.rotate"].commit("along")
    run = window.project.layer(car).clips[0]
    assert run.params == {"path": sine, "rotate": "along"}

    def heading(t: float) -> float:  # the direction of the triangle's first edge
        points = dict(window.evaluator.frame_layers(t))[car].family_members_with_points()[0].points
        return math.atan2(points[3][1] - points[0][1], points[3][0] - points[0][0])

    curve = adapter.build_child(window.project.layer(axes).spec, window.project.layer(sine).spec)
    for alpha in (0.25, 0.5):  # sin(x) climbs, then falls: the triangle tilts with it
        t = run.start + alpha * run.duration
        a = curve.point_from_proportion(max(m.smooth(alpha) - 1e-6, 0))
        b = curve.point_from_proportion(m.smooth(alpha) + 1e-6)
        start_a, start_b = curve.point_from_proportion(0), curve.point_from_proportion(1e-6)
        expected = math.atan2(b[1] - a[1], b[0] - a[0]) - math.atan2(
            start_b[1] - start_a[1], start_b[0] - start_a[0]
        )
        turned = heading(t) - heading(run.start)
        assert math.remainder(turned - expected, 2 * math.pi) == pytest.approx(0, abs=1e-4), alpha

    # scrubbing in any order shows what playing in order shows
    evaluator = window.evaluator
    project = window.project
    camera = make_camera(project.canvas)
    times = [i / project.canvas.fps for i in range(0, int(project.canvas.duration * project.canvas.fps), 3)]
    played = {t: render_frame(camera, evaluator.frame(t)) for t in times}
    shuffled = times[:]
    random.Random(12).shuffle(shuffled)
    for t in shuffled:
        assert np.array_equal(render_frame(camera, evaluator.frame(t)), played[t]), t

    # the export shows exactly what the editor shows
    window.show_export_dialog()
    dialog = window.export_dialog
    out = tmp_path / "p3g.mp4"
    dialog.path.setText(str(out))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=180)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    all_times = frame_times(project.canvas)
    for t in (create.start + 0.4, indicate.start + 0.3, run.start + 0.6):
        i = min(range(len(all_times)), key=lambda k: abs(all_times[k] - t))
        expected = render_frame(camera, evaluator.frame(all_times[i]))[:, :, :3].astype(int)
        assert np.abs(frames[i].astype(int) - expected).mean() < 3, t
