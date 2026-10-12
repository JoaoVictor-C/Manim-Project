"""The level meter's numbers (P6b.4, ADR 0041): the mix at the playhead.

``level_at`` reads a short window (100 ms, centred on the playhead) of the project's sound. The
window is mixed straight from the decoded files - each clip's gain and fades are computed for the
slice only, with the arithmetic of ``audio.clip_samples`` - so it is exactly that span of
``audio.mix`` but costs the window, not the whole video, however often the sound is edited (B58).
Decoding a file the first time is the only large cost, and the timeline's waveforms have paid it.
No Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import audio
from .schema import AudioClip, Project

WINDOW = 0.1  # seconds, centred on the playhead
FLOOR_DB = -60.0  # the bottom of the meter


@dataclass(frozen=True)
class Level:
    """Peak and RMS of a window of the mix, per channel (left, right), linear 0..1."""

    peak: tuple[float, float]
    rms: tuple[float, float]

    @property
    def peak_db(self) -> tuple[float, float]:
        return (to_db(self.peak[0]), to_db(self.peak[1]))

    @property
    def rms_db(self) -> tuple[float, float]:
        return (to_db(self.rms[0]), to_db(self.rms[1]))


SILENCE = Level((0.0, 0.0), (0.0, 0.0))


def to_db(value: float) -> float:
    """dB relative to full scale; ``-inf`` for silence."""
    return 20 * math.log10(value) if value > 0 else -math.inf


def fraction(db: float) -> float:
    """Where a level sits on the meter: 0 at ``FLOOR_DB`` and below, 1 at 0 dB and above."""
    if db <= FLOOR_DB:
        return 0.0
    return min(1.0, (db - FLOOR_DB) / -FLOOR_DB)


def label(db: float) -> str:
    return "-inf" if db == -math.inf else f"{db:.1f}"


def window_samples(project: Project, t0: float, t1: float) -> np.ndarray:
    """The project's mix from ``t0`` to ``t1`` seconds (clamped to the video): ``(2, n)`` float32,
    equal to ``audio.mix(project)`` over the same samples, without mixing the rest."""
    total = round(project.canvas.duration * audio.RATE)
    first = min(max(round(t0 * audio.RATE), 0), total)
    last = min(max(round(t1 * audio.RATE), first), total)
    out = np.zeros((2, last - first), np.float32)
    for clip in project.audio:
        start = round(clip.start * audio.RATE)
        a, b = max(first, start), min(last, start + round(clip.duration * audio.RATE))
        if a < b:
            out[:, a - first : b - first] += _clip_slice(clip, a - start, b - start)
    np.clip(out, -1.0, 1.0, out=out)
    return out


def _clip_slice(clip: AudioClip, lo: int, hi: int) -> np.ndarray:
    """Samples ``lo`` to ``hi`` of ``audio.clip_samples(clip)``, computed for that slice only."""
    length = round(clip.duration * audio.RATE)
    out = np.zeros((2, hi - lo), np.float32)
    samples = audio.decode(clip.path)
    if samples is None:
        return out
    begin = round(clip.offset * audio.RATE) + lo
    part = samples[:, begin : begin + (hi - lo)]
    out[:, : part.shape[1]] = part
    envelope = np.full(hi - lo, 10 ** (clip.gain / 20), np.float32)
    index = np.arange(lo, hi, dtype=np.float32)
    n_in = min(length, round(clip.fade_in * audio.RATE))
    if n_in and lo < n_in:
        up = min(hi, n_in) - lo
        envelope[:up] *= (index[:up] + 0.5) / n_in
    n_out = min(length, round(clip.fade_out * audio.RATE))
    if n_out and hi > length - n_out:
        down = max(lo, length - n_out) - lo
        # the ramp counts down from the end: sample ``length - 1`` is the first of the ramp's shape
        envelope[down:] *= (np.float32(length - 1) - index[down:] + 0.5) / n_out
    return out * envelope


def level_at(project: Project, t: float, window: float = WINDOW) -> Level:
    """Peak and RMS of the ``window`` seconds of the mix centred on ``t``."""
    samples = window_samples(project, t - window / 2, t + window / 2)
    if not samples.shape[1]:
        return SILENCE
    wide = samples.astype(np.float64)
    peak = np.abs(wide).max(axis=1)
    rms = np.sqrt((wide * wide).mean(axis=1))
    return Level((float(peak[0]), float(peak[1])), (float(rms[0]), float(rms[1])))
