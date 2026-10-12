"""The graph editor's model (P6b.2, decision session 35): curves, ranges, sampling parity with
the evaluator, the view, hits and the drag rule - no Qt needed."""

from __future__ import annotations

import random

import pytest

from manim_studio.core import adapter, edits
from manim_studio.core.evaluator import _sample, layer_transform
from manim_studio.core.schema import Canvas, Easing, Keyframe, Layer, Marker, Project, Spec
from manim_studio.ui import graph_model as gm
from manim_studio.ui.timeline.model import TimeScale

FPS = 10
SCALE = TimeScale(px_per_second=100)  # 8 px snap radius = 0.08 s
X, Y, SCALE_CURVE, ROT, OPACITY = (gm.BY_NAME[n] for n in ("x", "y", "scale", "rotation", "opacity"))


def project(**tracks) -> Project:
    return Project(
        canvas=Canvas(fps=FPS, duration=4.0),
        layers=[Layer(id="a", spec=Spec(type="Square"), tracks=tracks)],
    )


def posed() -> Project:
    """Position keyed at 0, 1, 2 s; rotation at 1 and 3 s; a marker at 1.5 s."""
    return project(
        position=[
            Keyframe(t=0.0, value=(0.0, 0.0)),
            Keyframe(t=1.0, value=(2.0, 1.0), ease=Easing(name="linear")),
            Keyframe(t=2.0, value=(4.0, -1.0)),
        ],
        rotation=[Keyframe(t=1.0, value=0.0), Keyframe(t=3.0, value=90.0)],
    )


# -- curves and ranges ------------------------------------------------------------------


def test_a_curve_per_value_and_a_locked_graph_offers_opacity_only() -> None:
    assert [c.name for c in gm.curves_for(posed().layer("a"))] == ["x", "y", "scale", "rotation", "opacity"]
    graph = Project(
        layers=[
            Layer(id="axes", spec=Spec(type="Axes")),
            Layer(id="g", parent_id="axes", spec=Spec(type="Graph", params={"expression": "sin(x)"})),
        ]
    )
    assert [c.name for c in gm.curves_for(graph.layer("g"))] == ["opacity"]
    assert {c.token for c in gm.CURVES} == {
        "curve_x",
        "curve_y",
        "curve_scale",
        "curve_rotation",
        "curve_opacity",
    }


def test_components_are_read_and_replaced_one_at_a_time() -> None:
    assert gm.component((2.0, 3.0), X) == 2.0 and gm.component((2.0, 3.0), Y) == 3.0
    assert gm.with_component((2.0, 3.0), Y, 7) == (2.0, 7.0)
    assert gm.with_component((2.0, 3.0), X, 7) == (7.0, 3.0)
    assert gm.with_component(1.5, SCALE_CURVE, 2) == 2.0
    assert gm.clamp_value(OPACITY, 1.4) == 1.0 and gm.clamp_value(OPACITY, -0.2) == 0.0
    assert gm.clamp_value(SCALE_CURVE, -0.2) == -0.2  # only opacity has bounds


def test_each_curve_has_its_own_padded_range() -> None:
    layer = posed().layer("a")
    assert gm.value_range(layer, X) == pytest.approx((-0.4, 4.4))  # 0..4, 10 % each side
    assert gm.value_range(layer, Y) == pytest.approx((-1.2, 1.2))
    assert gm.value_range(layer, ROT) == pytest.approx((-9.0, 99.0))
    assert gm.value_range(layer, OPACITY) == pytest.approx((-0.1, 1.1))  # always 0..1
    # flat or untracked: the minimum span around the value (the base, 1.0 for scale)
    assert gm.value_range(layer, SCALE_CURVE) == pytest.approx((0.7, 1.3))
    flat = project(rotation=[Keyframe(t=0.0, value=30.0), Keyframe(t=1.0, value=30.0)]).layer("a")
    assert gm.value_range(flat, ROT) == pytest.approx((3.0, 57.0))
    assert gm.normalise(gm.denormalise(0.3, (2.0, 6.0)), (2.0, 6.0)) == pytest.approx(0.3)


