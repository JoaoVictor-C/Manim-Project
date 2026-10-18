"""Shifting timing (U4): move a whole layer, or a selection of clips and keys, by one delta.

The user's complaint: moving things on by hand, and a moved preset left "Appears at" behind
(an explicit appear time does not follow its clips)."""

from __future__ import annotations

import pytest

from manim_studio.core import edits
from manim_studio.core.schema import Canvas, Clip, Keyframe, Layer, Lifetime, Marker, Project, Spec
from manim_studio.core.shift_timing import Selection, remove_items, shift_timing, timing_warnings

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=30.0)
SQUARE = Spec(type="Square")


def clip(clip_id: str, kind: str, start: float, duration: float = 1.0) -> Clip:
    return Clip(id=clip_id, kind=kind, start=start, duration=duration)


def keys(*times: float) -> dict:
    return {"scale": [Keyframe(t=t, value=1.0 + t / 10) for t in times]}


def project(*layers: Layer, **extra) -> Project:
    return Project(canvas=CANVAS, layers=list(layers), **extra)


def starts(p: Project, layer_id: str) -> list[float]:
    return [c.start for c in p.layer(layer_id).clips]


def key_times(p: Project, layer_id: str, prop: str = "scale") -> list[float]:
    return [k.t for k in p.layer(layer_id).tracks[prop]]


# -- a whole layer -----------------------------------------------------------------------------


def test_a_whole_layer_moves_its_clips_keys_and_lifetime() -> None:
    layer = Layer(
        id="a",
        spec=SQUARE,
        lifetime=Lifetime(in_=2.0, out=9.0),
        clips=[clip("w", "Write", 2.0), clip("u", "Unwrite", 8.0)],
        tracks=keys(3.0, 5.0),
    )
    edit = shift_timing(project(layer), Selection(layers=("a",)), 5.0)
    out = edit.project.layer("a")
    assert starts(edit.project, "a") == [7.0, 13.0]
    assert key_times(edit.project, "a") == [8.0, 10.0]
    assert (out.lifetime.in_, out.lifetime.out) == (7.0, 14.0)
    assert edit.layer_ids == frozenset({"a"}) and edit.kind != "spec"  # keys moved: frames change


def test_automatic_lifetime_stays_automatic() -> None:
    layer = Layer(id="a", spec=SQUARE, clips=[clip("w", "Write", 2.0)])
    out = shift_timing(project(layer), Selection(layers=("a",)), 3.0).project.layer("a")
    assert out.lifetime.in_ is None and out.lifetime.out is None


def test_the_delta_is_clamped_so_nothing_goes_below_zero() -> None:
    a = Layer(id="a", spec=SQUARE, clips=[clip("w", "Write", 1.0)])
    b = Layer(id="b", spec=SQUARE, clips=[clip("w", "Write", 4.0)], tracks=keys(0.5))
    edit = shift_timing(project(a, b), Selection(layers=("a", "b")), -3.0)
    assert key_times(edit.project, "b") == [0.0]  # the earliest item (0.5) sets the limit: -0.5
    assert starts(edit.project, "a") == [0.5] and starts(edit.project, "b") == [3.5]  # all by -0.5


def test_a_zero_delta_changes_nothing() -> None:
    layer = Layer(id="a", spec=SQUARE, clips=[clip("w", "Write", 0.0)])
    p = project(layer)
    assert shift_timing(p, Selection(layers=("a",)), -2.0).project == p  # already at 0: nowhere to go


# -- clips and keys -----------------------------------------------------------------------------


def test_selected_clips_move_together_across_layers() -> None:
    a = Layer(id="a", spec=SQUARE, clips=[clip("w", "Write", 1.0), clip("i", "Indicate", 3.0)])
    b = Layer(id="b", spec=SQUARE, clips=[clip("f", "FadeIn", 2.0)])
    sel = Selection(clips=(("a", "i"), ("b", "f")))
    edit = shift_timing(project(a, b), sel, 1.5)
    assert starts(edit.project, "a") == [1.0, 4.5] and starts(edit.project, "b") == [3.5]
    assert edit.layer_ids == frozenset({"a", "b"})


def test_selected_keys_move_on_the_frame_grid_and_only_their_properties() -> None:
    layer = Layer(
        id="a",
        spec=SQUARE,
        tracks={**keys(1.0, 2.0), "rotation": [Keyframe(t=1.0, value=0.0), Keyframe(t=2.0, value=90.0)]},
    )
    sel = Selection(keys=(("a", 1.0, ("scale",)),))  # the scale key at 1 s only
    edit = shift_timing(project(layer), sel, 0.57)  # not on the 10 fps grid: rounded to it
    assert key_times(edit.project, "a") == [pytest.approx(1.6), 2.0]
    assert key_times(edit.project, "a", "rotation") == [1.0, 2.0]


