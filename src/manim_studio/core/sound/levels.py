"""The level meter's numbers (P6b.4, ADR 0041): the mix at the playhead.

``level_at`` reads a short window (100 ms, centred on the playhead) of the project's sound:
``audio.mix_span``, exactly that span of ``audio.mix``, costing the window and the decoded windows
of the files under it, not the whole video, however often the sound is edited (B58, B70). No Qt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..model.schema import Project
from . import audio

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
    return audio.mix_span(project, first, last - first)


def level_at(project: Project, t: float, window: float = WINDOW) -> Level:
    """Peak and RMS of the ``window`` seconds of the mix centred on ``t``."""
    samples = window_samples(project, t - window / 2, t + window / 2)
    if not samples.shape[1]:
        return SILENCE
    wide = samples.astype(np.float64)
    peak = np.abs(wide).max(axis=1)
    rms = np.sqrt((wide * wide).mean(axis=1))
    return Level((float(peak[0]), float(peak[1])), (float(rms[0]), float(rms[1])))
