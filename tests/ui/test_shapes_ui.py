"""Freeze to shape in the editor (P10.2, ADR 0052), through the real MainWindow: the button in
Properties for objects that can be frozen, the Layers context menu and the Edit menu; one undo
step that undo reverses exactly; a reason in the status bar when it cannot be frozen."""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import manim as m
import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel

from manim_studio.core import python_object
from manim_studio.core.schema import Canvas, Clip, Layer, PartKey, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=2.0)
CIRCLE = Spec(type="Circle", params={"radius": 1.2}, style={"fill": "#ef4444", "fill_opacity": 0.6})


def layers(tmp_path) -> list[Layer]:
    return [
        Layer(
            id="dot",
            spec=CIRCLE,
            base=Transform2D(position=(1.0, 0.0)),
            clips=[Clip(id="c", kind="Create", start=0, duration=1)],
        ),
        Layer(id="eq", spec=Spec(type="MathTex", params={"text": r"e^{i\pi}+1=0"})),
        Layer(id="part", parent_id="eq", part=PartKey(tex="=")),
        Layer(
            id="code",
            spec=Spec(
                type="Code", params={"code": "class A(Scene):\n    def construct(self):\n        pass\n"}
            ),
        ),
        Layer(id="gone", spec=Spec(type="SVGMobject", params={"path": str(tmp_path / "gone.svg")})),
        # code no other test trusted (the trust store is shared by the session)
        Layer(
            id="py",
            spec=Spec(type="Python", params={"code": f"# {uuid.uuid4().hex}\n{python_object.STARTER}"}),
        ),
        Layer(
            id="word",
            spec=Spec(type="Text", params={"text": "Hi"}),
            clips=[Clip(id="abc", kind="AddTextLetterByLetter", start=0, duration=1)],
        ),
    ]


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(canvas=CANVAS, layers=layers(tmp_path))
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.ask_trust = lambda names: "skip"  # the Python object stays untrusted: a placeholder
    win.resize(1500, 850)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


def select(window, qt_app, layer_id: str) -> None:
    window.selection.select_layer(layer_id)
    qt_app.processEvents()


def pixels(window, t: float) -> np.ndarray:
    return render_frame(make_camera(window.project.canvas), window.evaluator.frame(t))


def status(window) -> str:
    return window.statusBar().currentMessage()


def test_the_button_shows_for_objects_that_can_be_frozen(window, qt_app) -> None:
    for layer_id, shown in (
        ("dot", True),
        ("eq", True),
        ("py", True),
        ("word", True),
        ("code", False),
        ("part", False),
    ):
        select(window, qt_app, layer_id)
        assert (window.properties.freeze_button is not None) is shown, layer_id


def test_clicking_freezes_in_one_undo_step_and_undo_restores_it(window, qt_app) -> None:
    select(window, qt_app, "dot")
    before = window.project.layer("dot")
    drawn = [pixels(window, t) for t in (0.3, 0.7, 1.5)]
    window.properties.freeze_button.click()
    qt_app.processEvents()
    after = window.project.layer("dot")
    assert after.spec.type == "Shape" and after.spec.style == {}
    assert after.clips == before.clips and after.base == before.base
    assert window.document.undo_stack.undoText() == "Freeze to shape"
    assert all(np.array_equal(x, pixels(window, t)) for x, t in zip(drawn, (0.3, 0.7, 1.5), strict=True))
    assert window.properties.freeze_button is None  # a shape: a note, no parameters, no button
    notes = [
        x for x in window.properties.findChildren(QLabel, "frozenNote") if x.isVisibleTo(window.properties)
    ]
    assert len(notes) == 1 and notes[0].text().startswith("Frozen: plain vector data")
    assert not any(path.startswith("params.") for path in window.properties.fields)
    assert "style.fill" in window.properties.fields  # its colours can still be changed
    window.document.undo_stack.undo()
    qt_app.processEvents()
    assert window.project.layer("dot") == before
    assert window.properties.freeze_button is not None


def test_refusals_say_why_in_the_status_bar(window, qt_app) -> None:
    select(window, qt_app, "py")
    window.properties.freeze_button.click()
    assert "Freeze to Shape" in status(window) and "code not trusted yet" in status(window)
    assert window.project.layer("py").spec.type == "Python"
    select(window, qt_app, "eq")
    window.properties.freeze_button.click()
    assert "it has parts" in status(window)
    select(window, qt_app, "word")
    window.properties.freeze_button.click()
    assert "AddTextLetterByLetter clip (abc) needs Text" in status(window)
    assert window.freeze_layer("gone") is False
    assert "placeholder" in status(window) and "file not found" in status(window)
    assert window.document.undo_stack.count() == 0


def test_only_what_the_editor_draws_is_frozen(window, qt_app, monkeypatch) -> None:
    """The code became runnable behind the editor's back (another window trusted it): until the
    editor rebuilds it, it shows the placeholder, so that - not the code's object - is what it has."""
    assert isinstance(dict(window.evaluator.frame_layers(0.5))["py"], m.DashedVMobject)
    monkeypatch.setattr(python_object, "_trust_everything", True)
    assert window.freeze_layer("py") is False
    assert "placeholder" in status(window) and "code not trusted yet" in status(window)
    window.reload_media()  # what Reload media / trusting in this window does: it is built now
    qt_app.processEvents()
    assert not isinstance(dict(window.evaluator.frame_layers(0.5))["py"], m.DashedVMobject)
    assert window.freeze_layer("py") is True
    assert window.project.layer("py").spec.type == "Shape"


def test_the_layers_menu_and_the_edit_menu_freeze_too(window, qt_app) -> None:
    menu = window.layers.context_menu("dot")
    action = next(a for a in menu.actions() if a.text() == "Freeze to Shape")
    assert all(a.text() != "Freeze to Shape" for a in window.layers.context_menu("code").actions())
    action.trigger()
    qt_app.processEvents()
    assert window.project.layer("dot").spec.type == "Shape"
    window.document.undo_stack.undo()
    select(window, qt_app, "dot")
    window.freeze_action.trigger()
    qt_app.processEvents()
    assert window.project.layer("dot").spec.type == "Shape"
    assert window.document.undo_stack.count() == 1  # the undone freeze was replaced
    assert not isinstance(dict(window.evaluator.frame_layers(1.5))["dot"], m.DashedVMobject)
