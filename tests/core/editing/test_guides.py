"""Layout guides (ADR 0074): edits, the file format, and no effect on any frame."""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from manim_studio.core.editing import edits
from manim_studio.core.engine import frame_cache
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.engine.python_export import to_python
from manim_studio.core.model.schema import Canvas, Guide, Layer, Marker, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame


def scene() -> Project:
    return Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[
            Layer(
                id="a",
                spec=Spec(type="Square", style={"fill": "#3b82f6", "fill_opacity": 0.8}),
                base=Transform2D(position=(1.0, 0.5)),
            )
        ],
    )


def test_add_move_and_remove_a_guide() -> None:
    project = edits.add_guide(scene(), "x", 1.5, "column").project
    (guide,) = project.guides
    assert (guide.axis, guide.position, guide.name) == ("x", 1.5, "column")
    moved = edits.move_guide(project, guide.id, -2.0).project
    assert moved.guides[0].position == -2.0 and moved.guides[0].name == "column"
    renamed = edits.move_guide(moved, guide.id, -2.0, "edge").project
    assert renamed.guides[0].name == "edge"
    assert edits.remove_guide(renamed, guide.id).project.guides == []
    with pytest.raises(edits.EditError):
        edits.remove_guide(renamed, "nope")


def test_a_guide_is_not_doubled_and_a_bad_axis_is_refused() -> None:
    project = edits.add_guide(scene(), "y", 0.0).project
    with pytest.raises(edits.EditError):
        edits.add_guide(project, "y", 0.0)
    with pytest.raises(edits.EditError):
        edits.add_guide(project, "z", 1.0)
    other = edits.add_guide(project, "x", 0.0).project  # the other axis is another guide
    with pytest.raises(edits.EditError):
        edits.move_guide(edits.add_guide(other, "x", 1.0).project, other.guides[1].id, 1.0)


def test_margins_add_four_edges_and_the_centre_and_thirds_divide_in_three() -> None:
    project = scene()
    half_w, half_h = project.canvas.frame_width / 2, project.canvas.frame_height / 2
    margins = edits.guides_from_margins(project, 0.5).project
    got = sorted((g.axis, round(g.position, 6)) for g in margins.guides)
    want = [
        ("x", round(-half_w + 0.5, 6)),
        ("x", 0.0),
        ("x", round(half_w - 0.5, 6)),
        ("y", round(-half_h + 0.5, 6)),
        ("y", 0.0),
        ("y", round(half_h - 0.5, 6)),
    ]
    assert got == want
    assert len({g.id for g in margins.guides}) == 6
    with pytest.raises(edits.EditError):
        edits.guides_from_margins(project, 0.0)
    with pytest.raises(edits.EditError):
        edits.guides_for_centre(margins)  # both centre guides are already there
    thirds = edits.guides_for_thirds(margins).project
    assert len(thirds.guides) == 10
    xs = sorted(g.position for g in thirds.guides if g.name.endswith("third") and g.axis == "x")
    assert xs == pytest.approx([-project.canvas.frame_width / 6, project.canvas.frame_width / 6])


def test_guides_round_trip_and_are_left_out_of_a_file_without_them() -> None:
    assert "guides" not in scene().model_dump(by_alias=True)
    project = edits.add_guide(scene(), "x", 1.25).project
    project = edits.add_guide(project, "y", -1.0, "floor").project
    data = project.model_dump(by_alias=True)
    assert data["guides"][0] == {"id": project.guides[0].id, "axis": "x", "position": 1.25}
    assert Project.model_validate_json(project.model_dump_json(by_alias=True)) == project


def test_guide_ids_are_unique_among_every_id() -> None:
    with pytest.raises(ValidationError):
        Project(
            layers=[Layer(id="g", spec=Spec(type="Square"))], guides=[Guide(id="g", axis="x", position=0)]
        )
    with pytest.raises(ValidationError):
        Project(markers=[Marker(id="g", t=0)], guides=[Guide(id="g", axis="y", position=0)])
    with pytest.raises(ValidationError):
        Guide(id="g", axis="z", position=0)
    project = edits.add_guide(scene(), "x", 0.0).project
    assert edits.new_layer_id(project, "guide") != project.guides[0].id


def test_guides_change_no_frame_and_no_cached_span() -> None:
    plain = scene()
    guided = edits.guides_for_thirds(edits.guides_from_margins(plain, 0.5).project).project
    assert frame_cache.changed_spans(plain, guided) == []
    assert frame_cache.changed_layers(plain, guided) == set()
    for t in (0.0, 1.0):
        before = render_frame(make_camera(plain.canvas), Evaluator(plain).frame(t))
        after = render_frame(make_camera(guided.canvas), Evaluator(guided).frame(t))
        assert np.array_equal(before, after)
    assert to_python(plain, "Guides").code == to_python(guided, "Guides").code
