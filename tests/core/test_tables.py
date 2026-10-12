"""The Audio page's table logic (P6b.4, ADR 0041): how a cell shows a sound or a subtitle, and the
edit a cell's text makes (or the reason it is refused). No Qt."""

from __future__ import annotations

import pytest

from manim_studio.core import edits, tables
from manim_studio.core.schema import AudioClip, Canvas, Cue, Project

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=10.0)


def sound(**fields) -> AudioClip:
    return AudioClip(id="audio-1", name="beat", path="C:/sounds/beat.wav", duration=4.0, **fields)


def scene(*, clips=(), cues=()) -> Project:
    return Project(canvas=CANVAS, audio=list(clips), subtitles=list(cues))


def cue(cue_id: str, start: float, end: float, text: str = "words") -> Cue:
    return Cue(id=cue_id, start=start, end=end, text=text)


# -- numbers -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1.5", 1.5),
        ("1,5", 1.5),
        ("  2 ", 2.0),
        ("1.5 s", 1.5),
        ("1.5s", 1.5),
        ("-6 dB", -6.0),
        ("-6db", -6.0),
        ("+3", 3.0),
        ("0:01.5", 1.5),
        ("1:02.5", 62.5),
        ("1:02:03", 3723.0),
        ("-0:01", -1.0),
    ],
)
def test_parse_number_reads_what_people_type(text, value) -> None:
    assert tables.parse_number(text) == pytest.approx(value)


@pytest.mark.parametrize(
    "text", ["", "abc", "1.2.3", "1:xx", "nan", "inf", "1e999", "1_0", "1:2:3:4", "1:-5", "--3", ":", "dB"]
)
def test_parse_number_refuses_what_is_not_a_number(text) -> None:
    with pytest.raises(edits.EditError, match="not a number"):
        tables.parse_number(text)


def test_seconds_and_decibels_are_shown_with_fixed_places() -> None:
    assert tables.format_seconds(1.5) == "1.500" and tables.format_seconds(0) == "0.000"
    assert tables.format_seconds(61.23456) == "61.235"
    assert (
        tables.format_db(-6.0) == "-6.0" and tables.format_db(0.0) == "0.0" and tables.format_db(3) == "3.0"
    )


# -- sounds ---------------------------------------------------------------------------------


def test_sound_cells_show_every_field() -> None:
    clip = sound(start=1.25, offset=0.5, gain=-6.0, fade_in=0.3, fade_out=0.1)
    cells = {c.key: tables.sound_cell(clip, c.key) for c in tables.SOUND_COLUMNS}
    assert cells == {
        "name": "beat",
        "path": "beat.wav",
        "start": "1.250",
        "offset": "0.500",
        "duration": "4.000",
        "gain": "-6.0",
        "fade_in": "0.300",
        "fade_out": "0.100",
    }
    assert [c.key for c in tables.SOUND_COLUMNS if not c.editable] == ["path"]
    assert tables.sound_cell(AudioClip(id="audio-2", path="x.wav", duration=1.0), "name") == "audio-2"


@pytest.mark.parametrize(
    ("key", "text", "field", "value"),
    [
        ("name", "  Kick  ", "name", "Kick"),
        ("start", "2.5", "start", 2.5),
        ("start", "0:03", "start", 3.0),
        ("offset", "0.75 s", "offset", 0.75),
        ("duration", "3", "duration", 3.0),
        ("gain", "-12 dB", "gain", -12.0),
        ("fade_in", "0,5", "fade_in", 0.5),
        ("fade_out", "1", "fade_out", 1.0),
    ],
)
def test_a_sound_cell_edit_changes_that_field_only(key, text, field, value) -> None:
    before = scene(clips=[sound(start=1.0)])
    after = tables.sound_edit(before, "audio-1", key, text).project
    changed = after.audio[0]
    assert getattr(changed, field) == value
    others = before.audio[0].model_dump() | {field: value}
    assert changed.model_dump() == others
    assert after.canvas == before.canvas and after.subtitles == before.subtitles


def test_a_sound_edit_keeps_every_cache_it_can() -> None:
    assert tables.sound_edit(scene(clips=[sound()]), "audio-1", "gain", "-3").kind == "timing"


@pytest.mark.parametrize(
    ("key", "text", "reason"),
    [
        ("start", "soon", "not a number"),
        ("start", "-1", "greater than or equal to 0"),
        ("offset", "-0.5", "greater than or equal to 0"),
        ("duration", "0", "greater than 0"),
        ("fade_in", "-1", "greater than or equal to 0"),
        ("fade_in", "5", "fades are longer than the sound"),  # 5 + 0 > 4
        ("path", "other.wav", "cannot be edited"),
    ],
)
def test_a_sound_edit_is_refused_with_its_reason(key, text, reason) -> None:
    project = scene(clips=[sound()])
    with pytest.raises((edits.EditError, ValueError)) as caught:
        tables.sound_edit(project, "audio-1", key, text)
    assert reason in tables.reason(caught.value)


