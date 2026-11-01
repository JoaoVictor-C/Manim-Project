"""The camera is always the first row of the Layers panel and the Timeline (ADR 0086): the last layer."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from manim_studio.core.editing import clipboard, edits
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec, camera_first
from manim_studio.render.cairo_export import make_camera, render_frame

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"
CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=1.0)
SQUARE = Spec(type="Square", params={"side_length": 1.0}, style={"fill": "#3b82f6", "fill_opacity": 1})


def layer(layer_id: str, spec: Spec = SQUARE) -> Layer:
    return Layer(id=layer_id, spec=spec)


def camera(layer_id: str = "cam") -> Layer:
    return Layer(id=layer_id, name="Camera", spec=Spec(type="Camera"))


def project(*layers: Layer) -> Project:
    return Project(canvas=CANVAS, layers=list(layers))


def ids(p: Project) -> list[str]:
    return [x.id for x in p.layers]


def with_camera() -> Project:
    return project(layer("a"), layer("b"), camera())


def test_the_camera_is_the_front_layer_whatever_the_order_given() -> None:
    assert ids(project(camera(), layer("a"), layer("b"))) == ["a", "b", "cam"]
    assert ids(project(layer("a"), camera(), layer("b"))) == ["a", "b", "cam"]
    assert ids(project(layer("a"), layer("b"), camera())) == ["a", "b", "cam"]


def test_a_project_that_complies_is_left_as_it_is() -> None:
    layers = [layer("a"), layer("b"), camera()]
    assert camera_first(layers) is layers
    p = project(*layers)
    assert p.layers == layers
    assert Project.model_validate_json(p.model_dump_json(by_alias=True)) == p
    assert camera_first([]) == []  # no camera, no change
    plain = [layer("a"), layer("b")]
    assert camera_first(plain) is plain


def test_loading_a_file_with_the_camera_in_the_middle_puts_it_first() -> None:
    data = json.loads((EXAMPLES / "camera.json").read_text(encoding="utf-8"))
    layers = data["layers"]
    cam = next(x for x in layers if x["spec"]["type"] == "Camera")
    assert layers[-1] is cam  # as the committed example is
    loaded = Project.model_validate(data)
    assert ids(loaded) == [x["id"] for x in layers]  # untouched: it complied
    layers.remove(cam)
    layers.insert(4, cam)
    moved = Project.model_validate_json(json.dumps(data))
    assert moved.layers[-1].is_camera
    assert ids(moved) == ids(loaded)  # and the others keep their order
    assert moved == loaded


def test_moving_the_camera_does_not_change_a_frame() -> None:
    """The camera draws nothing: every frame of the tour is the same with it at the back or in front.
    ``model_copy`` skips the project's validator, which would put the camera last again."""
    data = json.loads((EXAMPLES / "camera.json").read_text(encoding="utf-8"))
    data["canvas"].update(width_px=160, height_px=90)
    as_saved = Project.model_validate(data)
    assert as_saved.layers[-1].is_camera
    others = [x for x in as_saved.layers if not x.is_camera]
    at_back = as_saved.model_copy(update={"layers": [as_saved.layers[-1], *others]})
    assert at_back.layers[0].is_camera
    camera_view = make_camera(as_saved.canvas)
    for t in (0.0, 1.5, 4.0, 5.5, 7.5):
        a = render_frame(camera_view, Evaluator(as_saved).frame(t))
        b = render_frame(camera_view, Evaluator(at_back).frame(t))
        assert np.array_equal(a, b)
    assert Evaluator(as_saved).camera_moved(3.0)  # and the camera does move the view


def test_a_new_layer_goes_on_top_under_the_camera() -> None:
    edit = edits.add_layer(with_camera(), Spec(type="Circle"))
    assert ids(edit.project) == ["a", "b", "circle-1", "cam"]
    middle = edits.add_layer(with_camera(), Spec(type="Circle"), index=1)
    assert ids(middle.project) == ["a", "circle-1", "b", "cam"]
    above = edits.add_layer(with_camera(), Spec(type="Circle"), index=99)  # past the end: still under it
    assert ids(above.project) == ["a", "b", "circle-1", "cam"]


