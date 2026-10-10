"""Rendered frames kept for playback (P3f.1, ADR 0028): the grid, what an edit
changes, the store, and the selected object evaluated alone."""

from __future__ import annotations

import math

import pytest

from manim_studio.core import edits
from manim_studio.core.evaluator import Evaluator
from manim_studio.core.frame_cache import (
    FrameStore,
    changed_spans,
    frame_count,
    frame_index,
    frame_time,
    on_grid,
    span_indices,
)
from manim_studio.core.schema import Canvas, Clip, Keyframe, Layer, Lifetime, PartKey, Project, Spec

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=6.0)


def scene() -> Project:
    """An early circle (0-2 s), a late square (from 4 s), a dot following the square, a morph."""
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(id="early", spec=Spec(type="Circle"), lifetime=Lifetime(in_=0.0, out=2.0)),
            Layer(
                id="late",
                spec=Spec(type="Square"),
                clips=[Clip(id="in", kind="FadeIn", start=4.0, duration=1.0)],
            ),
            Layer(id="mid", spec=Spec(type="Star"), lifetime=Lifetime(in_=2.0, out=3.0)),
            Layer(
                id="a",
                spec=Spec(type="Triangle"),
                lifetime=Lifetime(in_=1.0),
                clips=[Clip(id="m", kind="Transform", start=2.0, duration=1.0, to_layer="b")],
            ),
            Layer(id="b", spec=Spec(type="Rectangle")),
        ],
    )


def update(project: Project, layer_id: str, **fields) -> Project:
    layers = [layer.model_copy(update=fields) if layer.id == layer_id else layer for layer in project.layers]
    return project.model_copy(update={"layers": layers})


# -- the grid -------------------------------------------------------------------------------------------


def test_the_grid_is_the_exports() -> None:
    assert frame_index(0.0, 30) == 0 and frame_index(1.0, 30) == 30
    assert frame_index(1 / 30 - 1e-9, 30) == 1  # float noise lands on the frame
    assert frame_index(0.049, 30) == 1 and frame_index(0.067, 30) == 2
    assert frame_time(45, 30) == 1.5
    assert on_grid(1.5, 30) and not on_grid(1.51, 30)
    assert frame_count(scene()) == 60


def test_span_indices_cover_start_to_before_end() -> None:
    assert span_indices([(0.0, 0.3)], 10, 60) == {0, 1, 2}
    assert span_indices([(0.25, 0.5)], 10, 60) == {3, 4}
    assert span_indices([(5.5, math.inf)], 10, 60) == {55, 56, 57, 58, 59}


# -- what an edit changes ---------------------------------------------------------------------------------


def test_nothing_changed_changes_nothing() -> None:
    assert changed_spans(scene(), scene()) == []


def test_a_canvas_change_changes_everything() -> None:
    project = scene()
    other = project.model_copy(update={"canvas": CANVAS.model_copy(update={"background": "#ffffff"})})
    assert changed_spans(project, other) is None


def test_editing_a_late_layer_keeps_the_early_frames() -> None:
    project = scene()
    edited = update(project, "late", spec=Spec(type="Square", params={"side_length": 3.0}))
    assert changed_spans(project, edited) == [(4.0, math.inf)]


def test_retiming_changes_the_old_and_the_new_lifetime() -> None:
    project = scene()
    moved = edits.move_clip(project, "late", "in", 1.0).project
    assert changed_spans(project, moved) == [(1.0, math.inf)]
    shorter = update(project, "early", lifetime=Lifetime(in_=0.0, out=1.0))
    assert changed_spans(project, shorter) == [(0.0, 2.0)]


def test_a_morph_reads_both_ends() -> None:
    project = scene()
    edited = update(project, "b", spec=Spec(type="Rectangle", params={"width": 1.0}))
    assert changed_spans(project, edited) == [(1.0, math.inf)]  # a (from 1 s) and b (from 3 s)


def test_a_z_order_move_changes_only_the_moved_layer() -> None:
    project = scene()
    order = ["early", "mid", "late", "a", "b"]  # mid moved under late
    moved = project.model_copy(update={"layers": [project.layer(i) for i in order]})
    assert changed_spans(project, moved) == [(2.0, 3.0)]


def test_adding_and_removing_layers_change_their_lifetimes() -> None:
    project = scene()
    added = project.model_copy(
        update={
            "layers": [*project.layers, Layer(id="new", spec=Spec(type="Dot"), lifetime=Lifetime(in_=5.0))]
        }
    )
    assert changed_spans(project, added) == [(5.0, math.inf)]
    assert changed_spans(added, project) == [(5.0, math.inf)]


def test_a_follower_changes_with_its_path() -> None:
    project = scene()
    runner = Layer(
        id="runner",
        spec=Spec(type="Dot"),
        lifetime=Lifetime(in_=0.5, out=1.5),
        clips=[Clip(id="r", kind="MoveAlongPath", start=0.5, duration=1.0, params={"path": "late"})],
    )
    project = project.model_copy(update={"layers": [*project.layers, runner]})
    edited = update(project, "late", spec=Spec(type="Square", params={"side_length": 3.0}))
    assert changed_spans(project, edited) == [(0.5, 1.5), (4.0, math.inf)]


