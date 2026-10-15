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
    points = snap_candidates(project, playhead=4.5, exclude=[("clip", "a", "c2")])
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


# -- adding clips (S2.6) -------------------------------------------------------------


def test_new_clip_starts_at_the_click_and_fits_the_gap() -> None:
    from manim_studio.ui.timeline.model import place_new_clip

    def place(t):
        return place_new_clip(lane(), t, duration=DURATION, fps=FPS)

    assert place(4.2) == pytest.approx((4.2, 1.0))  # gap 4-6
    assert place(5.5) == pytest.approx((5.5, 0.5))  # shortened by c3 at 6.0
    assert place(0.3) == pytest.approx((0.3, 0.7))  # before c1
    assert place(8.0) == pytest.approx((8.0, 1.0))
    assert place(9.9) == pytest.approx((9.9, 0.1))  # canvas end
    assert place(1.5) is None  # on c1


def test_new_clip_keeps_one_frame_at_the_end_of_a_gap() -> None:
    from manim_studio.ui.timeline.model import place_new_clip

    start, length = place_new_clip(lane(), 5.999, duration=DURATION, fps=FPS)
    assert start == pytest.approx(6.0 - 1 / FPS) and length == pytest.approx(1 / FPS)


def test_nothing_goes_after_a_morph_or_into_a_gap_under_a_frame() -> None:
    from manim_studio.ui.timeline.model import place_new_clip

    morphing = Layer(
        id="m",
        spec=Spec(type="Square"),
        clips=[Clip(id="x", kind="Transform", start=1.0, duration=1.0, to_layer="t")],
    )
    assert place_new_clip(morphing, 3.0, duration=DURATION, fps=FPS) is None
    assert place_new_clip(morphing, 0.5, duration=DURATION, fps=FPS) == pytest.approx((0.5, 0.5))
    tight = Layer(
        id="t",
        spec=Spec(type="Square"),
        clips=[
            Clip(id="a", kind="FadeIn", start=0, duration=1.0),
            Clip(id="b", kind="FadeOut", start=1.01, duration=1),
        ],
    )
    assert place_new_clip(tight, 1.005, duration=DURATION, fps=FPS) is None


# -- keyframes (P2b) ------------------------------------------------------------------


def keyed_lane() -> Layer:
    from manim_studio.core.schema import Keyframe

    return Layer(
        id="k",
        spec=Spec(type="Square"),
        tracks={
            "position": [
                Keyframe(t=0.5, value=(0, 0)),
                Keyframe(t=1.0, value=(1, 0)),
                Keyframe(t=2.0, value=(2, 0)),
            ],
            "rotation": [Keyframe(t=0.0, value=0.0), Keyframe(t=1.01, value=90.0)],
        },
    )


def test_key_times_merge_properties_within_half_a_frame() -> None:
    from manim_studio.ui.timeline.model import key_times

    assert key_times(keyed_lane(), FPS) == [
        (0.0, ("rotation",)),
        (0.5, ("position",)),
        (1.0, ("position", "rotation")),
        (2.0, ("position",)),
    ]


def test_moving_keys_is_clamped_by_each_moved_property() -> None:
    from manim_studio.ui.timeline.model import drag_keys, key_bounds

    lo, hi = key_bounds(keyed_lane(), 1.0, DURATION, FPS)
    assert (lo, hi) == pytest.approx((0.5 + 1 / FPS, 2.0 - 1 / FPS))  # position's neighbours are tighter
    moved = drag_keys(keyed_lane(), 1.0, 0.2, duration=DURATION, fps=FPS, scale=SCALE)
    assert moved == pytest.approx(0.5 + 1 / FPS)
    assert (
        drag_keys(keyed_lane(), 1.0, 1.47, duration=DURATION, fps=FPS, scale=SCALE, candidates=[1.5]) == 1.5
    )


# -- part layers (P2c.3) ----------------------------------------------------------------


def tree_project() -> Project:
    from manim_studio.core.schema import PartKey

    eq = Layer(
        id="eq",
        spec=Spec(type="MathTex", params={"text": "a + b = c"}),
        clips=[Clip(id="w", kind="Write", start=0.0, duration=1.0)],
    )
    b = Layer(
        id="b",
        parent_id="eq",
        part=PartKey(tex="b"),
        clips=[Clip(id="i", kind="Indicate", start=2.0, duration=1.0)],
    )
    c = Layer(
        id="c",
        parent_id="eq",
        part=PartKey(tex="c"),
        clips=[Clip(id="f", kind="FadeOut", start=2.5, duration=1.0)],
    )
    sq = Layer(id="sq", spec=Spec(type="Square"))
    return Project(canvas=Canvas(duration=5.0), layers=[eq, b, c, sq])


def test_rows_put_parts_under_their_object() -> None:
    from manim_studio.ui.timeline.model import depth, rows

    project = tree_project()
    assert [layer.id for layer in rows(project)] == ["sq", "eq", "b", "c"]
    assert [depth(project, layer) for layer in rows(project)] == [0, 0, 1, 1]


def test_a_part_clip_moves_around_its_ancestors_clips_but_not_its_siblings() -> None:
    from manim_studio.ui.timeline.model import move_bounds, obstacles

    project = tree_project()
    assert [c.id for c in obstacles(project, "b")] == ["w"]  # not the sibling's FadeOut
    assert [c.id for c in obstacles(project, "eq")] == ["i", "f"]
    lo, hi = move_bounds(project.layer("b"), "i", 5.0, obstacles(project, "b"))
    assert (lo, hi) == (1.0, 4.0)
    lo, hi = move_bounds(project.layer("eq"), "w", 5.0, obstacles(project, "eq"))
    assert (lo, hi) == (0.0, 1.0)  # the object's Write may not run into its parts' clips


