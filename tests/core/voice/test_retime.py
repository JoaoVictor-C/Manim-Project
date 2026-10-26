"""Follow speech and Fit speech to cues (ADR 0060): no overlaps, order kept, idempotent, within limits."""

from __future__ import annotations

import itertools
import random

import pytest

from manim_studio.core.model.schema import AudioClip, Canvas, Cue, Project
from manim_studio.core.voice import narration, retime


def narrated(
    lengths: list[float | None], windows: list[float] | None = None
) -> tuple[list[Cue], list[AudioClip]]:
    """Cues of the given windows (default 2 s, 3 s apart); each length is its speech, or None for no sound."""
    cues, clips = [], []
    for i, speech in enumerate(lengths):
        window = windows[i] if windows else 2.0
        cue = Cue(id=f"cue-{i}", start=i * 5.0, end=i * 5.0 + window, text=f"t{i}")
        if speech is not None:
            clips.append(AudioClip(id=f"v-{i}", path="x.wav", start=cue.start, duration=speech))
            cue = cue.model_copy(update={"audio_id": f"v-{i}", "audio_key": "k"})
        cues.append(cue)
    return cues, clips


def test_follow_lays_the_cues_out_one_speech_after_another() -> None:
    cues, clips = narrated([1.5, 2.5, 1.0])
    out, sounds = retime.follow(cues, clips, pause=0.5)
    assert [(c.start, c.end) for c in out] == [(0.0, 1.5), (2.0, 4.5), (5.0, 6.0)]
    assert [c.start for c in sounds] == [0.0, 2.0, 5.0]
    assert [c.duration for c in sounds] == [1.5, 2.5, 1.0]  # the sounds themselves are untouched


def test_follow_keeps_the_first_start_and_the_length_of_cues_without_sound() -> None:
    cues, clips = narrated([None, 2.0, None], windows=[1.0, 2.0, 4.0])
    cues[0] = cues[0].model_copy(update={"start": 3.0, "end": 4.0})
    out, _ = retime.follow(cues, clips, pause=1.0)
    assert [(c.start, c.end) for c in out] == [(3.0, 4.0), (5.0, 7.0), (8.0, 12.0)]


def test_a_cue_can_ask_for_its_own_pause() -> None:
    cues, clips = narrated([1.0, 1.0, 1.0])
    cues[2] = cues[2].model_copy(update={"pause_before": 2.5})
    out, _ = retime.follow(cues, clips, pause=0.5)
    assert [c.start for c in out] == [0.0, 1.5, 5.0]  # 0.5 after the first, 2.5 after the second
    cues[1] = cues[1].model_copy(update={"pause_before": 0.0})
    out, _ = retime.follow(cues, clips, pause=0.5)
    assert [c.start for c in out] == [0.0, 1.0, 4.5]


def test_follow_changes_nothing_else() -> None:
    cues, clips = narrated([1.0, 1.0])
    clips[0] = clips[0].model_copy(update={"gain": -3.0, "fade_out": 0.2})
    out, sounds = retime.follow(cues, clips)
    assert [(c.id, c.text, c.audio_id, c.audio_key) for c in out] == [
        (c.id, c.text, c.audio_id, c.audio_key) for c in cues
    ]
    assert (sounds[0].gain, sounds[0].fade_out) == (-3.0, 0.2)


@pytest.mark.parametrize("seed", range(20))
def test_follow_properties(seed: int) -> None:
    rng = random.Random(seed)
    n = rng.randint(1, 12)
    speech = [rng.choice([None, round(rng.uniform(0.2, 6.0), 3)]) for _ in range(n)]
    windows = [round(rng.uniform(0.2, 6.0), 3) for _ in range(n)]
    cues, clips = narrated(speech, windows)
    pause = round(rng.uniform(0, 2), 2)
    out, sounds = retime.follow(cues, clips, pause)
    assert [c.id for c in out] == [c.id for c in cues]  # the order is kept
    for a, b in itertools.pairwise(out):  # no overlaps, each pause exactly as asked
        assert b.start == pytest.approx(a.end + pause)
    total = sum(s if s is not None else w for s, w in zip(speech, windows, strict=True))
    assert out[-1].end - out[0].start == pytest.approx(total + pause * (n - 1))
    for cue in out:  # a spoken cue lasts exactly as long as its speech, and its sound starts with it
        clip = next((c for c in sounds if c.id == cue.audio_id), None)
        if clip is not None:
            assert cue.end - cue.start == pytest.approx(clip.duration)
            assert clip.start == pytest.approx(cue.start)
    again, again_sounds = retime.follow(out, sounds, pause)  # idempotent
    assert again == out
    assert again_sounds == sounds
    Project(canvas=Canvas(duration=600.0), subtitles=out, audio=sounds)  # and the project accepts it


def test_fit_finds_the_speed_that_fills_the_cue() -> None:
    cues, clips = narrated([2.4, 2.0, 1.0, 5.0], windows=[2.0, 2.0, 2.0, 2.0])
    fits = {f.cue_id: f for f in retime.fit_rates(cues, clips, {"cue-0": 1.0, "cue-2": 1.0, "cue-3": 1.0})}
    assert set(fits) == {"cue-0", "cue-2", "cue-3"}  # cue-1 already fits
    assert fits["cue-0"] == retime.Fit("cue-0", 1.2, True)  # 2.4 s into 2 s: 20% faster
    assert fits["cue-2"] == retime.Fit(
        "cue-2", 0.85, True
    )  # 1 s into 2 s: slower, to the limit; shorter is fine
    assert fits["cue-3"].rate == 1.25
    assert not fits["cue-3"].fits  # 5 s cannot be 2 s at 1.25x


def test_fit_multiplies_the_current_speed() -> None:
    cues, clips = narrated([2.4], windows=[2.0])
    (fit,) = retime.fit_rates(cues, clips, {"cue-0": 0.9})
    assert fit.rate == pytest.approx(1.08)


def test_fit_speech_through_the_project_makes_the_sounds_stale() -> None:
    cues, clips = narrated([2.4], windows=[2.0])
    from manim_studio.core.model.schema import VoiceChoice

    voice = VoiceChoice(provider="fake", voice="anna")
    cue = cues[0].model_copy(update={"audio_key": narration.make_key(voice, "t0")})
    p = Project(canvas=Canvas(duration=60.0), subtitles=[cue], audio=clips, voice=voice)
    assert narration.state(p, p.subtitles[0]) == narration.READY
    edit, fits = narration.fit_speech(p)
    assert [f.rate for f in fits] == [1.2]
    assert edit.project.subtitles[0].voice.rate == 1.2
    assert narration.state(edit.project, edit.project.subtitles[0]) == narration.STALE
