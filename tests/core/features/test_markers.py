"""Markers (P5c.1, ADR 0037): named moments on the ruler that change no frame.

They are part of the project (saved, undone, unique ids), at most one per frame
in the editor, kept in time order, invisible to render-ahead and the exports.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from manim_studio.core.editing import edits
from manim_studio.core.engine.frame_cache import changed_layers, changed_spans
from manim_studio.core.engine.python_export import to_python
from manim_studio.core.model.schema import AudioClip, Canvas, Clip, Cue, Layer, Marker, Project, Spec

CANVAS = Canvas(fps=10, duration=6.0)


def scene(*markers: Marker) -> Project:
    circle = Layer(id="c", spec=Spec(type="Circle"), clips=[Clip(id="f", kind="FadeIn", start=0, duration=1)])
    return Project(canvas=CANVAS, layers=[circle], markers=list(markers))


def test_markers_are_kept_in_time_order_and_saved_only_when_there_are_some() -> None:
    project = scene(Marker(id="b", t=3.0, name="Second"), Marker(id="a", t=1.0, name="First"))
    assert [m.id for m in project.markers] == ["a", "b"]
    again = Project.model_validate_json(project.model_dump_json(by_alias=True))
    assert again.markers == project.markers
    assert "markers" not in scene().model_dump(by_alias=True)
    assert Marker(id="m", t=0.5).colour == "#f59e0b"


@pytest.mark.parametrize(
    ("markers", "message"),
    [
        ([Marker(id="a", t=1.0), Marker(id="b", t=1.0)], "at the same time"),
        ([Marker(id="c", t=1.0)], "duplicate layer ids"),  # the circle's id
    ],
)
def test_invalid_markers_are_refused(markers, message) -> None:
    with pytest.raises(ValidationError, match=message):
        scene(*markers)
    with pytest.raises(ValidationError):
        Marker(id="m", t=-0.1)


def test_two_markers_one_frame_apart_and_an_fps_change_are_fine() -> None:
    project = scene(Marker(id="a", t=1.0), Marker(id="b", t=1.1))
    slower = project.model_copy(update={"canvas": CANVAS.model_copy(update={"fps": 5})})
    Project.model_validate(slower.model_dump())  # now on one frame: still a valid file


def test_adding_a_marker_puts_it_on_the_frame_grid_with_a_fresh_id() -> None:
    edit = edits.add_marker(scene(), 1.234, name="Intro")
    marker = edit.project.markers[0]
    assert (marker.t, marker.name) == (pytest.approx(1.2), "Intro")
    assert marker.id == "marker-1" and edit.kind == "timing" and edit.layer_ids == frozenset()
    assert edits.add_marker(edit.project, 3.0).project.markers[1].id == "marker-2"
    assert edits.new_layer_id(edit.project, "marker") == "marker-2"  # ids shared with layers
    assert edits.add_marker(scene(), -1.0).project.markers[0].t == 0.0


def test_one_marker_per_frame() -> None:
    project = edits.add_marker(scene(), 1.0).project
    with pytest.raises(edits.EditError, match="already at"):
        edits.add_marker(project, 1.04)  # the same frame at 10 fps
    two = edits.add_marker(project, 2.0).project
    with pytest.raises(edits.EditError, match="already at"):
        edits.update_marker(two, "marker-2", t=1.0)
    assert edits.update_marker(two, "marker-2", t=2.0).project.markers[1].t == 2.0  # its own frame
    assert edits.marker_at(two, 1.03).id == "marker-1" and edits.marker_at(two, 1.5) is None


def test_updating_and_removing() -> None:
    project = edits.add_marker(edits.add_marker(scene(), 1.0).project, 4.0).project
    moved = edits.update_marker(project, "marker-1", t=5.0, name="End", colour="#22d3ee").project
    assert [m.id for m in moved.markers] == ["marker-2", "marker-1"]  # re-sorted
    assert moved.markers[1].name == "End" and moved.markers[1].colour == "#22d3ee"
    assert [m.id for m in edits.remove_marker(moved, "marker-2").project.markers] == ["marker-1"]
    with pytest.raises(edits.EditError, match="no marker"):
        edits.remove_marker(moved, "zz")


def test_other_edits_keep_the_markers() -> None:
    project = edits.add_marker(scene(), 2.0).project
    for edit in (
        edits.add_layer(project, Spec(type="Square")),
        edits.add_audio(project, "x.wav", 1.0, 0.5),
        edits.add_cue(project, 0.5, 1.5, "Hi"),
        edits.set_subtitle_style(project, font_size=30),
    ):
        assert edit.project.markers == project.markers


def test_markers_change_no_frame() -> None:
    old = scene()
    new = edits.add_marker(old, 2.0, "Here").project
    assert changed_layers(old, new) == set()
    assert changed_spans(old, new) == []
    renamed = edits.update_marker(new, "marker-1", name="There").project
    assert changed_spans(new, renamed) == []


def test_exports_ignore_markers_but_the_exact_scene_carries_them() -> None:
    plain, marked = scene(), scene(Marker(id="m", t=2.0, name="Here"))
    assert to_python(marked, "S").code == to_python(plain, "S").code
    burned = marked.model_copy(update={"subtitles": [Cue(id="q", start=0, end=1, text="x")]})
    exact = to_python(burned, "S")  # burned-in subtitles make the export exact
    assert not exact.readable and '"markers"' in exact.code


def test_markers_share_the_id_namespace_with_sounds_and_cues() -> None:
    with pytest.raises(ValidationError, match="duplicate layer ids"):
        Project(
            canvas=CANVAS,
            audio=[AudioClip(id="s", path="x.wav", start=0, duration=1)],
            markers=[Marker(id="s", t=1.0)],
        )
