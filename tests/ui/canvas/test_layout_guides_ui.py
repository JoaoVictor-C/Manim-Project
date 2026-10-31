"""Layout guides on the canvas (ADR 0074): drawn when View > Layout Guides is on, and moves snap to them."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.editing import edits
from manim_studio.core.model.schema import Canvas, Guide, Layer, Project, Spec, Transform2D
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

NONE = Qt.KeyboardModifier.NoModifier
ALT = Qt.KeyboardModifier.AltModifier
GUIDE_X = -1.0


def scene() -> Project:
    return Project(
        canvas=Canvas(width_px=640, height_px=360, fps=30, duration=4.0),
        layers=[
            Layer(
                id="a",
                spec=Spec(
                    type="Square", params={"side_length": 1.0}, style={"fill": "#3b82f6", "fill_opacity": 1}
                ),
                base=Transform2D(position=(-3.0, 1.3)),
            )
        ],
        guides=[Guide(id="g", axis="x", position=GUIDE_X)],
    )


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(scene().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


def px(window, x: float, y: float) -> QPointF:
    return window.canvas.units_transform().map(QPointF(float(x), float(y)))


def mouse(window, kind, pos: QPointF, modifiers=NONE) -> None:
    canvas = window.canvas
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    global_pos = QPointF(canvas.mapToGlobal(pos.toPoint()))
    QApplication.sendEvent(canvas, QMouseEvent(kind, pos, global_pos, button, buttons, modifiers))


def drag_a(window, qt_app, modifiers=NONE) -> float:
    """Move a so its right edge stops 3 px short of the guide; a's x afterwards."""
    window.selection.set("a")
    qt_app.processEvents()
    dx = (GUIDE_X - (-2.5)) - 3.0 / window.canvas.px_per_unit()
    start = px(window, -3.0, 1.3)
    end = px(window, -3.0 + dx, 1.3)
    mouse(window, QEvent.Type.MouseButtonPress, start, NONE)
    for f in (0.3, 0.7, 1.0):
        mouse(window, QEvent.Type.MouseMove, start + (end - start) * f, modifiers)
        qt_app.processEvents()
    mouse(window, QEvent.Type.MouseButtonRelease, end, modifiers)
    qt_app.processEvents()
    return window.project.layer("a").base.position[0]


def test_the_view_actions_are_there_and_the_toggle_is_remembered(window) -> None:
    assert not window.layout_guides_action.isChecked()  # off by default
    assert window.edit_guides_action.text() == "Layout &Guides..."
    assert ("layout_guides", window.layout_guides_action, False) in window._toggles()
    window.layout_guides_action.setChecked(True)
    assert window.canvas.show_layout_guides


def test_a_moved_edge_snaps_to_a_shown_guide_and_alt_turns_it_off(window, qt_app) -> None:
    window.layout_guides_action.setChecked(True)
    assert drag_a(window, qt_app) == pytest.approx(GUIDE_X - 0.5, abs=1e-6)
    window.document.undo_stack.undo()
    assert drag_a(window, qt_app, ALT) != pytest.approx(GUIDE_X - 0.5, abs=1e-3)


def test_hidden_guides_do_not_snap(window, qt_app) -> None:
    assert drag_a(window, qt_app) != pytest.approx(GUIDE_X - 0.5, abs=1e-3)


def test_guides_are_drawn_over_the_frame_only_when_shown(window, qt_app) -> None:
    window.selection.set(None)
    qt_app.processEvents()
    point = px(window, GUIDE_X, -3.0).toPoint()

    def around() -> list:  # the pixels about the guide's line, across it
        image = window.canvas.grab().toImage()
        return [image.pixelColor(point.x() + dx, point.y()).name() for dx in (-1, 0, 1)]

    off = around()
    window.layout_guides_action.setChecked(True)
    qt_app.processEvents()
    assert around() != off
    window.document.apply(edits.remove_guide(window.project, "g"), "Delete guide")
    qt_app.processEvents()
    assert around() == off
