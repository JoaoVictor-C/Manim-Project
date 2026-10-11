"""P4c acceptance: traced paths and a plugin simulation, from the library to a video and a
Manim file (ADR 0033).

A dot runs along a sine graph on axes and leaves a trace; the example plugin's
swinging pendulum (examples/plugins/swinging_pendulum.py, in a plugin folder)
swings and its bob is traced too. With the real build worker and preview
process: scrubbing in any order equals playing, frames rendered ahead equal
live frames, the export process's video and the exact Python scene rendered by
``manim render`` match the editor.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import random
import shutil
from pathlib import Path

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")

from manim_studio import plugins
from manim_studio.core.schema import Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_p3b import add_graph
from ui.test_acceptance_p4a import assert_matches_editor, manim_render
from ui.test_acceptance_p4b import live, shown
from ui.test_acceptance_v1 import menu_action, timeline_menu, wait_until

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # real processes; renders with the Manim command line

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "plugins" / "swinging_pendulum.py"


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    folder = tmp_path / "plugins"
    folder.mkdir()
    shutil.copy(EXAMPLE, folder)
    monkeypatch.setenv("MANIM_STUDIO_PLUGINS", str(folder))  # helper processes load it from here
    monkeypatch.setenv("MANIM_STUDIO_WORKER", "1")
    monkeypatch.setenv("MANIM_STUDIO_PREVIEW", "1")
    plugins.load_plugins()
    assert plugins.loaded == {str(folder / "swinging_pendulum.py"): ["SwingingPendulum"]}, plugins.problems
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.close()
    plugins.unregister("SwingingPendulum")
    plugins.loaded.clear()


def test_traces_and_a_simulation_play_export_and_become_a_manim_file(window, qt_app, tmp_path) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    small = {"width_px": 320, "height_px": 180, "fps": 10, "duration": 3.0}
    window.document.replace(
        window.project.model_copy(update={"canvas": window.project.canvas.model_copy(update=small)})
    )

    # a dot runs along a sine graph and leaves a trace
    menu_action(window.layers.library_menu, "Axes").trigger()
    wait_until(qt_app, lambda: len(window.project.roots()) == 1)
    axes = window.project.roots()[0].id
    sine = add_graph(window, qt_app, axes, "sin(x)")
    menu_action(window.layers.library_menu, "Dot").trigger()
    wait_until(qt_app, lambda: len(window.project.roots()) == 2)
    dot = window.project.roots()[-1].id
    graph_name = window.project.layer(sine).name or sine
    menu_action(timeline_menu(window, dot, 0.0), "Add clip", "Move", "MoveAlongPath", graph_name).trigger()
    window.selection.set(dot)
    menu_action(window.layers.library_menu, "Traced path").trigger()
    dot_trace = window.project.layers[-1].id
    window.properties.fields["style.stroke"].commit("#facc15")

    # the pendulum swings, its bob traced, fading after a second
    menu_action(window.layers.library_menu, "Swinging pendulum").trigger()
    swing = window.project.layers[-1].id
    window.properties.fields["base.position"].commit((3.5, 1.5))
    menu_action(window.layers.library_menu, "Traced path").trigger()
    bob_trace = window.project.layers[-1].id
    window.properties.fields["params.dissipate"].commit(1.0)
    project = window.project
    assert project.layer(bob_trace).spec.params == {"target": swing, "dissipate": 1.0}
    assert window.evaluator.build_errors() == {}

    # the traces end where their objects are
    layers = dict(window.evaluator.frame_layers(1.5))
    assert layers[dot_trace].get_end() == pytest.approx(layers[dot].get_center())
    assert layers[bob_trace].get_end() == pytest.approx(layers[swing][2].get_center())

    # scrubbing in any order shows what playing in order shows
    camera = make_camera(project.canvas)
    times = [i / 10 for i in range(30)]
    played = {t: render_frame(camera, window.evaluator.frame(t)) for t in times}
    for t in random.Random(8).sample(times, len(times)):
        assert np.array_equal(render_frame(camera, window.evaluator.frame(t)), played[t]), t

    # the preview process renders the same frames (it loads the plugin itself)
    ahead = window.render_ahead
    wait_until(qt_app, lambda: ahead is not None and len(ahead.store) == ahead.store.total, timeout=120)
    for t in (0.7, 2.4):
        window.seek(t)
        assert window.canvas.from_cache and np.array_equal(shown(window), live(window, t)), t

    # the export process too
    window.show_export_dialog()
    dialog = window.export_dialog
    video = tmp_path / "traces.mp4"
    dialog.path.setText(str(video))
    dialog.start()
    wait_until(qt_app, lambda: not dialog.running, timeout=120)
    assert dialog.status.text().startswith("Exported to"), dialog.status.text()
    with av.open(str(video)) as container:
        assert_matches_editor(window, [f.to_ndarray(format="rgb24") for f in container.decode(video=0)])

    # and the Python export is the exact scene, rendered with the plugin by `manim render`
    scene = tmp_path / "traces.py"
    window.ask_python_path = lambda start: str(scene)
    menu_action(window.menuBar(), "File", "Export Python...").trigger()
    assert "a simulated layer" in window.statusBar().currentMessage()
    assert_matches_editor(window, manim_render(scene, "Traces"))
    assert project.layer(swing).base == Transform2D(position=(3.5, 1.5))
