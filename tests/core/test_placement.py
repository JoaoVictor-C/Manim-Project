"""Where a new object goes (GP): not on top of the others."""

from __future__ import annotations

import numpy as np
import pytest

from manim_studio.core import placement
from manim_studio.core.schema import Canvas, Layer, Project, Spec, Transform2D

FRAME = (np.array([-7.0, -4.0]), np.array([7.0, 4.0]))


def box(x0, y0, x1, y1):
    return np.array([x0, y0]), np.array([x1, y1])


def test_the_first_object_goes_to_the_centre() -> None:
    assert placement.place([], (2, 1), FRAME) == (0.0, 0.0)
    assert placement.place([box(3, 2, 5, 3)], (2, 1), FRAME) == (0.0, 0.0)  # the centre is free


def test_the_next_goes_below_then_above_then_beside() -> None:
    title = box(-3, -0.3, 3, 0.3)
    assert placement.place([title], (2, 1), FRAME) == pytest.approx((0.0, -0.3 - 0.3 - 0.5))
    low = box(-3, -4, 3, 0.3)  # nothing fits below
    assert placement.place([low], (2, 1), FRAME) == pytest.approx((0.0, 0.3 + 0.3 + 0.5))
    tall = box(-1, -4, 1, 4)  # the whole height taken: beside it
    assert placement.place([tall], (2, 1), FRAME) == pytest.approx((1 + 0.3 + 1, 0.0))
    right = box(-1, -4, 7, 4)
    assert placement.place([right], (2, 1), FRAME) == pytest.approx((-1 - 0.3 - 1, 0.0))
    full = box(-7, -4, 7, 4)
    assert placement.place([full], (2, 1), FRAME) == (0.0, 0.0)  # nowhere: the centre, as before


def test_a_typical_scene_lays_out_without_overlaps() -> None:
    project = Project(canvas=Canvas(width_px=640, height_px=360))
    from manim_studio.core import edits

    for spec in (
        Spec(type="Text", params={"text": "The Pythagorean theorem"}),
        Spec(type="Circle"),
        Spec(type="Square"),
    ):
        where = placement.position_for(project, spec, 0.0)
        edit = edits.add_layer(project, spec)
        new = edit.project.layers[-1]
        project = edits.update_layer(
            edit.project, new.id, base=new.base.model_copy(update={"position": where})
        ).project
    boxes = placement.occupied(project, 0.0)
    assert len(boxes) == 3
    for i, a in enumerate(boxes):
        assert (a[0] >= np.array([-7.12, -4.0]) - 1e-6).all() and (a[1] <= np.array([7.12, 4.0]) + 1e-6).all()
        for b in boxes[i + 1 :]:
            assert not placement._overlaps(a, b)


def test_boxes_follow_the_layer_transform_and_skip_what_has_no_box() -> None:
    project = Project(
        layers=[
            Layer(
                id="sq",
                spec=Spec(type="Square", params={"side_length": 2.0}),
                base=Transform2D(position=(1.0, 2.0), scale=2.0),
            ),
            Layer(id="dot", spec=Spec(type="Dot"), base=Transform2D(position=(-5.0, 0.0))),
            Layer(id="link", spec=Spec(type="Connector", params={"source": "sq", "target": "dot"})),
        ]
    )
    (low, high), _dot = placement.occupied(project, 0.0)  # the connector has no box of its own
    assert low == pytest.approx((-1.0, 0.0)) and high == pytest.approx((3.0, 4.0))
    assert placement.drawn_box(Spec(type="Code", params={"code": "x"})) is None
    assert placement.position_for(project, Spec(type="Code", params={"code": "x"}), 0.0) == (0.0, 0.0)


def test_layers_are_labelled_by_their_name_their_words_or_their_id() -> None:
    from manim_studio.core.schema import LABEL_CHARS, PartKey

    text = Layer(id="text-1", spec=Spec(type="Text", params={"text": "The  Pythagorean\ntheorem"}))
    assert text.label == "The Pythagorean theorem"  # words, one line
    long = Layer(id="m", spec=Spec(type="MathTex", params={"text": "x" * 50}))
    assert len(long.label) == LABEL_CHARS and long.label.endswith("…")
    assert Layer(id="sq", spec=Spec(type="Square")).label == "sq"
    assert Layer(id="sq", name="Box", spec=Spec(type="Square")).label == "Box"  # a name wins
    assert Layer(id="t", spec=Spec(type="Text", params={"text": "  "})).label == "t"
    assert Layer(id="p", parent_id="m", part=PartKey(tex="b^2")).label == "b^2"


def test_an_object_bigger_than_the_frame_in_an_empty_scene_stays_at_the_centre() -> None:
    assert placement.place([], (30, 20), FRAME) == (0.0, 0.0)  # no boxes to measure: no error
