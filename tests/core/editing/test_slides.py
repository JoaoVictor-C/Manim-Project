"""Slides (ADR 0087): stop markers cut the scene into slides that present mode and the HTML deck share.

A slide ends on its stop's frame (included) and the next starts one frame later; frames are counted on the
export's grid, ``[first, last)`` like ``render.options.frame_window``.
"""

from __future__ import annotations

import json

import pytest

from manim_studio.core.editing import edits, ripple, slides
from manim_studio.core.editing.edits import EditError
from manim_studio.core.editing.shift_timing import Selection, shift_timing
from manim_studio.core.model.schema import Canvas, Marker, Project

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=6.0)  # 60 frames, 0..59


def stop(marker_id: str, t: float, loop: float | None = None) -> Marker:
    return Marker(id=marker_id, t=t, slide="stop", loop=loop)


def scene(*markers: Marker) -> Project:
    return Project(canvas=CANVAS, markers=list(markers))


def ranges(project: Project) -> list[tuple[int, int]]:
    return [(s.first, s.last) for s in slides.windows(project)]


# -- the model -------------------------------------------------------------------------------


def test_plain_markers_save_as_before() -> None:
    plain = scene(Marker(id="m", t=1.0, name="beat"))
    assert json.loads(plain.model_dump_json())["markers"] == [
        {"id": "m", "t": 1.0, "name": "beat", "colour": "#f59e0b"}
    ]


def test_a_stop_and_its_loop_round_trip() -> None:
    project = scene(stop("s", 2.0, loop=0.5))
    data = json.loads(project.model_dump_json())["markers"][0]
    assert data["slide"] == "stop" and data["loop"] == 0.5
    again = Project.model_validate_json(project.model_dump_json())
    assert again.markers[0].slide == "stop" and again.markers[0].loop == 0.5


@pytest.mark.parametrize("loop", [0.0, -1.0])
def test_a_loop_must_be_longer_than_nothing(loop: float) -> None:
    with pytest.raises(ValueError):
        stop("s", 2.0, loop=loop)


# -- windows ---------------------------------------------------------------------------------


def test_no_stops_is_one_slide_the_whole_scene() -> None:
    assert ranges(scene()) == [(0, 60)]
    assert ranges(scene(Marker(id="m", t=2.0))) == [(0, 60)]  # plain markers do not cut


def test_a_slide_ends_on_its_stop_frame() -> None:
    project = scene(stop("a", 2.0), Marker(id="note", t=3.0), stop("b", 4.0))
    assert ranges(project) == [(0, 21), (21, 41), (41, 60)]
    found = slides.windows(project)
    assert [s.stop.id if s.stop else None for s in found] == ["a", "b", None]
    assert [s.index for s in found] == [0, 1, 2]
    assert found[0].start == 0.0 and found[0].end == pytest.approx(2.1)
    assert found[0].stop_time == pytest.approx(2.0)


def test_a_stop_on_frame_zero_is_a_title_slide() -> None:
    assert ranges(scene(stop("title", 0.0))) == [(0, 1), (1, 60)]


def test_a_stop_on_the_last_frame_leaves_no_empty_slide() -> None:
    assert ranges(scene(stop("end", 5.9))) == [(0, 60)]
    assert slides.windows(scene(stop("end", 5.9)))[0].stop.id == "end"


def test_a_stop_past_the_end_counts_as_the_last_frame() -> None:
    assert ranges(scene(stop("late", 9.0))) == [(0, 60)]
    assert ranges(scene(stop("end", 5.9), stop("late", 9.0))) == [(0, 60)]  # both on frame 59: one slide


def test_stops_that_fall_on_one_frame_at_a_lower_fps_make_one_slide() -> None:
    canvas = Canvas(width_px=320, height_px=180, fps=20, duration=6.0)
    fine = Project(canvas=canvas, markers=[stop("a", 1.95), stop("b", 2.0)])  # frames 39 and 40 at 20 fps
    found = slides.windows(fine, fps=10)  # both on frame 20 at 10 fps
    assert [(s.first, s.last) for s in found] == [(0, 21), (21, 60)]
    assert [s.stop.id if s.stop else None for s in found] == ["a", None]  # b is dropped


