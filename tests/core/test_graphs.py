"""Axes and function graphs (P3b.1-P3b.2, ADR 0024).

Graphs are child objects of their axes: built against them, carried by them,
locked to them. Frames are compared with the same Manim calls made by hand.
"""

from __future__ import annotations

import math
import random

import manim as m
import numpy as np
import pytest
from pydantic import ValidationError
from tests.support import CANVAS, FRAMES, TOLERANCE, assert_frames_equal, max_diff, render_in_order

from manim_studio.core import adapter, edits, expressions
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import (
    CLIP_KIND_INFO,
    Clip,
    Keyframe,
    Layer,
    Project,
    Spec,
    Transform2D,
    keyable_props,
)
from manim_studio.core.warm import warm_key
from manim_studio.render.cairo_export import make_camera, render_frame

AXES = Spec(type="Axes")
SIN = Spec(type="Graph", params={"expression": "sin(x)"})
PARABOLA = Spec(type="Graph", params={"expression": "x**2/10 - 1"})


def chart(*graphs: Layer, axes_fields=None) -> Project:
    axes = Layer(id="axes", spec=AXES, **(axes_fields or {}))
    return Project(canvas=CANVAS, layers=[axes, *graphs])


def graph(layer_id: str = "g", spec: Spec = SIN, **fields) -> Layer:
    return Layer(id=layer_id, parent_id="axes", spec=spec, **fields)


def manim_axes() -> m.Axes:
    axes = m.Axes(x_range=[-5, 5, 1], y_range=[-3, 3, 1], x_length=10, y_length=6)
    axes.move_to(m.ORIGIN)
    return axes


def manim_plot(axes: m.Axes, f) -> m.VMobject:
    xs = np.linspace(-5, 5, adapter.GRAPH_SAMPLES)
    curve = axes.plot(f, x_range=[xs[0], xs[-1], xs[1] - xs[0]], use_smoothing=False)
    return curve.set_stroke(m.YELLOW, width=4)


def assert_renders(evaluator: Evaluator, t: float, expected: list[m.Mobject]) -> None:
    camera = make_camera(CANVAS)
    diff = max_diff(render_frame(camera, evaluator.frame(t)), render_frame(camera, expected))
    assert diff <= TOLERANCE, f"t={t}: differs by {diff}"


# -- expressions -----------------------------------------------------------------------------------


def test_expressions_compute_like_numpy() -> None:
    xs = np.linspace(-3, 3, 101)
    with np.errstate(all="ignore"):
        cases = {
            "sin(x)": np.sin(xs),
            "x**2/10 - 1": xs**2 / 10 - 1,
            "exp(-x**2)*cos(3*x)": np.exp(-(xs**2)) * np.cos(3 * xs),
            "-sqrt(abs(x)) + pi*e": -np.sqrt(np.abs(xs)) + math.pi * math.e,
            "2": np.full_like(xs, 2.0),
        }
    for text, expected in cases.items():
        assert np.allclose(expressions.evaluate(text, xs), expected, equal_nan=True), text


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os').system('x')",
        "x.__class__",
        "open('f')",
        "[x for x in (1,)]",
        "lambda: 1",
        "x if x else 1",
        "sin(x, 2)",
        "y + 1",
        "",
        "x" * 600,
        "(",
    ],
)
def test_anything_outside_the_whitelist_is_refused(text: str) -> None:
    assert expressions.check(text) is not None
    with pytest.raises(expressions.ExpressionError):
        expressions.compile_expression(text)


# -- the model ---------------------------------------------------------------------------------------


def test_a_graph_lives_on_axes_only() -> None:
    chart(graph())  # fine
    with pytest.raises(ValidationError, match="a Graph needs a parent"):
        Project(layers=[Layer(id="g", spec=SIN)])
    circle = Layer(id="c", spec=Spec(type="Circle"))
    with pytest.raises(ValidationError, match="cannot be a child of Circle"):
        Project(layers=[circle, Layer(id="g", parent_id="c", spec=SIN)])
    with pytest.raises(ValidationError, match="graph expression"):
        graph(spec=Spec(type="Graph", params={"expression": "import os"}))


