"""Curved position paths (P3d.1, ADR 0026): tangents on keys, arc-length walking, edits.

A curved segment is the cubic Bezier p0, p0 + out, p1 + in, p1, walked so the
key's eased time is the fraction of its length travelled; straight segments
keep the exact linear formula.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from pydantic import ValidationError
from tests.support import CANVAS

from manim_studio.core.editing import edits
from manim_studio.core.engine.evaluator import Evaluator, layer_transform
from manim_studio.core.model import motion_paths
from manim_studio.core.model.schema import Easing, Keyframe, Layer, Project, Spec

LINEAR = Easing(name="linear")
P0, P1 = (-4.0, -1.0), (3.0, 1.5)
OUT, IN = (4.0, 5.0), (-1.0, 3.0)  # a strong S bend


def keyed(*keys: Keyframe) -> Layer:
    return Layer(id="dot", spec=Spec(type="Dot"), tracks={"position": list(keys)})


def curve() -> Layer:
    return keyed(
        Keyframe(t=0, value=P0, ease=LINEAR, out_tangent=OUT), Keyframe(t=2, value=P1, in_tangent=IN)
    )


def fine_reference(u: float) -> np.ndarray:
    """Arc-length walking on a 20001-sample table: the ground truth for the cached one."""
    points = motion_paths.controls(P0, OUT, IN, P1)
    us = np.linspace(0, 1, 20001)
    pts = motion_paths.bezier(points, us)
    lengths = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    return motion_paths.bezier(points, np.interp(u * lengths[-1], lengths, us))


def position(layer: Layer, t: float) -> np.ndarray:
    return np.array(layer_transform(layer, t).position)


# -- model --------------------------------------------------------------------------------------------


def test_keys_without_tangents_save_and_move_as_before() -> None:
    straight = keyed(Keyframe(t=0, value=P0, ease=LINEAR), Keyframe(t=2, value=P1))
    assert "tangent" not in straight.model_dump_json()
    for t in (0.0, 0.5, 1.3, 2.0):  # exactly the linear formula, not the table
        u = t / 2
        assert position(straight, t).tolist() == [P0[0] + (P1[0] - P0[0]) * u, P0[1] + (P1[1] - P0[1]) * u]
    saved = json.loads(curve().model_dump_json())
    assert saved["tracks"]["position"][0]["out_tangent"] == list(OUT)
    assert "in_tangent" not in saved["tracks"]["position"][0]


def test_only_position_keys_take_tangents() -> None:
    with pytest.raises(ValidationError, match="only position keys"):
        Layer(id="a", spec=Spec(type="Dot"), tracks={"scale": [Keyframe(t=0, value=1.0, out_tangent=(1, 0))]})


# -- evaluation ------------------------------------------------------------------------------------------


def test_a_curved_segment_is_walked_by_arc_length() -> None:
    layer = curve()
    for t in (0.0, 0.3, 1.0, 1.7, 2.0):
        assert position(layer, t) == pytest.approx(fine_reference(t / 2), abs=1e-3), t
    steps = [np.linalg.norm(position(layer, (i + 1) / 30) - position(layer, i / 30)) for i in range(60)]
    assert max(steps) / min(steps) < 1.01  # even speed with a linear ease (B39: raw walking is 3.4x)


def test_an_overshoot_continues_along_the_end_tangent() -> None:
    end = motion_paths.point_at(P0, OUT, IN, P1, 1.2)
    total = motion_paths.length(motion_paths.controls(P0, OUT, IN, P1))
    direction = np.array([1.0, -3.0]) / np.linalg.norm([1.0, -3.0])  # p1 - (p1 + in)
    assert end == pytest.approx(np.array(P1) + direction * 0.2 * total)


def test_the_evaluator_moves_the_object_along_the_curve() -> None:
    evaluator = Evaluator(Project(canvas=CANVAS, layers=[curve()]))
    drawn = evaluator.frame_layers(0.5)[0][1]
    assert drawn.get_center()[:2] == pytest.approx(fine_reference(0.25), abs=1e-3)


# -- edits -------------------------------------------------------------------------------------------------


def project() -> Project:
    return Project(canvas=CANVAS, layers=[curve()])


def test_edits_keep_tangents() -> None:
    p = edits.set_key(project(), "dot", "position", 0.0, (-3.0, -1.0)).project
    assert p.layer("dot").tracks["position"][0].out_tangent == OUT
    p = edits.retime_keys(p, "dot", 2.0, 1.5).project
    assert p.layer("dot").tracks["position"][-1].in_tangent == IN
    p = edits.set_key_ease(p, "dot", 0.0, Easing(name="smooth")).project
    assert p.layer("dot").tracks["position"][0].out_tangent == OUT


def test_a_new_key_inside_a_curve_keeps_its_shape() -> None:
    dense = motion_paths.bezier(motion_paths.controls(P0, OUT, IN, P1), np.linspace(0, 1, 20001))
    mid = position(curve(), 1.0)
    split = edits.set_key(project(), "dot", "position", 1.0, tuple(mid)).project.layer("dot")
    keys = split.tracks["position"]
    assert [k.t for k in keys] == [0.0, 1.0, 2.0] and keys[1].in_tangent and keys[1].out_tangent
    for t in np.linspace(0, 2, 201):  # every new position lies on the old curve
        assert np.linalg.norm(dense - position(split, t), axis=1).min() < 2e-3, t


def test_tangent_edits_and_smoothing() -> None:
    three = keyed(
        Keyframe(t=0, value=(0.0, 0.0)), Keyframe(t=1, value=(2.0, 1.0)), Keyframe(t=2, value=(4.0, 0.0))
    )
    p = Project(canvas=CANVAS, layers=[three])
    edit = edits.smooth_key(p, "dot", 1.0)
    assert edit.kind == "transform"
    middle = edit.project.layer("dot").tracks["position"][1]
    assert np.allclose(middle.out_tangent, (4 / 6, 0.0)) and np.allclose(middle.in_tangent, (-4 / 6, 0.0))
    first = edits.smooth_key(p, "dot", 0.0).project.layer("dot").tracks["position"][0]
    assert first.in_tangent is None and np.allclose(first.out_tangent, (2 / 3, 1 / 3))
    straight = edits.set_tangents(edit.project, "dot", 1.0, None, None).project.layer("dot")
    assert not straight.tracks["position"][1].curved
    with pytest.raises(edits.EditError):
        edits.set_tangents(p, "dot", 0.5, None, None)
