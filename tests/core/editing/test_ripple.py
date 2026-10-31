"""Linked ripple editing (ADR 0071): time opened or closed at a point, what follows moving with it."""

from __future__ import annotations

import pytest

from manim_studio.core.editing import edits, ripple
from manim_studio.core.model.schema import (
    AudioClip,
    Canvas,
    Clip,
    Cue,
    Keyframe,
    Layer,
    Marker,
    Project,
    Spec,
)

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=6.0)


def clip(clip_id: str, start: float, duration: float = 1.0) -> Clip:
    return Clip(id=clip_id, kind="FadeIn", start=start, duration=duration)


def scene() -> Project:
    a = Layer(id="a", spec=Spec(type="Square"), clips=[clip("a1", 0.0), clip("a2", 2.0), clip("a3", 4.0)])
    b = Layer(
        id="b",
        spec=Spec(type="Circle"),
        clips=[clip("b1", 4.0)],
        tracks={"opacity": [Keyframe(t=1.0, value=0.0), Keyframe(t=4.5, value=1.0)]},
    )
    return Project(
        canvas=CANVAS,
        layers=[a, b],
        audio=[
            AudioClip(id="s1", path="x.wav", start=1.0, duration=1.0),
            AudioClip(id="s2", path="y.wav", start=3.0, duration=1.0),
        ],
        subtitles=[
            Cue(id="c1", start=0.5, end=1.5, text="one"),
            Cue(id="c2", start=3.5, end=4.5, text="two"),
        ],
        markers=[Marker(id="m1", t=2.0, name="middle"), Marker(id="m2", t=4.0, name="end")],
    )


def starts(project: Project) -> dict[str, float]:
    out = {c.id: c.start for layer in project.layers for c in layer.clips}
    out |= {a.id: a.start for a in project.audio} | {c.id: c.start for c in project.subtitles}
    out |= {m.id: m.t for m in project.markers}
    return out


def test_everything_that_starts_at_or_after_the_point_moves_and_the_rest_stays() -> None:
    edit = ripple.ripple(scene(), 2.0, 1.0)
    now = starts(edit.project)
    assert (now["a1"], now["a2"], now["a3"], now["b1"]) == (0.0, 3.0, 5.0, 5.0)
    assert (now["s1"], now["s2"], now["c1"], now["c2"]) == (1.0, 4.0, 0.5, 4.5)
    assert (now["m1"], now["m2"]) == (3.0, 5.0)
    keys = [k.t for k in edit.project.layer("b").tracks["opacity"]]
    assert keys == [1.0, 5.5]  # the key before the point stays, the one after moves


def test_the_scope_leaves_unchosen_kinds_where_they_are() -> None:
    edit = ripple.ripple(scene(), 2.0, 1.0, ripple.Scope(audio=False, subtitles=False, markers=False))
    now = starts(edit.project)
    assert now["a2"] == 3.0 and now["s2"] == 3.0 and now["c2"] == 3.5 and now["m2"] == 4.0
    only_audio = ripple.ripple(
        scene(), 2.0, 1.0, ripple.Scope(clips=False, keys=False, subtitles=False, markers=False)
    )
    assert starts(only_audio.project)["s2"] == 4.0 and starts(only_audio.project)["a2"] == 2.0


def test_the_preview_counts_what_would_move() -> None:
    found = ripple.affected(scene(), 3.0)
    assert found.counts == {"clips": 2, "keys": 1, "sounds": 1, "subtitles": 1, "markers": 1}
    assert set(found.layers) == {"a", "b"}
    assert found.summary() == "Moves 2 clips, 1 keys, 1 sounds, 1 subtitles, 1 markers on 2 layer(s)."
    assert ripple.affected(scene(), 5.9).summary() == "Nothing starts at or after that time."


def test_the_scene_grows_when_something_moves_past_its_end() -> None:
    edit = ripple.ripple(scene(), 4.0, 3.0)
    assert edit.project.canvas.duration >= 8.0  # the clips that started at 4.0 now end at 8.0


def test_closing_time_moves_back_and_a_collision_is_refused_with_its_reason() -> None:
    edit = ripple.ripple(scene(), 4.0, -1.0)
    assert starts(edit.project)["a3"] == 3.0 and starts(edit.project)["m2"] == 3.0
    with pytest.raises(edits.EditError):
        ripple.ripple(scene(), 4.0, -2.5)  # a3 would start at 1.5, inside a2 (2.0-3.0)... and a1's neighbour


def test_nothing_moves_below_zero() -> None:
    edit = ripple.ripple(scene(), 0.0, -5.0)
    assert min(starts(edit.project).values()) >= 0.0


def test_nothing_to_move_is_refused_and_zero_changes_nothing() -> None:
    with pytest.raises(edits.EditError, match="nothing starts"):
        ripple.ripple(scene(), 5.9, 1.0)
    assert ripple.ripple(scene(), 2.0, 0.0).project == scene()
    with pytest.raises(edits.EditError):
        ripple.ripple(scene(), -1.0, 1.0)


def test_beats_are_the_spans_between_markers() -> None:
    found = ripple.beats(scene())
    assert [(b.name, b.start, b.end) for b in found] == [
        ("Start", 0.0, 2.0),
        ("middle", 2.0, 4.0),
        ("end", 4.0, 6.0),
    ]
    assert found[1].length == 2.0
    assert [b.name for b in ripple.beats(Project(canvas=CANVAS))] == ["Start"]


def test_retiming_a_beat_ripples_at_its_end() -> None:
    middle = ripple.beats(scene())[1]
    longer = ripple.retime_beat(scene(), middle, 3.0)
    now = starts(longer.project)
    assert now["a2"] == 2.0 and now["m1"] == 2.0  # inside and at its start: unmoved
    assert (now["a3"], now["m2"], now["b1"]) == (5.0, 5.0, 5.0)  # what started at the end moved by +1
    assert (now["s2"], now["c2"]) == (3.0, 3.5)  # what started inside the beat stays
    shorter = ripple.retime_beat(scene(), middle, 2.0 - 0.5)
    assert starts(shorter.project)["m2"] == 3.5


def test_a_beat_cannot_be_cut_short_of_a_clip_inside_it_or_to_nothing() -> None:
    middle = ripple.beats(scene())[1]
    with pytest.raises(edits.EditError, match="cannot be shorter"):
        ripple.retime_beat(scene(), middle, 0.5)  # a2 runs 2.0-3.0
    with pytest.raises(edits.EditError, match="above 0"):
        ripple.retime_beat(scene(), middle, 0.0)
