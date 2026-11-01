"""The inspector's Properties | Clip | Scene tabs (ADR 0084) and Add object > Camera once there is one."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.model.schema import Canvas, Clip, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.panels.inspector_tabs import CLIP, PROPERTIES, SCENE

pytestmark = pytest.mark.ui


def scene() -> Project:
    a = Layer(
        id="a",
        spec=Spec(type="Square", params={"side_length": 1.0}),
        clips=[
            Clip(id="c1", kind="Create", start=0.5, duration=1.0),
            Clip(id="c2", kind="Indicate", start=2.0, duration=1.0),
        ],
    )
    b = Layer(id="b", spec=Spec(type="Circle", params={"radius": 0.5}))
    return Project(canvas=Canvas(width_px=640, height_px=360, fps=30, duration=4.0), layers=[a, b])


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(scene().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1440, 900)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


def tabs(window):
    return window.properties.tabs


def test_the_three_tabs_are_always_in_the_header_and_the_title_is_not_repeated(window) -> None:
    assert list(tabs(window).buttons) == [PROPERTIES, CLIP, SCENE]
    assert [b.text() for b in tabs(window).buttons.values()] == ["Properties", "Clip", "Scene"]
    assert window.properties_card.header.isAncestorOf(tabs(window))
    assert window.properties_card.title_label.isHidden()
    assert all(not b.isHidden() for b in tabs(window).buttons.values())


def test_with_nothing_selected_scene_is_current_and_the_others_say_why_they_are_off(window) -> None:
    window.selection.clear()
    assert tabs(window).current() == SCENE
    assert not tabs(window).buttons[PROPERTIES].isEnabled() and not tabs(window).buttons[CLIP].isEnabled()
    assert "Select" in tabs(window).buttons[PROPERTIES].toolTip()


def test_the_tabs_follow_the_selection(window) -> None:
    window.selection.set("b")
    assert tabs(window).current() == PROPERTIES
    assert tabs(window).buttons[PROPERTIES].isEnabled() and not tabs(window).buttons[CLIP].isEnabled()
    window.selection.set("a", "c2")
    assert tabs(window).current() == CLIP and window.properties.clip_id == "c2"
    window.selection.set("a")
    assert tabs(window).current() == PROPERTIES and tabs(window).buttons[CLIP].isEnabled()


def test_clicking_a_tab_shows_that_view_and_scene_returns_to_the_object(window) -> None:
    window.selection.set("a")
    tabs(window).buttons[CLIP].click()  # the playhead is at 0: the first clip
    assert window.properties.clip_id == "c1" and tabs(window).current() == CLIP
    window.t = 2.5
    tabs(window).buttons[PROPERTIES].click()
    assert window.properties.layer_id == "a" and window.properties.clip_id is None
    tabs(window).buttons[CLIP].click()
    assert window.properties.clip_id == "c2"  # the clip under the playhead
    tabs(window).buttons[SCENE].click()
    assert window.properties.scene_shown and tabs(window).current() == SCENE
    assert tabs(window).buttons[PROPERTIES].isEnabled() and tabs(window).buttons[CLIP].isEnabled()
    tabs(window).buttons[PROPERTIES].click()
    assert window.properties.layer_id == "a" and tabs(window).current() == PROPERTIES


def test_an_unknown_marker_falls_back_to_the_scene_tab(window) -> None:
    window.properties.show_marker("nope")
    assert tabs(window).current() == SCENE


def test_add_object_camera_is_off_with_a_tooltip_once_the_camera_exists(window, qt_app) -> None:
    action = window.layers.add_camera_action
    assert action.isEnabled() and "Add the camera" in action.toolTip()
    window.layers.add_camera()
    qt_app.processEvents()
    assert not action.isEnabled()
    assert "already has a camera" in action.toolTip()
    window.document.undo_stack.undo()
    qt_app.processEvents()
    assert action.isEnabled()


def test_the_layers_header_counts_the_objects(window, qt_app) -> None:
    assert window.layers_count.text() == "2"
    window.layers.add_camera()
    qt_app.processEvents()
    assert window.layers_count.text() == "3"
