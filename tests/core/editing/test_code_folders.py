from __future__ import annotations

import pytest

from manim_studio.core.editing import edits
from manim_studio.core.model.schema import Layer, Project, Spec


def project() -> Project:
    return Project(
        layers=[
            Layer(id="code", spec=Spec(type="Code", params={"code": "class A(Scene): pass"})),
            Layer(id="python", spec=Spec(type="Python", params={"code": "def build(p): return Circle()"})),
            Layer(id="shape", spec=Spec(type="Square")),
        ]
    )


def test_folder_edits_keep_empty_folders_and_code_assignments_serializable() -> None:
    original = project()
    current = edits.add_code_folder(original, "Drafts").project
    current = edits.move_code_layer_to_folder(current, "code", "Drafts").project
    current = edits.move_code_layer_to_folder(current, "python", "Drafts").project
    current = edits.rename_code_folder(current, "Drafts", "Scenes").project

    restored = Project.model_validate_json(current.model_dump_json(by_alias=True))
    assert restored.code_folders == {"Scenes": ["code", "python"]}
    assert edits.move_code_layer_to_folder(restored, "code").project.code_folders == {
        "Scenes": ["python"]
    }

    emptied = edits.delete_code_folder(restored, "Scenes").project
    assert emptied.code_folders == {}
    assert [layer.id for layer in emptied.layers] == ["code", "python", "shape"]


@pytest.mark.parametrize("name", ["", " / ", "a/b", "a\\b", "x" * 65])
def test_folder_names_must_be_nonempty_short_and_flat(name: str) -> None:
    with pytest.raises(edits.EditError):
        edits.add_code_folder(project(), name)


def test_folder_names_are_unique_and_only_code_layers_can_be_moved() -> None:
    with pytest.raises(edits.EditError, match="already exists"):
        edits.add_code_folder(edits.add_code_folder(project(), "Drafts").project, "drafts")
    with pytest.raises(edits.EditError, match="not a code layer"):
        edits.move_code_layer_to_folder(project(), "shape", "Drafts")
