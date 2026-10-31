"""Script to timeline (ADR 0069): sentences and paragraphs become timed subtitle cues."""

from __future__ import annotations

from itertools import pairwise

import pytest

from manim_studio.core.editing import edits, script_import
from manim_studio.core.model.schema import Canvas, Cue, Layer, Project, Spec

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=5.0)
SCRIPT = """# Intro
Welcome to **the course**. Dr. Chen explains e.g. momentum. Is it hard? No!

- First point goes here.
- Second point.

Last paragraph has one sentence only
"""


def empty() -> Project:
    return Project(canvas=CANVAS)


def test_sentences_keep_abbreviations_and_drop_markdown() -> None:
    script = script_import.split_script(SCRIPT)
    assert [p.text for p in script.pieces] == [
        "Welcome to the course.",
        "Dr. Chen explains e.g. momentum.",
        "Is it hard?",
        "No!",
        "First point goes here.",
        "Second point.",
        "Last paragraph has one sentence only",
    ]
    assert [p.paragraph for p in script.pieces] == [0, 0, 0, 0, 1, 1, 2]
    assert script.titles == {0: "Intro"}


def test_a_paragraph_can_be_the_unit() -> None:
    script = script_import.split_script(SCRIPT, "paragraph")
    assert len(script.pieces) == 3 and script.pieces[0].text.startswith("Welcome to the course. Dr. Chen")


def test_initials_and_ellipses_do_not_split_wrongly() -> None:
    pieces = script_import.split_script("J. Smith arrived... Then he left. Fig. 2 shows it.").pieces
    assert [p.text for p in pieces] == ["J. Smith arrived...", "Then he left.", "Fig. 2 shows it."]


def test_cues_follow_each_other_by_reading_time() -> None:
    edit, report = script_import.import_script(empty(), SCRIPT, words_per_second=2.0)
    cues = edit.project.subtitles
    assert [c.text for c in cues][:2] == ["Welcome to the course.", "Dr. Chen explains e.g. momentum."]
    assert cues[0].start == 0.0 and cues[0].end - cues[0].start == pytest.approx(2.0)  # 4 words at 2 words/s
    assert cues[1].start == pytest.approx(cues[0].end + script_import.GAP, abs=0.1)  # frames of 0.1 s
    assert cues[4].start - cues[3].end == pytest.approx(script_import.PARAGRAPH_GAP, abs=0.1)
    assert all(a.end <= b.start + 1e-9 for a, b in pairwise(cues))
    assert report.cues == 7 and report.paragraphs == 3 and report.seconds == pytest.approx(cues[-1].end)


def test_a_short_cue_lasts_at_least_a_second() -> None:
    edit, _ = script_import.import_script(empty(), "No!")
    (cue,) = edit.project.subtitles
    assert cue.end - cue.start == pytest.approx(script_import.MIN_SECONDS)


def test_the_script_goes_after_existing_subtitles_or_where_asked() -> None:
    project = empty().model_copy(update={"subtitles": [Cue(id="old", start=0.0, end=3.0, text="before")]})
    after, _ = script_import.import_script(project, "Next.")
    assert after.project.subtitles[1].start == pytest.approx(3.0)
    there, _ = script_import.import_script(project, "Next.", start=10.0)
    assert there.project.subtitles[1].start == pytest.approx(10.0)


def test_the_scene_grows_to_hold_the_script_and_ids_do_not_clash() -> None:
    project = empty().model_copy(update={"layers": [Layer(id="cue-1", spec=Spec(type="Square"))]})
    edit, _ = script_import.import_script(project, "One. Two. Three. Four. Five. Six.")
    assert edit.project.canvas.duration >= edit.project.subtitles[-1].end
    ids = [c.id for c in edit.project.subtitles]
    assert len(set(ids)) == 6 and "cue-1" not in ids


def test_placeholders_name_each_paragraph_and_last_as_long_as_it_is_read() -> None:
    edit, report = script_import.import_script(empty(), SCRIPT, placeholders=True)
    layers = edit.project.layers
    assert [layer.name for layer in layers] == ["Beat 1", "Beat 2", "Beat 3"] and report.layers == 3
    assert layers[0].spec.params["text"] == "Intro"  # the heading
    assert layers[2].spec.params["text"] == "Last paragraph has one sentence only"
    first_cue = edit.project.subtitles[0]
    assert layers[0].lifetime.in_ == first_cue.start
    assert layers[0].lifetime.out == pytest.approx(edit.project.subtitles[3].end)


def test_long_sentences_are_reported_and_nothing_to_read_is_refused() -> None:
    long = " ".join(["word"] * 50) + "."
    _, report = script_import.import_script(empty(), long)
    assert report.long_sentences == (long,)
    with pytest.raises(edits.EditError, match="nothing to read"):
        script_import.import_script(empty(), "  \n\n# only a heading\n")
    with pytest.raises(edits.EditError, match="positive"):
        script_import.import_script(empty(), "Hi.", words_per_second=0)
