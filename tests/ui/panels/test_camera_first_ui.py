"""The camera is always the first row of the Layers panel (ADR 0086): not moved, not dragged, no row above."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView

from manim_studio.core.editing import edits
from manim_studio.core.model.schema import Layer, Project, Spec
from manim_studio.ui.panels.layers_panel import LayersPanel
from manim_studio.ui.session.build_service import BuildService
from manim_studio.ui.session.document import Document
from qt_support import FakeWorker
from support import CANVAS

pytestmark = pytest.mark.ui


def project() -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(id="back", spec=Spec(type="Square")),
            Layer(id="front", spec=Spec(type="Triangle")),
            Layer(id="cam", name="Camera", spec=Spec(type="Camera")),
        ],
    )


@pytest.fixture
def panel(qt_app):
    doc = Document(project())
    builds = BuildService(doc, FakeWorker())
    widget = LayersPanel(builds)
    widget.messages = []
    widget.message.connect(widget.messages.append)
    widget.show()
    yield widget
    widget.close()


def order(panel) -> list[str]:
    return [layer.id for layer in panel.project.layers]


def pick(panel, layer_id: str) -> None:
    """Select as a click does, so the buttons follow."""
    panel.select(layer_id)
    panel.update_buttons()


def test_the_camera_is_the_first_row_and_stays_so_when_objects_are_added(panel) -> None:
    assert panel.ids_front_to_back() == ["cam", "front", "back"]
    panel.add_object("Star")
    assert panel.ids_front_to_back() == ["cam", "star-1", "front", "back"]
    assert panel.selected_id() == "star-1"  # the new object is the one selected, not the camera
    assert order(panel)[-1] == "cam"


def test_the_camera_row_cannot_be_dragged_and_says_why(panel) -> None:
    camera, other = panel.items()[0], panel.items()[1]
    assert not camera.flags() & Qt.ItemFlag.ItemIsDragEnabled
    assert other.flags() & Qt.ItemFlag.ItemIsDragEnabled
    assert edits.CAMERA_FIRST in camera.toolTip(0)


def test_up_and_down_are_off_for_the_camera_with_the_reason(panel) -> None:
    pick(panel, "cam")
    assert not panel.up_button.isEnabled() and not panel.down_button.isEnabled()
    assert panel.up_button.toolTip() == panel.down_button.toolTip() == edits.CAMERA_FIRST
    panel.shift_selected(+1)
    panel.shift_selected(-1)
    assert order(panel) == ["back", "front", "cam"]
    assert panel.document.undo_stack.count() == 0
    pick(panel, "back")  # and the tips are the usual ones again
    assert panel.up_button.toolTip() == "Bring forward (Ctrl+])"
    assert panel.down_button.toolTip() == "Send backward (Ctrl+[)"


def test_the_object_under_the_camera_cannot_come_forward(panel) -> None:
    pick(panel, "front")
    assert not panel.up_button.isEnabled() and panel.down_button.isEnabled()
    panel.shift_selected(+1)
    assert order(panel) == ["back", "front", "cam"]
    pick(panel, "back")
    assert panel.up_button.isEnabled()
    panel.shift_selected(+1)
    assert order(panel) == ["front", "back", "cam"]


def test_a_drop_on_the_camera_or_of_the_camera_changes_nothing(panel) -> None:
    panel._on_row_dropped("back", 0)  # to the top of the list: under the camera, the front of the objects
    assert order(panel) == ["front", "back", "cam"]
    panel._on_row_dropped("back", 0)  # already there: no undo step
    assert panel.document.undo_stack.count() == 1
    panel._on_row_dropped("cam", 2)  # the camera dragged down
    assert order(panel) == ["front", "back", "cam"]
    assert panel.messages[-1] == edits.CAMERA_FIRST
    assert panel.document.undo_stack.count() == 1
    assert panel.ids_front_to_back()[0] == "cam"


def test_the_layer_tree_refuses_a_drop_above_the_camera(panel) -> None:
    tree = panel.list
    centre = tree.visualItemRect(tree.topLevelItem(0)).center()
    tree.dropIndicatorPosition = lambda: QAbstractItemView.DropIndicatorPosition.AboveItem
    assert tree._above_camera(centre)
    tree.dropIndicatorPosition = lambda: QAbstractItemView.DropIndicatorPosition.BelowItem
    assert not tree._above_camera(centre)  # the lower half of its row: under it
    other = tree.visualItemRect(tree.topLevelItem(1)).center()
    tree.dropIndicatorPosition = lambda: QAbstractItemView.DropIndicatorPosition.AboveItem
    assert not tree._above_camera(other)