def test_keys_of_every_property_at_a_time_move_when_no_props_are_named() -> None:
    layer = Layer(
        id="a",
        spec=SQUARE,
        tracks={**keys(1.0), "rotation": [Keyframe(t=1.0, value=0.0)]},
    )
    edit = shift_timing(project(layer), Selection(keys=(("a", 1.0, None),)), 2.0)
    assert key_times(edit.project, "a") == [3.0] and key_times(edit.project, "a", "rotation") == [3.0]


def test_a_move_that_collides_is_refused_whole() -> None:
    layer = Layer(id="a", spec=SQUARE, clips=[clip("w", "Write", 1.0), clip("i", "Indicate", 2.5)])
    with pytest.raises(edits.EditError):
        shift_timing(project(layer), Selection(clips=(("a", "w"),)), 1.0)  # Write would overlap Indicate


# -- the lifetime follows the boundary clip -----------------------------------------------------


def test_the_first_clip_carries_an_explicit_appears_at_that_matched_it() -> None:
    layer = Layer(
        id="a",
        spec=SQUARE,
        lifetime=Lifetime(in_=4.0),
        clips=[clip("f", "FadeIn", 4.0), clip("i", "Indicate", 6.0)],
    )
    edit = shift_timing(project(layer), Selection(clips=(("a", "f"),)), 3.0)
    assert edit.project.layer("a").lifetime.in_ == 7.0
    assert starts(edit.project, "a") == [6.0, 7.0]  # the Indicate at 6 s is now before the FadeIn: sorted


def test_a_deliberate_offset_is_not_carried() -> None:
    layer = Layer(id="a", spec=SQUARE, lifetime=Lifetime(in_=1.0), clips=[clip("f", "FadeIn", 1.5)])
    edit = shift_timing(project(layer), Selection(clips=(("a", "f"),)), 2.0)
    assert edit.project.layer("a").lifetime.in_ == 1.0


def test_only_the_boundary_clip_carries_in_and_the_last_carries_out() -> None:
    layer = Layer(
        id="a",
        spec=SQUARE,
        lifetime=Lifetime(in_=1.0, out=9.0),
        clips=[clip("w", "Write", 1.0), clip("i", "Indicate", 4.0), clip("u", "Unwrite", 8.0)],
    )
    p = project(layer)
    middle = shift_timing(p, Selection(clips=(("a", "i"),)), 1.0).project.layer("a")
    assert (middle.lifetime.in_, middle.lifetime.out) == (1.0, 9.0)
    last = shift_timing(p, Selection(clips=(("a", "u"),)), 2.0).project.layer("a")
    assert (last.lifetime.in_, last.lifetime.out) == (1.0, 11.0)


def test_keys_never_carry_the_lifetime() -> None:
    layer = Layer(
        id="a",
        spec=SQUARE,
        lifetime=Lifetime(in_=2.0),
        clips=[clip("f", "FadeIn", 2.0)],
        tracks=keys(2.0, 3.0),
    )
    edit = shift_timing(project(layer), Selection(keys=(("a", 2.0, None),)), 1.0)
    assert edit.project.layer("a").lifetime.in_ == 2.0


# -- warnings, other timed things ---------------------------------------------------------------


def test_a_lifetime_that_ends_before_its_animation_is_warned_about() -> None:
    layer = Layer(
        id="a",
        name="Title",
        spec=SQUARE,
        lifetime=Lifetime(out=3.0),
        clips=[clip("w", "Write", 0.0), clip("u", "Unwrite", 2.2, 0.8)],
    )
    ok = project(layer)
    assert timing_warnings(ok) == []
    moved = shift_timing(ok, Selection(clips=(("a", "w"),)), 0.0).project
    assert timing_warnings(moved) == []
    broken = edits.update_layer(ok, "a", lifetime=Lifetime(out=1.0)).project
    [warning] = timing_warnings(broken)
    assert "Title" in warning and "ends before" in warning


def test_markers_sounds_and_subtitles_can_ride_along() -> None:
    p = project(
        Layer(id="a", spec=SQUARE, clips=[clip("w", "Write", 1.0)]),
        markers=[Marker(id="m", t=2.0)],
    )
    edit = shift_timing(p, Selection(layers=("a",), markers=("m",)), 1.0)
    assert edit.project.markers[0].t == 3.0 and starts(edit.project, "a") == [2.0]


def test_an_empty_selection_is_refused() -> None:
    with pytest.raises(edits.EditError):
        shift_timing(project(Layer(id="a", spec=SQUARE)), Selection(), 1.0)


def test_a_disappears_at_that_did_not_match_the_last_clip_is_not_carried() -> None:
    layer = Layer(
        id="a",
        spec=SQUARE,
        lifetime=Lifetime(out=9.5),  # held on screen after the Unwrite on purpose
        clips=[clip("w", "Write", 1.0), clip("u", "Unwrite", 4.0)],
    )
    out = shift_timing(project(layer), Selection(clips=(("a", "u"),)), 2.0).project.layer("a")
    assert out.lifetime.out == 9.5


