"""Marking slide stops (P18 D2, ADR 0087): the Marker section's Slide stop and Loop fields, the stop's
own flag and loop band on the ruler with their tooltip, and Edit > Add Slide Stop (Shift+M)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, QPointF
from PySide6.QtGui import QHelpEvent, QKeySequence

from acceptance.test_acceptance_v1 import menu_action
from manim_studio.core.model.schema import Canvas, Marker, Project
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.timeline import model
from manim_studio.ui.timeline.view import RULER_HEIGHT

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=6.0)


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=CANVAS,
        markers=[
            Marker(id="plain", t=1.0, name="Formula"),
            Marker(id="hold", t=3.0, slide="stop"),
            Marker(id="spin", t=5.0, slide="stop", loop=0.5),
        ],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    win.load(path)
    yield win
    win.close()


def marker(window, marker_id: str) -> Marker:
    return next(m for m in window.project.markers if m.id == marker_id)


def ruler_x(timeline, t: float) -> float:
    return timeline.mapFromScene(QPointF(timeline.scale.x(t), 0)).x()


# -- Properties ---------------------------------------------------------------------------


def test_the_slide_stop_box_makes_and_removes_a_stop_in_one_undo_step_each(window) -> None:
    panel, stack = window.properties, window.document.undo_stack
    panel.show_marker("plain")
    assert panel.fields["marker.slide"].widget.isChecked() is False
    assert panel.fields["marker.loop"].widget.isEnabled() is False
    steps = stack.count()
    panel.fields["marker.slide"].commit(True)
    assert marker(window, "plain").slide == "stop" and stack.count() == steps + 1
    assert stack.undoText() == "Make slide stop"
    assert panel.fields["marker.loop"].widget.isEnabled() is True
    assert "slide stop at 1 s" in panel.title.text()
    panel.fields["marker.slide"].commit(False)
    assert marker(window, "plain").slide is None and stack.undoText() == "Remove slide stop"
    assert "marker at 1 s" in panel.title.text()
    stack.undo()
    assert marker(window, "plain").slide == "stop"
    stack.undo()
    assert marker(window, "plain").slide is None


def test_the_loop_field_sets_and_clears_the_loop_and_turning_the_stop_off_clears_it(window) -> None:
    panel, stack = window.properties, window.document.undo_stack
    panel.show_marker("hold")
    assert panel.fields["marker.loop"].widget.isEnabled() is True
    panel.fields["marker.loop"].commit(0.8)
    assert marker(window, "hold").loop == pytest.approx(0.8) and stack.undoText() == "Slide loop"
    panel.fields["marker.loop"].commit(0.0)  # 0 = hold still
    assert marker(window, "hold").loop is None
    panel.fields["marker.loop"].commit(1.5)
    panel.fields["marker.slide"].commit(False)
    assert marker(window, "hold").slide is None and marker(window, "hold").loop is None
    stack.undo()
    assert marker(window, "hold").slide == "stop" and marker(window, "hold").loop == pytest.approx(1.5)


def test_the_fields_show_the_stop_and_its_loop(window) -> None:
    panel = window.properties
    panel.show_marker("spin")
    assert panel.fields["marker.slide"].widget.isChecked() is True
    assert panel.fields["marker.loop"].widget.value() == pytest.approx(0.5)
    assert "slide stop at 5 s" in panel.title.text()
    panel.show_marker("hold")
    assert panel.fields["marker.loop"].widget.value() <= 0  # "hold still"


# -- the ruler ----------------------------------------------------------------------------


def test_loop_band_and_tips_come_from_the_slide_rules(window) -> None:
    project = window.project
    assert model.loop_band(project, marker(window, "plain")) is None
    assert model.loop_band(project, marker(window, "hold")) is None
    start, end = model.loop_band(project, marker(window, "spin"))
    assert (start, end) == (pytest.approx(4.6), pytest.approx(5.0))  # five frames at 10 fps, the stop's own the last
    assert model.marker_tip(marker(window, "plain")) == "Formula at 1 s"
    assert model.marker_tip(marker(window, "hold")) == "Slide stop - holds still"
    assert model.marker_tip(marker(window, "spin")) == "Slide stop - loops 0.5 s"
    named = marker(window, "spin").model_copy(update={"name": "Result"})
    assert model.marker_tip(named) == "Result: Slide stop - loops 0.5 s"


def test_a_stop_is_drawn_with_its_own_flag_and_a_loop_band(window, qt_app) -> None:
    timeline = window.timeline
    timeline.set_selected_marker(None)
    qt_app.processEvents()
    image = timeline.viewport().grab().toImage()
    y = RULER_HEIGHT - 8  # the ruler's lower half: above the stem's tip, left of a flag, in the band
    flag_y = 6
    plain = [image.pixelColor(round(ruler_x(timeline, 1.0)) + dx, flag_y).rgb() for dx in range(2, 7)]
    hold = [image.pixelColor(round(ruler_x(timeline, 3.0)) + dx, flag_y).rgb() for dx in range(2, 7)]
    assert len(set(plain)) == 1  # a plain flag is one flat colour
    assert len(set(hold)) > 1  # a stop's flag carries a pause glyph
    inside = image.pixelColor(round(ruler_x(timeline, 4.75)), y)
    outside = image.pixelColor(round(ruler_x(timeline, 3.75)), y)
    assert inside != outside  # the loop band, not drawn for a stop that holds still


def test_hovering_a_flag_shows_what_it_is(window, qt_app, monkeypatch) -> None:
    timeline = window.timeline
    shown: list[str] = []
    monkeypatch.setattr(
        "manim_studio.ui.timeline.view.QToolTip.showText",
        lambda pos, text, *args, **kwargs: shown.append(text),
    )

    def hover(t: float, y: int = RULER_HEIGHT // 2) -> None:
        where = QPoint(round(ruler_x(timeline, t)), y)
        event = QHelpEvent(QEvent.Type.ToolTip, where, timeline.viewport().mapToGlobal(where))
        qt_app.sendEvent(timeline.viewport(), event)

    hover(5.0)
    hover(3.0)
    hover(4.0)  # no flag there
    hover(5.0, y=RULER_HEIGHT + 30)  # below the ruler
    assert shown == ["Slide stop - loops 0.5 s", "Slide stop - holds still"]


# -- Edit > Add Slide Stop ----------------------------------------------------------------


def test_add_slide_stop_is_in_the_edit_menu_on_shift_m(window) -> None:
    action = menu_action(window.menuBar(), "Edit", "Add Slide Stop")
    assert action.shortcut() == QKeySequence("Shift+M")
    taken = [
        a for a in window.findChildren(type(action)) if a is not action and a.shortcut() == action.shortcut()
    ]
    assert taken == []


def test_add_slide_stop_adds_one_at_the_playhead_and_selects_it(window) -> None:
    window.seek(2.0)
    steps = window.document.undo_stack.count()
    menu_action(window.menuBar(), "Edit", "Add Slide Stop").trigger()
    added = next(m for m in window.project.markers if m.t == pytest.approx(2.0))
    assert added.slide == "stop" and window.document.undo_stack.count() == steps + 1
    assert window.selection.marker_id == added.id and window.properties.marker_id == added.id
    window.document.undo_stack.undo()
    assert all(m.t != pytest.approx(2.0) for m in window.project.markers)


def test_add_slide_stop_turns_the_marker_at_the_playhead_into_a_stop(window) -> None:
    window.seek(1.0)
    count = len(window.project.markers)
    menu_action(window.menuBar(), "Edit", "Add Slide Stop").trigger()
    assert len(window.project.markers) == count and marker(window, "plain").slide == "stop"
    assert marker(window, "plain").name == "Formula"


def test_add_slide_stop_on_a_stop_says_why_in_the_status_bar(window) -> None:
    window.seek(3.0)
    steps = window.document.undo_stack.count()
    menu_action(window.menuBar(), "Edit", "Add Slide Stop").trigger()
    assert window.document.undo_stack.count() == steps
    assert "already" in window.statusBar().currentMessage()


def test_add_slide_stop_is_in_the_command_palette(window) -> None:
    from manim_studio.ui.shell import palette, shortcuts_help

    items = palette.collect_items(window)
    assert any(i.title == "Add Slide Stop" for i in items)
    rows = shortcuts_help.keyboard_rows(window.menuBar(), window)
    assert any(r.what == "Add Slide Stop" and r.keys == "Shift+M" for r in rows)