def test_a_part_or_a_graph_changes_its_whole_object() -> None:
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(
                id="eq",
                spec=Spec(type="MathTex", params={"text": "a+b"}),
                lifetime=Lifetime(in_=1.0, out=2.0),
            ),
            Layer(id="b", parent_id="eq", part=PartKey(tex="b")),
            Layer(id="axes", spec=Spec(type="Axes"), lifetime=Lifetime(in_=3.0, out=4.0)),
            Layer(id="g", parent_id="axes", spec=Spec(type="Graph", params={"expression": "x"})),
        ],
    )
    part = update(project, "b", base=project.layer("b").base.model_copy(update={"rotation": 30.0}))
    assert changed_spans(project, part) == [(1.0, 2.0)]
    graph = update(project, "g", spec=Spec(type="Graph", params={"expression": "x**2"}))
    assert changed_spans(project, graph) == [(3.0, 4.0)]
    # a part alive for less than its equation: re-keying it changes what the root draws after it
    short = update(project, "b", lifetime=Lifetime(in_=1.0, out=1.5))
    rekeyed = update(short, "b", part=PartKey(tex="a"))
    assert changed_spans(short, rekeyed) == [(1.0, 2.0)]


def test_spans_contain_every_frame_that_differs() -> None:
    """Exhaustive for one edit of each kind: frames outside the spans render the same."""
    from manim_studio.render.cairo_export import make_camera, render_frame

    project = scene()
    camera = make_camera(CANVAS)
    for edited in (
        update(project, "late", spec=Spec(type="Square", params={"side_length": 3.0})),
        update(project, "b", spec=Spec(type="Rectangle", params={"width": 1.0})),
        update(project, "mid", tracks={"position": [Keyframe(t=2.0, value=(1.0, 1.0))]}),
    ):
        spans = changed_spans(project, edited)
        inside = span_indices(spans, CANVAS.fps, frame_count(project))
        before, after = Evaluator(project), Evaluator(edited)
        for i in range(frame_count(project)):
            same = (
                render_frame(camera, before.frame(i / 10)) == render_frame(camera, after.frame(i / 10))
            ).all()
            assert same or i in inside, (spans, i)


# -- the store ------------------------------------------------------------------------------------------


def test_the_store_refuses_other_views_and_stale_generations() -> None:
    store = FrameStore(total=60)
    store.set_view(1)
    rendered_at = store.generation
    assert store.accept(1, rendered_at, 5, b"five")
    assert not store.accept(2, rendered_at, 6, b"other view")
    store.invalidate([5, 6])
    assert store.get(5) is None
    assert not store.accept(1, rendered_at, 6, b"rendered before the edit")
    assert store.accept(1, rendered_at, 7, b"untouched by the edit")
    assert store.accept(1, store.generation, 6, b"after")
    store.set_view(2)
    assert len(store) == 0 and store.nbytes == 0
    assert not store.accept(1, store.generation, 7, b"for the old view")
    assert store.accept(2, rendered_at, 7, b"the same project, the new view")  # 7 never changed


def test_the_store_asks_from_the_playhead_and_wraps() -> None:
    store = FrameStore(total=10)
    for i in (3, 4, 6):
        store.accept(0, 0, i, b"x")
    assert store.missing(3, 4) == [5, 7, 8, 9]
    assert store.missing(8, 5) == [8, 9, 0, 1, 2]


def test_a_full_store_evicts_farthest_ahead_and_stops_asking_beyond() -> None:
    store = FrameStore(total=10, budget=30)
    for i in range(3):
        assert store.accept(0, 0, i, b"0123456789", playhead=0)
    assert store.nbytes == 30
    assert store.accept(0, 0, 9, b"0123456789", playhead=8)  # 9 is just ahead of the playhead at 8
    assert sorted(store.frames) == [0, 1, 9]  # 2 was the farthest ahead of 8 (wrapping)
    assert store.missing(8, 10) == [8]  # from 8: only what is nearer than 1 (the farthest kept)
    assert store.missing(0, 10) == [2, 3, 4, 5, 6, 7, 8]  # from 0: all nearer than 9
    assert store.nbytes == 30


# -- the selected object alone ------------------------------------------------------------------------------


@pytest.mark.latex
def test_object_frame_is_that_objects_part_of_the_frame() -> None:
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(id="c", spec=Spec(type="Circle")),
            Layer(id="eq", spec=Spec(type="MathTex", params={"text": "a+b"})),
            Layer(id="b", parent_id="eq", part=PartKey(tex="b")),
            Layer(id="axes", spec=Spec(type="Axes")),
            Layer(id="g", parent_id="axes", spec=Spec(type="Graph", params={"expression": "x"})),
        ],
    )
    evaluator = Evaluator(project)
    objects = {"c": {"c"}, "eq": {"eq", "b"}, "b": {"eq", "b"}, "axes": {"axes", "g"}, "g": {"axes", "g"}}
    for layer_id, members in objects.items():
        whole = [(i, mob.points.copy()) for i, mob in evaluator.frame_layers(1.0) if i in members]
        alone = [(i, mob.points.copy()) for i, mob in evaluator.object_frame(layer_id, 1.0)]
        assert [i for i, _ in alone] == [i for i, _ in whole], layer_id
        assert all((a == b).all() for (_, a), (_, b) in zip(alone, whole, strict=True)), layer_id
