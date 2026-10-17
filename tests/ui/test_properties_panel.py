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
from manim_studio.core.schema import Clip, Easing, Keyframe, Layer, Project, Spec, Transform2D
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
    assert panel.fields["keys.scale"].widget.isChecked()  # scale is keyframed
    assert not panel.fields["keys.rotation"].widget.isChecked()


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
    assert set(panel.fields) == {
        "clip.kind",
        "clip.start",
        "clip.duration",
        "clip.ease",
        "clip.params.color",  # Indicate's registered params (ADR 0022)
        "clip.params.scale_factor",
    }
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


def test_clip_params_follow_the_kind(panel) -> None:
    panel.show_clip("ball", "i")
    assert panel.fields["clip.params.color"].button.text() == "#FFFF00"  # the default, shown
    panel.fields["clip.params.color"].commit("#22d3ee")
    panel.fields["clip.params.scale_factor"].commit(1.6)
    assert layer(panel, "ball").clips[1].params == {"color": "#22d3ee", "scale_factor": 1.6}
    panel.fields["clip.params.color"].commit(None)  # back to the default
    assert layer(panel, "ball").clips[1].params == {"scale_factor": 1.6}
    panel.fields["clip.kind"].commit("Circumscribe")
    assert layer(panel, "ball").clips[1].params == {}  # Circumscribe has no scale factor
    assert {"clip.params.shape", "clip.params.color"} <= set(panel.fields)  # rebuilt for the new kind
    assert "clip.params.scale_factor" not in panel.fields
    panel.fields["clip.params.shape"].commit("circle")
    assert layer(panel, "ball").clips[1].params == {"shape": "circle"}
    assert undo_texts(panel)[-1] == "Change shape"


def test_a_fade_can_come_from_a_side(panel) -> None:
    panel.show_clip("ball", "c")  # Create
    panel.fields["clip.kind"].commit("FadeIn")
    field = panel.fields["clip.params.shift"]
    assert [field.widget.itemText(i) for i in range(field.widget.count())] == [
        "None",
        "Up",
        "Down",
        "Left",
        "Right",
    ]
    field.commit("LEFT")
    assert layer(panel, "ball").clips[0].params == {"shift": "LEFT"}


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


# -- stopwatch (S3.6, ADR 0016) ------------------------------------------------------


def test_stopwatch_on_adds_one_key_holding_the_current_value(panel) -> None:
    panel.playhead = lambda: 0.4  # frame 6 at 15 fps
    panel.show_layer("box")
    panel.document.apply(
        edits.update_layer(panel.project, "box", base=Transform2D(position=(1.0, 2.0))), "Move layer"
    )
    panel.fields["keys.position"].widget.setChecked(True)
    track = layer(panel, "box").tracks["position"]
    assert [(k.t, k.value) for k in track] == [(pytest.approx(0.4), (1.0, 2.0))]
    assert "Keyed" in panel.fields["base.position"].widget.toolTip()  # edited through keys now
    assert undo_texts(panel)[-1] == "Animate position"


def test_stopwatch_off_keeps_the_value_at_the_playhead(panel) -> None:
    doc = panel.document
    doc.apply(edits.set_key(panel.project, "box", "position", 0.0, (0.0, 0.0)), "Key")
    doc.apply(edits.set_key(panel.project, "box", "position", 1.0, (2.0, 0.0)), "Key")
    panel.playhead = lambda: 0.5
    panel.show_layer("box")
    assert panel.fields["keys.position"].widget.isChecked()
    panel.fields["keys.position"].widget.setChecked(False)
    box = layer(panel, "box")
    assert "position" not in box.tracks
    assert box.base.position[0] == pytest.approx(1.0, abs=0.2)  # where it was at 0.5 s (smooth ease)
    assert panel.fields["base.position"].widget.toolTip() == ""
    doc.undo_stack.undo()
    assert len(layer(panel, "box").tracks["position"]) == 2


# -- keyable transform fields and auto-key (P2a.3-P2a.4, ADR 0018) -----------------------


def test_every_transform_property_has_a_keys_toggle(panel) -> None:
    panel.show_layer("box")
    assert {"keys.position", "keys.scale", "keys.rotation", "keys.opacity"} <= set(panel.fields)


def test_the_anchor_point_field_moves_the_pivot_without_keys(panel) -> None:
    panel.playhead = lambda: 0.5  # ball's scale is keyed: the drawing is kept at 0.5 s only
    panel.show_layer("ball")
    assert "keys.anchor" not in panel.fields  # base only (ADR 0021)
    assert panel.fields["base.anchor"].x.value() == 0.0
    panel.fields["base.anchor"].commit((0.5, 0.0))
    ball = layer(panel, "ball")
    assert ball.base.anchor == (0.5, 0.0)
    assert "anchor" not in ball.tracks and set(ball.tracks) == {"scale"}
    assert ball.base.position != (0.0, 0.0)  # compensated
    assert undo_texts(panel)[-1] == "Move anchor"
    assert "keeps its place at this frame only" in panel.messages[-1]
    panel.show_layer("box")
    panel.fields["base.anchor"].commit((0.5, 0.0))
    assert layer(panel, "box").base.position == (0.0, 0.0)  # nothing turned: nothing to compensate


