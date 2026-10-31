"""The beat sheet (ADR 0073): beats between markers, with what appears, is said and heard in each."""

from __future__ import annotations

from manim_studio.core.editing import beat_sheet
from manim_studio.core.model.schema import (
    AudioClip,
    Canvas,
    Clip,
    Cue,
    Layer,
    Lifetime,
    Marker,
    Project,
    Spec,
)

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=10.0)


def text(layer_id: str, words: str, appears: float) -> Layer:
    return Layer(
        id=layer_id,
        spec=Spec(type="Text", params={"text": words}),
        lifetime=Lifetime(in_=appears, out=appears + 2.0),
    )


def scene() -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            text("a", "Hello", 0.0),
            text("b", "Middle", 4.0),
            Layer(
                id="c",
                name="Shape",
                spec=Spec(type="Square"),
                clips=[Clip(id="k", kind="FadeIn", start=7.0, duration=1.0)],
            ),
            Layer(id="camera", spec=Spec(type="Camera")),
        ],
        markers=[Marker(id="m1", t=3.0, name="Idea"), Marker(id="m2", t=6.0)],
        subtitles=[
            Cue(id="s1", start=0.5, end=2.0, text="Welcome"),
            Cue(id="s2", start=6.5, end=8.0, text="Done"),
        ],
        audio=[AudioClip(id="au", path="C:/media/music.wav", start=3.5, duration=2.0)],
    )


def test_rows_follow_the_markers_and_say_what_happens_in_each() -> None:
    rows = beat_sheet.sheet(scene())
    assert [(r.beat.name, r.beat.start, r.beat.end) for r in rows] == [
        ("Start", 0.0, 3.0),
        ("Idea", 3.0, 6.0),
        ("Marker 2", 6.0, 10.0),
    ]
    assert rows[0].appears == ["Hello"] and rows[0].said == ["Welcome"]
    assert rows[1].appears == ["Middle"] and rows[1].sounds == ["music.wav"]
    assert rows[2].said == ["Done"]


def test_the_camera_is_not_something_that_appears() -> None:
    assert all("camera" not in " ".join(r.appears).lower() for r in beat_sheet.sheet(scene()))


def test_a_project_without_markers_is_one_beat() -> None:
    rows = beat_sheet.sheet(Project(canvas=CANVAS, layers=[text("a", "Only", 0.0)]))
    assert len(rows) == 1 and rows[0].appears == ["Only"]


def test_the_picture_is_drawn_a_little_into_the_beat() -> None:
    first = beat_sheet.sheet(scene())[0]
    assert 0.0 < first.thumbnail_time < first.beat.end


def test_markdown_lists_every_beat() -> None:
    out = beat_sheet.to_markdown(scene(), "Lesson")
    assert out.startswith("# Lesson\n")
    assert "## 2. Idea (0:03.0 - 0:06.0, 3 s)" in out
    assert '- Says: "Welcome"' in out and "- Sound: music.wav" in out