# -- sampling ---------------------------------------------------------------------------


def random_track(rng: random.Random, vec: bool, curved: bool) -> list[Keyframe]:
    eases = [Easing(name=n) for n in adapter.EASE_NAMES] + [
        Easing(name=None, bezier=b) for b in adapter.BEZIER_PRESETS.values()
    ]
    times = sorted(rng.sample(range(0, 40), rng.randint(1, 6)))
    track = []
    for t in times:
        value = (rng.uniform(-3, 3), rng.uniform(-3, 3)) if vec else rng.uniform(-3, 3)
        tangents = {}
        if curved and rng.random() < 0.6:
            tangents = {"in_tangent": (rng.uniform(-1, 1), rng.uniform(-1, 1)), "out_tangent": (0.5, -0.4)}
        track.append(Keyframe(t=t / 10, value=value, ease=rng.choice(eases), **tangents))
    return track


@pytest.mark.parametrize("seed", range(12))
def test_sampling_matches_the_evaluator(seed) -> None:
    """The segment walk gives exactly what ``evaluator._sample`` gives at every time."""
    rng = random.Random(seed)
    track = random_track(rng, vec=seed % 2 == 0, curved=seed % 2 == 0 and seed % 3 == 0)
    times = sorted({round(rng.uniform(-0.5, 4.5), 4) for _ in range(150)} | {k.t for k in track})
    got = gm.sample_track(track, times, 0.0)
    for t, value in zip(times, got, strict=True):
        assert value == pytest.approx(_sample(track, t, 0.0), abs=1e-12), t
    # times that go back restart the walk
    assert gm.sample_track(track, [3.9, 0.15], 0.0) == pytest.approx(
        [_sample(track, t, 0.0) for t in (3.9, 0.15)]
    )
    steps = [Keyframe(t=float(t), value=float(t * t)) for t in range(4)]
    assert gm.sample_track(steps, [2.5, 0.5], 0.0) == pytest.approx(
        [_sample(steps, t, 0.0) for t in (2.5, 0.5)]
    )
    assert gm.sample_track([], [0.0, 1.0], 5.0) == [5.0, 5.0]


def test_curve_points_include_every_key_and_the_instant_before_it() -> None:
    layer = project(
        scale=[
            Keyframe(t=1.0, value=1.0, ease=Easing(name="there_and_back")),  # ends where it started
            Keyframe(t=2.0, value=3.0),
        ]
    ).layer("a")
    points = gm.curve_points(layer, SCALE_CURVE, 0.0, 4.0, 0.3)
    times = [t for t, _ in points]
    assert times == sorted(times) and times[0] == 0.0 and times[-1] == 4.0
    by_time = dict(points)
    assert by_time[2.0] == 3.0 and by_time[2.0 - gm.EPS] == pytest.approx(1.0, abs=1e-3)  # the jump is drawn
    assert gm.value_at(layer, SCALE_CURVE, 1.5) == layer_transform(layer, 1.5).scale
    untracked = gm.curve_points(layer, ROT, 0.0, 4.0, 1.0)
    assert {v for _, v in untracked} == {0.0}  # the base, flat


# -- the view ---------------------------------------------------------------------------


def test_the_value_window_maps_zooms_and_pans() -> None:
    view = gm.ValueView(top=10, height=100)
    assert view.y(1.0) == 10 and view.y(0.0) == 110 and view.n(60) == pytest.approx(0.5)
    zoomed = view.zoomed(2.0, anchor_y=35)  # the value under y=35 stays there
    assert zoomed.n(35) == pytest.approx(view.n(35)) and zoomed.n1 - zoomed.n0 == pytest.approx(0.5)
    assert view.zoomed(1e6, 50).n1 - view.zoomed(1e6, 50).n0 == pytest.approx(gm.MIN_WINDOW)
    panned = view.panned(50)
    assert panned.n0 == pytest.approx(0.5) and panned.n1 == pytest.approx(1.5)
    assert view.resized(0, 200).y(0.0) == 200


