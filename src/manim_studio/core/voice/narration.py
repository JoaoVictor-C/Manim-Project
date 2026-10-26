"""Narration (ADR 0060): which cues need speech, what to ask a voice for, and where the sound goes.

A narrated cue is a subtitle plus a sound. Whether its sound is current is *derived*, never stored as a
flag: the cue keeps the key of what its sound says (``audio_key``) and the sound is stale when the key
of the cue as it is now differs. Everything here is pure; a provider is only named, never called.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ... import plugins
from ..editing import edits
from ..model.schema import AudioClip, Cue, Project, VoiceChoice
from . import pronunciation, retime, voice_cache

EMPTY = "no text"
NO_VOICE = "no voice"
NEW = "not generated"
STALE = "stale"
READY = "ready"


@dataclass(frozen=True)
class Job:
    """One text to speak: everything the voice helper needs, and where the file goes."""

    cue_id: str
    provider: str
    voice: str
    rate: float
    text: str  # as spoken (the pronunciation dictionary applied)
    key: str
    out: Path


@dataclass(frozen=True)
class Spoken:
    """A finished job: the file exists and lasts ``seconds``."""

    cue_id: str
    key: str
    path: Path
    seconds: float


@dataclass(frozen=True)
class Plan:
    jobs: list[Job]  # to be spoken
    cached: list[Job]  # their file exists already: only to be placed
    skipped: dict[str, str]  # cue id -> why nothing is generated for it


def effective_voice(project: Project, cue: Cue) -> VoiceChoice | None:
    return cue.voice or project.voice


def spoken_text(project: Project, cue: Cue) -> str:
    return pronunciation.spoken(cue.text, project.pronunciations)


def make_key(choice: VoiceChoice, text: str) -> str:
    raw = "\x1f".join((choice.provider, choice.voice, f"{choice.rate:.3f}", text))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def key_for(project: Project, cue: Cue) -> str | None:
    """The key of what the cue would say now; None when it has no text or no voice."""
    choice, text = effective_voice(project, cue), spoken_text(project, cue)
    return make_key(choice, text) if choice is not None and text else None


def state(project: Project, cue: Cue) -> str:
    """The cue's EMPTY, NO_VOICE, NEW (none made, or its sound deleted), STALE or READY."""
    if not cue.text.strip():
        return EMPTY
    key = key_for(project, cue)
    if key is None:
        return NO_VOICE
    if cue.audio_key is None or not any(clip.id == cue.audio_id for clip in project.audio):
        return NEW
    return READY if cue.audio_key == key else STALE


def counts(project: Project) -> dict[str, int]:
    found: dict[str, int] = {}
    for cue in project.subtitles:
        found[state(project, cue)] = found.get(state(project, cue), 0) + 1
    return found


def plan(project: Project, cue_ids: list[str] | None, folder: Path, *, only_missing: bool = True) -> Plan:
    """What to generate for ``cue_ids`` (None: every cue). With ``only_missing`` a cue whose sound is
    current is left alone; a file already in ``folder`` is not spoken again (``cached``)."""
    providers = plugins.voice_providers()
    chosen = None if cue_ids is None else set(cue_ids)
    jobs: list[Job] = []
    cached: list[Job] = []
    skipped: dict[str, str] = {}
    for cue in project.subtitles:
        if chosen is not None and cue.id not in chosen:
            continue
        why = state(project, cue)
        if why in (EMPTY, NO_VOICE):
            skipped[cue.id] = why
            continue
        if only_missing and why == READY:
            continue
        choice = effective_voice(project, cue)
        provider = providers.get(choice.provider)
        if provider is None:
            skipped[cue.id] = f"the voice provider {choice.provider!r} is not installed"
            continue
        text = spoken_text(project, cue)
        key = make_key(choice, text)
        job = Job(
            cue.id,
            choice.provider,
            choice.voice,
            choice.rate,
            text,
            key,
            voice_cache.path_for(folder, key, provider.extension),
        )
        (cached if job.out.exists() and job.out.stat().st_size > 0 else jobs).append(job)
    return Plan(jobs, cached, skipped)


def place(
    project: Project, spoken: list[Spoken], *, follow: bool = False, pause: float = retime.PAUSE
) -> edits.Edit:
    """The edit that puts each finished sound at its cue's start (a new sound, or the cue's own
    replaced, keeping its gain) and, with ``follow``, retimes the cues to their speech."""
    clips = list(project.audio)
    cues = list(project.subtitles)
    taken = {x.id for x in clips} | {c.id for c in cues} | {layer.id for layer in project.layers}
    taken |= {m.id for m in project.markers}
    by_cue = {s.cue_id: s for s in spoken}
    for i, cue in enumerate(cues):
        result = by_cue.get(cue.id)
        if result is None:
            continue
        at = next((n for n, c in enumerate(clips) if c.id == cue.audio_id), None)
        name = " ".join(cue.text.split())[:40]
        if at is None:
            clip_id = _free(f"voice-{cue.id}", taken)
            taken.add(clip_id)
            clips.append(
                AudioClip(
                    id=clip_id, name=name, path=str(result.path), start=cue.start, duration=result.seconds
                )
            )
        else:
            old = clips[at]
            fades = {} if old.fade_in + old.fade_out <= result.seconds else {"fade_in": 0.0, "fade_out": 0.0}
            clips[at] = old.model_copy(
                update={
                    "path": str(result.path),
                    "offset": 0.0,
                    "start": cue.start,
                    "duration": result.seconds,
                    "name": old.name or name,
                    **fades,
                }
            )
            clip_id = old.id
        cues[i] = cue.model_copy(update={"audio_id": clip_id, "audio_key": result.key})
    if follow:
        cues, clips = retime.follow(cues, clips, pause)
    return edits.set_narration(project, cues, clips)


def follow_speech(project: Project, pause: float = retime.PAUSE) -> edits.Edit:
    """Retime the cues to the length of their speech (see ``retime.follow``)."""
    cues, clips = retime.follow(list(project.subtitles), list(project.audio), pause)
    return edits.set_narration(project, cues, clips)


def fit_speech(project: Project) -> tuple[edits.Edit, list[retime.Fit]]:
    """Set each narrated cue's speed to the one that fits its length (``retime.fit_rates``); their
    sounds become stale and are generated again at the new speed. Also reports the cues that cannot fit."""
    rates = {
        c.id: (effective_voice(project, c).rate if effective_voice(project, c) else 1.0)
        for c in project.subtitles
    }
    fits = retime.fit_rates(list(project.subtitles), list(project.audio), rates)
    changed = {f.cue_id: f.rate for f in fits}
    cues = []
    for cue in project.subtitles:
        choice = effective_voice(project, cue)
        if cue.id in changed and choice is not None:
            cue = cue.model_copy(update={"voice": choice.model_copy(update={"rate": changed[cue.id]})})
        cues.append(cue)
    return edits.set_narration(project, cues, list(project.audio)), fits


def _free(wanted: str, taken: set[str]) -> str:
    name, n = wanted, 1
    while name in taken:
        n += 1
        name = f"{wanted}-{n}"
    return name


def script(project: Project) -> str:
    """The narration as plain text for reading aloud or for a script review: each cue's words as
    written (not as pronounced), with the time it starts, one paragraph per cue."""
    paragraphs = []
    for cue in project.subtitles:
        words = " ".join(cue.text.split())
        if words:
            minutes, seconds = divmod(cue.start, 60)
            paragraphs.append(f"[{int(minutes)}:{seconds:04.1f}] {words}")
    return "\n\n".join(paragraphs) + ("\n" if paragraphs else "")
