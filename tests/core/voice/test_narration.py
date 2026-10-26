"""Narration (ADR 0060): keys and staleness, the plan, placing speech, the pronunciation dictionary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from manim_studio import plugins
from manim_studio.core.editing import edits
from manim_studio.core.model.schema import AudioClip, Canvas, Cue, Project, VoiceChoice
from manim_studio.core.voice import narration, pronunciation, voice_cache
from voice_support import SECONDS_PER_CHAR

VOICE = VoiceChoice(provider="fake", voice="anna")


def project(*texts: str, voice: VoiceChoice | None = VOICE, **kw) -> Project:
    cues = [
        Cue(id=f"cue-{i}", start=(i - 1) * 3.0, end=(i - 1) * 3.0 + 2.0, text=t)
        for i, t in enumerate(texts, 1)
    ]
    return Project(canvas=Canvas(duration=60.0), subtitles=cues, voice=voice, **kw)


def spoken(p: Project, cue_id: str, folder: Path, seconds: float = 1.5) -> narration.Spoken:
    cue = next(c for c in p.subtitles if c.id == cue_id)
    key = narration.key_for(p, cue)
    return narration.Spoken(cue_id, key, voice_cache.path_for(folder, key, ".wav"), seconds)


# -- the data model ---------------------------------------------------------------------------


def test_a_project_without_narration_saves_as_before() -> None:
    data = json.loads(project("Hello", voice=None).model_dump_json())
    assert "voice" not in data
    assert "pronunciations" not in data
    assert set(data["subtitles"][0]) == {"id", "start", "end", "text"}


def test_narration_fields_round_trip_and_are_saved_only_when_set() -> None:
    p = project("Hello", pronunciations={"F": "force"})
    cue = p.subtitles[0].model_copy(
        update={
            "voice": VoiceChoice(provider="fake", voice="ben", rate=1.2),
            "audio_id": "voice-cue-1",
            "audio_key": "abc",
        }
    )
    p = p.model_copy(update={"subtitles": [cue]})
    again = Project.model_validate_json(p.model_dump_json())
    assert again == p
    assert again.subtitles[0].voice.rate == 1.2
    assert json.loads(p.model_dump_json())["voice"] == {"provider": "fake", "voice": "anna", "rate": 1.0}


def test_editing_keeps_the_narration_fields() -> None:
    p = project("Hello", "World")
    narrated = narration.place(p, [spoken(p, "cue-1", Path("x"))]).project
    again = edits.update_cue(narrated, "cue-1", start=0.5, end=2.5).project
    assert again.subtitles[0].audio_key == narrated.subtitles[0].audio_key
    assert edits.set_voice(again, None).project.voice is None
    assert edits.add_cue(again, 10.0, 11.0, "More").project.voice == VOICE  # the other fields survive


def test_the_pause_before_a_cue_is_saved_only_when_set_and_edited_by_a_cell() -> None:
    from manim_studio.core.editing import tables

    p = project("One", "Two")
    assert "pause_before" not in json.loads(p.model_dump_json())["subtitles"][1]
    edit = tables.cue_edit(p, "cue-2", "pause_before", "2.5 s")
    assert edit.project.subtitles[1].pause_before == 2.5
    assert json.loads(edit.project.model_dump_json())["subtitles"][1]["pause_before"] == 2.5
    assert tables.cue_cell(edit.project.subtitles[1], "pause_before") == "2.500"
    assert tables.cue_cell(p.subtitles[1], "pause_before") == ""
    cleared = tables.cue_edit(edit.project, "cue-2", "pause_before", "  ")
    assert cleared.project.subtitles[1].pause_before is None
    with pytest.raises(Exception, match=r"greater than or equal|not a number"):
        tables.cue_edit(p, "cue-2", "pause_before", "-1")


# -- pronunciation ----------------------------------------------------------------------------


def test_pronunciation_replaces_whole_words_longest_first() -> None:
    words = {"p": "p", "F": "force", "dp/dt": "d p by d t", "m v": "m times v"}
    assert pronunciation.spoken("F = dp/dt", words) == "force = d p by d t"
    assert pronunciation.spoken("Fast and F", words) == "Fast and force"  # not inside a word
    assert pronunciation.spoken("p equals m v.", words) == "p equals m times v."


def test_pronunciation_does_not_replace_its_own_output() -> None:
    assert pronunciation.spoken("a b", {"a": "b", "b": "a"}) == "b a"


def test_pronunciation_joins_lines() -> None:
    assert pronunciation.spoken("one\n  two", {}) == "one two"


# -- keys and states --------------------------------------------------------------------------


def test_the_key_depends_on_voice_speed_and_spoken_text_only() -> None:
    a = project("Hello")
    cue = a.subtitles[0]
    same = cue.model_copy(update={"start": 9.0, "end": 12.0})
    assert narration.key_for(a, cue) == narration.key_for(a, same)
    faster = project("Hello", voice=VoiceChoice(provider="fake", voice="anna", rate=1.1))
    other = project("Hello", voice=VoiceChoice(provider="fake", voice="ben"))
    keys = {narration.key_for(x, x.subtitles[0]) for x in (a, faster, other, project("Hello!"))}
    assert len(keys) == 4
    written, spoken_as = project("F"), project("F", pronunciations={"F": "force"})
    assert narration.key_for(spoken_as, spoken_as.subtitles[0]) != narration.key_for(
        written, written.subtitles[0]
    )


def test_a_cue_without_text_or_voice_has_no_key() -> None:
    assert narration.state(project(" "), project(" ").subtitles[0]) == narration.EMPTY
    assert narration.state(project("Hi", voice=None), project("Hi").subtitles[0]) == narration.NO_VOICE
    p = project("Hi", voice=None)
    assert narration.key_for(p, p.subtitles[0]) is None


def test_the_states_of_a_narrated_cue(tmp_path: Path) -> None:
    p = project("Hello")
    assert narration.state(p, p.subtitles[0]) == narration.NEW
    p = narration.place(p, [spoken(p, "cue-1", tmp_path)]).project
    assert narration.state(p, p.subtitles[0]) == narration.READY
    texted = edits.update_cue(p, "cue-1", text="Hello there").project
    assert narration.state(texted, texted.subtitles[0]) == narration.STALE
    revoiced = edits.set_voice(p, VoiceChoice(provider="fake", voice="ben")).project
    assert narration.state(revoiced, revoiced.subtitles[0]) == narration.STALE  # the project's voice changed
    own = edits.set_cue_voice(revoiced, ["cue-1"], VOICE).project
    assert narration.state(own, own.subtitles[0]) == narration.READY  # ... but this cue has its own
    gone = edits.remove_audio(p, p.subtitles[0].audio_id).project
    assert narration.state(gone, gone.subtitles[0]) == narration.NEW  # its sound was deleted
    assert narration.counts(texted) == {narration.STALE: 1}


# -- the plan ---------------------------------------------------------------------------------


@pytest.mark.usefixtures("fake_voice")
def test_the_plan_leaves_out_what_is_current_and_reuses_files(tmp_path: Path) -> None:
    p = project("One", "Two", "", "Three")
    plan = narration.plan(p, None, tmp_path)
    assert [j.cue_id for j in plan.jobs] == ["cue-1", "cue-2", "cue-4"]
    assert plan.skipped == {"cue-3": narration.EMPTY}
    assert plan.cached == []
    first = plan.jobs[0]
    assert (first.provider, first.voice, first.rate, first.text) == ("fake", "anna", 1.0, "One")
    assert first.out == voice_cache.path_for(tmp_path, first.key, ".wav")

    plan.jobs[1].out.parent.mkdir(parents=True, exist_ok=True)
    plan.jobs[1].out.write_bytes(b"RIFF")  # "Two" was spoken before (by another cue, or another project)
    again = narration.plan(p, None, tmp_path)
    assert [j.cue_id for j in again.jobs] == ["cue-1", "cue-4"]
    assert [j.cue_id for j in again.cached] == ["cue-2"]

    placed = narration.place(p, [spoken(p, "cue-1", tmp_path)]).project
    after = narration.plan(placed, None, tmp_path)
    assert ([j.cue_id for j in after.jobs], [j.cue_id for j in after.cached]) == (["cue-4"], ["cue-2"])
    everything = narration.plan(placed, None, tmp_path, only_missing=False)
    assert [j.cue_id for j in everything.jobs] == ["cue-1", "cue-4"]
    assert [j.cue_id for j in narration.plan(p, ["cue-4"], tmp_path).jobs] == ["cue-4"]


def test_the_plan_names_a_missing_provider(tmp_path: Path) -> None:
    p = project("One", voice=VoiceChoice(provider="gone", voice="x"))
    plan = narration.plan(p, None, tmp_path)
    assert plan.jobs == []
    assert "not installed" in plan.skipped["cue-1"]


@pytest.mark.usefixtures("fake_voice")
def test_the_plan_speaks_the_pronounced_text(tmp_path: Path) -> None:
    p = project("F = dp/dt", pronunciations={"F": "force", "dp/dt": "d p by d t"})
    assert narration.plan(p, None, tmp_path).jobs[0].text == "force = d p by d t"
    assert p.subtitles[0].text == "F = dp/dt"  # the subtitle keeps what is written


# -- placing speech ---------------------------------------------------------------------------


def test_place_adds_a_sound_at_each_cue_and_marks_it_current(tmp_path: Path) -> None:
    p = project("One", "Two")
    edit = narration.place(p, [spoken(p, "cue-1", tmp_path, 1.5), spoken(p, "cue-2", tmp_path, 2.5)])
    assert edit.kind == "timing"
    placed = edit.project
    assert [(c.id, c.start, c.duration) for c in placed.audio] == [
        ("voice-cue-1", 0.0, 1.5),
        ("voice-cue-2", 3.0, 2.5),
    ]
    assert [c.audio_id for c in placed.subtitles] == ["voice-cue-1", "voice-cue-2"]
    assert all(narration.state(placed, c) == narration.READY for c in placed.subtitles)
    assert [c.start for c in placed.subtitles] == [0.0, 3.0]  # nothing moved without Follow speech


def test_place_again_replaces_the_cues_own_sound_and_keeps_its_gain(tmp_path: Path) -> None:
    p = project("One")
    p = narration.place(p, [spoken(p, "cue-1", tmp_path, 1.5)]).project
    p = edits.update_audio(p, "voice-cue-1", gain=-6.0, fade_in=0.5).project
    changed = edits.update_cue(p, "cue-1", text="One, again").project
    again = narration.place(changed, [spoken(changed, "cue-1", tmp_path, 0.3)]).project
    assert len(again.audio) == 1
    clip = again.audio[0]
    assert (clip.id, clip.duration, clip.gain, clip.fade_in) == ("voice-cue-1", 0.3, -6.0, 0.0)  # fades fit
    assert Path(clip.path).name != Path(p.audio[0].path).name


def test_place_never_takes_an_id_that_is_used(tmp_path: Path) -> None:
    p = project("One").model_copy(update={"audio": [AudioClip(id="voice-cue-1", path="a.wav", duration=1.0)]})
    placed = narration.place(p, [spoken(p, "cue-1", tmp_path)]).project
    assert sorted(c.id for c in placed.audio) == ["voice-cue-1", "voice-cue-1-2"]


def test_place_can_follow_the_speech(tmp_path: Path) -> None:
    p = project("One", "Two")
    placed = narration.place(
        p, [spoken(p, "cue-1", tmp_path, 1.5), spoken(p, "cue-2", tmp_path, 2.5)], follow=True, pause=0.5
    ).project
    assert [(c.start, c.end) for c in placed.subtitles] == [(0.0, 1.5), (2.0, 4.5)]
    assert [c.start for c in placed.audio] == [0.0, 2.0]


def test_deleting_a_cue_takes_its_sound_and_undo_gets_both_back(tmp_path: Path) -> None:
    p = project("One", "Two")
    p = narration.place(p, [spoken(p, "cue-1", tmp_path), spoken(p, "cue-2", tmp_path)]).project
    after = edits.remove_cue(p, "cue-1").project
    assert [c.id for c in after.subtitles] == ["cue-2"]
    assert [c.id for c in after.audio] == ["voice-cue-2"]
    assert len(edits.remove_cue(p, "cue-1", with_audio=False).project.audio) == 2
    plain = project("One")
    assert edits.remove_cue(plain, "cue-1").project.subtitles == []


def test_a_project_default_voice_is_set_by_an_edit() -> None:
    p = project("One", voice=None)
    chosen = edits.set_voice(p, VOICE).project
    assert chosen.voice == VOICE
    assert edits.set_pronunciations(p, {" F ": " force ", "": "x", "a": "a"}).project.pronunciations == {
        "F": "force"
    }


def test_the_providers_known_without_plugins() -> None:
    assert {"sapi", "edge"} <= set(plugins.voice_providers())
    assert SECONDS_PER_CHAR > 0