def test_a_graph_is_locked_to_its_axes_but_can_fade() -> None:
    with pytest.raises(ValidationError, match="only its opacity can change"):
        graph(base=Transform2D(position=(1.0, 0.0)))
    with pytest.raises(ValidationError, match="only its opacity can change"):
        graph(tracks={"rotation": [Keyframe(t=0, value=0.0)]})
    faded = graph(tracks={"opacity": [Keyframe(t=0, value=1.0), Keyframe(t=1, value=0.2)]})
    assert keyable_props(faded) == ("opacity",)
    assert keyable_props(Layer(id="axes", spec=AXES)) == ("position", "scale", "rotation", "opacity")


def test_part_rules_do_not_apply_to_graphs() -> None:
    write_axes = {"clips": [Clip(id="c", kind="Create", start=0, duration=1)]}
    create = Clip(id="c", kind="Create", start=0.5, duration=1)  # overlaps the axes' clip
    morph = Clip(id="m", kind="Transform", start=2, duration=1, to_layer="p")
    chart(graph(clips=[create, morph]), graph("p", PARABOLA), axes_fields=write_axes)


def test_add_child_puts_the_graph_after_its_family_and_moving_it_alone_is_refused() -> None:
    project = Project(layers=[Layer(id="axes", spec=AXES), Layer(id="dot", spec=Spec(type="Dot"))])
    project = edits.add_child(project, "axes", SIN, layer_id="g").project
    assert [layer.id for layer in project.layers] == ["axes", "g", "dot"]
    with pytest.raises(edits.EditError, match="drawn with their object"):
        edits.move_layer(project, "g", 0)
    assert [layer.id for layer in edits.remove_layer(project, "axes").project.layers] == ["dot"]


def test_numbered_axes_wait_for_the_build_worker() -> None:
    assert warm_key(AXES) is None
    assert warm_key(Spec(type="Axes", params={"numbers": "yes"})) is not None


# -- building ---------------------------------------------------------------------------------------


def test_a_graph_is_manims_plot_on_the_same_axes() -> None:
    built = adapter.build_child(AXES, SIN)
    expected = manim_plot(manim_axes(), math.sin)
    assert np.allclose(built.points, expected.points)


def test_bad_values_split_the_curve_instead_of_spiking() -> None:
    for text, pieces in (("tan(x)", 4), ("1/x", 2)):
        curve = adapter.build_child(AXES, Spec(type="Graph", params={"expression": text}))
        assert len(curve.get_subpaths()) >= pieces, text
        assert np.isfinite(curve.points).all()
        assert np.abs(curve.points[:, 1]).max() <= 6 + 1e-6  # y range +-3, margin 50 % of its 6 units
    log = adapter.build_child(AXES, Spec(type="Graph", params={"expression": "log(x)"}))
    assert log.points[:, 0].min() > 0  # only where it is defined
    nothing = adapter.build_child(AXES, Spec(type="Graph", params={"expression": "sqrt(-1-x**2)"}))
    assert not nothing.has_points()


def test_a_graph_range_and_style() -> None:
    spec = Spec(type="Graph", params={"expression": "x", "x_range": [0, 2]}, style={"stroke": "#22d3ee"})
    curve = adapter.build_child(AXES, spec)
    axes = manim_axes()
    assert curve.points[0][:2] == pytest.approx(axes.c2p(0, 0)[:2])
    assert curve.points[-1][:2] == pytest.approx(axes.c2p(2, 2)[:2])
    assert curve.get_stroke_color().to_hex().lower() == "#22d3ee"


# -- evaluating ---------------------------------------------------------------------------------------