def test_editing_a_keyed_field_sets_a_key_at_the_playhead(panel) -> None:
    panel.playhead = lambda: 0.4  # ball's scale is keyed 1.0 at 0 s and 2.0 at 1 s
    panel.show_layer("ball")
    assert 1.0 < panel.fields["base.scale"].widget.value() < 2.0  # the eased value at 0.4 s
    panel.fields["base.scale"].commit(3.0)
    keys = layer(panel, "ball").tracks["scale"]
    assert [(k.t, k.value) for k in keys] == [(0, 1.0), (pytest.approx(0.4), 3.0), (1, 2.0)]
    assert layer(panel, "ball").base.scale == 1.0


def test_auto_key_from_a_field_animates_from_the_layer_start(panel) -> None:
    panel.playhead = lambda: 0.6
    panel.auto_key = lambda: True
    panel.show_layer("dot")  # no clips: visible from 0 s
    panel.fields["base.rotation"].commit(45.0)
    keys = layer(panel, "dot").tracks["rotation"]
    assert [(k.t, k.value) for k in keys] == [(0.0, 0.0), (pytest.approx(0.6), 45.0)]


# -- key view (P2b.3) -------------------------------------------------------------------


def test_key_view_edits_values_and_easing(panel) -> None:
    panel.show_key("ball", 1.0)  # ball: scale keyed at 0 s and 1 s
    assert set(panel.fields) == {"keys.time", "keys.scale.value", "keys.scale.ease"}
    assert "Keys at 1 s" in panel.title.text()
    assert not panel.fields["keys.scale.ease"].widget.isEnabled()  # the last key: nothing follows it
    panel.fields["keys.scale.value"].commit(3.0)
    assert layer(panel, "ball").tracks["scale"][1].value == 3.0
    panel.show_key("ball", 0.0)
    assert panel.fields["keys.scale.ease"].widget.isEnabled()
    panel.fields["keys.scale.ease"].commit(Easing(name="linear"))
    assert layer(panel, "ball").tracks["scale"][0].ease == Easing(name="linear")


def test_key_view_retimes_and_reports_the_new_time(panel) -> None:
    moved = []
    panel.keyMoved.connect(lambda *a: moved.append(a))
    panel.show_key("ball", 1.0)
    panel.fields["keys.time"].commit(0.6)
    assert [k.t for k in layer(panel, "ball").tracks["scale"]] == [0, pytest.approx(0.6)]
    assert moved == [("ball", pytest.approx(0.6))]


def test_custom_curve_from_the_easing_list(panel) -> None:
    curve = Easing(name=None, bezier=(0.2, 0.0, 0.3, 1.2))
    asked = []
    panel.curve_dialog = lambda ease: asked.append(ease) or curve
    panel.show_key("ball", 0.0)
    panel.fields["keys.scale.ease"].commit("custom-curve")
    assert asked == [Easing()]  # the key's current ease (smooth) is where the editor starts
    assert layer(panel, "ball").tracks["scale"][0].ease == curve
    assert panel.fields["keys.scale.ease"].widget.currentText().startswith("Custom curve")


def test_cancelling_the_curve_editor_changes_nothing(panel) -> None:
    panel.curve_dialog = lambda ease: None
    panel.show_clip("ball", "i")
    before = panel.project
    panel.fields["clip.ease"].commit("custom-curve")
    assert panel.project is before
    assert panel.fields["clip.ease"].widget.currentText() == "Animation default"


# -- part layers (P2c.3) ----------------------------------------------------------------


@pytest.fixture
def part_panel(qt_app):
    from manim_studio.core.schema import PartKey

    eq = Layer(id="eq", spec=Spec(type="MathTex", params={"text": "a^2 + b^2 = c^2"}))
    part = Layer(id="b", name="b^2", parent_id="eq", part=PartKey(tex="b^2"))
    doc = Document(Project(canvas=CANVAS, layers=[eq, part]))
    worker = FakeWorker()
    widget = PropertiesPanel(BuildService(doc, worker))
    widget.worker = worker
    widget.messages = []
    widget.message.connect(widget.messages.append)
    widget.show()
    yield widget
    widget.close()


def test_a_part_shows_its_key_and_transform_but_no_object_or_style(part_panel) -> None:
    part_panel.show_layer("b")
    assert {"part.tex", "part.occurrence", "base.position", "lifetime.in"} <= set(part_panel.fields)
    assert not any(path.startswith(("params.", "style.")) for path in part_panel.fields)
    assert part_panel.fields["part.tex"].widget.text() == "b^2"
    assert part_panel.fields["part.occurrence"].widget.value() == 1
    assert "part of a^2 + b^2 = c^2" in part_panel.title.text()  # the equation by its words (GP)


def test_editing_a_part_key_retargets_it_or_is_refused(part_panel) -> None:
    part_panel.show_layer("b")
    part_panel.fields["part.tex"].commit("c^2")
    part_panel.worker.reply_all()  # the object is rebuilt with the new marker
    assert part_panel.project.layer("b").part.tex == "c^2"
    part_panel.fields["part.occurrence"].commit(2)  # there is one c^2
    assert part_panel.project.layer("b").part.occurrence == 0
    assert part_panel.messages and "occurs 1 time, not 2" in part_panel.messages[-1]