def test_frame_all_fits_the_keys_or_the_scene() -> None:
    layer = posed().layer("a")
    assert gm.frame_times(layer, [X, ROT], 4.0) == pytest.approx((-0.15, 3.15))  # 0..3 s, 5 %
    assert gm.frame_times(layer, [SCALE_CURVE], 4.0) == (0.0, 4.0)  # no keys
    assert gm.frame_times(None, gm.CURVES, 4.0) == (0.0, 4.0)
    near = project(scale=[Keyframe(t=1.0, value=1.0), Keyframe(t=1.5, value=2.0)]).layer("a")
    assert gm.frame_times(near, [SCALE_CURVE], 4.0) == (0.0, 4.0)  # under a second: the scene


def test_grid_steps_are_round() -> None:
    assert gm.nice_step(0.01) == 1.0  # 60 px at 100 px/s
    assert gm.nice_step(0.004) == 0.5
    assert gm.nice_step(1.3) == 100.0
    assert gm.nice_step(0.0) == 1.0
    assert gm.ticks(-0.3, 1.1, 0.5) == [0.0, 0.5, 1.0]


# -- hits -------------------------------------------------------------------------------


def test_the_nearest_point_within_the_radius_wins() -> None:
    points = [gm.Point("x", 1.0, 100, 50), gm.Point("y", 1.0, 100, 58), gm.Point("x", 2.0, 200, 50)]
    assert gm.nearest_point(points, 101, 56, 6).curve == "y"
    assert gm.nearest_point(points, 100, 51, 6).curve == "x"
    assert gm.nearest_point(points, 150, 50, 6) is None
    assert gm.nearest_point(points, 107, 50, 6) is None  # just outside


def test_distance_to_a_polyline_and_the_segment_around_a_time() -> None:
    line = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    assert gm.distance_to_polyline(line, 5, 3) == pytest.approx(3.0)
    assert gm.distance_to_polyline(line, 13, 5) == pytest.approx(3.0)
    assert gm.distance_to_polyline(line, -4, -3) == pytest.approx(5.0)
    assert gm.distance_to_polyline([(1.0, 1.0)], 4, 5) == pytest.approx(5.0)
    assert gm.distance_to_polyline([], 4, 5) == float("inf")
    layer = posed().layer("a")
    assert gm.segment_start(layer, X, 0.5) == 0.0 and gm.segment_start(layer, X, 1.0) == 1.0
    assert gm.segment_start(layer, X, 2.5) is None and gm.segment_start(layer, SCALE_CURVE, 1.0) is None


# -- edits ------------------------------------------------------------------------------


def drag(
    proj: Project, curve: gm.Curve, t: float, to_t: float, to_value: float, **kw
) -> tuple[Project, float]:
    edit, new_t = gm.drag_key(proj, "a", curve, t, to_t, to_value, scale=SCALE, playhead=0.0, **kw)
    return edit.project, new_t


def test_dragging_a_point_retimes_that_track_only_and_changes_its_component() -> None:
    p, new_t = drag(posed(), Y, 1.0, 1.32, 2.5)
    layer = p.layer("a")
    assert new_t == pytest.approx(1.3)  # the frame grid
    assert [k.t for k in layer.tracks["position"]] == [0.0, pytest.approx(1.3), 2.0]
    assert layer.tracks["position"][1].value == (2.0, 2.5)  # x kept
    assert layer.tracks["position"][1].ease == Easing(name="linear")  # the key keeps its ease
    assert [k.t for k in layer.tracks["rotation"]] == [1.0, 3.0]  # another track's key at 1 s stays


