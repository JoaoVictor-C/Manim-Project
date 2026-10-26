"""P3d acceptance: bend a motion path on the canvas (ADR 0026).

A dot from the library, two position keys set through Properties, its first
key made smooth with a double-click and its handle pulled up on the canvas: the
dot then travels an arc, at even speed, scrubbing shows what playing shows and
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

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF

from acceptance.test_acceptance_v1 import menu_action, wait_until
from manim_studio.core.engine.evaluator import layer_transform
from manim_studio.core.model import motion_paths
from manim_studio.render.cairo_export import frame_times, make_camera, render_frame
from manim_studio.ui.main_window import MainWindow
from ui.canvas.test_canvas_tools import drag, mouse, px

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # the export starts a real process


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()


def test_bend_a_motion_path(window, qt_app, tmp_path) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    menu_action(window.layers.library_menu, "Dot").trigger()
    wait_until(qt_app, lambda: len(window.project.roots()) == 1)
    dot = window.project.roots()[0].id
    fields = window.properties.fields
    fields["base.position"].commit((-4.0, -1.0))
    fields["keys.position"].commit(True)  # a key at 0 s
    window.seek(2.0)
    window.properties.fields["base.position"].commit((4.0, -1.0))  # a key at 2 s
    keys = window.project.layer(dot).tracks["position"]
    assert [(k.t, k.value) for k in keys] == [(0.0, (-4.0, -1.0)), (2.0, (4.0, -1.0))]

    window.seek(3.0)
    window.selection.set(dot)
    qt_app.processEvents()
    mouse(window, QEvent.Type.MouseButtonDblClick, px(window, -4.0, -1.0))  # smooth: a handle appears
    qt_app.processEvents()
    handle = window.canvas.motion.keys[0].out_handle
    start = px(window, *handle)
    drag(window, start, start + QPointF(0, -150), qt_app)  # pull it up: an arc
    layer = window.project.layer(dot)
    first, last = layer.tracks["position"]
    assert first.out_tangent[1] > 1.0

    # the dot travels the arc, at even speed along it
    mid = np.array(layer_transform(layer, 1.0).position)
    assert mid[1] > -1.0 + 0.3  # off the straight line
    reference = motion_paths.point_at(first.value, first.out_tangent, last.in_tangent, last.value, 0.5)
    assert mid == pytest.approx(reference)  # smooth(0.5) = 0.5 of the length
    for t in (0.3, 0.7, 1.4, 1.8):  # the ease decides the fraction of the ARC travelled
        u = m.smooth(t / 2)
        expected = motion_paths.point_at(first.value, first.out_tangent, last.in_tangent, last.value, u)
        assert np.array(layer_transform(layer, t).position) == pytest.approx(expected), t

    # scrubbing in any order shows what playing in order shows
    evaluator = window.evaluator
    project = window.project
    camera = make_camera(project.canvas)
    times = [i / project.canvas.fps for i in range(0, int(project.canvas.duration * project.canvas.fps), 2)]
    played = {t: render_frame(camera, evaluator.frame(t)) for t in times}
    shuffled = times[:]
    random.Random(8).shuffle(shuffled)
    for t in shuffled:
        assert np.array_equal(render_frame(camera, evaluator.frame(t)), played[t]), t

    # the export shows exactly what the editor shows
    window.show_export_dialog()
    dialog = window.export_dialog
    out = tmp_path / "p3d.mp4"
    dialog.path.setText(str(out))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=180)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(out)) as container:
        frames = [f.to_ndarray(format="rgb24") for f in container.decode(video=0)]
    all_times = frame_times(project.canvas)
    for t in (0.5, 1.0, 1.5):
        i = min(range(len(all_times)), key=lambda k: abs(all_times[k] - t))
        expected = render_frame(camera, evaluator.frame(all_times[i]))[:, :, :3].astype(int)
        assert np.abs(frames[i].astype(int) - expected).mean() < 3, t
