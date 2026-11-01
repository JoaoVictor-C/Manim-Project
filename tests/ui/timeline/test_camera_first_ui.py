"""The camera is the first row of the Timeline (ADR 0086), above every object, and its name says why."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core.editing import edits
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.session.document import Document
from manim_studio.ui.timeline.view import ROW_HEIGHT, RULER_HEIGHT, TimelineView

pytestmark = pytest.mark.ui


def project() -> Project:
    return Project(
        canvas=Canvas(duration=6.0, fps=30),
        layers=[
            Layer(id="a", spec=Spec(type="Square")),
            Layer(id="b", spec=Spec(type="Circle")),
            Layer(id="cam", name="Camera", spec=Spec(type="Camera")),
        ],
    )


@pytest.fixture
def view(qt_app):
    doc = Document(project())
    v = TimelineView()
    v.resize(1000, 240)
    v.set_document(doc)
    v.show()
    qt_app.processEvents()
    v.doc = doc
    yield v
    v.close()


def hover(header, y: float) -> None:
    pos = QPointF(20, y)
    glob = QPointF(header.mapToGlobal(pos.toPoint()))
    none, mods = Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier
    QApplication.sendEvent(header, QMouseEvent(QEvent.Type.MouseMove, pos, glob, none, none, mods))


def test_the_camera_is_the_first_row(view) -> None:
    assert [layer.id for layer in view.rows()] == ["cam", "b", "a"]
    assert view.row_of("cam") == 0


def test_a_layer_added_later_is_a_row_under_the_camera(view, qt_app) -> None:
    view.doc.apply(edits.add_layer(view.project, Spec(type="Star")), "Add Star")
    qt_app.processEvents()
    assert [layer.id for layer in view.rows()] == ["cam", "star-1", "b", "a"]


def test_the_camera_row_has_a_tooltip_saying_it_stays_first(view) -> None:
    y = RULER_HEIGHT + ROW_HEIGHT / 2 - view.verticalScrollBar().value()
    hover(view.header, y)
    assert view.header.toolTip() == edits.CAMERA_FIRST
    hover(view.header, y + ROW_HEIGHT)  # the next row
    assert view.header.toolTip() == ""
