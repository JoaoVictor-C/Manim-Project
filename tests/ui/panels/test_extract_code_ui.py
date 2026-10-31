"""Extract selection as code in the editor (ADR 0076), through the real MainWindow: the Edit menu and the
Layers context menu, one undo step, the new code layer selected on the Code page and trusted because the
editor wrote it from the user's own layers - but not when it embeds code that was not trusted yet."""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.code import python_object
from manim_studio.core.model.schema import Canvas, Clip, Layer, Pin, Project, Spec, Transform2D
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=3.0)


def layers() -> list[Layer]:
    return [
        Layer(
            id="ring",
            name="Ring",
            spec=Spec(type="Circle", params={"radius": 1.0}),
            clips=[Clip(id="c", kind="Create", start=0.5, duration=1.0)],
        ),
        Layer(
            id="word", spec=Spec(type="Text", params={"text": "Hi"}), base=Transform2D(position=(0.0, 2.0))
        ),
        Layer(id="dot", spec=Spec(type="Dot")),
        Layer(id="label", spec=Spec(type="Text", params={"text": "v"}), pin=Pin(target="dot")),
        Layer(  # code no other test trusted (the trust store is shared by the session)
            id="py",
            spec=Spec(type="Python", params={"code": f"# {uuid.uuid4().hex}\n{python_object.STARTER}"}),
        ),
    ]


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(Project(canvas=CANVAS, layers=layers()).model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.ask_trust = lambda names: "skip"
    win.resize(1500, 850)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


def status(window) -> str:
    return window.statusBar().currentMessage()


def test_the_edit_menu_extracts_in_one_undo_step_and_shows_the_code(window, qt_app) -> None:
    before = window.project
    window.selection.set_layers(["ring", "word"])
    qt_app.processEvents()
    window.extract_code_action.trigger()
    qt_app.processEvents()
    (new_id,) = {x.id for x in window.project.layers} - {x.id for x in before.layers}
    code_layer = window.project.layer(new_id)
    assert code_layer.spec.type == "Code" and not {"ring", "word"} & {x.id for x in window.project.layers}
    assert window.document.undo_stack.undoText() == "Extract as code"
    assert window.selection.layer_id == new_id and window.page == "code"
    assert window.trust.is_trusted(code_layer.spec.params["code"])  # written by the editor from the layers
    window.document.undo_stack.undo()
    qt_app.processEvents()
    assert window.project == before


def test_refusals_say_why_and_change_nothing(window, qt_app) -> None:
    assert window.extract_selection_as_code(["dot", "label"]) is False
    assert "Extract as Code" in status(window) and "pinned to another layer" in status(window)
    assert window.extract_selection_as_code([]) is False
    assert "select the objects" in status(window)
    assert window.document.undo_stack.count() == 0


def test_code_embedding_an_untrusted_python_object_is_not_trusted(window, qt_app) -> None:
    assert window.extract_selection_as_code(["py"]) is True
    (layer,) = [x for x in window.project.layers if x.spec is not None and x.spec.type == "Code"]
    assert "build" in layer.spec.params["code"]
    assert not window.trust.is_trusted(layer.spec.params["code"])  # asked about, as the object was


def test_the_layers_menu_extracts_the_selected_objects(window, qt_app) -> None:
    window.selection.set_layers(["ring", "word"])
    qt_app.processEvents()
    menu = window.layers.context_menu("ring")
    action = next(a for a in menu.actions() if a.text() == "Extract as Code")
    action.trigger()
    qt_app.processEvents()
    assert not {"ring", "word"} & {x.id for x in window.project.layers}
    assert window.document.undo_stack.count() == 1
