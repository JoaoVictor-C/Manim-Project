"""Explain a moment (ADR 0082): the moments where something changes, and what makes the frame at each."""

from __future__ import annotations

import pytest

from manim_studio.core.editing import explain
from manim_studio.core.model.schema import (
    AudioClip,
    Canvas,
    Clip,
    Cue,
    Easing,
    Keyframe,
    Layer,
    Lifetime,
    Marker,
    Project,
    Spec,
)

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=10.0)


def scene() -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(
                id="c",
                name="Circle",
                spec=Spec(type="Circle"),
                clips=[Clip(id="draw", kind="Create", start=1.0, duration=2.0, ease=Easing(name="linear"))],
                tracks={"opacity": [Keyframe(t=4.0, value=1.0), Keyframe(t=6.0, value=0.0)]},
            ),
            Layer(
                id="t",
                spec=Spec(type="Text", params={"text": "Hello"}),
                lifetime=Lifetime(in_=2.0, out=5.0),
            ),
            Layer(id="camera", spec=Spec(type="Camera")),
        ],
        markers=[Marker(id="m", t=4.0, name="Fade")],
        subtitles=[Cue(id="s", start=1.5, end=3.0, text="A circle")],
        audio=[AudioClip(id="au", path="C:/media/music.wav", start=2.5, duration=3.0)],
    )


def test_moments_are_sorted_distinct_frames_where_something_changes() -> None:
    assert explain.moments(scene()) == [0.0, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0]


def test_moments_are_deduped_to_the_frame_and_capped() -> None:
    near = Project(
        canvas=CANVAS,
        layers=[Layer(id="a", spec=Spec(type="Square"), lifetime=Lifetime(in_=1.0, out=1.02))],
    )
    assert explain.moments(near) == [0.0, 1.0]
    many = Project(
        canvas=Canvas(fps=30, duration=60.0),
        markers=[Marker(id=f"m{i}", t=i * 0.1) for i in range(1, 500)],
    )
    capped = explain.moments(many, limit=50)
    assert len(capped) == 50 and capped == sorted(set(capped))
    assert capped[0] == 0.0 and capped[-1] == pytest.approx(49.9)


def test_step_goes_to_the_neighbouring_moment() -> None:
    times = explain.moments(scene())
    assert explain.step(times, 2.0, +1) == 2.5
    assert explain.step(times, 2.2, -1) == 2.0
    assert explain.step(times, 6.0, +1) is None and explain.step(times, 0.0, -1) is None


def test_a_clip_running_says_how_far_and_how_eased() -> None:
    found = explain.explain(scene(), 1.8)
    assert found.beat == "Start"
    assert [(v.layer_id, v.start) for v in found.layers] == [("c", 1.0)]
    (clip,) = found.clips
    assert (clip.layer_id, clip.kind, clip.easing) == ("c", "Create", "linear")
    assert clip.progress == pytest.approx(0.4)
    assert clip.sentence == "Circle is drawn in by Create, 40% through, linear easing"
    assert [s.text for s in found.subtitles] == ["A circle"]
    assert not found.keys and not found.sounds


def test_keys_moving_and_sounds_playing() -> None:
    found = explain.explain(scene(), 4.5)
    assert found.beat == "Fade"
    assert {v.layer_id for v in found.layers} == {"c", "t"}  # never the camera
    (key,) = found.keys
    assert (key.layer_id, key.track, key.start, key.end) == ("c", "opacity", 4.0, 6.0)
    assert 0.0 < key.value < 1.0
    (sound,) = found.sounds
    assert sound.name == "music.wav" and sound.into == pytest.approx(2.0)
    assert not found.clips and not found.subtitles


def test_lifetimes_say_why_a_layer_is_shown() -> None:
    found = explain.explain(scene(), 2.0)
    text = next(v for v in found.layers if v.layer_id == "t")
    assert (text.label, text.type, text.start, text.end) == ("Hello", "Text", 2.0, 5.0)
    assert text.sentence == "Hello (Text) is on screen from 0:02.0 to 0:05.0"
    circle = next(v for v in found.layers if v.layer_id == "c")
    assert "to the end" in circle.sentence
    assert not any(v.layer_id == "t" for v in explain.explain(scene(), 5.0).layers)


def test_text_has_a_sentence_per_item() -> None:
    out = explain.to_text(explain.explain(scene(), 2.6))
    assert out.startswith('At 0:02.6, in the beat "Start"\n')
    assert "Running:\n- Circle is drawn in by Create, 80% through, linear easing" in out
    assert '- The subtitle "A circle" is shown' in out
    assert "- music.wav plays, 0.1 s in" in out
    assert "Nothing is on screen." in explain.to_text(explain.explain(Project(canvas=CANVAS), 1.0))
