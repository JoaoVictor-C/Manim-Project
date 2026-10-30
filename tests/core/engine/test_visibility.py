from __future__ import annotations

from manim_studio.core.editing import edits
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.engine.python_export import to_python
from manim_studio.core.model.schema import Clip, Layer, Project, Spec


def test_layer_visibility_is_backward_compatible_and_persisted_when_hidden() -> None:
    layer = Layer(id="shape", spec=Spec(type="Square"))
    assert "visible" not in layer.model_dump_json()

    hidden = Project(layers=[layer.model_copy(update={"visible": False})])
    restored = Project.model_validate_json(hidden.model_dump_json())
    assert restored.layer("shape").visible is False
    assert Evaluator(restored).frame_layers(0.0) == []

    edit = edits.update_layer(Project(layers=[layer]), "shape", visible=False)
    assert edit.kind == "timing" and edit.layer_ids == {"shape"}


def test_a_hidden_group_hides_its_children_and_a_hidden_child_hides_only_itself() -> None:
    group = Layer(id="group", spec=Spec(type="Group"))
    one = Layer(id="one", parent_id="group", spec=Spec(type="Square"))
    two = Layer(id="two", parent_id="group", spec=Spec(type="Circle"))
    project = Project(layers=[group, one, two])

    hidden_group = project.model_copy(
        update={"layers": [group.model_copy(update={"visible": False}), one, two]}
    )
    assert Evaluator(hidden_group).frame_layers(0.0) == []

    hidden_child = project.model_copy(
        update={"layers": [group, one.model_copy(update={"visible": False}), two]}
    )
    assert [layer_id for layer_id, _mob in Evaluator(hidden_child).frame_layers(0.0)] == ["two"]


def test_readable_python_export_does_not_add_or_animate_hidden_layers() -> None:
    hidden = Layer(
        id="hidden",
        visible=False,
        spec=Spec(type="Circle"),
        clips=[Clip(id="fade", kind="FadeIn", start=0.5, duration=0.5)],
    )
    shown = Layer(id="shown", spec=Spec(type="Square"))
    exported = to_python(Project(layers=[hidden, shown]), "Visibility")

    assert exported.readable
    assert "self.add(hidden)" not in exported.code
    assert "self.play(FadeIn(hidden)" not in exported.code
    assert "self.add(shown)" in exported.code
