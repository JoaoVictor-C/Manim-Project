"""The Animate page (P6b.2, decision session 35) through the real window: the graph editor of the
selected layer's keys - selection shared with Properties and the timeline, drags in time and
value as one undo step, Escape, Shift, double-click, Delete, eases, the view, the legend."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.evaluator import layer_transform
from manim_studio.core.schema import Canvas, Easing, Keyframe, Layer, Project, Spec
from manim_studio.ui import graph_model, theme
from manim_studio.ui.graph_editor import RULER, GraphEditor
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.timeline.model import TimeScale
from ui.test_acceptance_v1 import menu_action

pytestmark = pytest.mark.ui

FPS = 30


def scene() -> Project:
    return Project(
        canvas=Canvas(width_px=320, height_px=180, fps=FPS, duration=4.0),
        layers=[
            Layer(
                id="s",
                spec=Spec(type="Square"),
                tracks={
                    "position": [
                        Keyframe(t=0.0, value=(0.0, 0.0)),
                        Keyframe(t=1.0, value=(2.0, 1.0), ease=Easing(name="linear")),
                        Keyframe(t=2.0, value=(4.0, -1.0)),
                    ],
                    "rotation": [Keyframe(t=1.0, value=0.0), Keyframe(t=3.0, value=90.0)],
                },
            ),
            Layer(id="axes", spec=Spec(type="Axes")),
            Layer(id="g", parent_id="axes", spec=Spec(type="Graph", params={"expression": "sin(x)"})),
        ],
    )


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(scene().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    win.load(path)
    win.show_page("animate")
    win.selection.select_layer("s")
    qt_app.processEvents()
    yield win
    win.close()


def graph(window) -> GraphEditor:
    return window.pages.pages["animate"].graph


def send(
    widget, kind, pos: QPointF, button=Qt.MouseButton.LeftButton, modifiers=Qt.KeyboardModifier.NoModifier
):
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button
    if kind == QEvent.Type.MouseMove:
        button = Qt.MouseButton.NoButton
    global_pos = QPointF(widget.mapToGlobal(pos.toPoint()))
    QApplication.sendEvent(widget, QMouseEvent(kind, pos, global_pos, button, buttons, modifiers))


def drag(
    window, qt_app, start: QPointF, end: QPointF, modifiers=Qt.KeyboardModifier.NoModifier, release=True
):
    g = graph(window)
    send(g, QEvent.Type.MouseButtonPress, start)
    send(g, QEvent.Type.MouseMove, (start + end) / 2, modifiers=modifiers)
    send(g, QEvent.Type.MouseMove, end, modifiers=modifiers)
    qt_app.processEvents()
    if release:
        send(g, QEvent.Type.MouseButtonRelease, end)


def key(widget, code) -> None:
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, code, Qt.KeyboardModifier.NoModifier))


def track(window, prop: str, layer_id: str = "s") -> list[tuple[float, object]]:
    return [(k.t, k.value) for k in window.document.project.layer(layer_id).tracks.get(prop, [])]


# -- the page -----------------------------------------------------------------------------


def test_animate_is_the_second_page_with_the_viewer_properties_graph_and_timeline(window) -> None:
    from ui.test_acceptance_v1 import menu_action as action

    assert list(window.pages.pages)[:2] == ["compose", "animate"] and window.page == "animate"
    assert action(window.menuBar(), "View", "Pages", "Animate").shortcut().toString() == "Shift+2"
    assert window.pages.bar.tabText(1) == "Animate" and not window.pages.bar.tabIcon(1).isNull()
    page = window.pages.pages["animate"]
    for view in (window.viewer, window.properties, window.timeline, graph(window)):
        assert page.widget.isAncestorOf(view) and view.isVisible()
    assert window.layers.parentWidget() is window.pages.parking
    sizes = page.outer.sizes()
    assert sizes[1] >= sizes[2]  # the graph is the large middle part
    window.show_page("compose")  # the graph stays with its page
    assert not graph(window).isVisible() and window.pages.pages["compose"].widget.isAncestorOf(
        window.timeline
    )


def test_curves_of_the_selected_layer_and_a_locked_graph_offers_opacity_only(window, qt_app) -> None:
    g = graph(window)
    assert [c.name for c in g.curves()] == ["x", "y", "scale", "rotation", "opacity"]
    assert {p.curve for p in g.points()} == {"x", "y", "rotation"}
    checks = window.pages.pages["animate"].checks
    assert all(check.isEnabled() for check in checks.values())
    window.selection.select_layer("g")
    assert [c.name for c in g.curves()] == ["opacity"]
    assert [name for name, check in checks.items() if check.isEnabled()] == ["opacity"]
    window.selection.select_layer(None)
    assert g.curves() == [] and g.points() == []
    g.grab()  # paints the empty state


def test_the_legend_hides_a_curve(window) -> None:
    g, checks = graph(window), window.pages.pages["animate"].checks
    checks["rotation"].setChecked(False)
    assert "rotation" not in {p.curve for p in g.points()} and "rotation" not in [c.name for c in g.curves()]
    checks["rotation"].setChecked(True)
    assert "rotation" in {p.curve for p in g.points()}


def test_curve_colours_read_on_the_graph() -> None:
    for curve in graph_model.CURVES:  # WCAG 1.4.11: 3:1 for graphical objects
        assert theme.contrast(getattr(theme.THEME, curve.token), theme.THEME.track) >= 3.0


# -- selecting --------------------------------------------------------------------------


def test_clicking_a_key_selects_its_time_and_highlights_that_curve(window, qt_app) -> None:
    g = graph(window)
    pos = g.point_pos("rotation", 1.0)
    send(g, QEvent.Type.MouseButtonPress, pos)
    send(g, QEvent.Type.MouseButtonRelease, pos)
    assert (window.selection.layer_id, window.selection.key_time) == ("s", 1.0)
    assert window.properties.key_time == 1.0  # Properties shows the keys at that time
    assert window.timeline.selected_key == ("s", 1.0)
    assert g.highlighted() == {("rotation", 1.0)}  # not the position key at the same time
    assert g.focus_curve().name == "rotation"
    assert window.document.undo_stack.count() == 0  # a click is no edit
    window.selection.set_key("s", 1.0)  # unchanged: the curve stays chosen
    assert g.highlighted() == {("rotation", 1.0)}
    window.selection.set_key("s", 2.0)  # chosen on the timeline: the column
    assert g.highlighted() == {("x", 2.0), ("y", 2.0)}
    send(g, QEvent.Type.MouseButtonPress, QPointF(g.plot_rect().center().x(), g.plot_rect().top() + 3))
    assert window.selection.key_time is None and window.selection.layer_id == "s"


# -- dragging ---------------------------------------------------------------------------


def test_dragging_a_key_sideways_retimes_that_curve_as_one_undo_step(window, qt_app) -> None:
    g = graph(window)
    start = g.point_pos("rotation", 1.0)
    drag(window, qt_app, start, QPointF(g.x_of(1.5), start.y()))
    assert [t for t, _ in track(window, "rotation")] == [pytest.approx(1.5), 3.0]
    assert [t for t, _ in track(window, "position")] == [0.0, 1.0, 2.0]  # the other track stays
    assert window.document.undo_stack.count() == 1
    assert window.selection.key_time == pytest.approx(1.5) and g.highlighted() == {("rotation", 1.5)}
    assert window.evaluator.project is window.document.project  # the canvas follows the edit
    window.document.undo_stack.undo()
    assert track(window, "rotation") == [(1.0, 0.0), (3.0, 90.0)]


def test_dragging_a_key_up_changes_its_value_only(window, qt_app) -> None:
    g = graph(window)
    start = g.point_pos("y", 1.0)
    target = g.y_of(graph_model.BY_NAME["y"], 0.0)
    drag(window, qt_app, start, QPointF(start.x(), target))
    (t, value) = track(window, "position")[1]
    assert t == 1.0 and value[0] == 2.0 and value[1] == pytest.approx(0.0, abs=0.02)  # x kept
    assert window.document.undo_stack.count() == 1


def test_ranges_hold_still_while_dragging(window, qt_app) -> None:
    g = graph(window)
    before = dict(g.ranges)
    start = g.point_pos("x", 2.0)
    drag(window, qt_app, start, QPointF(start.x(), g.plot_rect().top() - 200), release=False)
    assert track(window, "position")[2][1][0] > 4.0 and g.ranges == before  # past the old top
    send(g, QEvent.Type.MouseButtonRelease, QPointF(start.x(), g.plot_rect().top() - 200))
    assert g.ranges["x"] != before["x"]  # the new value fits again


def test_escape_cancels_a_drag(window, qt_app) -> None:
    g = graph(window)
    start = g.point_pos("x", 1.0)
    drag(window, qt_app, start, start + QPointF(80, -60), release=False)
    assert window.document.project != scene() and window.document.dragging
    key(g, Qt.Key.Key_Escape)
    assert not window.document.dragging
    assert track(window, "position") == [(0.0, (0.0, 0.0)), (1.0, (2.0, 1.0)), (2.0, (4.0, -1.0))]
    send(g, QEvent.Type.MouseButtonRelease, start + QPointF(80, -60))
    assert window.document.undo_stack.count() == 0


def test_shift_keeps_a_drag_on_one_axis(window, qt_app) -> None:
    g = graph(window)
    start = g.point_pos("rotation", 3.0)
    drag(window, qt_app, start, start + QPointF(-60, -10), modifiers=Qt.KeyboardModifier.ShiftModifier)
    (t, value) = track(window, "rotation")[1]
    assert t < 3.0 and value == 90.0  # mostly sideways: time only
    window.document.undo_stack.undo()
    drag(window, qt_app, start, start + QPointF(5, 40), modifiers=Qt.KeyboardModifier.ShiftModifier)
    (t, value) = track(window, "rotation")[1]
    assert t == 3.0 and value < 90.0  # mostly up and down: value only
    window.document.undo_stack.undo()
    g = graph(window)
    send(g, QEvent.Type.MouseButtonPress, start)
    send(g, QEvent.Type.MouseMove, start + QPointF(-60, -10), modifiers=Qt.KeyboardModifier.ShiftModifier)
    qt_app.processEvents()
    send(g, QEvent.Type.MouseMove, start + QPointF(-60, 40))  # Shift let go: free again
    qt_app.processEvents()
    send(g, QEvent.Type.MouseButtonRelease, start + QPointF(-60, 40))
    (t, value) = track(window, "rotation")[1]
    assert t < 3.0 and value < 90.0


def test_a_key_grabbed_off_centre_does_not_jump(window, qt_app) -> None:
    g = graph(window)
    start = g.point_pos("rotation", 3.0) + QPointF(0, 4)  # within the grab radius, below the key
    drag(window, qt_app, start, QPointF(g.x_of(2.5), start.y()))
    assert track(window, "rotation")[1] == (2.5, 90.0)  # moved in time, its value kept


def test_a_curve_stays_chosen_while_its_key_moves_onto_another_time(window, qt_app) -> None:
    g = graph(window)
    start = g.point_pos("rotation", 3.0)  # the only key at 3 s: the selection loses it mid-drag
    drag(window, qt_app, start, QPointF(g.x_of(2.0), start.y()), release=False)
    assert g.focus_prop == "rotation"
    send(g, QEvent.Type.MouseButtonRelease, QPointF(g.x_of(2.0), start.y()))
    assert track(window, "rotation")[1][0] == 2.0  # onto the position key's time
    assert g.highlighted() == {("rotation", 2.0)}  # not the position key there


def test_alt_drags_on_frames_only(window, qt_app) -> None:
    g = graph(window)
    g.scale = TimeScale(px_per_second=300.0)  # a frame is 10 px; the snap radius 8 px
    window.seek(1.5)
    near = g.x_of(1.5) + 7  # inside the snap radius of the playhead, nearer the next frame
    start = g.point_pos("rotation", 1.0)
    drag(window, qt_app, start, QPointF(near, start.y()))
    assert track(window, "rotation")[0][0] == pytest.approx(1.5)  # snapped to the playhead
    window.document.undo_stack.undo()
    drag(window, qt_app, start, QPointF(near, start.y()), modifiers=Qt.KeyboardModifier.AltModifier)
    t = track(window, "rotation")[0][0]
    assert t == pytest.approx(46 / FPS)  # the nearest frame, not the playhead


# -- adding, deleting, easing -----------------------------------------------------------


def test_double_click_on_a_curve_adds_a_key_that_keeps_the_motion(window, qt_app) -> None:
    g = graph(window)
    before = layer_transform(window.document.project.layer("s"), 0.5).position
    pos = g.curve_pos("x", 0.5)
    send(g, QEvent.Type.MouseButtonDblClick, pos)
    keys = track(window, "position")
    assert [t for t, _ in keys] == [0.0, 0.5, 1.0, 2.0]
    assert keys[1][1] == pytest.approx(before)
    assert window.selection.key_time == 0.5 and g.highlighted() == {("x", 0.5), ("y", 0.5)}
    send(g, QEvent.Type.MouseButtonDblClick, g.curve_pos("scale", 3.5))  # the dashed base line, alone there
    assert track(window, "scale") == [(3.5, 1.0)]
    send(g, QEvent.Type.MouseButtonDblClick, QPointF(g.plot_rect().left() + 5, g.plot_rect().bottom() - 1))
    assert window.document.undo_stack.count() == 2  # nowhere near a curve


def test_delete_removes_the_highlighted_keys(window, qt_app) -> None:
    g = graph(window)
    pos = g.point_pos("rotation", 1.0)
    send(g, QEvent.Type.MouseButtonPress, pos)
    send(g, QEvent.Type.MouseButtonRelease, pos)
    key(g, Qt.Key.Key_Delete)
    assert [t for t, _ in track(window, "rotation")] == [3.0]
    assert [t for t, _ in track(window, "position")] == [0.0, 1.0, 2.0]  # the column's other key stays
    window.selection.set_key("s", 2.0)  # chosen on the timeline: the column
    key(g, Qt.Key.Key_Backspace)
    assert [t for t, _ in track(window, "position")] == [0.0, 1.0]
    assert window.document.undo_stack.count() == 2
    key(g, Qt.Key.Key_Delete)  # nothing highlighted: nothing happens
    assert window.document.undo_stack.count() == 2


def test_right_click_a_segment_sets_its_ease(window, qt_app) -> None:
    g = graph(window)
    pos = g.curve_pos("rotation", 2.0)
    menu = g.context_menu(pos)
    assert any("Rotation from 1 s" in a.text() for a in menu.actions())
    menu_action(menu, "ease out back").trigger()
    assert window.document.project.layer("s").tracks["rotation"][0].ease == Easing(name="ease_out_back")
    assert window.document.project.layer("s").tracks["position"][1].ease == Easing(name="linear")
    chosen = Easing(name=None, bezier=(0.2, 0.0, 0.3, 1.0))
    g.edit_curve = lambda parent, ease: chosen
    menu_action(g.context_menu(g.curve_pos("rotation", 2.0)), "Edit curve...").trigger()
    assert window.document.project.layer("s").tracks["rotation"][0].ease == chosen
    g.edit_curve = lambda parent, ease: None  # cancelled
    menu_action(g.context_menu(g.curve_pos("rotation", 2.0)), "Edit curve...").trigger()
    assert window.document.undo_stack.count() == 2
    assert g.context_menu(g.curve_pos("rotation", 3.5)).isEmpty()  # after the last key: no segment


def test_right_click_a_key_deletes_it(window) -> None:
    g = graph(window)
    menu = g.context_menu(g.point_pos("y", 2.0))
    menu_action(menu, "Delete position y key at 2 s").trigger()
    assert [t for t, _ in track(window, "position")] == [0.0, 1.0]


def test_a_refused_edit_goes_to_the_status_bar(window) -> None:
    g = graph(window)
    messages = []
    g.message.connect(messages.append)
    g.set_ease("rotation", 2.0, Easing(name="linear"))  # no rotation key at 2 s
    assert messages and "no keys" in messages[0]


# -- the view ---------------------------------------------------------------------------


def test_frame_all_wheel_zoom_and_pan(window, qt_app) -> None:
    g = graph(window)
    key(g, Qt.Key.Key_F)
    rect = g.plot_rect()
    assert g.x_of(0.0) >= rect.left() and g.x_of(3.0) <= rect.right()  # every key in view
    pos = QPointF(g.x_of(1.0), rect.center().y())

    def wheel(modifiers=Qt.KeyboardModifier.NoModifier) -> None:
        QApplication.sendEvent(
            g,
            QWheelEvent(
                pos,
                QPointF(g.mapToGlobal(pos.toPoint())),
                QPoint(),
                QPoint(0, 120),
                Qt.MouseButton.NoButton,
                modifiers,
                Qt.ScrollPhase.NoScrollPhase,
                False,
            ),
        )

    pps = g.scale.px_per_second
    wheel()
    assert g.scale.px_per_second == pytest.approx(pps * 1.2) and g.x_of(1.0) == pytest.approx(pos.x())
    window_n = g.values.n1 - g.values.n0
    wheel(Qt.KeyboardModifier.ControlModifier)
    assert g.values.n1 - g.values.n0 == pytest.approx(window_n / 1.2)
    offset, n0 = g.scale.offset, g.values.n0
    send(g, QEvent.Type.MouseButtonPress, pos, Qt.MouseButton.MiddleButton)
    send(g, QEvent.Type.MouseMove, pos + QPointF(50, 20), Qt.MouseButton.MiddleButton)
    send(g, QEvent.Type.MouseButtonRelease, pos + QPointF(50, 20), Qt.MouseButton.MiddleButton)
    assert g.scale.offset < offset and g.values.n0 > n0
    assert window.document.undo_stack.count() == 0
    window.pages.pages["animate"].frame_button.click()
    assert g.values.n0 == 0.0 and g.values.n1 == 1.0


def test_the_top_strip_scrubs_and_the_playhead_follows(window, qt_app) -> None:
    g = graph(window)
    pos = QPointF(g.x_of(2.5), RULER / 2)
    send(g, QEvent.Type.MouseButtonPress, pos)
    send(g, QEvent.Type.MouseMove, QPointF(g.x_of(2.0), RULER / 2))
    send(g, QEvent.Type.MouseButtonRelease, QPointF(g.x_of(2.0), RULER / 2))
    assert window.t == pytest.approx(2.0, abs=0.02)
    assert window.document.undo_stack.count() == 0 and window.selection.key_time is None
    painted = []
    g.update = lambda *a: painted.append(1)
    window.seek(1.0)
    assert painted  # every seek repaints the playhead


def test_opening_another_project_resets_the_graph(window, qt_app, tmp_path) -> None:
    g = graph(window)
    pos = g.point_pos("rotation", 1.0)
    send(g, QEvent.Type.MouseButtonPress, pos)
    send(g, QEvent.Type.MouseButtonRelease, pos)
    window.new_project()
    assert g.focus is None and g.focus_prop is None and g.points() == []
    g.grab()
