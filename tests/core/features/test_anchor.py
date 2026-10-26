"""The anchor point (P2f.1, ADR 0021): the pivot of rotating and scaling, and moving it.

world(p) = A (p - P) + P + position, P = anchor for objects, rest centre + anchor
for parts. Frames are compared with the same Manim methods applied by hand.
"""

from __future__ import annotations

import json
import math

import manim as m
import numpy as np
import pytest
from tests.support import TOLERANCE, max_diff

from manim_studio.core.editing import edits
from manim_studio.core.engine import adapter
from manim_studio.core.engine.evaluator import Evaluator, layer_transform
from manim_studio.core.model.schema import Canvas, Keyframe, Layer, PartKey, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame

CANVAS = Canvas(width_px=320, height_px=180, fps=15, duration=4.0)
LINE = Spec(type="Line", params={"start": (0.0, 0.0), "end": (0.0, -3.0)})  # built centred: (0, ±1.5)
TOP = (0.0, 1.5)


def line(**fields) -> Project:
    return Project(canvas=CANVAS, layers=[Layer(id="line", spec=LINE, **fields)])


def points(evaluator: Evaluator, t: float) -> np.ndarray:
    drawn = [sub for _, mob in evaluator.frame_layers(t) for sub in mob.family_members_with_points()]
    return np.concatenate([sub.points[:, :2] for sub in drawn])


def assert_renders(evaluator: Evaluator, t: float, expected: list[m.Mobject]) -> None:
    camera = make_camera(CANVAS)
    diff = max_diff(render_frame(camera, evaluator.frame(t)), render_frame(camera, expected))
    assert diff <= TOLERANCE, f"t={t}: differs by {diff}"


# -- model and format -----------------------------------------------------------------------


def test_the_anchor_defaults_to_the_centre_and_is_not_written_unless_moved() -> None:
    assert Transform2D().anchor == (0.0, 0.0)
    plain = line()
    assert "anchor" not in plain.model_dump_json(by_alias=True)
    moved = line(base=Transform2D(anchor=TOP))
    data = json.loads(moved.model_dump_json(by_alias=True))
    assert data["layers"][0]["base"]["anchor"] == [0.0, 1.5]
    assert Project.model_validate(data).layers[0].base == moved.layers[0].base


def test_layer_transform_carries_the_base_anchor_into_keyed_frames() -> None:
    layer = line(
        base=Transform2D(anchor=TOP),
        tracks={"rotation": [Keyframe(t=0, value=0.0), Keyframe(t=2, value=90.0)]},
    ).layers[0]
    assert layer_transform(layer, 1.0).anchor == TOP


# -- evaluating -----------------------------------------------------------------------------


def test_an_object_rotates_and_scales_about_its_anchor() -> None:
    project = line(base=Transform2D(anchor=TOP, rotation=40.0, scale=1.5, position=(1.0, -0.5)))
    expected = adapter.build_mobject(LINE)
    pivot = np.array([*TOP, 0.0])
    expected.scale(1.5, about_point=pivot).rotate(math.radians(40.0), about_point=pivot).shift((1.0, -0.5, 0))
    assert_renders(Evaluator(project), 1.0, [expected])


def test_the_world_pivot_stays_put_while_the_object_turns() -> None:
    track = [Keyframe(t=0, value=-30.0), Keyframe(t=1, value=30.0), Keyframe(t=2, value=-30.0)]
    project = line(base=Transform2D(anchor=TOP, position=(0.5, 0.0)), tracks={"rotation": track})
    evaluator = Evaluator(project)
    for t in (0.0, 0.4, 1.0, 1.7):
        top = evaluator.frame_layers(t)[0][1].get_start()[:2]  # the Line's start is its top end
        assert np.allclose(top, (0.5, 1.5), atol=1e-9), t
        pivot, rotation, to_local = evaluator.layer_frame(project.layers[0], t)
        assert np.allclose(pivot, (0.5, 1.5))
        assert rotation == pytest.approx(layer_transform(project.layers[0], t).rotation)
        assert np.allclose(to_local, np.eye(2))


