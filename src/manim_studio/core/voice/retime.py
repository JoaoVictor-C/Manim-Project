"""Follow speech and Fit speech to cues (ADR 0060): keeping subtitles and their sound in step.

Both are pure: they take the cues and sounds of a project and return new ones. They move cues and the
sounds they generated and nothing else (layers, markers and code stay where they are).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model.schema import AudioClip, Cue

FIT_LIMITS = (0.85, 1.25)  # the speeds Fit speech to cues may use, as a multiple of the cue's own
PAUSE = 0.6  # seconds between two spoken cues, by default
FIT_SLACK = 1.02  # a speech this much longer than its cue still counts as fitting


def follow(
    cues: list[Cue], audio: list[AudioClip], pause: float = PAUSE
) -> tuple[list[Cue], list[AudioClip]]:
    """Retime ``cues`` (in order) so each one lasts as long as its speech and starts ``pause`` seconds
    after the previous one ends; the first keeps its start. A cue without a generated sound keeps its
    own length. A cue with its own ``pause_before`` is that long after the one before it. The sound of
    a cue starts with it. Idempotent."""
    by_id = {clip.id: clip for clip in audio}
    moved: dict[str, AudioClip] = {}
    out: list[Cue] = []
    t = 0.0
    for i, cue in enumerate(cues):
        clip = by_id.get(cue.audio_id) if cue.audio_id else None
        length = clip.duration if clip is not None else cue.end - cue.start
        start = cue.start if i == 0 else t + (pause if cue.pause_before is None else cue.pause_before)
        out.append(cue.model_copy(update={"start": start, "end": start + length}))
        if clip is not None:
            moved[clip.id] = clip.model_copy(update={"start": start})
        t = start + length
    return out, [moved.get(clip.id, clip) for clip in audio]


@dataclass(frozen=True)
class Fit:
    cue_id: str
    rate: float  # the speed to speak at (the cue's current speed times the correction)
    fits: bool  # False: even at the limit the speech is longer than the cue


def fit_rates(
    cues: list[Cue], audio: list[AudioClip], rates: dict[str, float], limits: tuple[float, float] = FIT_LIMITS
) -> list[Fit]:
    """For each cue with a generated sound, the speed that makes it last as long as the cue (within
    ``limits`` times its current speed). ``rates`` has each cue's current speed. The sound must be
    generated again at the new speed; cues already within a frame of fitting are left out."""
    by_id = {clip.id: clip for clip in audio}
    low, high = limits
    fitted: list[Fit] = []
    for cue in cues:
        clip = by_id.get(cue.audio_id) if cue.audio_id else None
        if clip is None:
            continue
        window, current = cue.end - cue.start, rates.get(cue.id, 1.0)
        wanted = clip.duration / window  # >1: the speech is longer than the cue, speak faster
        factor = min(max(wanted, low), high)
        if abs(factor - 1.0) < 1e-3:
            continue
        fitted.append(Fit(cue.id, round(current * factor, 3), clip.duration / factor <= window * FIT_SLACK))
    return fitted
