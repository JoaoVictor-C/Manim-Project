"""Points, areas, rectangles and labels on axes (P3h.1, ADR 0030).

Each object is Manim's own Axes helper applied to the editor's axes and graph;
references to graphs are validated, follow edits and go with deletions.
"""

from __future__ import annotations

import math
import random

import manim as m
import numpy as np
import pytest
from pydantic import ValidationError
from tests.core.test_graphs import AXES, PARABOLA, SIN, assert_renders, manim_axes, manim_plot
from tests.support import CANVAS, FRAMES, assert_frames_equal, render_in_order

from manim_studio.core import adapter, edits
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Clip, Layer, Project, Spec
from manim_studio.core.warm import needs_warm, warm_key


def figure(*objects: Layer, graphs=(("sin", SIN),)) -> Project:
    layers = [Layer(id="axes", spec=AXES)]
    layers += [Layer(id=i, parent_id="axes", spec=s) for i, s in graphs]
    return Project(canvas=CANVAS, layers=[*layers, *objects])


def on_axes(layer_id: str, type_name: str, **params) -> Layer:
    return Layer(id=layer_id, parent_id="axes", spec=Spec(type=type_name, params=params))


def manim_graph(axes: m.Axes, f) -> m.VMobject:
    return manim_plot(axes, f)  # a ParametricFunction: Manim's helpers read its function


# -- each object is Manim's helper -------------------------------------------------------------------


def test_a_point_sits_at_axes_coordinates() -> None:
    axes = manim_axes()
    expected = [axes, manim_graph(axes, math.sin), m.Dot(axes.c2p(2.0, -1.0), radius=0.1)]
    project = figure(on_axes("p", "Point", x=2.0, y=-1.0, radius=0.1))
    assert_renders(Evaluator(project), 0.5, expected)


def test_an_area_under_and_between_graphs() -> None:
    axes = manim_axes()
    sine, parabola = manim_graph(axes, math.sin), manim_graph(axes, lambda x: x**2 / 10 - 1)
    under = figure(on_axes("a", "Area", graph="sin", x_range=[0.5, 3.0]))
    assert_renders(Evaluator(under), 0.5, [axes, sine, axes.get_area(sine, x_range=(0.5, 3.0))])
    between = figure(
        on_axes("a", "Area", graph="sin", bounded_graph="par", x_range=[-2.0, 2.0]),
        graphs=(("sin", SIN), ("par", PARABOLA)),
    )
    expected = [axes, sine, parabola, axes.get_area(sine, x_range=(-2.0, 2.0), bounded_graph=parabola)]
    assert_renders(Evaluator(between), 0.5, expected)


def test_riemann_rectangles() -> None:
    axes = manim_axes()
    sine = manim_graph(axes, math.sin)
    project = figure(
        on_axes("r", "RiemannRectangles", graph="sin", x_range=[0.0, 3.0], dx=0.5, sample="center")
    )
    rects = axes.get_riemann_rectangles(sine, x_range=(0.0, 3.0), dx=0.5, input_sample_type="center")
    assert_renders(Evaluator(project), 0.5, [axes, sine, rects])


@pytest.mark.latex
def test_labels() -> None:
    axes = manim_axes()
    sine = manim_graph(axes, math.sin)
    labels = figure(on_axes("l", "AxisLabels", x_label="t", y_label="v"))
    assert_renders(Evaluator(labels), 0.5, [axes, sine, axes.get_axis_labels(m.MathTex("t"), m.MathTex("v"))])
    named = figure(on_axes("n", "GraphLabel", graph="sin", label=r"\sin x", x=4.9, direction="UR"))
    label = m.MathTex(r"\sin x").next_to(axes.c2p(4.9, math.sin(4.9)), m.UR, buff=m.MED_SMALL_BUFF)
    label.set_color(sine.get_color())  # near the frame's edge, not moved onto the screen
    assert_renders(Evaluator(named), 0.5, [axes, sine, label])