@pytest.mark.latex
def test_a_part_turns_about_its_rest_centre_plus_its_anchor_under_a_turned_object() -> None:
    text = r"a^2 + b^2 = c^2"
    spec = Spec(type="MathTex", params={"text": text})
    b = Layer(
        id="b", parent_id="eq", part=PartKey(tex="b^2"), base=Transform2D(anchor=(0.2, -0.1), rotation=60.0)
    )
    root = Layer(id="eq", spec=spec, base=Transform2D(rotation=30.0, scale=2.0, position=(-1.0, 0.0)))
    project = Project(canvas=CANVAS, layers=[root, b])
    evaluator = Evaluator(project)

    eq = adapter.build_mobject(spec)
    leaves = eq.family_members_with_points()
    glyphs = m.VGroup(leaves[3], leaves[4])  # b^2 (B28)
    centre = glyphs.get_center()
    pivot = centre + np.array([0.2, -0.1, 0.0])
    glyphs.rotate(math.radians(60.0), about_point=pivot)
    eq.scale(2.0, about_point=m.ORIGIN).rotate(math.radians(30.0), about_point=m.ORIGIN).shift((-1.0, 0, 0))
    assert_renders(evaluator, 1.0, [eq])

    world_pivot, rotation, _ = evaluator.layer_frame(b, 1.0)
    a = 2.0 * np.array(
        [
            [math.cos(math.radians(30)), -math.sin(math.radians(30))],
            [math.sin(math.radians(30)), math.cos(math.radians(30))],
        ]
    )
    assert np.allclose(world_pivot, a @ pivot[:2] + (-1.0, 0.0))
    assert rotation == pytest.approx(90.0)


def test_a_code_layer_placeholder_follows_the_anchor() -> None:
    code = Layer(
        id="code",
        spec=Spec(type="Code", params={"code": ""}),
        base=Transform2D(anchor=(2.0, 1.125), rotation=90.0),
    )
    evaluator = Evaluator(Project(canvas=CANVAS, layers=[code]))
    drawn = evaluator.frame_layers(0.5)[0][1]
    # The dashed 4 x 2.25 box turned a quarter about its top-right corner: that corner,
    # now its top-left, stays where it was.
    assert np.allclose(drawn.get_corner(m.UL)[:2], (2.0, 1.125), atol=0.05)
    assert np.allclose(drawn.get_corner(m.DR)[:2], (4.25, -2.875), atol=0.05)


# -- moving the anchor ----------------------------------------------------------------------


def test_moving_the_anchor_keeps_the_drawing_and_moves_the_base_position() -> None:
    project = line(base=Transform2D(rotation=40.0, scale=1.5, position=(1.0, -0.5)))
    before = points(Evaluator(project), 1.0)
    edit = edits.set_anchor(project, "line", TOP, 1.0)
    assert edit.kind == "transform"
    moved = edit.project.layers[0]
    assert moved.base.anchor == TOP
    assert moved.tracks == {}  # never keys anything
    assert np.allclose(points(Evaluator(edit.project), 1.0), before, atol=1e-9)
    assert not edits.anchor_shifts_elsewhere(moved)


def test_moving_the_anchor_shifts_every_position_key_and_stays_exact_at_all_times() -> None:
    track = [Keyframe(t=0, value=(0.0, 0.0)), Keyframe(t=2, value=(4.0, 1.0))]
    project = line(base=Transform2D(rotation=40.0), tracks={"position": track})
    edit = edits.set_anchor(project, "line", TOP, 1.0)
    old, new = Evaluator(project), Evaluator(edit.project)
    for t in (0.0, 0.5, 1.0, 1.9, 3.0):
        assert np.allclose(points(new, t), points(old, t), atol=1e-9), t
    assert [k.t for k in edit.project.layers[0].tracks["position"]] == [0.0, 2.0]


def test_with_rotation_keyed_the_drawing_is_kept_at_the_edit_time_only() -> None:
    track = [Keyframe(t=0, value=0.0), Keyframe(t=2, value=90.0)]
    project = line(tracks={"rotation": track})
    edit = edits.set_anchor(project, "line", TOP, 1.0)
    old, new = Evaluator(project), Evaluator(edit.project)
    assert np.allclose(points(new, 1.0), points(old, 1.0), atol=1e-9)
    assert not np.allclose(points(new, 0.0), points(old, 0.0), atol=1e-3)
    assert edits.anchor_shifts_elsewhere(edit.project.layers[0])
    assert edit.project.layers[0].tracks["rotation"] == track


@pytest.mark.latex
def test_moving_a_parts_anchor_keeps_it_in_place_under_a_turned_object() -> None:
    spec = Spec(type="MathTex", params={"text": r"a^2 + b^2 = c^2"})
    b = Layer(id="b", parent_id="eq", part=PartKey(tex="b^2"), base=Transform2D(rotation=45.0, scale=0.8))
    root = Layer(id="eq", spec=spec, base=Transform2D(rotation=30.0, scale=2.0))
    project = Project(canvas=CANVAS, layers=[root, b])
    before = points(Evaluator(project), 1.0)
    edit = edits.set_anchor(project, "b", (0.3, 0.2), 1.0)
    assert np.allclose(points(Evaluator(edit.project), 1.0), before, atol=1e-9)


def test_set_anchor_refuses_an_unknown_layer() -> None:
    with pytest.raises(edits.EditError):
        edits.set_anchor(line(), "nope", TOP, 0.0)
