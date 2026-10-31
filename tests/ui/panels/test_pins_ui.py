"""Pin to... and Unpin in the Layers panel (ADR 0075)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.editing import edits
from manim_studio.core.model.schema import Layer, Pin, Project, Spec
from manim_studio.ui.panels.layers_panel import LayersPanel, PinDialog, PinRequest
from manim_studio.ui.session.build_service import BuildService
from manim_studio.ui.session.document import Document
from qt_support import FakeWorker
from support import CANVAS

pytestmark = pytest.mark.ui


def project() -> Project:
    layers = [
        Layer(id="sq", name="Box", spec=Spec(type="Square")),
        Layer(id="t", spec=Spec(type="Text", params={"text": "label"})),
        Layer(id="c", spec=Spec(type="Circle")),
    ]
    return Project(canvas=CANVAS, layers=layers)


@pytest.fixture
def layers(qt_app):
    worker = FakeWorker()
    widget = LayersPanel(BuildService(Document(project()), worker))
    widget.worker = worker
    widget.messages = []
    widget.message.connect(widget.messages.append)
    widget.show()
    yield widget
    widget.close()


def texts(layers: LayersPanel, layer_id: str) -> list[str]:
    layers.select(layer_id)
    return [a.text() for a in layers.context_menu(layer_id).actions() if a.text()]


def undo_texts(document: Document) -> list[str]:
    return [document.undo_stack.text(i) for i in range(document.undo_stack.count())]


def test_pin_to_is_offered_on_texts_and_unpin_on_pinned_ones(layers) -> None:
    assert "Pin to..." in texts(layers, "t") and "Unpin" not in texts(layers, "t")
    assert "Pin to..." not in texts(layers, "c")


def test_pinning_and_unpinning_are_one_undo_step_each(layers) -> None:
    layers.ask_pin = lambda layer_id: PinRequest("sq", "bottom", follow_rotation=True)
    layers.select("t")
    next(a for a in layers.context_menu("t").actions() if a.text() == "Pin to...").trigger()
    layers.worker.reply_all()
    assert layers.project.layer("t").pin == Pin(target="sq", anchor="bottom", follow_rotation=True)
    assert "Unpin" in texts(layers, "t")
    layers.unpin_position = lambda layer_id: (1.0, -2.0)
    next(a for a in layers.context_menu("t").actions() if a.text() == "Unpin").trigger()
    layers.worker.reply_all()
    unpinned = layers.project.layer("t")
    assert unpinned.pin is None and unpinned.base.position == (1.0, -2.0)
    assert undo_texts(layers.document) == ["Pin label", "Unpin label"]


def test_a_cancelled_chooser_changes_nothing(layers) -> None:
    layers.ask_pin = lambda layer_id: None
    assert layers.pin_label("t") is False
    assert layers.document.undo_stack.count() == 0


def test_the_chooser_lists_what_the_label_may_follow_and_shows_its_pin(qt_app) -> None:
    scene = edits.pin_label(project(), "t", "c", "left", follow_scale=True).project
    dialog = PinDialog(scene, "t")
    ids = [dialog.target.itemData(i) for i in range(dialog.target.count())]
    assert ids == ["sq", "c"]  # not itself
    assert dialog.request() == PinRequest("c", "left", follow_rotation=False, follow_scale=True)
    lonely = Project(canvas=CANVAS, layers=[Layer(id="t", spec=Spec(type="Text", params={"text": "x"}))])
    assert PinDialog(lonely, "t").request() is None


def test_the_window_unpins_a_label_where_it_is_drawn(qt_app, tmp_path) -> None:
    from manim_studio.ui.main_window import MainWindow

    path = tmp_path / "p.json"
    path.write_text(
        edits.pin_label(project(), "t", "sq").project.model_dump_json(by_alias=True), encoding="utf-8"
    )
    window = MainWindow()
    try:
        window.load(path)
        qt_app.processEvents()
        expected = window.evaluator.unpinned_position(window.project.layer("t"), window.t)
        assert window.layers.unpin_position("t") == expected and expected[1] > 0.5  # above the square
        assert window.layers.unpin_position("missing") is None
    finally:
        window.close()