def test_adding_the_camera_to_a_project_puts_it_last() -> None:
    edit = edits.add_camera(project(layer("a"), layer("b")))
    assert ids(edit.project) == ["a", "b", "camera-1"]
    assert edit.project.layers[-1].is_camera


def test_the_camera_cannot_be_moved() -> None:
    p = with_camera()
    for index in (0, 1, 2, 99):
        with pytest.raises(edits.EditError, match="always stays first"):
            edits.move_layer(p, "cam", index)


def test_no_layer_can_be_moved_above_the_camera() -> None:
    p = with_camera()
    edit = edits.move_layer(p, "a", 99)
    assert ids(edit.project) == ["b", "a", "cam"]
    edit = edits.move_layer(p, "b", 2)  # the index of the camera itself
    assert ids(edit.project) == ["a", "b", "cam"]
    assert edit.project == p
    edit = edits.move_layer(p, "b", 0)
    assert ids(edit.project) == ["b", "a", "cam"]


def test_the_camera_stays_first_whatever_the_parts_and_groups() -> None:
    tex = Spec(type="MathTex", params={"tex": "ab"})
    p = project(layer("a"), layer("t", tex), layer("b"), camera())
    moved = edits.move_layer(p, "t", 99)
    assert ids(moved.project) == ["a", "b", "t", "cam"]
    grouped = edits.group_layers(with_camera(), ["a", "b"])
    assert grouped.project.layers[-1].is_camera
    group = next(x for x in grouped.project.layers if x.is_group)
    freed = edits.ungroup(grouped.project, group.id)
    assert ids(freed.project) == ["a", "b", "cam"]


def test_the_camera_is_not_put_in_a_group() -> None:
    with pytest.raises(edits.EditError, match="always stays first"):
        edits.group_layers(with_camera(), ["a", "cam"])
    with pytest.raises(edits.EditError):
        edits.group_layers(with_camera(), ["cam"])


def test_deleting_other_layers_keeps_it_last_and_deleting_it_leaves_the_rest() -> None:
    p = with_camera()
    assert ids(edits.remove_layer(p, "a").project) == ["b", "cam"]
    assert ids(edits.remove_layer(p, "cam").project) == ["a", "b"]
    assert ids(edits.remove_layers(p, ["a", "cam"]).project) == ["b"]


def test_duplicating_and_pasting_keep_the_camera_first() -> None:
    p = with_camera()
    duplicated = clipboard.duplicate_layers(p, ["b"])
    assert duplicated.edit.project.layers[-1].is_camera
    assert ids(duplicated.edit.project)[:-1].count("b") == 1 and len(duplicated.edit.project.layers) == 4
    data = clipboard.copy_layers(p, ["a"])
    onto_camera = clipboard.paste_layers(p, data.payload, above="cam")  # "above" the camera is below it
    assert onto_camera.edit.project.layers[-1].is_camera and len(onto_camera.edit.project.layers) == 4
    on_top = clipboard.paste_layers(p, data.payload)
    assert on_top.edit.project.layers[-1].is_camera
    without = project(layer("a"))
    camera_data = clipboard.copy_layers(p, ["cam"])
    pasted = clipboard.paste_layers(without, camera_data.payload)
    assert pasted.edit.project.layers[-1].is_camera


def test_undo_and_redo_snapshots_keep_it_first() -> None:
    p = with_camera()
    edit = edits.add_layer(p, Spec(type="Circle"))
    restored = edits.restore_project(edit.project, p)
    assert restored.project == p and restored.project.layers[-1].is_camera
    again = edits.restore_project(p, edit.project)
    assert ids(again.project) == ["a", "b", "circle-1", "cam"]


def test_a_second_camera_is_still_refused() -> None:
    with pytest.raises(edits.EditError):
        edits.add_camera(with_camera())
    with pytest.raises(ValidationError):
        project(camera("c1"), camera("c2"))


def test_edits_of_other_kinds_keep_the_order() -> None:
    p = with_camera()
    renamed = edits.update_layer(p, "a", name="Alpha")
    assert ids(renamed.project) == ["a", "b", "cam"]
    keyed = edits.set_property(p, "cam", "position", (1.0, 0.0), 0.0)
    assert ids(keyed.project) == ["a", "b", "cam"]
    moved = edits.set_property(p, "a", "position", (1.0, 0.0), 0.0)
    assert ids(moved.project) == ["a", "b", "cam"]
