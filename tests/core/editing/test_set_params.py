"""edits.set_params: a canvas handle's edit (P6c.1, ADR 0043)."""

from __future__ import annotations

import pytest

from manim_studio.core.editing import edits
from manim_studio.core.model.schema import Keyframe, Layer, Project, Spec, Transform2D


def project() -> Project:
    return Project(
        layers=[
            Layer(
                id="line",
                spec=Spec(type="Line", params={"start": [0, 0], "end": [2, 0]}, style={"stroke": "#ff0000"}),
                base=Transform2D(position=(1.0, 1.0), rotation=30.0),
            ),
            Layer(
                id="moving",
                spec=Spec(type="Circle", params={"radius": 1.0}),
                tracks={
                    "position": [
                        Keyframe(t=0, value=(0.0, 0.0), out_tangent=(1.0, 0.0)),
                        Keyframe(t=1, value=(4.0, 0.0)),
                    ]
                },
            ),
        ]
    )


def test_set_params_changes_only_the_named_params() -> None:
    edit = edits.set_params(project(), "line", {"end": (3.0, 1.0)})
    layer = edit.project.layer("line")
    assert layer.spec.params["start"] == [0, 0]
    assert tuple(layer.spec.params["end"]) == (3.0, 1.0)
    assert layer.spec.style == {"stroke": "#ff0000"}
    assert layer.base == project().layer("line").base  # no shift: nothing else moves
    assert edit.kind == "spec" and edit.layer_ids == frozenset({"line"})


def test_a_shift_moves_the_base_and_every_position_key_rigidly() -> None:
    edit = edits.set_params(project(), "moving", {"radius": 2.0}, shift=(0.5, -1.0))
    layer = edit.project.layer("moving")
    assert layer.spec.params["radius"] == 2.0
    assert layer.base.position == pytest.approx((0.5, -1.0))
    assert [k.value for k in layer.tracks["position"]] == [(0.5, -1.0), (4.5, -1.0)]
    assert layer.tracks["position"][0].out_tangent == (1.0, 0.0)  # tangents are relative: unchanged
    assert len(layer.tracks["position"]) == 2  # no keys are made


def test_set_params_refuses_an_unknown_layer() -> None:
    with pytest.raises(edits.EditError):
        edits.set_params(project(), "nope", {"radius": 1.0})


def test_remove_layers_deletes_several_in_one_edit() -> None:
    edit = edits.remove_layers(project(), ["line", "moving"])
    assert edit.project.layers == []
    assert edits.remove_layers(project(), ["line"]).project == edits.remove_layer(project(), "line").project
    with pytest.raises(edits.EditError):
        edits.remove_layers(project(), [])
    with pytest.raises(edits.EditError):
        edits.remove_layers(project(), ["line", "nope"])
