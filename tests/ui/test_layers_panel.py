"""Layers dock (S2.4): library, delete, rename, z-order — one undo step each."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

from manim_studio.core import adapter
from manim_studio.core.schema import Clip, Layer, Project, Spec
from manim_studio.ui.build_service import BuildService
from manim_studio.ui.document import Document
from manim_studio.ui.layers_panel import LayersPanel
from qt_support import FakeWorker
from support import CANVAS

pytestmark = pytest.mark.ui


def project() -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(id="back", spec=Spec(type="Square")),
            Layer(
                id="mid",
                name="Ball",
                spec=Spec(type="Circle"),
                clips=[Clip(id="m", kind="Transform", start=0.2, duration=0.3, to_layer="front")],
            ),
            Layer(id="front", spec=Spec(type="Triangle")),
        ],
    )


@pytest.fixture
def panel(qt_app):
    doc = Document(project())
    worker = FakeWorker()
    builds = BuildService(doc, worker)
    widget = LayersPanel(builds)
    widget.worker = worker
    widget.selections = []
    widget.messages = []
    widget.layerSelected.connect(widget.selections.append)
    widget.message.connect(widget.messages.append)
    widget.show()
    yield widget
    widget.close()


def undo_texts(panel) -> list[str]:
    stack = panel.document.undo_stack
    return [stack.text(i) for i in range(stack.count())]


def test_list_is_front_to_back_with_names(panel) -> None:
    assert panel.ids_front_to_back() == ["front", "mid", "back"]
    assert [panel.list.item(r).text() for r in range(3)] == ["front", "Ball", "back"]


def test_library_menu_lists_every_type_in_sections(panel) -> None:
    texts = [a.text() for a in panel.library_menu.actions()]
    for section, types in adapter.LIBRARY:
        assert section in texts
        assert all(t in texts for t in types)


def test_adding_a_shape_puts_it_on_top_and_selects_it(panel) -> None:
    panel.add_object("Star")
    assert panel.project.layers[-1].id == "star-1"
    assert panel.ids_front_to_back()[0] == "star-1"
    assert panel.selected_id() == "star-1" and panel.selections[-1] == "star-1"
    assert undo_texts(panel) == ["Add Star"]


def test_adding_cold_text_waits_for_the_worker_then_selects_it(panel) -> None:
    panel.add_object("MathTex")
    assert len(panel.project.layers) == 3  # building
    panel.worker.reply(adapter.default_spec("MathTex"))
    assert panel.project.layers[-1].spec == adapter.default_spec("MathTex")
    assert panel.selected_id() == "mathtex-1"


def test_adding_an_image_asks_for_a_file(panel, tmp_path) -> None:
    panel.choose_image = lambda: ""
    panel.add_object("ImageMobject")
    assert panel.document.undo_stack.count() == 0  # cancelled
    panel.choose_image = lambda: str(tmp_path / "logo.png")
    panel.add_object("ImageMobject")
    assert panel.project.layers[-1].spec.params == {"path": str(tmp_path / "logo.png")}


def test_delete_removes_the_layer_and_the_morph_into_it(panel) -> None:
    panel.select("front")
    panel.delete_selected()
    assert [layer.id for layer in panel.project.layers] == ["back", "mid"]
    assert panel.project.layer("mid").clips == []
    assert undo_texts(panel) == ["Delete layer"]
    assert panel.selected_id() is None and panel.selections[-1] == ""
    panel.document.undo_stack.undo()
    assert panel.project == project()


def test_delete_and_z_order_have_shortcuts_scoped_to_the_panel(panel) -> None:
    actions = {b.defaultAction().text(): b.defaultAction() for b in (panel.delete_button, panel.up_button)}
    assert actions["Delete"].shortcut() == QKeySequence(QKeySequence.StandardKey.Delete)
    assert actions["Up"].shortcut() == QKeySequence("Ctrl+]")
    assert actions["Delete"].shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut


def test_up_and_down_change_z_order_and_keep_selection(panel) -> None:
    panel.select("back")
    assert not panel.down_button.isEnabled()
    panel.shift_selected(+1)
    assert [layer.id for layer in panel.project.layers] == ["mid", "back", "front"]
    assert panel.selected_id() == "back"
    panel.shift_selected(+1)
    assert panel.ids_front_to_back() == ["back", "front", "mid"]
    assert not panel.up_button.isEnabled()
    panel.shift_selected(+1)  # already in front: nothing happens
    assert undo_texts(panel) == ["Reorder layers", "Reorder layers"]


def test_dropping_a_row_reorders(panel) -> None:
    panel._on_row_dropped("back", 0)  # dragged to the top of the list = front
    assert [layer.id for layer in panel.project.layers] == ["mid", "front", "back"]
    panel._on_row_dropped("back", 0)  # same place: no undo step
    assert undo_texts(panel) == ["Reorder layers"]


def test_rename_through_the_list(panel) -> None:
    item = panel.list.item(2)  # "back"
    item.setText("Background")
    assert panel.project.layer("back").name == "Background"
    panel.list.item(2).setText("  ")  # blank -> back to the id
    assert panel.project.layer("back").name == ""
    assert undo_texts(panel) == ["Rename layer", "Rename layer"]


def test_undo_keeps_the_list_in_sync(panel) -> None:
    panel.add_object("Circle")
    panel.document.undo_stack.undo()
    assert panel.ids_front_to_back() == ["front", "mid", "back"]
    panel.document.undo_stack.redo()
    assert panel.ids_front_to_back()[0] == "circle-1"


def test_opening_another_project_resets_the_list(panel) -> None:
    panel.select("mid")
    panel.document.replace(Project(canvas=CANVAS, layers=[Layer(id="solo", spec=Spec(type="Dot"))]))
    assert panel.ids_front_to_back() == ["solo"]
    assert panel.selected_id() is None
