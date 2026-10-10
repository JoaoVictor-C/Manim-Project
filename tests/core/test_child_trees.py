"""Child objects animate with their object (P3g.1, ADR 0029).

An axes with graphs evaluates as one tree: a clip on the axes animates the
graphs with them, exactly as Manim animating ``VGroup(axes, graph)``; graph
clips, graph morphs and paths keep working; edits rebuild what they must.
"""

from __future__ import annotations

import math
import random

import manim as m
import numpy as np
import pytest
from tests.core.test_graphs import AXES, PARABOLA, assert_renders, chart, graph, manim_axes, manim_plot
from tests.support import CANVAS, FRAMES, assert_frames_equal, render_in_order

from manim_studio.core import adapter, edits
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Clip, Layer, PartKey, Project, Spec, Transform2D

RING = Spec(type="Circle", params={"radius": 2.0})


def figure() -> m.VGroup:
    axes = manim_axes()
    return m.VGroup(axes, manim_plot(axes, math.sin))


@pytest.mark.parametrize(
    ("kind", "alpha"), [("Create", 0.6), ("FadeOut", 0.5), ("Indicate", 0.5), ("Wiggle", 0.3)]
)
def test_a_clip_on_the_axes_animates_their_graphs_too(kind: str, alpha: float) -> None:
    project = chart(graph(), axes_fields={"clips": [Clip(id="c", kind=kind, start=0, duration=1)]})
    anim = adapter.make_animation(kind, figure(), None, {})
    anim.begin()
    anim.interpolate(alpha)
    assert_renders(Evaluator(project), alpha, [anim.mobject])


def test_after_an_axes_fade_out_nothing_of_the_figure_is_drawn() -> None:
    project = chart(graph(), axes_fields={"clips": [Clip(id="o", kind="FadeOut", start=0, duration=0.5)]})
    assert Evaluator(project).frame_layers(0.7) == []


def test_figure_clips_scrub_exactly() -> None:
    """The harness with a clip on the axes, then one on the graph, then a graph morph."""
    project = chart(
        graph(
            clips=[
                Clip(id="i", kind="Indicate", start=0.4, duration=0.2),
                Clip(id="m", kind="Transform", start=0.7, duration=0.3, to_layer="p"),
            ]
        ),
        graph("p", PARABOLA),
        axes_fields={"clips": [Clip(id="c", kind="Create", start=0, duration=0.4)]},
    )
    expected = render_in_order(project, list(range(len(FRAMES))))
    order = random.Random(5).sample(range(len(FRAMES)), len(FRAMES))
    reference = [expected[i] for i in range(len(FRAMES))]
    assert_frames_equal(reference, render_in_order(project, order), "scrubbed")
    assert_frames_equal(reference, render_in_order(project, order, fresh_each_frame=True), "fresh")


def test_the_axes_ride_a_path_carrying_their_graphs() -> None:
    run = Clip(
        id="r", kind="MoveAlongPath", start=0, duration=1, params={"path": "ring"}, ease={"name": "linear"}
    )
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(id="ring", spec=RING),
            Layer(id="axes", spec=AXES, base=Transform2D(scale=0.3), clips=[run]),
            graph(),
        ],
    )
    evaluator = Evaluator(project)
    ring = m.Circle(radius=2.0)
    small = figure().scale(0.3, about_point=m.ORIGIN)
    for alpha in (0.0, 0.3, 0.8):
        drawn = dict(evaluator.frame_layers(alpha))
        target = ring.point_from_proportion(alpha)
        assert drawn["axes"].get_center() == pytest.approx(target, abs=1e-3)  # the axes' own glyphs
        moved = small.copy().move_to(target)
        assert drawn["g"].get_center() == pytest.approx(moved[1].get_center(), abs=1e-3), alpha


