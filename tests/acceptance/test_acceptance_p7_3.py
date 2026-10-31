"""P7.3 acceptance: animate one property without the graph, in the real window.

On the Animate page: expand the square's timeline row with its twirl, key its rotation at two
moments with the rotation row's diamond, give the second key a value, drag it later in its row,
ease the first from Properties, delete the second with Delete - each one undo step, the other
properties never keyed. Choosing the rotation row shows only its curve in the graph; Record is
Edit > Auto-key; A frames the keys.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from manim_studio.core.model.schema import Canvas, Easing, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.timeline.view import KEY_BUTTON_X
from ui.panels.test_property_rows import click_header, move, press, release, sub_point, sub_y, twirl

pytestmark = pytest.mark.ui


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "scene.json"
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=30, duration=4.0),
        layers=[Layer(id="sq", spec=Spec(type="Square")), Layer(id="dot", spec=Spec(type="Dot"))],
    )
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    win.load(path)
    win.show_page("animate")
    qt_app.processEvents()
    yield win
    win.close()


def rotation(window) -> list[tuple[float, float]]:
    return [(k.t, k.value) for k in window.document.project.layer("sq").tracks.get("rotation", [])]


def test_key_move_ease_and_delete_one_property(window, qt_app) -> None:
    timeline, stack = window.timeline, window.document.undo_stack
    graph = window.pages.pages["animate"].graph

    # 1. the twirl opens the square's property rows; nothing is edited
    twirl(timeline, "sq")
    assert timeline.sub_rows("sq") == (
        "position",
        "scale",
        "scale_x",
        "scale_y",
        "rotation",
        "opacity",
    )
    assert stack.count() == 0

    # 2. the rotation row's diamond keys rotation at the playhead: at 0 s, then at 2 s
    window.seek(0.0)
    click_header(timeline, KEY_BUTTON_X, sub_y(timeline, "sq", "rotation"))
    assert rotation(window) == [(0.0, 0.0)] and stack.count() == 1
    window.seek(2.0)
    click_header(timeline, KEY_BUTTON_X, sub_y(timeline, "sq", "rotation"))
    assert rotation(window) == [(0.0, 0.0), (2.0, 0.0)] and stack.count() == 2
    assert (window.selection.layer_id, window.selection.key_time) == ("sq", 2.0)
    window.properties.fields["keys.rotation.value"].commit(90.0)  # Properties shows that key
    assert rotation(window) == [(0.0, 0.0), (2.0, 90.0)] and stack.count() == 3
    assert set(window.document.project.layer("sq").tracks) == {"rotation"}  # nothing else keyed

    # 3. drag the 2 s key to 3 s in its row: one undo step
    start = sub_point(timeline, 2.0, "sq", "rotation")
    end = QPointF(timeline.mapFromScene(QPointF(timeline.scale.x(3.0), 0)).x(), start.y())
    press(timeline, start)
    move(timeline, end)
    qt_app.processEvents()
    release(timeline, end)
    assert rotation(window) == [(0.0, 0.0), (pytest.approx(3.0), 90.0)] and stack.count() == 4
    assert window.selection.key_time == pytest.approx(3.0)

    # 4. ease the first key from Properties, after clicking it in its row
    first = sub_point(timeline, 0.0, "sq", "rotation")
    press(timeline, first)
    release(timeline, first)
    assert window.properties.key_time == 0.0 and timeline.selected_key_prop == "rotation"
    window.properties.fields["keys.rotation.ease"].commit(Easing(name="ease_out_back"))
    keys = window.document.project.layer("sq").tracks["rotation"]
    assert keys[0].ease == Easing(name="ease_out_back") and stack.count() == 5

    # 5. click the last key and press Delete: only it goes
    last = sub_point(timeline, 3.0, "sq", "rotation")
    press(timeline, last)
    release(timeline, last)
    timeline.setFocus()
    QTest.keyClick(timeline, Qt.Key.Key_Delete)
    assert [t for t, _ in rotation(window)] == [0.0] and stack.count() == 6

    # each step undoes alone
    stack.undo()
    assert [t for t, _ in rotation(window)] == [0.0, pytest.approx(3.0)]
    stack.undo()
    assert window.document.project.layer("sq").tracks["rotation"][0].ease != Easing(name="ease_out_back")

    # 6. choosing the rotation row shows only its curve
    assert [c.name for c in graph.curves()] == [
        "x",
        "y",
        "scale",
        "scale_x",
        "scale_y",
        "rotation",
        "opacity",
    ]
    click_header(timeline, 60, sub_y(timeline, "sq", "rotation"))
    assert [c.name for c in graph.curves()] == ["rotation"]


def test_record_is_auto_key_and_a_frames_the_keys(window, qt_app) -> None:
    page = window.pages.pages["animate"]
    record = page.record_button
    assert record.isCheckable() and not record.isChecked() and not record.icon().isNull()
    record.click()
    assert window.auto_key_action.isChecked()
    window.auto_key_action.setChecked(False)  # Edit > Auto-key
    assert not record.isChecked()
    graph = page.graph
    zoomed = graph.scale.zoomed(8.0, 0)
    graph.scale = zoomed
    window.timeline.setFocus()
    QTest.keyClick(window.timeline, Qt.Key.Key_A)
    framed = graph.scale
    assert framed != zoomed
    graph.frame_all()
    assert graph.scale == framed
