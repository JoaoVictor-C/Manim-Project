"""Properties dock (S2.5): registry-generated fields, one undo step per field."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from manim_studio.core import adapter, edits
from manim_studio.core.schema import Clip, Easing, Keyframe, Layer, Project, Spec
from manim_studio.core.warm import warm_key
from manim_studio.ui.build_service import BuildService
from manim_studio.ui.document import Document
from manim_studio.ui.properties_panel import PropertiesPanel
from qt_support import FakeWorker
from support import CANVAS

pytestmark = pytest.mark.ui

MATH = Spec(type="MathTex", params={"text": "x^2"})


def project() -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(id="eq", spec=MATH, clips=[Clip(id="w", kind="Write", start=0, duration=0.3)]),
            Layer(
                id="ball",
                spec=Spec(type="Circle"),
                tracks={"scale": [Keyframe(t=0, value=1.0), Keyframe(t=1, value=2.0)]},
                clips=[
                    Clip(id="c", kind="Create", start=0.0, duration=0.4),
                    Clip(id="i", kind="Indicate", start=0.5, duration=0.2),
                    Clip(id="m", kind="Transform", start=0.8, duration=0.2, to_layer="box"),
                ],
            ),
            Layer(id="box", spec=Spec(type="Square")),
            Layer(id="dot", spec=Spec(type="Dot")),
            Layer(id="pic", spec=Spec(type="ImageMobject", params={"path": "logo.png"})),
        ],
    )


@pytest.fixture
def panel(qt_app):
    doc = Document(project())
    worker = FakeWorker()
    builds = BuildService(doc, worker)
    builds._warmed.add(warm_key(MATH))
    widget = PropertiesPanel(builds)
    widget.worker = worker
    widget.messages = []
    widget.message.connect(widget.messages.append)
    widget.resize(360, 700)
    widget.show()
    yield widget
    widget.close()


def layer(panel, layer_id: str) -> Layer:
    return panel.project.layer(layer_id)


def undo_texts(panel) -> list[str]:
    stack = panel.document.undo_stack
    return [stack.text(i) for i in range(stack.count())]


# -- layers ---------------------------------------------------------------------------


def test_fields_come_from_the_registry(panel) -> None:
    panel.show_layer("ball")
    params = sorted(p for p in panel.fields if p.startswith("params."))
    assert params == [f"params.{p.name}" for p in adapter.MOBJECT_PARAMS["Circle"]]
    assert {"name", "style.fill", "base.position", "lifetime.in"} <= set(panel.fields)
    panel.show_layer("pic")
    assert "style.fill" not in panel.fields  # images have no fill/stroke
    assert "params.path" in panel.fields


def test_fields_show_document_values_and_registry_defaults(panel) -> None:
    panel.show_layer("ball")
    assert panel.fields["params.radius"].widget.value() == 1.0  # default, not in the spec
    assert panel.fields["style.fill"].button.text() == "Default"
    assert panel.fields["lifetime.out"].widget.text() == "Auto"


def test_a_param_change_is_one_undo_step(panel) -> None:
    panel.show_layer("ball")
    panel.fields["params.radius"].widget.setValue(2.5)  # what an Enter in the spin box does
    assert layer(panel, "ball").spec.params == {"radius": 2.5}
    assert undo_texts(panel) == ["Change radius"]
    panel.document.undo_stack.undo()
    assert panel.fields["params.radius"].widget.value() == 1.0


def test_style_set_and_reset(panel) -> None:
    panel.show_layer("box")
    panel.fields["style.fill"].commit("#ff0000")
    panel.fields["style.fill_opacity"].commit(0.5)
    assert layer(panel, "box").spec.style == {"fill": "#ff0000", "fill_opacity": 0.5}
    panel.fields["style.fill"].commit(None)
    assert layer(panel, "box").spec.style == {"fill_opacity": 0.5}
    assert panel.fields["style.fill"].button.text() == "Default"


def test_transform_and_keyframed_properties(panel) -> None:
    panel.show_layer("ball")
    panel.fields["base.position"].commit((1.0, -0.5))
    assert layer(panel, "ball").base.position == (1.0, -0.5)
    assert not panel.fields["base.scale"].widget.isEnabled()  # animated by keyframes
    assert panel.fields["base.rotation"].widget.isEnabled()


def test_lifetime_explicit_and_auto(panel) -> None:
    panel.show_layer("dot")
    panel.fields["lifetime.in"].commit(0.25)
    assert layer(panel, "dot").lifetime.in_ == 0.25
    panel.fields["lifetime.in"].commit(None)
    assert layer(panel, "dot").lifetime.in_ is None
    assert panel.fields["lifetime.in"].widget.text() == "Auto"


def test_rename(panel) -> None:
    panel.show_layer("dot")
    panel.fields["name"].widget.setText("Marker")
    panel.fields["name"].widget.editingFinished.emit()
    assert layer(panel, "dot").name == "Marker"
    assert "Marker" in panel.title.text()


# -- text and the build worker ---------------------------------------------------------


def test_new_latex_shows_as_pending_until_built(panel) -> None:
    panel.show_layer("eq")
    field = panel.fields["params.text"]
    field.widget.setPlainText(r"\int_0^1 x\,dx")
    QApplication.sendEvent(
        field.widget,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier),
    )
    assert layer(panel, "eq").spec == MATH  # not yet
    assert "italic" in field.widget.styleSheet()
    # an unrelated edit refreshes the panel: the typed text must survive
    panel.document.apply(edits.move_clip(panel.project, "ball", "i", 0.55), "Move clip")
    assert field.widget.toPlainText() == r"\int_0^1 x\,dx"
    panel.worker.reply(Spec(type="MathTex", params={"text": r"\int_0^1 x\,dx"}))
    assert layer(panel, "eq").spec.params["text"] == r"\int_0^1 x\,dx"
    assert field.widget.styleSheet() == ""
    assert undo_texts(panel) == ["Move clip", "Change latex (math)"]


def test_bad_latex_reverts_the_field(panel) -> None:
    panel.show_layer("eq")
    panel.fields["params.text"].commit(r"\notamacro")
    panel.worker.reply(Spec(type="MathTex", params={"text": r"\notamacro"}), ok=False, error="LaTeX error")
    assert layer(panel, "eq").spec == MATH
    assert panel.fields["params.text"].widget.toPlainText() == "x^2"


def test_font_size_does_not_wait(panel) -> None:
    """B19: font_size is cache-neutral, so it applies at once."""
    panel.show_layer("eq")
    panel.fields["params.font_size"].commit(72.0)
    assert layer(panel, "eq").spec.params["font_size"] == 72.0
    assert panel.worker.requests == {}


# -- clips -------------------------------------------------------------------------


def test_clip_fields_and_kind_choices(panel) -> None:
    panel.show_clip("ball", "i")
    assert set(panel.fields) == {"clip.kind", "clip.start", "clip.duration", "clip.ease"}
    kinds = [
        panel.fields["clip.kind"].widget.itemText(i) for i in range(panel.fields["clip.kind"].widget.count())
    ]
    assert "Indicate" in kinds and "Transform" not in kinds  # a clip stays in its family
    assert "Indicate" in panel.title.text()


def test_clip_edits(panel) -> None:
    panel.show_clip("ball", "i")
    panel.fields["clip.kind"].commit("Wiggle")
    panel.fields["clip.duration"].commit(0.25)
    panel.fields["clip.ease"].commit(Easing(name=None, bezier=adapter.BEZIER_PRESETS["CSS ease-in-out"]))
    clip = layer(panel, "ball").clips[1]
    assert (clip.kind, clip.duration, clip.ease.bezier) == ("Wiggle", 0.25, (0.42, 0.0, 0.58, 1.0))
    assert undo_texts(panel) == ["Change animation", "Trim clip", "Change easing"]


def test_an_overlapping_start_is_refused_and_reverted(panel) -> None:
    panel.show_clip("ball", "i")
    panel.fields["clip.start"].commit(0.3)  # overlaps Create (0-0.4)
    assert layer(panel, "ball").clips[1].start == 0.5
    assert panel.fields["clip.start"].widget.value() == 0.5
    assert panel.messages and "overlap" in panel.messages[-1]


def test_image_clips_only_offer_raster_safe_kinds(panel) -> None:
    doc = panel.document
    doc.apply(edits.add_clip(doc.project, "pic", "FadeIn", 0, 0.2), "Add clip")
    panel.show_clip("pic", "fadein-1")
    widget = panel.fields["clip.kind"].widget
    kinds = {widget.itemText(i) for i in range(widget.count())}
    assert "FadeIn" in kinds and "Write" not in kinds


def test_morph_targets_exclude_layers_that_are_already_targets(panel) -> None:
    doc = panel.document
    doc.apply(edits.add_clip(doc.project, "dot", "FadeTransform", 0.1, 0.2, to_layer="eq"), "Add morph")
    panel.show_clip("dot", "fadetransform-1")
    widget = panel.fields["clip.to_layer"].widget
    targets = {widget.itemData(i) for i in range(widget.count())}
    assert targets == {"eq", "ball", "pic"}  # not itself, not "box" (ball morphs into it)
    panel.fields["clip.to_layer"].commit("pic")
    assert layer(panel, "dot").clips[0].to_layer == "pic"


# -- selection follows the document ------------------------------------------------


def test_deleting_the_shown_clip_or_layer(panel) -> None:
    panel.show_clip("ball", "i")
    panel.document.apply(edits.remove_clip(panel.project, "ball", "i"), "Delete clip")
    assert panel.clip_id is None and panel.layer_id == "ball"
    panel.document.apply(edits.remove_layer(panel.project, "ball"), "Delete layer")
    assert panel.layer_id is None and panel.fields == {}


def test_widgets_of_a_previous_selection_cannot_commit(panel) -> None:
    panel.show_layer("ball")
    stale = panel.fields["params.radius"]
    panel.show_layer("dot")
    stale.commit(3.0)  # e.g. focus-out of a widget being deleted
    assert layer(panel, "ball").spec.params == {} and layer(panel, "dot").spec.params == {}
    assert panel.document.undo_stack.count() == 0


def test_opening_another_project_clears_the_panel(panel) -> None:
    panel.show_layer("ball")
    panel.document.replace(project())
    assert panel.layer_id is None
