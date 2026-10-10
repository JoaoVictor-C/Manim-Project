"""MoveAlongPath: moving along another layer's shape (P3c.1-P3c.2, ADR 0025).

The path layer's rest shape, in world space at the clip's start, is followed by
the mover's centre; frames are compared with Manim's own MoveAlongPath on the
same world path, and the harness checks order independence with two layers.
"""

from __future__ import annotations

import random

import manim as m
import numpy as np
import pytest
from pydantic import ValidationError
from tests.support import CANVAS, FRAMES, TOLERANCE, assert_frames_equal, max_diff, render_in_order

from manim_studio.core import adapter, edits
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.schema import Clip, Keyframe, Layer, PartKey, Project, Spec, Transform2D
from manim_studio.render.cairo_export import make_camera, render_frame

DOT = Spec(type="Dot", params={"radius": 0.2}, style={"fill": "#facc15", "fill_opacity": 1.0})
CIRCLE = Spec(type="Circle", params={"radius": 2.0})


def run(path: str = "ring", start: float = 0.0, duration: float = 1.0) -> Clip:
    return Clip(id="run", kind="MoveAlongPath", start=start, duration=duration, params={"path": path})


def scene(*clips: Clip, dot_base=None, ring_base=None, extra=()) -> Project:
    dot = Layer(id="dot", spec=DOT, base=dot_base or Transform2D(position=(-4.0, 0.0)), clips=list(clips))
    ring = Layer(id="ring", spec=CIRCLE, base=ring_base or Transform2D(position=(1.0, 0.5)))
    return Project(canvas=CANVAS, layers=[ring, dot, *extra])


def centre(evaluator: Evaluator, layer_id: str, t: float) -> np.ndarray:
    return dict(evaluator.frame_layers(t))[layer_id].get_center()


def ring_world(position=(1.0, 0.5)) -> m.VMobject:
    return adapter.build_mobject(CIRCLE).shift((*position, 0))


# -- the adapter patch ------------------------------------------------------------------------------


def test_the_measured_path_gives_manims_points() -> None:
    graph = adapter.build_child(Spec(type="Axes"), Spec(type="Graph", params={"expression": "sin(x)"}))
    for path in (m.Circle(radius=2), m.Line(m.LEFT, m.RIGHT * 3 + m.UP), graph):
        ours, theirs = m.Dot(), m.Dot()
        fast = adapter.TabledMoveAlongPath(ours, path, rate_func=m.linear)
        slow = m.MoveAlongPath(theirs, path, rate_func=m.linear)
        for alpha in (0.0, 0.13, 0.5, 0.77, 1.0):
            fast.interpolate(alpha)
            slow.interpolate(alpha)
            assert np.allclose(ours.get_center(), theirs.get_center(), atol=1e-9), alpha


# -- validation ---------------------------------------------------------------------------------------


def test_a_path_clip_needs_a_real_path() -> None:
    scene(run())  # fine
    with pytest.raises(ValidationError, match="needs a path layer"):
        scene(run(path="nowhere"))
    with pytest.raises(ValidationError, match="cannot be its path"):
        scene(run(path="dot"))
    eq = Layer(id="eq", spec=Spec(type="MathTex", params={"text": "a+b"}))
    part = Layer(id="b", parent_id="eq", part=PartKey(tex="b"))
    with pytest.raises(ValidationError, match="cannot be its path"):
        scene(run(path="b"), extra=(eq, part))
    code = Layer(id="code", spec=Spec(type="Code", params={"code": ""}))
    with pytest.raises(ValidationError, match="cannot be its path"):
        scene(run(path="code"), extra=(code,))


def test_only_whole_objects_travel() -> None:
    axes = Layer(id="axes", spec=Spec(type="Axes"))
    graph = Layer(
        id="g", parent_id="axes", spec=Spec(type="Graph", params={"expression": "x"}), clips=[run()]
    )
    with pytest.raises(ValidationError, match="moves whole objects"):
        scene(extra=(axes, graph))
    assert "MoveAlongPath" not in adapter.allowed_clip_kinds("Graph")
    assert "MoveAlongPath" in adapter.allowed_clip_kinds("Dot")


def test_deleting_the_path_layer_drops_the_clips_that_follow_it() -> None:
    project = edits.remove_layer(scene(run()), "ring").project
    assert project.layer("dot").clips == []


# -- evaluating ---------------------------------------------------------------------------------------


