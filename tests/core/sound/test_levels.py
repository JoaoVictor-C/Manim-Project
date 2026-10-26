"""The level meter's numbers (P6b.4, ADR 0041): a short window of the mix at the playhead, equal to
the full mix (ADR 0034) there, with its peak and RMS per channel. No Qt."""

from __future__ import annotations

import math

import numpy as np
import pytest

from manim_studio.core.model.schema import AudioClip, Canvas, Project
from manim_studio.core.sound import audio, levels

RATE = audio.RATE
CANVAS = Canvas(width_px=160, height_px=90, fps=10, duration=4.0)


@pytest.fixture(autouse=True)
def _fresh():
    audio.forget()
    yield
    audio.forget()


def tone(seconds: float, amplitude: float = 0.5, hz: float = 440.0, right: float | None = None) -> np.ndarray:
    t = np.arange(round(seconds * RATE)) / RATE
    wave = np.sin(2 * np.pi * hz * t).astype(np.float32)
    return np.stack([amplitude * wave, (amplitude if right is None else right) * wave]).astype(np.float32)


@pytest.fixture
def wav(tmp_path):
    path = tmp_path / "tone.wav"
    audio.write_wav(tone(3.0, 0.5), path)
    return path


@pytest.fixture
def ramp_wav(tmp_path):
    path = tmp_path / "ramp.wav"
    left = np.linspace(-0.9, 0.9, 3 * RATE, dtype=np.float32)
    audio.write_wav(np.stack([left, -left]), path)
    return path


def clip(path, clip_id="a", **fields) -> AudioClip:
    return AudioClip(id=clip_id, path=str(path), duration=fields.pop("duration", 1.0), **fields)


def project(*clips: AudioClip) -> Project:
    return Project(canvas=CANVAS, audio=list(clips))


# -- the window equals the mix -------------------------------------------------------------


def span(t0: float, t1: float) -> slice:
    return slice(round(t0 * RATE), round(t1 * RATE))


@pytest.mark.parametrize(
    ("t0", "t1"),
    [(0.0, 4.0), (0.0, 0.05), (0.9, 1.1), (1.0, 1.0001), (1.45, 1.55), (2.45, 2.65), (3.9, 4.0), (3.95, 4.5)],
)
def test_a_window_equals_the_same_span_of_the_mix(ramp_wav, wav, t0, t1) -> None:
    sounds = [
        clip(ramp_wav, "a", start=0.5, offset=0.7, duration=2.0, gain=-4.0, fade_in=0.4, fade_out=0.6),
        clip(wav, "b", start=1.0, duration=2.5, gain=3.0, fade_in=0.2, fade_out=0.3),  # loud: sums clip at 1
        clip(wav, "c", start=2.5, offset=0.1, duration=1.2, fade_out=0.5),
    ]
    mixed = audio.mix(project(*sounds))
    window = levels.window_samples(project(*sounds), t0, t1)
    a, b = span(t0, min(t1, CANVAS.duration)).start, span(t0, min(t1, CANVAS.duration)).stop
    assert window.shape == (2, b - a)
    np.testing.assert_array_equal(window, mixed[:, a:b])


def test_a_window_inside_a_fade_gets_the_fade(ramp_wav) -> None:
    sound = clip(ramp_wav, start=1.0, duration=2.0, fade_in=1.0, fade_out=1.0)
    p = project(sound)
    for t in (1.0, 1.3, 1.99, 2.0, 2.5, 2.9, 3.0):
        np.testing.assert_array_equal(
            levels.window_samples(p, t, t + 0.01), audio.mix(p)[:, span(t, t + 0.01)], err_msg=str(t)
        )


def test_a_clip_past_the_end_of_its_file_is_silent_there(tmp_path) -> None:
    short = tmp_path / "short.wav"
    audio.write_wav(tone(0.5, 0.5), short)
    p = project(clip(short, start=0.5, duration=2.0))  # the file is 0.5 s long
    window = levels.window_samples(p, 0.9, 1.4)
    np.testing.assert_array_equal(window, audio.mix(p)[:, span(0.9, 1.4)])
    assert not window[:, round(0.1 * RATE) :].any() and window[:, : round(0.1 * RATE)].any()


def test_a_missing_file_and_a_project_without_sound_are_silence(tmp_path) -> None:
    gone = project(clip(tmp_path / "gone.wav", start=0.0, duration=2.0))
    assert not levels.window_samples(gone, 0.5, 0.6).any()
    assert not levels.window_samples(project(), 0.5, 0.6).any()
    assert levels.window_samples(project(), 0.5, 0.6).shape == (2, round(0.1 * RATE))


