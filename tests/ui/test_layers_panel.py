"""Layers dock (S2.4): library, delete, rename, z-order — one undo step each."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

from manim_studio.core import adapter, edits
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
    assert [item.text(0) for item in panel.items()] == ["front", "Ball", "back"]


def test_library_menu_lists_every_type_in_sections(panel) -> None:
    texts = [a.text() for a in panel.library_menu.actions()]
    for section, types in adapter.LIBRARY:
        assert section in texts
        assert all(adapter.LIBRARY_LABELS.get(t, t) in texts for t in types)
    assert "SVG" in texts and "Image" in texts  # media types by their everyday names


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
    item = panel.items()[2]  # "back"
    item.setText(0, "Background")
    assert panel.project.layer("back").name == "Background"
    panel.items()[2].setText(0, "  ")  # blank -> back to the id
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


# -- part layers (P2c.3) ----------------------------------------------------------------

EQ = "a^2 + b^2 = c^2"


@pytest.fixture
def eq_panel(qt_app):
    eq = Layer(id="eq", spec=Spec(type="MathTex", params={"text": EQ}))
    doc = Document(Project(canvas=CANVAS, layers=[Layer(id="sq", spec=Spec(type="Square")), eq]))
    worker = FakeWorker()
    widget = LayersPanel(BuildService(doc, worker))
    widget.worker = worker
    widget.messages = []
    widget.message.connect(widget.messages.append)
    widget.show()
    yield widget
    widget.close()


def test_add_part_asks_for_a_key_and_nests_the_part_under_its_object(eq_panel) -> None:
    eq_panel.select("eq")
    asked = []
    eq_panel.ask_part = lambda parent_id: asked.append(parent_id) or ("b^2", 0)
    eq_panel.add_part()
    eq_panel.worker.reply_all()  # the object is rebuilt with the part's marker (warm gate)
    assert asked == ["eq"]
    part = eq_panel.project.layer("part-1")
    assert (part.parent_id, part.part.tex, part.name) == ("eq", "b^2", "b^2")
    top = eq_panel.list.topLevelItem(0)
    assert top.data(0, Qt.ItemDataRole.UserRole) == "eq" and top.child(0).text(0) == "b^2"
    assert eq_panel.ids_front_to_back() == ["eq", "part-1", "sq"]
    assert eq_panel.selected_id() == "part-1"
    assert undo_texts(eq_panel) == ["Add part"]


def test_split_into_terms_is_one_undo_step_and_skips_existing_parts(eq_panel) -> None:
    eq_panel.select("eq")
    eq_panel.ask_part = lambda _parent: ("b^2", 0)
    eq_panel.add_part()
    eq_panel.worker.reply_all()
    eq_panel.select("eq")
    eq_panel.split_terms()
    eq_panel.worker.reply_all()
    assert [c.part.tex for c in eq_panel.project.children("eq")] == ["b^2", "a^2", "c^2"]
    assert undo_texts(eq_panel) == ["Add part", "Split into terms"]
    eq_panel.select("eq")
    eq_panel.split_terms()
    assert eq_panel.messages == ["Split into terms: no terms left to split"]


def test_a_part_cannot_be_reordered_and_parts_are_only_offered_for_tex(eq_panel) -> None:
    eq_panel.select("sq")
    assert not eq_panel.part_button.isEnabled()
    eq_panel.select("eq")
    assert eq_panel.part_button.isEnabled()
    eq_panel.ask_part = lambda _parent: ("c^2", 0)
    eq_panel.add_part()  # selects the new part
    eq_panel.worker.reply_all()
    assert not eq_panel.up_button.isEnabled() and not eq_panel.down_button.isEnabled()
    eq_panel.shift_selected(-1)
    assert eq_panel.ids_front_to_back() == ["eq", "part-1", "sq"]
    assert eq_panel.part_button.isEnabled()  # parts of parts


def test_an_orphaned_part_is_labelled(eq_panel) -> None:
    eq_panel.select("eq")
    eq_panel.ask_part = lambda _parent: ("c^2", 0)
    eq_panel.add_part()
    eq_panel.worker.reply_all()
    retyped = edits.update_layer(eq_panel.project, "eq", spec=Spec(type="MathTex", params={"text": "x"}))
    eq_panel.document.apply(retyped, "Edit")
    item = eq_panel.items()[1]
    assert item.text(0) == "c^2 (not found)"
    assert "not in the text" in item.toolTip(0)


def test_the_context_menu_offers_parts_on_equations(eq_panel) -> None:
    eq_panel.select("eq")
    texts = [a.text() for a in eq_panel.context_menu("eq").actions() if a.text()]
    assert texts == [
        "Add part...",
        "Split into terms",
        "Colour part...",
        "Colour Characters...",
        "Freeze to Shape",
        "Delete",
    ]
    eq_panel.select("sq")
    assert [a.text() for a in eq_panel.context_menu("sq").actions() if a.text()] == [
        "Freeze to Shape",
        "Delete",
    ]


def test_the_part_dialog_says_whether_a_part_resolves(eq_panel) -> None:
    from PySide6.QtWidgets import QDialogButtonBox

    from manim_studio.ui.layers_panel import PartDialog

    dialog = PartDialog(eq_panel.project, "eq")
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    dialog.tex.setText("2")
    assert ok.isEnabled() and dialog.status.text() == "Matches 3 times."
    assert dialog.occurrence.maximum() == 3
    dialog.occurrence.setValue(3)
    assert dialog.key() == ("2", 2)
    dialog.tex.setText("2 + b")
    assert not ok.isEnabled() and "superscript" in dialog.status.text()
    dialog.tex.setText("z")
    assert dialog.status.text() == "'z' is not in the text"


def test_the_buttons_drop_their_captions_when_the_panel_is_narrow(panel, qt_app) -> None:
    """P6d.4: the panel can be narrower than its captioned buttons; then they show icons only."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    host = QWidget()  # as in a splitter: a child, not a window that enforces its layout's minimum
    panel.setParent(host)
    host.resize(800, 500)
    host.show()
    assert panel.minimumSizeHint().width() < panel._full_width
    panel.resize(panel._full_width + 40, 400)
    panel.show()
    qt_app.processEvents()
    assert not panel.compact
    assert panel.add_button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    panel.resize(panel.minimumSizeHint().width(), 400)
    qt_app.processEvents()
    assert panel.compact and panel.part_button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    for button in (panel.add_button, panel.part_button, panel.down_button):
        assert button.geometry().right() <= panel.width()  # every button still fits
        assert button.toolTip()  # and says what it does
    panel.resize(panel._full_width + 40, 400)
    qt_app.processEvents()
    assert not panel.compact
    panel.setParent(None)


def test_new_shapes_are_placed_where_they_cover_nothing_and_texts_show_their_words(panel) -> None:
    """GP: every new object used to land on the centre, on top of the others."""
    import numpy as np

    from manim_studio.core import placement

    panel.document.replace(Project(canvas=CANVAS))
    for type_name in ("Square", "Circle", "Star"):
        panel.add_object(type_name)
    boxes = placement.occupied(panel.project, 0.0)
    assert len(boxes) == 3
    assert panel.project.layers[0].base.position == (0.0, 0.0)  # the first one: the centre
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            assert not placement._overlaps(a, b)
    assert all(np.isfinite(layer.base.position).all() for layer in panel.project.layers)
    text = Layer(id="text-1", spec=Spec(type="Text", params={"text": "Hello world"}))
    panel.document.replace(Project(canvas=CANVAS, layers=[text]))
    assert [item.text(0) for item in panel.items()] == ["Hello world"]