def test_drawing_objects_on_axes_scrubs_exactly() -> None:
    project = figure(
        Layer(
            id="a",
            parent_id="axes",
            spec=Spec(type="Area", params={"graph": "sin", "x_range": [0.0, 3.0]}),
            clips=[Clip(id="c", kind="Create", start=0.0, duration=0.5)],
        ),
        Layer(
            id="r",
            parent_id="axes",
            spec=Spec(type="RiemannRectangles", params={"graph": "sin", "x_range": [-3.0, 0.0]}),
            clips=[Clip(id="d", kind="DrawBorderThenFill", start=0.5, duration=0.5)],
        ),
    )
    expected = render_in_order(project, list(range(len(FRAMES))))
    order = random.Random(2).sample(range(len(FRAMES)), len(FRAMES))
    reference = [expected[i] for i in range(len(FRAMES))]
    assert_frames_equal(reference, render_in_order(project, order), "scrubbed")
    assert_frames_equal(reference, render_in_order(project, order, fresh_each_frame=True), "fresh")


def test_undefined_values_never_reach_an_area() -> None:
    root = Spec(type="Graph", params={"expression": "sqrt(x)"})
    tangent = Spec(type="Graph", params={"expression": "tan(x)"})
    for graph, x_range in ((root, [-2.0, 2.0]), (tangent, [-2.0, 2.0])):
        area = adapter.build_child(
            AXES, Spec(type="Area", params={"graph": "g", "x_range": x_range}), {"g": graph}
        )
        assert np.isfinite(area.points).all()


# -- references -------------------------------------------------------------------------------------------


def test_a_reference_must_name_a_graph_on_the_same_axes() -> None:
    figure(on_axes("a", "Area", graph="sin"))
    with pytest.raises(ValidationError, match="graph must name a graph"):
        figure(on_axes("a", "Area", graph="nothing"))
    with pytest.raises(ValidationError, match="graph must name a graph"):
        figure(on_axes("p", "Point"), on_axes("a", "Area", graph="p"))  # not a graph
    with pytest.raises(ValidationError, match="graph must name a graph"):
        Project(
            canvas=CANVAS,
            layers=[
                Layer(id="axes", spec=AXES),
                Layer(id="other", spec=AXES),
                Layer(id="sin", parent_id="other", spec=SIN),  # a graph on other axes
                on_axes("a", "Area", graph="sin"),
            ],
        )


def test_deleting_a_graph_deletes_what_is_built_from_it() -> None:
    project = figure(
        on_axes("a", "Area", graph="sin"),
        on_axes("r", "RiemannRectangles", graph="sin"),
        on_axes("p", "Point"),
        on_axes("b", "Area", graph="par", bounded_graph="sin"),
        graphs=(("sin", SIN), ("par", PARABOLA)),
    )
    remaining = [layer.id for layer in edits.remove_layer(project, "sin").project.layers]
    assert remaining == ["axes", "par", "p"]


def test_editing_a_graph_rebuilds_its_area() -> None:
    project = figure(on_axes("a", "Area", graph="sin", x_range=[0.0, 3.0]))
    evaluator = Evaluator(project)
    evaluator.frame(0.5)
    edit = edits.update_layer(project, "sin", spec=Spec(type="Graph", params={"expression": "cos(x)"}))
    assert "a" in edit.layer_ids and edit.kind == "spec"
    evaluator.apply(edit)
    axes = manim_axes()
    cosine = manim_graph(axes, math.cos)
    assert_renders(evaluator, 0.5, [axes, cosine, axes.get_area(cosine, x_range=(0.0, 3.0))])


def test_labels_are_warmed_and_are_no_paths() -> None:
    project = figure()
    labelled = figure(on_axes("l", "AxisLabels", x_label="t", y_label="v"))
    keys = needs_warm(project, labelled, set())
    assert keys == {warm_key(Spec(type="MathTex", params={"text": t})) for t in "tv"}
    assert "l" not in [layer.id for layer in labelled.path_layers("x")]
    runner = Layer(
        id="dot",
        spec=Spec(type="Dot"),
        clips=[Clip(id="r", kind="MoveAlongPath", start=0, duration=1, params={"path": "l"})],
    )
    with pytest.raises(ValidationError, match="cannot be its path"):
        figure(on_axes("l", "AxisLabels"), runner)
