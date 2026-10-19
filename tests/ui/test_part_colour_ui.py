"""Colouring part of a text from Properties and Layers (U5, ADR 0049): one undo step each."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.schema import Layer, PartKey, Project, Spec
from manim_studio.ui.build_service import BuildService
from manim_studio.ui.document import Document
from manim_studio.ui.layers_panel import LayersPanel
from manim_studio.ui.properties_panel import PropertiesPanel
from qt_support import FakeWorker
from support import CANVAS

pytestmark = pytest.mark.ui

EQ = "a^2 + b^2 = c^2"
RED, GREEN = "#ff0000", "#00ff00"  # content: the colours the user picks


def document() -> Document:
    eq = Layer(id="eq", spec=Spec(type="MathTex", params={"text": EQ}))
    words = Layer(id="t", spec=Spec(type="Text", params={"text": "Hi ok"}))
    return Document(Project(canvas=CANVAS, layers=[eq, words]))


def undo_texts(document: Document) -> list[str]:
    stack = document.undo_stack
    return [stack.text(i) for i in range(stack.count())]


@pytest.fixture
def panel(qt_app):
    worker = FakeWorker()
    widget = PropertiesPanel(BuildService(document(), worker))
    widget.worker = worker
    widget.messages = []
    widget.message.connect(widget.messages.append)
    widget.show()
    yield widget
    widget.close()


@pytest.fixture
def layers(qt_app):
    worker = FakeWorker()
    widget = LayersPanel(BuildService(document(), worker))
    widget.worker = worker
    widget.messages = []
    widget.message.connect(widget.messages.append)
    widget.show()
    yield widget
    widget.close()


def test_colour_a_part_from_the_equation_makes_and_colours_the_part_in_one_step(panel) -> None:
    panel.show_layer("eq")
    assert panel.part_tex is not None and panel.part_occurrence.value() == 1
    panel.part_tex.setText("b^2")
    asked = []
    panel.ask_colour = lambda current: asked.append(current) or RED
    panel.part_colour_button.click()
    panel.worker.reply_all()  # the object is rebuilt with the part's marker
    (made,) = panel.project.children("eq")
    assert (made.part, made.style) == (PartKey(tex="b^2"), {"fill": RED})
    assert undo_texts(panel.document) == ["Colour part"] and asked == [None]
    panel.show_layer("eq")
    panel.part_tex.setText("b^2")
    panel.ask_colour = lambda current: asked.append(current) or GREEN
    panel.part_colour_button.click()
    panel.worker.reply_all()
    assert [x.style for x in panel.project.children("eq")] == [{"fill": GREEN}]  # the same part
    assert asked[-1] == RED  # starts from its colour
    panel.document.undo_stack.undo()
    panel.document.undo_stack.undo()
    assert panel.project.children("eq") == []


def test_colour_a_part_refuses_what_is_not_in_the_text_or_was_cancelled(panel) -> None:
    panel.show_layer("eq")
    panel.ask_colour = lambda current: RED
    panel.part_colour_button.click()
    assert panel.messages[-1] == "Colour part: type the TeX of the part first"
    panel.part_tex.setText("z")
    panel.part_colour_button.click()
    assert "not in the text" in panel.messages[-1]
    panel.part_tex.setText("b^2")
    panel.ask_colour = lambda current: None
    panel.part_colour_button.click()
    assert panel.document.undo_stack.count() == 0


def test_a_part_has_fill_and_stroke_colours_and_its_not_drawn_note(panel) -> None:
    from manim_studio.core import edits

    panel.document.apply(edits.add_part(panel.project, "eq", "b^2", layer_id="b"), "Add part")
    panel.show_layer("b")
    assert {"part_style.fill", "part_style.stroke"} <= set(panel.fields)
    assert panel.fields["part_style.fill"].button.text() == "Default"
    panel.fields["part_style.fill"].commit(RED)
    assert panel.project.layer("b").style == {"fill": RED}
    assert panel.fields["part_style.fill"].button.text() == RED
    panel.fields["part_style.fill"].commit(None)  # the reset button: its object's colour again
    assert panel.project.layer("b").style == {}
    assert undo_texts(panel.document)[-2:] == ["Colour part fill", "Colour part fill"]
    retyped = edits.update_layer(panel.project, "eq", spec=Spec(type="MathTex", params={"text": "x^2"}))
    panel.document.apply(retyped, "Edit")
    assert "Not drawn: 'b^2' is not in the text" in panel.title.text()


def test_a_text_lists_its_coloured_pieces_and_colours_another(panel) -> None:
    panel.show_layer("t")
    assert panel.part_occurrence is None  # every match of a piece is coloured
    panel.part_tex.setText("ok")
    panel.ask_colour = lambda current: RED
    panel.part_colour_button.click()
    panel.worker.reply_all()  # a Text with other colours is built first (ADR 0015)
    assert panel.project.layer("t").spec.params["t2c"] == {"ok": RED}
    assert panel.fields["t2c.ok"].button.text() == RED  # a row of its own now
    panel.fields["t2c.ok"].commit(GREEN)
    panel.worker.reply_all()
    assert panel.project.layer("t").spec.params["t2c"] == {"ok": GREEN}
    panel.fields["t2c.ok"].commit(None)  # x: stop colouring it
    panel.worker.reply_all()
    assert "t2c" not in panel.project.layer("t").spec.params
    assert "t2c.ok" not in panel.fields
    assert undo_texts(panel.document) == ["Colour piece"] * 3


def test_layers_offer_colour_part_on_equations_and_parts(layers) -> None:
    layers.select("eq")
    texts = [a.text() for a in layers.context_menu("eq").actions() if a.text()]
    assert texts == [
        "Add part...",
        "Split into terms",
        "Colour part...",
        "Colour Characters...",
        "Freeze to Shape",
        "Delete",
    ]
    layers.ask_part = lambda parent_id: ("c^2", 0)
    layers.ask_colour = lambda current: RED
    layers.colour_part()
    layers.worker.reply_all()
    (made,) = layers.project.children("eq")
    assert (made.part.tex, made.style) == ("c^2", {"fill": RED})
    assert undo_texts(layers.document) == ["Colour part"]
    layers.select(made.id)
    menu = [a.text() for a in layers.context_menu(made.id).actions() if a.text()]
    assert "Colour this part..." in menu
    seen = []
    layers.ask_colour = lambda current: seen.append(current) or GREEN
    layers.colour_part()
    assert seen == [RED] and layers.project.layer(made.id).style == {"fill": GREEN}
    layers.select("t")
    texts = [a.text() for a in layers.context_menu("t").actions() if a.text()]
    assert texts == ["Colour Characters...", "Freeze to Shape", "Delete"]
