"""Timeline geometry and drag rules (S1 plan, "Interaction rules") — no Qt needed."""

from __future__ import annotations

import pytest

from manim_studio.core.schema import Canvas, Clip, Layer, Project, Spec
from manim_studio.ui.timeline.model import (
    TimeScale,
    drag_move,
    drag_trim,
    move_bounds,
    quantize,
    snap,
    snap_candidates,
    trim_bounds,
)

FPS = 30
DURATION = 10.0
SCALE = TimeScale(px_per_second=100)  # 8 px snap radius = 0.08 s


def lane() -> Layer:
    return Layer(
        id="a",
        spec=Spec(type="Square"),
        clips=[
            Clip(id="c1", kind="Create", start=1.0, duration=1.0),
            Clip(id="c2", kind="Indicate", start=3.0, duration=1.0),
            Clip(id="c3", kind="FadeOut", start=6.0, duration=1.0),
        ],
    )


# -- TimeScale ----------------------------------------------------------------------


@pytest.mark.parametrize("pps", [10, 37.5, 100, 2400])
@pytest.mark.parametrize("offset", [0.0, 2.5])
def test_time_x_round_trip(pps: float, offset: float) -> None:
    scale = TimeScale(pps, offset)
    for t in (0.0, 0.123, 4.0, 9.99):
        assert scale.t(scale.x(t)) == pytest.approx(t)


def test_zoom_keeps_the_time_under_the_anchor() -> None:
    scale = TimeScale(100, 1.0)
    anchor_x = 340.0
    before = scale.t(anchor_x)
    for factor in (1.25, 0.5, 3.0):
        scale = scale.zoomed(factor, anchor_x)
        assert scale.t(anchor_x) == pytest.approx(before)


def test_zoom_is_clamped() -> None:
    assert TimeScale(100).zoomed(1e-6, 0).px_per_second == 10
    assert TimeScale(100).zoomed(1e6, 0).px_per_second == 4000


# -- quantize / snap -----------------------------------------------------------------


def test_quantize_to_frames() -> None:
    assert quantize(1.01, 30) == pytest.approx(1.0)
    assert quantize(1.02, 30) == pytest.approx(31 / 30)


def test_snap_prefers_a_candidate_within_radius() -> None:
    assert snap(2.95, [3.0], SCALE, FPS) == 3.0  # 5 px away


def test_snap_ignores_candidates_outside_radius() -> None:
    assert snap(2.9, [3.0], SCALE, FPS) == pytest.approx(quantize(2.9, FPS))  # 10 px away


def test_snap_radius_is_in_pixels_so_it_follows_zoom() -> None:
    assert snap(2.9, [3.0], TimeScale(px_per_second=50), FPS) == 3.0  # 5 px at this zoom


def test_snapping_disabled_keeps_only_the_frame_grid() -> None:
    assert snap(2.99, [3.0004], SCALE, FPS, enabled=False) == pytest.approx(3.0)
    assert snap(2.99, [3.0004], SCALE, FPS, enabled=True) == 3.0004


def test_snap_candidates_exclude_the_dragged_clip() -> None:
    project = Project(canvas=Canvas(duration=DURATION), layers=[lane()])
    points = snap_candidates(project, playhead=4.5, exclude=("a", "c2"))
    assert points == [0.0, 1.0, 2.0, 4.5, 6.0, 7.0, 10.0]


# -- bounds --------------------------------------------------------------------------


def test_move_bounds_stop_at_neighbours() -> None:
    assert move_bounds(lane(), "c2", DURATION) == (2.0, 5.0)


def test_move_bounds_at_lane_ends() -> None:
    assert move_bounds(lane(), "c1", DURATION) == (0.0, 2.0)
    assert move_bounds(lane(), "c3", DURATION) == (4.0, 9.0)


def test_trim_bounds_keep_one_frame() -> None:
    lo, hi = trim_bounds(lane(), "c2", "start", DURATION, FPS)
    assert (lo, hi) == pytest.approx((2.0, 4.0 - 1 / FPS))
    lo, hi = trim_bounds(lane(), "c2", "end", DURATION, FPS)
    assert (lo, hi) == pytest.approx((3.0 + 1 / FPS, 6.0))


def test_trim_end_of_last_clip_is_bounded_by_canvas() -> None:
    assert trim_bounds(lane(), "c3", "end", DURATION, FPS)[1] == DURATION


# -- drag rules ----------------------------------------------------------------------


def _move(proposed: float, **kw) -> float:
    return drag_move(lane(), "c2", proposed, duration=DURATION, fps=FPS, scale=SCALE, **kw)


def test_move_clamps_instead_of_overlapping() -> None:
    assert _move(1.2) == 2.0  # would overlap c1
    assert _move(5.8) == 5.0  # would overlap c3


def test_move_snaps_the_start_edge() -> None:
    assert _move(4.47, candidates=[4.5]) == 4.5


def test_move_snaps_the_end_edge() -> None:
    assert _move(3.47, candidates=[4.5]) == 3.5  # end 4.47 -> 4.5


def test_move_without_snapping_is_frame_quantized() -> None:
    assert _move(3.511, candidates=[3.5], snapping=False) == pytest.approx(quantize(3.511, FPS))


def test_trim_clamps_and_snaps() -> None:
    def trim(edge, t, **kw):
        return drag_trim(lane(), "c2", edge, t, duration=DURATION, fps=FPS, scale=SCALE, **kw)

    assert trim("start", 0.5) == (2.0, 4.0)
    assert trim("end", 9.0) == (3.0, 6.0)
    assert trim("end", 3.0) == pytest.approx((3.0, 3.0 + 1 / FPS))
    assert trim("end", 4.96, candidates=[5.0]) == (3.0, 5.0)


def test_dragged_results_are_valid_documents() -> None:
    """Whatever the mouse does, clamped results always validate (ADR 0014)."""
    from manim_studio.core import edits

    project = Project(canvas=Canvas(duration=DURATION, fps=FPS), layers=[lane()])
    for proposed in [x / 7 for x in range(-20, 90)]:
        start = drag_move(project.layers[0], "c2", proposed, duration=DURATION, fps=FPS, scale=SCALE)
        edits.move_clip(project, "a", "c2", start)
        for edge in ("start", "end"):
            new_start, new_end = drag_trim(
                project.layers[0], "c2", edge, proposed, duration=DURATION, fps=FPS, scale=SCALE
            )
            edits.trim_clip(project, "a", "c2", start=new_start, end=new_end)