def test_two_stops_a_frame_apart_make_a_one_frame_slide() -> None:
    assert ranges(scene(stop("a", 2.0), stop("b", 2.1))) == [(0, 21), (21, 22), (22, 60)]


def test_windows_follow_the_fps_they_are_asked_for() -> None:
    project = scene(stop("a", 2.0))
    assert [(s.first, s.last) for s in slides.windows(project, fps=30)] == [(0, 61), (61, 180)]


# -- loops -----------------------------------------------------------------------------------


def test_a_slide_without_a_loop_has_none() -> None:
    project = scene(stop("a", 2.0))
    assert slides.loop_window(slides.windows(project)[0]) is None
    assert slides.loop_window(slides.windows(project)[1]) is None  # the last slide has no stop


def test_a_loop_is_the_frames_before_its_stop() -> None:
    first = slides.windows(scene(stop("a", 2.0, loop=0.5)))[0]
    assert slides.loop_window(first) == (16, 21)


def test_a_loop_is_at_least_one_frame_and_at_most_the_slide() -> None:
    tiny = slides.windows(scene(stop("a", 2.0, loop=0.01)))[0]
    assert slides.loop_window(tiny) == (20, 21)
    long = slides.windows(scene(stop("a", 1.0), stop("b", 2.0, loop=30.0)))[1]
    assert slides.loop_window(long) == (11, 21)


# -- moving between slides ------------------------------------------------------------------


def test_slide_at_and_the_stops_around_a_time() -> None:
    project = scene(stop("a", 2.0), stop("b", 4.0))
    assert [slides.slide_at(project, t).index for t in (0.0, 2.0, 2.1, 4.0, 5.95)] == [0, 0, 1, 1, 2]
    assert slides.next_stop(project, 0.0).id == "a"
    assert slides.next_stop(project, 2.0).id == "b"  # standing on a stop: the next one
    assert slides.next_stop(project, 4.0) is None
    assert slides.previous_stop(project, 4.0).id == "a"
    assert slides.previous_stop(project, 3.0).id == "a"
    assert slides.previous_stop(project, 2.0) is None


# -- editing ---------------------------------------------------------------------------------


def test_add_slide_stop_makes_a_marker_or_turns_one_into_a_stop() -> None:
    project = scene(Marker(id="m", t=1.0, name="intro"))
    turned = edits.add_slide_stop(project, 1.0).project
    assert [(m.id, m.slide, m.name) for m in turned.markers] == [("m", "stop", "intro")]
    added = edits.add_slide_stop(turned, 3.04).project
    assert [(m.t, m.slide) for m in added.markers] == [(1.0, "stop"), (3.0, "stop")]
    with pytest.raises(EditError):
        edits.add_slide_stop(added, 3.0)  # already a stop


def test_update_marker_sets_and_clears_the_slide_fields() -> None:
    project = scene(Marker(id="m", t=1.0))
    on = edits.update_marker(project, "m", slide="stop", loop=0.5).project
    assert (on.markers[0].slide, on.markers[0].loop) == ("stop", 0.5)
    off = edits.update_marker(on, "m", slide=None, loop=None).project
    assert (off.markers[0].slide, off.markers[0].loop) == (None, None)
    assert "slide" not in json.loads(off.model_dump_json())["markers"][0]


def test_stops_move_with_the_content_and_keep_their_loop() -> None:
    project = scene(stop("a", 2.0, loop=0.5))
    shifted = shift_timing(project, Selection(markers=("a",)), 1.0).project
    assert (shifted.markers[0].t, shifted.markers[0].slide, shifted.markers[0].loop) == (3.0, "stop", 0.5)
    rippled = ripple.ripple(project, 1.0, 1.0).project
    assert (rippled.markers[0].t, rippled.markers[0].slide, rippled.markers[0].loop) == (3.0, "stop", 0.5)