def test_moving_the_path_runs_the_figure_again() -> None:
    run = Clip(id="r", kind="MoveAlongPath", start=0, duration=1, params={"path": "ring"})
    project = Project(
        canvas=CANVAS,
        layers=[Layer(id="ring", spec=RING), Layer(id="axes", spec=AXES, clips=[run]), graph()],
    )
    evaluator = Evaluator(project)
    before = dict(evaluator.frame_layers(1.0))["g"].get_center()
    moved = edits.update_layer(project, "ring", base=Transform2D(position=(1.0, 1.0)))
    evaluator.apply(moved)
    after = dict(evaluator.frame_layers(1.0))["g"].get_center()
    assert after == pytest.approx(before + np.array([1.0, 1.0, 0.0]), abs=1e-6)
    assert after == pytest.approx(dict(Evaluator(moved.project).frame_layers(1.0))["g"].get_center())


def test_a_graph_morph_after_a_run_happens_where_the_axes_went() -> None:
    run = Clip(id="r", kind="MoveAlongPath", start=0, duration=0.4, params={"path": "ring"})
    morph = Clip(id="m", kind="Transform", start=0.5, duration=0.4, to_layer="p")
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(id="ring", spec=RING),
            Layer(id="axes", spec=AXES, base=Transform2D(scale=0.3), clips=[run]),
            graph(clips=[morph]),
            graph("p", PARABOLA),
        ],
    )
    evaluator = Evaluator(project)
    evaluator.frame(0.7)
    moved = edits.update_layer(project, "ring", base=Transform2D(position=(-1.0, 0.5)))
    evaluator.apply(moved)  # a transform edit: caches kept, so the morph must notice its ends moved
    fresh = Evaluator(moved.project)
    for t in (0.6, 0.7, 0.95):
        mine = np.concatenate([s.points for s in evaluator.frame(t)[-1].family_members_with_points()])
        theirs = np.concatenate([s.points for s in fresh.frame(t)[-1].family_members_with_points()])
        assert np.allclose(mine, theirs), t


def test_a_whole_figure_morph_takes_its_graphs_along() -> None:
    morph = Clip(id="m", kind="Transform", start=0, duration=0.5, to_layer="dot")
    project = Project(
        canvas=CANVAS,
        layers=[Layer(id="axes", spec=AXES, clips=[morph]), graph(), Layer(id="dot", spec=Spec(type="Dot"))],
    )
    evaluator = Evaluator(project)
    assert [i for i, _ in evaluator.frame_layers(0.25)] == ["axes"]  # one hand-off, graphs inside it
    assert [i for i, _ in evaluator.frame_layers(0.75)] == ["dot"]


def test_adding_and_editing_a_graph_rebuilds_the_figure() -> None:
    project = chart(graph())
    evaluator = Evaluator(project)
    evaluator.frame(0.5)
    added = edits.add_child(project, parent_id="axes", spec=PARABOLA)
    evaluator.apply(added)
    assert [i for i, _ in evaluator.frame_layers(0.5)] == ["axes", "g", added.project.layers[-1].id]
    edited = edits.update_layer(added.project, "g", spec=Spec(type="Graph", params={"expression": "cos(x)"}))
    evaluator.apply(edited)
    axes = manim_axes()
    expected = [axes, manim_plot(axes, math.cos), manim_plot(axes, lambda x: x**2 / 10 - 1)]
    assert_renders(evaluator, 0.5, expected)


@pytest.mark.latex
def test_an_equation_with_parts_can_ride_a_path() -> None:
    """A MoveAlongPath on a tree root crashed before P3g ('needs a target')."""
    run = Clip(
        id="r", kind="MoveAlongPath", start=0, duration=1, params={"path": "ring"}, ease={"name": "linear"}
    )
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(id="ring", spec=RING),
            Layer(id="eq", spec=Spec(type="MathTex", params={"text": "a+b"}), clips=[run]),
            Layer(id="b", parent_id="eq", part=PartKey(tex="b")),
        ],
    )
    evaluator = Evaluator(project)
    ring = m.Circle(radius=2.0)
    for alpha in (0.25, 0.75):
        whole = m.Group(*(mob for i, mob in evaluator.frame_layers(alpha) if i != "ring"))
        assert whole.get_center() == pytest.approx(ring.point_from_proportion(alpha), abs=1e-3)