def test_frames_match_manims_move_along_path() -> None:
    evaluator = Evaluator(scene(run()))
    camera = make_camera(CANVAS)
    for t in (0.0, 0.3, 0.75):
        ring = ring_world()
        dot = adapter.build_mobject(DOT).shift((-4.0, 0.0, 0.0))
        anim = m.MoveAlongPath(dot, ring)
        anim.begin()
        anim.interpolate(t)
        diff = max_diff(render_frame(camera, evaluator.frame(t)), render_frame(camera, [ring, anim.mobject]))
        assert diff <= TOLERANCE, f"t={t}: {diff}"


def test_the_dot_follows_a_graph_on_moved_axes_and_stays_at_the_end() -> None:
    axes = Layer(id="axes", spec=Spec(type="Axes"), base=Transform2D(position=(0.5, -1.0), scale=0.6))
    graph = Layer(id="g", parent_id="axes", spec=Spec(type="Graph", params={"expression": "sin(x)"}))
    project = scene(run(path="g", duration=2.0), extra=(axes, graph))
    evaluator = Evaluator(project)
    world = adapter.build_child(axes.spec, graph.spec).scale(0.6, about_point=m.ORIGIN).shift((0.5, -1.0, 0))
    for t in (0.0, 0.5, 1.2, 1.99):
        expected = world.point_from_proportion(m.smooth(t / 2.0))
        assert centre(evaluator, "dot", t) == pytest.approx(expected, abs=1e-6), t
    assert centre(evaluator, "dot", 3.0) == pytest.approx(world.point_from_proportion(1.0), abs=1e-6)


def test_a_scaled_and_turned_mover_still_follows_the_path() -> None:
    base = Transform2D(position=(-4.0, 0.0), scale=1.7, rotation=35.0)
    evaluator = Evaluator(scene(run(), dot_base=base))
    ring = ring_world()
    for t in (0.2, 0.6):
        assert centre(evaluator, "dot", t) == pytest.approx(ring.point_from_proportion(m.smooth(t)), abs=1e-6)


def test_moving_the_path_or_the_mover_later_runs_the_path_again() -> None:
    fade = Clip(id="fade", kind="FadeOut", start=1.5, duration=1.0)
    project = scene(run(), fade)
    evaluator = Evaluator(project)
    evaluator.frame(0.5)
    evaluator.frame(1.8)  # caches: the begun run and the checkpoint after it
    moved = edits.update_layer(project, "ring", base={"position": (-1.0, -1.0)})
    assert moved.kind == "transform"  # caches are kept: the path's signature picks other entries
    evaluator.apply(moved)
    ring = ring_world((-1.0, -1.0))
    assert centre(evaluator, "dot", 0.5) == pytest.approx(ring.point_from_proportion(m.smooth(0.5)), abs=1e-6)
    assert centre(evaluator, "dot", 1.8) == pytest.approx(ring.point_from_proportion(1.0), abs=1e-6)
    elsewhere = edits.update_layer(moved.project, "dot", base={"position": (3.0, 3.0)})
    evaluator.apply(elsewhere)
    assert centre(evaluator, "dot", 0.5) == pytest.approx(ring.point_from_proportion(m.smooth(0.5)), abs=1e-6)
    fresh = Evaluator(elsewhere.project)
    assert centre(fresh, "dot", 1.8) == pytest.approx(centre(evaluator, "dot", 1.8), abs=1e-9)


def test_keys_on_the_path_during_the_run_are_not_followed() -> None:
    track = [Keyframe(t=0.0, value=(1.0, 0.5)), Keyframe(t=1.0, value=(3.0, 0.5))]
    keyed = scene(run())
    keyed = edits.update_layer(keyed, "ring", tracks={"position": track}).project
    evaluator = Evaluator(keyed)
    at_start = ring_world((1.0, 0.5))  # the path's shape at the clip start
    assert centre(evaluator, "dot", 0.6) == pytest.approx(
        at_start.point_from_proportion(m.smooth(0.6)), abs=1e-6
    )


def test_path_clips_scrub_exactly() -> None:
    """The harness (ADR 0007) with two layers: played in order = scrubbed = fresh."""
    project = scene(run(), Clip(id="i", kind="Indicate", start=1.0, duration=0.5))
    n = len(FRAMES)
    expected = render_in_order(project, list(range(n)))
    order = random.Random(17).sample(range(n), n)
    assert_frames_equal([expected[i] for i in range(n)], render_in_order(project, order), "scrub")
    assert_frames_equal([expected[i] for i in range(n)], render_in_order(project, order, True), "fresh")
