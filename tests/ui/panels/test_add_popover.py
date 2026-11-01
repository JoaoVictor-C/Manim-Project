"""The Add object card (ADR 0087): search, recent, categories, and the same add paths as the menus."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from manim_studio.core.code import python_templates
from manim_studio.core.engine import adapter
from manim_studio.core.model.schema import Layer, Project, Spec
from manim_studio.ui.panels.layers_panel import LayersPanel
from manim_studio.ui.session import insert_catalogue as catalogue
from manim_studio.ui.session.build_service import BuildService
from manim_studio.ui.session.document import Document
from qt_support import FakeWorker
from support import CANVAS

pytestmark = pytest.mark.ui


@pytest.fixture
def panel(qt_app):
    doc = Document(Project(canvas=CANVAS, layers=[Layer(id="back", spec=Spec(type="Square"))]))
    widget = LayersPanel(BuildService(doc, FakeWorker()))
    widget.resize(300, 500)
    widget.show()
    widget.saved = []
    widget.recent_save = widget.saved.append
    yield widget
    widget.add_popover.close()
    widget.close()


def tiles(panel) -> list[str]:
    return [t.entry.key for t in panel.add_popover.tiles]


def open_card(panel):
    panel.show_add_popover()
    return panel.add_popover


def test_every_library_type_is_in_a_category_and_the_python_templates_under_code() -> None:
    found = {e.type_name for e in catalogue.entries() if e.kind == "object"}
    assert found == {t for _section, types in adapter.LIBRARY for t in types}
    assert {e.key for e in catalogue.entries() if e.category == "code"} >= {
        f"py:{name}" for name in python_templates.LAYER_TEMPLATES
    }
    assert {e.type_name for e in catalogue.entries() if e.category == "math"} >= {"MathTex", "Tex"}
    assert all(e.category in catalogue.CATEGORY_BY_KEY for e in catalogue.entries())


def test_the_footer_and_the_header_plus_open_the_card_and_there_is_no_quick_add_grid(panel, qt_app) -> None:
    assert not hasattr(panel, "quick_add_buttons")
    card = panel.add_popover
    panel.add_button.click()
    assert card.isVisible()
    card.close()
    panel.header_add_button.click()
    assert card.isVisible()
    card.close()
    assert not card.isVisible()


def test_the_card_lists_a_category_as_tiles_and_a_click_adds_by_the_normal_path(panel, qt_app) -> None:
    card = open_card(panel)
    assert tiles(panel)[:3] == ["obj:Circle", "obj:Ellipse", "obj:Square"]
    card.set_category("lines")
    assert "obj:Arrow" in tiles(panel) and "obj:Circle" not in tiles(panel)
    arrow = next(t for t in card.tiles if t.entry.key == "obj:Arrow")
    arrow.click()
    qt_app.processEvents()
    assert not card.isVisible()
    assert panel.project.layers[-1].spec.type == "Arrow"
    assert panel.document.undo_stack.text(0) == "Add Arrow"


def test_search_filters_every_object_and_enter_adds_the_first(panel, qt_app) -> None:
    card = open_card(panel)
    card.search.setText("arrow")
    assert tiles(panel)[0] == "obj:Arrow"
    assert {"obj:DoubleArrow", "obj:CurvedArrow"} <= set(tiles(panel))
    assert "obj:Circle" not in tiles(panel)
    QTest.keyClick(card.search, Qt.Key.Key_Down)
    assert card.current_entry().key == tiles(panel)[4]  # a row down: four to a row
    QTest.keyClick(card.search, Qt.Key.Key_Up)
    QTest.keyClick(card.search, Qt.Key.Key_Return)
    qt_app.processEvents()
    assert panel.project.layers[-1].spec.type == "Arrow"
    card.search.setText("rtri")  # letters in order, when no name holds them
    assert tiles(panel)[0] == "obj:RightTriangle"
    card.search.setText("zzzz")
    assert tiles(panel) == [] and card.title.text().startswith("0 RESULT")


def test_arrows_move_over_the_grid_by_row_and_column(panel) -> None:
    card = open_card(panel)
    assert card.index == 0
    card.step(rows=1)
    assert card.index == 4  # four to a row
    card.step(columns=1)
    assert card.index == 5
    QTest.keyClick(card.search, Qt.Key.Key_Left)  # an empty field: Left and Right move over tiles
    assert card.index == 4
    card.step(rows=-9)
    assert card.index == 0


def test_the_recent_row_keeps_the_last_six_and_survives_through_the_hook(panel, qt_app) -> None:
    for name in ("Circle", "Square", "Arrow", "Cube", "Axes", "Star", "Line"):
        panel.add_object(name)
    assert panel.recent_keys() == [f"obj:{n}" for n in ("Line", "Star", "Axes", "Cube", "Arrow", "Square")]
    assert panel.saved[-1] == panel.recent_keys()
    card = open_card(panel)
    chips = [card.recent_row.itemAt(i).widget() for i in range(card.recent_row.count())]
    chips = [c for c in chips if c is not None]
    assert [c.entry.key for c in chips] == panel.recent_keys()
    chips[0].click()
    qt_app.processEvents()
    assert panel.project.layers[-1].spec.type == "Line"
    assert panel.recent_keys()[0] == "obj:Line"
    panel.set_recent_keys(["obj:Nonexistent", "obj:Circle"])  # a removed plugin type is skipped
    card.refresh()
    assert [
        c.entry.key for c in (card.recent_row.itemAt(i).widget() for i in range(card.recent_row.count())) if c
    ] == ["obj:Circle"]


def test_a_failing_save_does_not_break_adding(panel) -> None:
    def broken(keys):
        raise OSError("read-only settings")

    panel.recent_save = broken
    panel.add_object("Circle")
    assert panel.project.layers[-1].spec.type == "Circle"


def test_python_templates_and_the_steps_and_the_camera_use_their_own_paths(panel, qt_app) -> None:
    name, code = next(iter(python_templates.LAYER_TEMPLATES.items()))
    panel.insert_entry(catalogue.by_key()[f"py:{name}"])
    assert panel.project.layers[-1].spec.params["code"] == code
    assert panel.recent_keys()[0] == f"py:{name}"
    asked = []
    panel.ask_steps = lambda t: asked.append(t)  # the dialog's hook: cancelled
    panel.insert_entry(catalogue.by_key()["steps"])
    assert asked == [panel.playhead()]


def test_the_scene_category_offers_the_camera_only_while_the_project_has_none(panel) -> None:
    assert panel.project.camera_layer is None
    card = open_card(panel)
    assert not card.categories["scene"].isHidden()
    card.set_category("scene")
    assert tiles(panel) == ["camera"]
    card.close()
    panel.insert_entry(catalogue.by_key()["camera"])
    assert panel.project.camera_layer is not None
    card = open_card(panel)
    assert card.categories["scene"].isHidden() and "camera" not in {e.key for e in card._entries}


def test_presets_in_the_card_opens_the_browser(panel, qt_app) -> None:
    asked = []
    panel.browse_presets = lambda: asked.append(True)
    card = open_card(panel)
    card.presets_button.click()
    qt_app.processEvents()
    assert asked == [True] and not card.isVisible()


def test_the_layer_list_has_the_height_the_grid_used_to_take(panel, qt_app) -> None:
    qt_app.processEvents()
    assert panel.list.geometry().top() < 70  # right under the filter field