def test_a_dragged_key_stays_more_than_a_frame_from_its_neighbours_and_snaps() -> None:
    _, new_t = drag(posed(), X, 1.0, 5.0, 2.0)
    assert new_t == pytest.approx(1.9)  # the key at 2 s minus a frame
    _, new_t = drag(posed(), ROT, 1.0, 2.5, 0.0)
    assert new_t == pytest.approx(2.5)  # only rotation's own neighbours bound it, not position's
    _, new_t = drag(posed(), X, 1.0, -3.0, 2.0)
    assert new_t == pytest.approx(0.1)
    marked = posed().model_copy(update={"markers": [Marker(id="m", t=1.57)]})
    _, new_t = drag(marked, X, 1.0, 1.52, 2.0)
    assert new_t == pytest.approx(1.6)  # snapped to the marker, then onto the frame grid by retime_keys
    _, new_t = drag(marked, X, 1.0, 1.52, 2.0, snapping=False)
    assert new_t == pytest.approx(1.5)


def test_a_drag_that_moves_nothing_returns_the_same_snapshot() -> None:
    start = posed()
    p, new_t = drag(start, X, 1.0, 1.02, 2.0)  # within half a frame, same value
    assert p is start and new_t == 1.0  # no edit at all: releasing records no undo step


def test_a_key_never_snaps_back_to_where_it_was() -> None:
    _, new_t = drag(posed(), X, 1.0, 1.07, 2.0)  # 7 px from its own time: the next frame
    assert new_t == pytest.approx(1.1)


def test_opacity_is_clamped_and_values_rounded() -> None:
    p, _ = drag(project(opacity=[Keyframe(t=1.0, value=0.5)]), OPACITY, 1.0, 1.0, 1.7)
    assert p.layer("a").tracks["opacity"][0].value == 1.0
    p, _ = drag(posed(), ROT, 3.0, 3.0, 12.3456789)
    assert p.layer("a").tracks["rotation"][1].value == 12.3457
    with pytest.raises(edits.EditError, match="no rotation key"):
        drag(posed(), ROT, 2.0, 2.5, 1.0)


def test_adding_a_key_keeps_the_motion() -> None:
    start = posed()
    edit = gm.add_key(start, "a", Y, 0.53)
    layer = edit.project.layer("a")
    added = next(k for k in layer.tracks["position"] if k.t == pytest.approx(0.5))
    assert added.value == pytest.approx(layer_transform(start.layer("a"), 0.5).position)
    started = gm.add_key(start, "a", SCALE_CURVE, 2.0).project.layer("a")
    assert [(k.t, k.value) for k in started.tracks["scale"]] == [(2.0, 1.0)]  # the base value
    assert gm.add_key(start, "a", SCALE_CURVE, 9.0).project.layer("a").tracks["scale"][0].t == 4.0


def test_deleting_and_easing_one_curve() -> None:
    layer = gm.delete_keys(posed(), "a", 1.0, ["rotation"]).project.layer("a")
    assert [k.t for k in layer.tracks["rotation"]] == [3.0] and len(layer.tracks["position"]) == 3
    layer = gm.delete_keys(posed(), "a", 1.0, None).project.layer("a")
    assert [k.t for k in layer.tracks["position"]] == [0.0, 2.0] and [
        k.t for k in layer.tracks["rotation"]
    ] == [3.0]
    ease = Easing(name="ease_out_back")
    layer = gm.set_segment_ease(posed(), "a", ROT, 1.0, ease).project.layer("a")
    assert layer.tracks["rotation"][0].ease == ease
    assert layer.tracks["position"][1].ease == Easing(name="linear")  # not the other curve's
    choices = gm.ease_choices()
    assert (
        choices[0] == Easing(name="smooth")
        and Easing(name=None, bezier=adapter.BEZIER_PRESETS["Overshoot"]) in choices
    )
