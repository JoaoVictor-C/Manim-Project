"""Simulated layers in the editor (P4c.2, ADR 0033): tracing from the library, the target
chooser in Properties, no clips on the timeline, a plugin simulation from the library."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import manim as m
import pytest

pytest.importorskip("PySide6")

from acceptance.test_acceptance_v1 import menu_action, timeline_menu
from manim_studio import plugins
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "plugins" / "swinging_pendulum.py"


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=3.0),
        layers=[
            Layer(id="dot", name="Dot", spec=Spec(type="Dot")),
            Layer(id="sq", name="Square", spec=Spec(type="Square")),
        ],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.show()
    win.load(path)
    yield win
    win.close()


def test_a_traced_path_follows_the_selected_object(window) -> None:
    window.selection.clear()  # nothing selected
    menu_action(window.layers.library_menu, "Traced path").trigger()
    assert len(window.project.layers) == 2
    assert window.statusBar().currentMessage() == "Select the object to trace first"

    window.selection.set("dot")
    menu_action(window.layers.library_menu, "Traced path").trigger()
    trace = window.project.layers[-1]
    assert trace.spec.type == "TracedPath" and trace.spec.params["target"] == "dot"
    assert window.selection.layer_id == trace.id

    fields = window.properties.fields
    box = fields["params.target"].widget
    assert [box.itemText(i) for i in range(box.count())] == ["Dot", "Square"]  # not itself
    fields["params.target"].commit("sq")
    fields["params.dissipate"].commit(0.5)
    assert window.project.layer(trace.id).spec.params == {"target": "sq", "dissipate": 0.5}

    add = menu_action(timeline_menu(window, trace.id, 1.0), "Add clip (none: it is simulated)")
    assert not add.isEnabled()


def test_a_plugin_simulation_is_added_from_the_library_and_traced(window) -> None:
    plugins.load_file(EXAMPLE)
    try:
        window.layers.library_menu = None
        window.layers._library_menu()  # the library is built once: rebuild it with the plugin
        menu_action(window.layers.library_menu, "Swinging pendulum").trigger()
        swing = window.project.layers[-1]
        assert swing.spec.type == "SwingingPendulum" and window.evaluator.build_errors() == {}
        menu_action(window.layers.library_menu, "Traced path").trigger()
        trace = window.project.layers[-1]
        assert trace.spec.params["target"] == swing.id
        drawn = dict(window.evaluator.frame_layers(2.0))
        assert len(drawn[trace.id].get_subpaths()) == 1 and isinstance(drawn[swing.id], m.VGroup)
        assert drawn[trace.id].get_end() == pytest.approx(drawn[swing.id][2].get_center())  # at the bob
    finally:
        plugins.unregister("SwingingPendulum")