def test_windows_outside_the_video_are_clamped_or_empty(wav) -> None:
    p = project(clip(wav, duration=3.0))
    assert levels.window_samples(p, -1.0, 0.0).shape == (2, 0)
    assert levels.window_samples(p, 4.0, 5.0).shape == (2, 0)
    assert levels.window_samples(p, 5.0, 6.0).shape == (2, 0)
    assert levels.window_samples(p, 3.0, 2.0).shape == (2, 0)
    assert levels.window_samples(p, -0.5, 0.5).shape == (2, RATE // 2)


# -- levels ------------------------------------------------------------------------------


def test_a_known_tone_reads_its_peak_and_rms(wav) -> None:
    level = levels.level_at(project(clip(wav, start=0.0, duration=3.0)), 1.0)
    assert level.peak == pytest.approx((0.5, 0.5), abs=1e-3)
    assert level.rms == pytest.approx((0.5 / math.sqrt(2),) * 2, abs=2e-3)
    assert level.peak_db == pytest.approx((-6.02, -6.02), abs=0.05)
    assert level.rms_db == pytest.approx((-9.03, -9.03), abs=0.1)


def test_gain_moves_the_level_by_that_many_decibels(wav) -> None:
    quiet = levels.level_at(project(clip(wav, duration=3.0, gain=-6.0)), 1.0)
    plain = levels.level_at(project(clip(wav, duration=3.0)), 1.0)
    assert quiet.rms_db[0] - plain.rms_db[0] == pytest.approx(-6.0, abs=0.05)


def test_the_channels_are_read_apart(tmp_path) -> None:
    path = tmp_path / "pan.wav"
    audio.write_wav(tone(2.0, 0.8, right=0.2), path)
    level = levels.level_at(project(clip(path, duration=2.0)), 1.0)
    assert level.peak == pytest.approx((0.8, 0.2), abs=2e-3)
    assert level.rms[0] > 3.9 * level.rms[1]


def test_the_window_is_centred_on_the_playhead(wav) -> None:
    p = project(clip(wav, start=1.0, duration=1.0))
    on_the_edge = levels.level_at(p, 1.0)  # half the window sees the tone
    assert on_the_edge.peak[0] > 0.4 and on_the_edge.rms[0] < 0.30  # about half the energy
    assert levels.level_at(p, 0.9).peak == (0.0, 0.0)  # window ends at 0.95: before the sound
    assert levels.level_at(p, 2.0).rms[0] < 0.30
    assert levels.level_at(p, 2.2).peak == (0.0, 0.0)
    assert pytest.approx(0.1) == levels.WINDOW


def test_the_peak_is_of_the_absolute_value(tmp_path) -> None:
    path = tmp_path / "dc.wav"
    audio.write_wav(np.full((2, 2 * RATE), -0.4, np.float32), path)  # below zero all the time
    level = levels.level_at(project(clip(path, duration=2.0)), 1.0)
    assert level.peak == pytest.approx((0.4, 0.4), abs=1e-3) and level.rms == pytest.approx(
        (0.4, 0.4), abs=1e-3
    )


def test_silence_and_the_ends_of_the_video_are_not_nan(wav) -> None:
    p = project(clip(wav, start=0.0, duration=3.0))
    for t in (-1.0, 0.0, 4.0, 4.5):
        level = levels.level_at(p, t)
        assert all(math.isfinite(v) for v in (*level.peak, *level.rms))
    assert levels.level_at(p, 4.5).peak == (0.0, 0.0) and levels.level_at(p, 4.0).rms == (0.0, 0.0)
    assert levels.level_at(p, 0.0).peak[0] > 0.0  # the clipped half-window still reads
    assert levels.level_at(project(), 1.0) == levels.SILENCE


def test_decibels_and_the_meter_scale() -> None:
    assert levels.to_db(1.0) == pytest.approx(0.0) and levels.to_db(0.1) == pytest.approx(-20.0)
    assert levels.to_db(0.0) == -math.inf and levels.to_db(-0.5) == -math.inf
    assert levels.fraction(0.0) == 1.0 and levels.fraction(-60.0) == 0.0
    assert levels.fraction(-30.0) == pytest.approx(0.5)
    assert levels.fraction(-math.inf) == 0.0 and levels.fraction(-90.0) == 0.0 and levels.fraction(6.0) == 1.0
    assert (
        levels.label(-math.inf) == "-inf" and levels.label(-6.0206) == "-6.0" and levels.label(0.0) == "0.0"
    )