def test_shortening_a_sound_below_its_fades_is_refused_and_changes_nothing_else() -> None:
    project = scene(clips=[sound(fade_in=1.5, fade_out=1.5)])
    with pytest.raises(ValueError) as caught:
        tables.sound_edit(project, "audio-1", "duration", "2")
    assert "fades are longer than the sound" in tables.reason(caught.value)
    assert project.audio[0].duration == 4.0


def test_a_sound_that_is_gone_is_an_edit_error() -> None:
    with pytest.raises(edits.EditError, match="no sound"):
        tables.sound_edit(scene(), "audio-9", "gain", "1")


# -- subtitles --------------------------------------------------------------------------


def test_cue_cells_show_times_and_one_line_of_text() -> None:
    c = cue("cue-1", 1.0, 2.5, "first line\nsecond line")
    assert [tables.cue_cell(c, col.key) for col in tables.CUE_COLUMNS] == [
        "1.000",
        "2.500",
        "first line \u21b5 second line",
    ]
    assert all(col.editable for col in tables.CUE_COLUMNS)


def test_a_cue_text_round_trips_through_its_cell() -> None:
    original = cue("cue-1", 0.0, 1.0, "a\nb  c\nd")
    shown = tables.cue_cell(original, "text")
    project = scene(cues=[original])
    after = tables.cue_edit(project, "cue-1", "text", shown + " ").project  # trailing blank is dropped
    assert after.subtitles[0].text == "a\nb  c\nd"


@pytest.mark.parametrize(
    ("key", "text", "start", "end"),
    [("start", "0.5", 0.5, 3.0), ("end", "4", 1.0, 4.0), ("end", "0:05", 1.0, 5.0)],
)
def test_a_cue_time_edit_changes_that_time_only(key, text, start, end) -> None:
    project = scene(cues=[cue("cue-1", 1.0, 3.0)])
    (changed,) = tables.cue_edit(project, "cue-1", key, text).project.subtitles
    assert (changed.start, changed.end, changed.text) == (start, end, "words")


@pytest.mark.parametrize(
    ("key", "text", "reason"),
    [
        ("start", "4.5", "must end after it starts"),
        ("start", "4", "must end after it starts"),
        ("end", "1", "must end after it starts"),
        ("start", "-1", "greater than or equal to 0"),
        ("end", "later", "not a number"),
        ("end", "6", "overlap"),  # cue-2 starts at 5
        ("start", "1.5", "overlap"),  # cue-0 ends at 2
    ],
)
def test_a_cue_edit_is_refused_with_its_reason(key, text, reason) -> None:
    project = scene(cues=[cue("cue-0", 0.0, 2.0), cue("cue-1", 3.0, 4.0), cue("cue-2", 5.0, 7.0)])
    with pytest.raises((edits.EditError, ValueError)) as caught:
        tables.cue_edit(project, "cue-1", key, text)
    assert reason in tables.reason(caught.value)


def test_moving_a_cue_past_another_one_is_an_overlap_not_a_reorder() -> None:
    project = scene(cues=[cue("cue-1", 0.0, 1.0), cue("cue-2", 2.0, 3.0)])
    with pytest.raises(ValueError) as caught:
        tables.cue_edit(project, "cue-1", "end", "2.5")
    assert "overlap" in tables.reason(caught.value)


def test_cue_edits_without_such_a_cue_or_column() -> None:
    project = scene(cues=[cue("cue-1", 0.0, 1.0)])
    with pytest.raises(edits.EditError, match="no subtitle"):
        tables.cue_edit(project, "cue-7", "text", "x")
    with pytest.raises(edits.EditError, match="cannot be edited"):
        tables.cue_edit(project, "cue-1", "id", "x")


def test_a_field_refusal_names_the_column_and_a_whole_clip_refusal_does_not() -> None:
    with pytest.raises(edits.EditError) as caught:
        tables.sound_edit(scene(clips=[sound()]), "audio-1", "start", "-1")
    assert str(caught.value) == "Start (s): Input should be greater than or equal to 0"
    with pytest.raises(edits.EditError) as caught:
        tables.cue_edit(scene(cues=[cue("cue-1", 1.0, 2.0)]), "cue-1", "end", "0.5")
    assert str(caught.value) == "subtitle 'cue-1' must end after it starts"


def test_reason_is_one_short_sentence() -> None:
    with pytest.raises(ValueError) as caught:
        tables.sound_edit(scene(clips=[sound()]), "audio-1", "fade_out", "9")
    text = tables.reason(caught.value)
    assert "\n" not in text and not text.startswith("Value error") and "audio-1" in text
    assert tables.reason(edits.EditError("no sound 'x'")) == "no sound 'x'"
