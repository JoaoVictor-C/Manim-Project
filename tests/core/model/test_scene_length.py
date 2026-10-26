"""The scene's length (P7.1): set by hand, or growing with what it holds."""

from __future__ import annotations

import pytest

from manim_studio.core.editing import edits
from manim_studio.core.engine.frame_cache import changed_spans
from manim_studio.core.model import scene_length
from manim_studio.core.model.schema import (
    AudioClip,
    Canvas,
    Clip,
    Cue,
    Keyframe,
    Layer,
    Lifetime,
    Marker,
    Project,
    Spec,
)

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=4.0)
CIRCLE = Spec(type="Circle")


def scene(**fields) -> Project:
    return Project(canvas=CANVAS, layers=[Layer(id="c", spec=CIRCLE, **fields)])


def test_an_empty_scene_ends_at_zero() -> None:
    assert scene_length.content_end(Project(canvas=CANVAS)) == 0.0


@pytest.mark.parametrize(
    ("project", "end"),
    [
        (scene(clips=[Clip(id="w", kind="Write", start=5.0, duration=1.5)]), 6.5),
        (scene(tracks={"opacity": [Keyframe(t=0.0, value=1.0), Keyframe(t=7.0, value=0.0)]}), 7.0),
        (scene(lifetime=Lifetime(in_=0.0, out=8.0)), 8.0),
        (Project(canvas=CANVAS, audio=[AudioClip(id="s", path="a.wav", start=3.0, duration=6.0)]), 9.0),
        (Project(canvas=CANVAS, subtitles=[Cue(id="q", start=9.0, end=10.0)]), 10.0),
        (Project(canvas=CANVAS, markers=[Marker(id="m", t=11.0)]), 11.0),
    ],
    ids=["clip", "key", "lifetime", "sound", "cue", "marker"],
)
def test_every_kind_of_content_counts(project: Project, end: float) -> None:
    assert scene_length.content_end(project) == pytest.approx(end)


def test_the_scene_grows_to_a_whole_frame_past_its_content() -> None:
    project = scene(clips=[Clip(id="w", kind="Write", start=4.0, duration=0.42)])
    grown = scene_length.grow_to_fit(project)
    assert grown.canvas.duration == pytest.approx(4.5)  # 4.42 s -> the next frame at 10 fps
    assert grown.layers == project.layers


def test_content_inside_the_scene_changes_nothing() -> None:
    project = scene(clips=[Clip(id="w", kind="Write", start=1.0, duration=3.0)])
    assert scene_length.grow_to_fit(project) is project


def test_a_scene_that_does_not_grow_keeps_its_length() -> None:
    project = scene(clips=[Clip(id="w", kind="Write", start=4.0, duration=2.0)])
    fixed = project.model_copy(update={"canvas": CANVAS.model_copy(update={"grow_with_content": False})})
    assert scene_length.grow_to_fit(fixed) is fixed


def test_fit_to_content_trims_and_grows() -> None:
    short = scene(clips=[Clip(id="w", kind="Write", start=0.0, duration=1.25)])
    assert scene_length.fit_to_content(short).canvas.duration == pytest.approx(1.3)
    long = scene(clips=[Clip(id="w", kind="Write", start=0.0, duration=6.0)])
    assert scene_length.fit_to_content(long).canvas.duration == pytest.approx(6.0)


def test_fit_to_content_leaves_an_untimed_scene_alone() -> None:
    """Objects there from the start with no animation (their end on "auto"): nothing to fit to,
    so the scene keeps its length instead of shrinking to one frame (the user's report)."""
    assert scene_length.fit_to_content(Project(canvas=CANVAS)) == Project(canvas=CANVAS)
    still = scene()
    assert scene_length.fit_to_content(still) is still


def test_an_object_that_appears_late_counts_from_when_it_appears() -> None:
    late = scene(lifetime=Lifetime(in_=3.0))
    assert scene_length.content_end(late) == pytest.approx(3.0)
    assert scene_length.fit_to_content(late).canvas.duration == pytest.approx(3.0)


def test_ends_only_the_window_knows_count_too() -> None:
    """A code layer's rendered animation (its length is known once it is rendered)."""
    assert scene_length.fit_to_content(scene(), [2.25]).canvas.duration == pytest.approx(2.3)


def test_set_canvas_changes_the_length_without_touching_layers() -> None:
    project = scene()
    edit = edits.set_canvas(project, duration=12.0)
    assert edit.project.canvas.duration == 12.0
    assert edit.project.layers == project.layers
    assert (edit.kind, edit.layer_ids) == ("timing", frozenset())


def test_set_canvas_on_the_picture_changes_every_layer() -> None:
    edit = edits.set_canvas(scene(), background="#ffffff")
    assert edit.project.canvas.background == "#ffffff"
    assert (edit.kind, edit.layer_ids) == ("spec", frozenset({"c"}))


def test_set_canvas_refuses_what_is_not_a_scene_setting() -> None:
    with pytest.raises(edits.EditError):
        edits.set_canvas(scene(), frame_height=4.0)
    with pytest.raises(ValueError):
        edits.set_canvas(scene(), duration=-1.0)


def test_a_longer_scene_keeps_every_rendered_frame() -> None:
    """The length draws nothing: render-ahead keeps its frames when the scene grows."""
    project = scene()
    assert changed_spans(project, edits.set_canvas(project, duration=20.0).project) == []
    assert changed_spans(project, edits.set_canvas(project, grow_with_content=False).project) == []
    assert changed_spans(project, edits.set_canvas(project, fps=24).project) is None