def test_a_lifetime_that_starts_after_its_animation_is_warned_about() -> None:
    layer = Layer(
        id="a", name="Late", spec=SQUARE, lifetime=Lifetime(in_=5.0), clips=[clip("w", "Write", 2.0)]
    )
    [warning] = timing_warnings(project(layer))
    assert "Late" in warning and "starts after" in warning


# -- several keys of one track (U4b: the timeline's multi-selection) ----------------------------


def test_keys_one_delta_apart_each_move_once() -> None:
    """Keys at 1 and 2 moved by 1 s: the key moved onto 2 is not picked up again by the pick at 2."""
    layer = Layer(id="a", spec=SQUARE, tracks=keys(1.0, 2.0, 6.0))
    picks = (("a", 1.0, None), ("a", 2.0, None))
    out = shift_timing(project(layer), Selection(keys=picks), 1.0).project
    assert key_times(out, "a") == [2.0, 3.0, 6.0]


def test_keys_moved_earlier_in_reverse_order_each_move_once() -> None:
    layer = Layer(id="a", spec=SQUARE, tracks=keys(1.0, 2.0, 3.0))
    picks = (("a", 3.0, None), ("a", 2.0, None), ("a", 1.0, None))
    out = shift_timing(project(layer), Selection(keys=picks), -1.0).project
    assert key_times(out, "a") == [0.0, 1.0, 2.0]


# -- removing several clips and keys at once (U4b) ----------------------------------------------


def test_remove_items_takes_clips_and_keys_in_one_edit() -> None:
    layers = (
        Layer(id="a", spec=SQUARE, clips=[clip("w", "Write", 1.0), clip("i", "Indicate", 4.0)]),
        Layer(id="b", spec=SQUARE, tracks=keys(1.0, 2.0, 3.0)),
    )
    picks = Selection(clips=(("a", "w"),), keys=(("b", 1.0, None), ("b", 3.0, ("scale",))))
    out = remove_items(project(*layers), picks).project
    assert [c.id for c in out.layer("a").clips] == ["i"]
    assert key_times(out, "b") == [2.0]


def test_removing_every_key_of_a_track_keeps_the_last_as_its_base() -> None:
    layer = Layer(id="a", spec=SQUARE, tracks=keys(1.0, 2.0))
    out = remove_items(project(layer), Selection(keys=(("a", 1.0, None), ("a", 2.0, None)))).project
    assert "scale" not in out.layer("a").tracks
    assert out.layer("a").base.scale == pytest.approx(1.2)  # the key removed last held 1.2


def test_a_key_already_removed_by_a_wider_pick_is_not_an_error() -> None:
    layer = Layer(id="a", spec=SQUARE, tracks=keys(1.0, 2.0))
    picks = Selection(keys=(("a", 1.0, None), ("a", 1.0, ("scale",))))
    out = remove_items(project(layer), picks).project
    assert key_times(out, "a") == [2.0]


def test_remove_items_refuses_nothing_selected() -> None:
    with pytest.raises(edits.EditError):
        remove_items(project(Layer(id="a", spec=SQUARE)), Selection())


def a_group() -> Project:
    group = Layer(id="g", spec=Spec(type="Group"), lifetime=Lifetime(in_=1.0, out=9.0))
    kids = [
        Layer(id="k1", parent_id="g", spec=SQUARE, clips=[clip("w", "Write", 1.0)], tracks=keys(2.0, 3.0)),
        Layer(id="k2", parent_id="g", spec=SQUARE, clips=[clip("f", "FadeIn", 4.0)]),
    ]
    return project(group, *kids)


def test_shifting_a_group_shifts_its_children_too() -> None:
    """A group has no clips of its own: moving it moves what is inside (ADR 0050)."""
    edit = shift_timing(a_group(), Selection(layers=("g",)), 2.0)
    assert starts(edit.project, "k1") == [3.0] and starts(edit.project, "k2") == [6.0]
    assert key_times(edit.project, "k1") == [4.0, 5.0]
    life = edit.project.layer("g").lifetime
    assert (life.in_, life.out) == (3.0, 11.0)


def test_the_clamp_and_the_reach_see_a_groups_children() -> None:
    from manim_studio.core.shift_timing import earliest, latest

    sel = Selection(layers=("g",))
    assert earliest(a_group(), sel) == 1.0 and latest(a_group(), sel) == 9.0
    edit = shift_timing(a_group(), sel, -5.0)  # the group's Appears at (1.0) is the earliest: -1.0
    assert starts(edit.project, "k1") == [0.0] and edit.project.layer("g").lifetime.in_ == 0.0