def test_graphs_are_drawn_after_their_axes_and_carried_by_them() -> None:
    base = Transform2D(position=(1.0, -0.5), scale=0.6, rotation=20.0)
    project = chart(graph(), axes_fields={"base": base})
    evaluator = Evaluator(project)
    assert [i for i, _ in evaluator.frame_layers(0.5)] == ["axes", "g"]
    axes = manim_axes()
    both = m.VGroup(axes, manim_plot(axes, math.sin)).copy()
    both.scale(0.6, about_point=m.ORIGIN).rotate(math.radians(20), about_point=m.ORIGIN).shift((1, -0.5, 0))
    assert_renders(evaluator, 0.5, [both])
    pivot, rotation, _ = evaluator.layer_frame(project.layer("g"), 0.5)
    assert pivot == pytest.approx((1.0, -0.5)) and rotation == pytest.approx(20.0)


@pytest.mark.parametrize(
    "kind",
    [k for k in adapter.allowed_clip_kinds("Graph") if CLIP_KIND_INFO[k].category != "morph"],
)
def test_clips_on_a_graph_scrub_exactly(kind: str) -> None:
    """The harness (ADR 0007) on a child spec: played in order = scrubbed = fresh."""
    project = chart(graph(clips=[Clip(id="c", kind=kind, start=0, duration=1)]))
    expected = render_in_order(project, list(range(len(FRAMES))))
    order = random.Random(11).sample(range(len(FRAMES)), len(FRAMES))
    assert_frames_equal([expected[i] for i in range(len(FRAMES))], render_in_order(project, order), kind)
    fresh = render_in_order(project, order, fresh_each_frame=True)
    assert_frames_equal([expected[i] for i in range(len(FRAMES))], fresh, f"{kind} fresh")


def test_create_on_a_graph_matches_manim() -> None:
    project = chart(graph(clips=[Clip(id="c", kind="Create", start=0, duration=1)]))
    evaluator = Evaluator(project)
    axes = manim_axes()
    anim = m.Create(manim_plot(axes, math.sin))
    anim.begin()
    anim.interpolate(0.4)  # applies Create's own rate function
    assert_renders(evaluator, 0.4, [axes, anim.mobject])


def test_a_graph_turns_into_another_graph() -> None:
    morph = Clip(id="m", kind="Transform", start=0.0, duration=1.0, to_layer="p")
    project = chart(graph(clips=[morph]), graph("p", PARABOLA), axes_fields={"base": Transform2D(scale=0.8)})
    evaluator = Evaluator(project)
    axes = manim_axes()
    source = manim_plot(axes, math.sin).scale(0.8, about_point=m.ORIGIN)
    target = manim_plot(axes, lambda x: x**2 / 10 - 1).scale(0.8, about_point=m.ORIGIN)
    anim = m.ReplacementTransform(source, target)
    anim.begin()
    anim.interpolate(0.5)
    assert_renders(evaluator, 0.5, [axes.copy().scale(0.8, about_point=m.ORIGIN), anim.mobject])
    assert [i for i, _ in evaluator.frame_layers(0.5)] == ["axes", "g"]
    assert [i for i, _ in evaluator.frame_layers(1.0)] == ["axes", "p"]


def test_editing_the_axes_plots_the_graphs_again() -> None:
    project = chart(graph(clips=[Clip(id="c", kind="Create", start=0, duration=1)]))
    evaluator = Evaluator(project)
    before = evaluator.frame_layers(0.5)[1][1].points.copy()
    taller = Spec(type="Axes", params={"y_range": [-1.0, 1.0]})
    edit = edits.update_layer(project, "axes", spec=taller)
    assert edit.kind == "spec" and "g" in edit.layer_ids
    evaluator.apply(edit)
    after = evaluator.frame_layers(0.5)[1][1].points
    assert not np.allclose(before, after)  # sin(x) now spans the full height
    assert after.shape == Evaluator(edit.project).frame_layers(0.5)[1][1].points.shape


def test_a_graph_lives_within_its_axes_lifetime() -> None:
    fade = Clip(id="f", kind="FadeOut", start=1.0, duration=0.5)
    project = chart(graph(), axes_fields={"clips": [fade]})
    evaluator = Evaluator(project)
    assert [i for i, _ in evaluator.frame_layers(1.2)] == ["axes", "g"]
    assert evaluator.frame_layers(1.6) == []
