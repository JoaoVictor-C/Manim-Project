"""Pinned labels as edits (ADR 0075): pinning, unpinning, and what deleting, copying and grouping do."""

from __future__ import annotations

import pytest

from manim_studio.core.editing import clipboard, edits
from manim_studio.core.model.schema import Canvas, Keyframe, Layer, Pin, Project, Spec, Transform2D

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=4.0)


def square(layer_id: str = "sq") -> Layer:
    return Layer(id=layer_id, spec=Spec(type="Square", params={"side_length": 2}))


def label(layer_id: str = "lab", **fields) -> Layer:
    return Layer(id=layer_id, spec=Spec(type="Text", params={"text": "A"}), **fields)


def project(*layers: Layer) -> Project:
    return Project(canvas=CANVAS, layers=list(layers))


def pinned() -> Project:
    return edits.pin_label(project(square(), label()), "lab", "sq", "top").project


def test_pinning_sets_the_pin_and_the_offset_and_drops_the_scene_position_keys() -> None:
    keyed = label(
        base=Transform2D(position=(4.0, 2.0)),
        tracks={"position": [Keyframe(t=0, value=(0.0, 0.0)), Keyframe(t=1, value=(1.0, 0.0))]},
    )
    edit = edits.pin_label(project(square(), keyed), "lab", "sq", "right", (0.5, -0.25))
    lab = edit.project.layer("lab")
    assert lab.pin == Pin(target="sq", anchor="right")
    assert lab.base.position == (0.5, -0.25) and "position" not in lab.tracks
    assert edit.kind == "transform" and "lab" in edit.layer_ids


def test_pinning_again_keeps_the_offset_unless_one_is_given() -> None:
    moved = edits.set_property(pinned(), "lab", "position", (0.0, 0.5), 0.0).project
    again = edits.pin_label(moved, "lab", "sq", "bottom", follow_rotation=True).project.layer("lab")
    assert again.pin == Pin(target="sq", anchor="bottom", follow_rotation=True)
    assert again.base.position == (0.0, 0.5)


@pytest.mark.parametrize(
    ("label_id", "target_id", "match"),
    [
        ("lab", "lab", "itself"),
        ("lab", "camera", "camera"),
        ("lab", "join", "Connector"),
        ("sq", "lab", "only a label"),
    ],
)
def test_what_cannot_be_pinned(label_id: str, target_id: str, match: str) -> None:
    connector = Layer(id="join", spec=Spec(type="Connector", params={"source": "sq", "target": "lab"}))
    camera = Layer(id="camera", spec=Spec(type="Camera"))
    scene = project(square(), label(), connector, camera)
    with pytest.raises(edits.EditError, match=match):
        edits.pin_label(scene, label_id, target_id)


def test_pins_never_go_round_in_a_circle() -> None:
    scene = edits.pin_label(project(square(), label(), label("other")), "lab", "other").project
    assert "lab" not in {x.id for x in scene.pin_targets("other")}
    with pytest.raises(edits.EditError, match="circle"):
        edits.pin_label(scene, "other", "lab")
    with pytest.raises(ValueError, match="circle"):
        Project.model_validate(
            {
                **scene.model_dump(by_alias=True),
                "layers": [
                    square().model_dump(by_alias=True),
                    label(pin=Pin(target="other")).model_dump(by_alias=True),
                    label("other", pin=Pin(target="lab")).model_dump(by_alias=True),
                ],
            }
        )


def test_the_project_file_has_no_pin_unless_a_label_is_pinned() -> None:
    plain = project(square(), label())
    assert "pin" not in plain.model_dump_json(by_alias=True)
    scene = pinned()
    data = scene.model_dump(by_alias=True)
    assert data["layers"][1]["pin"] == {"target": "sq", "anchor": "top"}  # follows are left out when off
    assert Project.model_validate_json(scene.model_dump_json(by_alias=True)) == scene


def test_a_pin_to_a_missing_layer_is_refused_when_loading() -> None:
    data = project(label(pin=Pin(target="lab-2")), label("lab-2")).model_dump(by_alias=True)
    data["layers"] = data["layers"][:1]
    with pytest.raises(ValueError, match="missing"):
        Project.model_validate(data)


def test_unpinning_keeps_the_offset_or_puts_it_where_it_is_drawn() -> None:
    scene = pinned()
    assert edits.unpin_label(scene, "lab").project.layer("lab").pin is None
    placed = edits.unpin_label(scene, "lab", (1.0, 2.5)).project.layer("lab")
    assert placed.pin is None and placed.base.position == (1.0, 2.5)
    with pytest.raises(edits.EditError, match="not pinned"):
        edits.unpin_label(project(square(), label()), "lab")


def test_deleting_the_target_unpins_the_label_and_keeps_it() -> None:
    after = edits.remove_layer(pinned(), "sq").project
    assert [x.id for x in after.layers] == ["lab"] and after.layer("lab").pin is None
    assert [x.id for x in edits.remove_layer(pinned(), "lab").project.layers] == ["sq"]


def test_duplicating_the_label_alone_pins_the_copy_to_the_same_target() -> None:
    pasted = clipboard.duplicate_layers(pinned(), ["lab"])
    copy = pasted.edit.project.layer(pasted.selected)
    assert copy.pin is not None and copy.pin.target == "sq"


def test_duplicating_label_and_target_together_pins_the_copy_to_the_copied_target() -> None:
    pasted = clipboard.duplicate_layers(pinned(), ["sq", "lab"])
    scene = pasted.edit.project
    copies = [x for x in scene.layers if x.id not in ("sq", "lab")]
    target = next(x for x in copies if x.spec.type == "Square")
    copied_label = next(x for x in copies if x.spec.type == "Text")
    assert copied_label.pin is not None and copied_label.pin.target == target.id
    assert scene.layer("lab").pin.target == "sq"


def test_pasting_a_label_where_its_target_is_not_unpins_it_and_says_so() -> None:
    data = clipboard.copy_layers(pinned(), ["lab"])
    pasted = clipboard.paste_layers(project(square("other")), data.payload)
    assert pasted.edit.project.layer(pasted.selected).pin is None
    assert any("unpinned" in note for note in pasted.notes)


def test_grouping_the_target_keeps_the_pin_and_ungrouping_its_group_unpins() -> None:
    grouped = edits.group_layers(pinned(), ["sq"]).project
    group = next(x for x in grouped.layers if x.is_group)
    assert grouped.layer("lab").pin.target == "sq"
    on_group = edits.pin_label(grouped, "lab", group.id).project
    assert edits.ungroup(on_group, group.id).project.layer("lab").pin is None


def test_a_pinned_label_cannot_be_grouped() -> None:
    with pytest.raises(edits.EditError, match="unpin it"):
        edits.group_layers(pinned(), ["lab"])