def test_new_clips_on_a_part_avoid_ancestor_clips() -> None:
    from manim_studio.ui.timeline.model import obstacles, place_new_clip

    project = tree_project()
    b, block = project.layer("b"), obstacles(project, "b")
    assert place_new_clip(b, 0.5, duration=5.0, fps=10, obstacles=block) is None  # inside the Write
    assert place_new_clip(b, 1.2, duration=5.0, fps=10, obstacles=block) == (1.2, 0.8)
    eq = project.layer("eq")
    assert place_new_clip(eq, 2.2, duration=5.0, fps=10, obstacles=obstacles(project, "eq")) is None


# -- snapping to every row and to markers (P5c, ADR 0037) -------------------------------


def busy() -> Project:
    from manim_studio.core.schema import AudioClip, Cue, Keyframe, Marker

    keyed = lane().model_copy(
        update={"tracks": {"opacity": [Keyframe(t=4.5, value=1.0), Keyframe(t=8.0, value=0.0)]}}
    )
    return Project(
        canvas=Canvas(duration=DURATION, fps=FPS),
        layers=[keyed],
        audio=[AudioClip(id="s", path="x.wav", start=2.5, duration=0.6)],
        subtitles=[Cue(id="q", start=5.0, end=5.5, text="Hi")],
        markers=[Marker(id="m", t=9.0)],
    )


def test_every_row_and_every_marker_is_a_snap_point() -> None:
    points = snap_candidates(busy(), playhead=0.5)
    for t in (0.0, 0.5, 1.0, 2.0, 2.5, 3.1, 4.5, 5.0, 5.5, 8.0, 9.0, 10.0):
        assert any(abs(p - t) < 1e-9 for p in points), t


@pytest.mark.parametrize(
    ("item", "gone"),
    [
        (("clip", "a", "c1"), (1.0, 2.0)),
        (("key", "a", 4.5), (4.5,)),
        (("audio", "s"), (2.5, 3.1)),
        (("cue", "q"), (5.0, 5.5)),
        (("marker", "m"), (9.0,)),
    ],
)
def test_the_dragged_item_is_not_its_own_snap_point(item, gone) -> None:
    every = snap_candidates(busy(), playhead=0.5)
    points = snap_candidates(busy(), playhead=0.5, exclude=[item])
    for t in gone:
        assert not any(abs(p - t) < 1e-9 for p in points), t
    assert len(every) - len(points) == len(gone)  # nothing else left out


def test_a_key_drag_leaves_out_only_the_keys_on_its_frame() -> None:
    points = snap_candidates(busy(), playhead=0.5, exclude=[("key", "a", 4.5 + 0.2 / FPS)])
    assert 4.5 not in points and 8.0 in points
    assert 4.5 in snap_candidates(busy(), playhead=0.5, exclude=[("key", "other", 4.5)])


def test_snapped_tells_when_an_edge_rests_on_a_point() -> None:
    from manim_studio.ui.timeline.model import snapped

    assert snapped(9.0, [1.0, 9.0]) and not snapped(9.01, [1.0, 9.0])


def test_a_marker_drag_snaps_and_never_lands_on_another_marker() -> None:
    from manim_studio.core.schema import Marker
    from manim_studio.ui.timeline.model import drag_marker

    project = Project(
        canvas=Canvas(duration=DURATION, fps=FPS),
        layers=[lane()],
        markers=[Marker(id="m", t=9.0), Marker(id="n", t=5.0)],
    )
    candidates = snap_candidates(project, playhead=0.0, exclude=[("marker", "n")])
    snap_to_c2 = drag_marker(project, "n", 2.97, 5.0, scale=SCALE, candidates=candidates)
    assert snap_to_c2 == 3.0  # c2's start
    assert drag_marker(project, "n", 6.51, 5.0, scale=SCALE, candidates=candidates) == pytest.approx(6.5)
    assert drag_marker(project, "n", 9.02, 6.5, scale=SCALE, candidates=candidates) == 6.5  # m's frame: stays
    assert drag_marker(project, "n", 12.0, 6.5, scale=SCALE, candidates=candidates) == DURATION
    assert drag_marker(project, "n", -1.0, 6.5, scale=SCALE, candidates=candidates) == 0.0
    assert drag_marker(project, "n", 2.97, 5.0, scale=SCALE, snapping=False) == pytest.approx(
        2.9666, abs=1e-3
    )


def test_fit_scale_shows_the_whole_scene_within_the_zoom_limits() -> None:
    from manim_studio.ui.timeline.model import (
        FIT_MARGIN_PX,
        MAX_PX_PER_SECOND,
        MIN_PX_PER_SECOND,
        fit_scale,
    )

    assert fit_scale(5.0, 500 + FIT_MARGIN_PX).px_per_second == pytest.approx(100.0)
    assert fit_scale(0.0, 800).px_per_second == MAX_PX_PER_SECOND  # a zero-length scene
    assert fit_scale(3600.0, 300).px_per_second == MIN_PX_PER_SECOND  # an hour in 300 px
    assert fit_scale(5.0, 500).offset == 0.0
