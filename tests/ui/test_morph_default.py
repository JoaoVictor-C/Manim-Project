"""The project's morph matching (ADR 0056 amended): smart by default, chosen when a project is
created (File > New) and changeable in Properties' Scene section."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.editing import edits
from manim_studio.core.engine.python_export import readable_problems
from manim_studio.core.model.new_project import NewProjectSettings
from manim_studio.core.model.schema import Clip, Layer, Project, Spec, new_clip_params
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.shell.new_project_dialog import NewProjectDialog

pytestmark = pytest.mark.ui


def two_shapes() -> Project:
    return Project(layers=[Layer(id="a", spec=Spec(type="Circle")), Layer(id="b", spec=Spec(type="Square"))])


# -- the schema ---------------------------------------------------------------------------------


def test_smart_is_the_default_and_is_not_written_to_the_file() -> None:
    project = Project()
    assert project.morph_matching == "smart"
    assert "morph_matching" not in project.model_dump(by_alias=True)


def test_classic_is_saved_and_loaded() -> None:
    saved = Project(morph_matching="classic").model_dump_json(by_alias=True)
    assert '"morph_matching":"classic"' in saved.replace(" ", "")
    assert Project.model_validate_json(saved).morph_matching == "classic"


def test_an_unknown_value_is_refused() -> None:
    with pytest.raises(ValueError):
        Project(morph_matching="fancy")


def test_new_clips_follow_the_projects_choice() -> None:
    assert new_clip_params("Transform", "smart") == {"match": "smart"}
    assert new_clip_params("Transform", "classic") == {}
    assert new_clip_params("Transform") == {"match": "smart"}
    assert new_clip_params("FadeIn", "smart") == {}


def test_the_edit_changes_only_the_setting_and_is_undoable() -> None:
    project = two_shapes()
    edit = edits.set_morph_matching(project, "classic")
    assert edit.project.morph_matching == "classic" and edit.project.layers == project.layers
    assert (edit.kind, edit.layer_ids) == ("timing", frozenset())  # no frame changes
    with pytest.raises(edits.EditError):
        edits.set_morph_matching(project, "fancy")


def test_equation_steps_and_added_morphs_use_the_projects_choice() -> None:
    for matching, expected in (("smart", "smart"), ("classic", None)):
        project = Project(morph_matching=matching)
        steps, _report = edits.add_equation_steps(
            project, ["x", "7"], start=0.0
        )  # nothing shared: a plain Transform
        morph = next(c for layer in steps.project.layers for c in layer.clips if c.to_layer)
        assert morph.params.get("match") == expected


def test_a_classic_project_exports_readable_python_where_a_smart_one_does_not() -> None:
    def with_morph(matching: str) -> Project:
        base = two_shapes().model_copy(update={"morph_matching": matching})
        layers = [
            base.layers[0].model_copy(
                update={
                    "clips": [
                        Clip(
                            id="m",
                            kind="Transform",
                            start=0.0,
                            duration=1.0,
                            to_layer="b",
                            params=new_clip_params("Transform", matching),
                        )
                    ]
                }
            ),
            base.layers[1],
        ]
        return Project.model_validate(
            {**base.model_dump(by_alias=True), "layers": [x.model_dump(by_alias=True) for x in layers]}
        )

    assert readable_problems(with_morph("classic")) == []
    assert any("smart morph" in why for why in readable_problems(with_morph("smart")))


# -- the dialog -------------------------------------------------------------------------------


def test_the_dialog_offers_both_choices_with_the_remembered_one_selected(qt_app) -> None:
    dialog = NewProjectDialog(remembered="classic")
    assert dialog.choice() == "classic"
    dialog.smart_button.setChecked(True)
    assert dialog.choice() == "smart"
    assert dialog.smart_button.toolTip() and dialog.classic_button.toolTip()
    assert "Python" in dialog.classic_button.text() + dialog.classic_button.toolTip()
    default = NewProjectDialog()
    assert default.choice() == "smart"


# -- the window ---------------------------------------------------------------------------------


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1100, 700)
    win.show()
    qt_app.processEvents()
    yield win
    win.document.undo_stack.setClean()
    win.close()


def test_new_project_asks_and_creates_the_project_with_that_choice(window, monkeypatch) -> None:
    asked = []
    monkeypatch.setattr(
        window,
        "ask_new_project",
        lambda remembered, template="blank": (
            asked.append(remembered) or NewProjectSettings(morph_matching="classic")
        ),
    )
    window.new_project()
    assert window.project.morph_matching == "classic"
    assert asked == ["smart"]  # first time: smart is offered
    window.new_project()
    assert asked == ["smart", "classic"]  # the next time the last choice is offered


def test_cancelling_the_dialog_keeps_the_current_project(window, monkeypatch) -> None:
    window.new_project()
    window.document.apply(edits.add_layer(window.project, Spec(type="Circle")), "Add")
    monkeypatch.setattr(window, "ask_new_project", lambda remembered, template="blank": None)
    window.new_project()
    assert len(window.project.layers) == 1


def test_the_welcome_new_button_goes_through_the_same_question(window, monkeypatch) -> None:
    monkeypatch.setattr(
        window,
        "ask_new_project",
        lambda remembered, template="blank": NewProjectSettings(morph_matching="classic"),
    )
    window.welcome.new_button.click()
    assert window.project.morph_matching == "classic"


def test_properties_scene_section_changes_it_in_one_undo_step(window, qt_app) -> None:
    window.new_project()  # the test hook answers "smart"
    window.selection.clear()
    field = window.properties.fields["project.morph_matching"]
    assert field.widget.currentData() == "smart"
    field.commit("classic")
    assert window.project.morph_matching == "classic"
    assert window.document.undo_stack.undoText() == "New morphs"
    window.document.undo_stack.undo()
    assert window.project.morph_matching == "smart"
    assert field.widget.currentData() == "smart"


def test_a_new_morph_clip_from_the_timeline_follows_the_setting(window) -> None:
    window.new_project()
    window.document.apply(edits.add_layer(window.project, Spec(type="Circle")), "Add")
    window.document.apply(edits.add_layer(window.project, Spec(type="Square")), "Add")
    first, second = (layer.id for layer in window.project.layers)
    for matching, expected in (("smart", "smart"), ("classic", None)):
        window.document.apply(edits.set_morph_matching(window.project, matching), "New morphs")
        window.timeline.add_clip(first, "Transform", 0.0, 1.0, to_layer=second)
        clip = next(c for c in window.project.layer(first).clips if c.kind == "Transform")
        assert clip.params.get("match") == expected
        window.document.apply(edits.remove_clip(window.project, first, clip.id), "Remove")


def test_other_edits_keep_the_projects_choice() -> None:
    project = Project(morph_matching="classic")
    after = edits.add_layer(project, Spec(type="Circle")).project
    assert after.morph_matching == "classic"
    assert edits.set_canvas(after, fps=24).project.morph_matching == "classic"


def test_changing_the_setting_keeps_every_rendered_frame() -> None:
    from manim_studio.core.engine.frame_cache import changed_spans

    project = two_shapes()
    assert changed_spans(project, edits.set_morph_matching(project, "classic").project) == []
