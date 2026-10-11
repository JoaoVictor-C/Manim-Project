"""The project's sound (P4d, ADR 0034): one mix for playback, the export and exported scenes.

A project's audio clips are mixed into stereo float samples at 48 kHz, exactly
as long as the canvas: each clip plays ``duration`` seconds of its file from
``offset``, starting at ``start``, scaled by its gain (dB) and faded in and out
linearly; the sum is clipped to [-1, 1]. A file that is missing or cannot be
read is silent; ``problems`` says why.

Decoded files are kept in a small cache keyed by path and file signature (mtime
and size): a 10-minute file is ~230 MB decoded (B47). No Qt here.
"""

from __future__ import annotations

import json
import os
import wave
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

import av
import numpy as np

from ..logging_config import get_logger
from .schema import AudioClip, Project

log = get_logger(__name__)

RATE = 48_000  # samples per second, per channel
MISSING = "missing"
_DECODED: OrderedDict[tuple[str, str], np.ndarray | None] = OrderedDict()
_DECODED_KEEP = 4  # files kept decoded
_MIXES: OrderedDict[str, np.ndarray] = OrderedDict()  # by mix signature: the last two


def signature(path: str) -> str:
    """What a file's sound depends on: its modification time and size (``MISSING`` if unreadable)."""
    try:
        stat = os.stat(path) if path else None
    except OSError:
        stat = None
    return f"{stat.st_mtime_ns}:{stat.st_size}" if stat is not None else MISSING


def probe(path: str) -> float | None:
    """A file's length in seconds, read from its container (no decoding); None if unreadable."""
    return _probe(path, signature(path))


@lru_cache(maxsize=128)
def _probe(path: str, sig: str) -> float | None:
    if sig == MISSING:
        return None
    try:
        with av.open(path) as container:
            stream = container.streams.audio[0]
            if stream.duration is not None and stream.time_base is not None:
                return float(stream.duration * stream.time_base)
            if container.duration is not None:
                return container.duration / av.time_base
    except (av.FFmpegError, IndexError, OSError) as exc:
        log.info("cannot probe %s: %s", path, exc)
        return None
    decoded = decode(path)  # no duration in the header: measure it
    return None if decoded is None else decoded.shape[1] / RATE


def decode(path: str) -> np.ndarray | None:
    """A file's sound as ``(2, n)`` float32 at ``RATE``; None if it cannot be read."""
    key = (path, signature(path))
    if key in _DECODED:
        _DECODED.move_to_end(key)
        return _DECODED[key]
    samples = None if key[1] == MISSING else _decode(path)
    _DECODED[key] = samples
    while len(_DECODED) > _DECODED_KEEP:
        _DECODED.popitem(last=False)
    return samples


def _decode(path: str) -> np.ndarray | None:
    chunks = []
    try:
        with av.open(path) as container:
            resampler = av.AudioResampler(format="fltp", layout="stereo", rate=RATE)
            for frame in container.decode(audio=0):
                chunks.extend(out.to_ndarray() for out in resampler.resample(frame))
            chunks.extend(out.to_ndarray() for out in resampler.resample(None))
    except (av.FFmpegError, IndexError, OSError) as exc:
        log.info("cannot decode %s: %s", path, exc)
        return None
    if not chunks:
        return np.zeros((2, 0), np.float32)
    return np.ascontiguousarray(np.concatenate(chunks, axis=1), dtype=np.float32)


def peaks(path: str, per_second: int = 100) -> np.ndarray:
    """The loudest sample of each 1/``per_second`` of the file (both channels), for waveforms."""
    return _peaks(path, signature(path), per_second)


@lru_cache(maxsize=64)
def _peaks(path: str, sig: str, per_second: int) -> np.ndarray:
    samples = decode(path)
    if samples is None or not samples.shape[1]:
        return np.zeros(0, np.float32)
    loud = np.abs(samples).max(axis=0)
    step = RATE // per_second
    padded = np.pad(loud, (0, -len(loud) % step))
    return padded.reshape(-1, step).max(axis=1)


def problem(clip: AudioClip) -> str | None:
    """Why a sound is silent, or None."""
    if signature(clip.path) == MISSING:
        return "file not found"
    if decode(clip.path) is None:
        return "cannot read the file"
    return None


def problems(project: Project) -> dict[str, str]:
    return {clip.id: why for clip in project.audio if (why := problem(clip)) is not None}


def clip_samples(clip: AudioClip) -> np.ndarray:
    """A clip's own sound, ``round(duration × RATE)`` samples: trimmed, gained, faded (silence past
    the file's end, or for a file that cannot be read)."""
    length = round(clip.duration * RATE)
    out = np.zeros((2, length), np.float32)
    samples = decode(clip.path)
    if samples is None:
        return out
    first = round(clip.offset * RATE)
    part = samples[:, first : first + length]
    out[:, : part.shape[1]] = part
    envelope = np.full(length, 10 ** (clip.gain / 20), np.float32)
    for seconds, ramp in ((clip.fade_in, 1), (clip.fade_out, -1)):
        n = min(length, round(seconds * RATE))
        if n:
            shape = (np.arange(n, dtype=np.float32) + 0.5) / n
            if ramp > 0:
                envelope[:n] *= shape
            else:
                envelope[length - n :] *= shape[::-1]
    return out * envelope


def mix_signature(project: Project) -> str:
    """What the mix depends on: the clips, their files' signatures and the canvas duration."""
    clips = [(clip.model_dump(), signature(clip.path)) for clip in project.audio]
    return json.dumps([project.canvas.duration, clips], sort_keys=True)


def mix(project: Project) -> np.ndarray:
    """The project's sound: ``(2, round(duration × RATE))`` float32 in [-1, 1]."""
    key = mix_signature(project)
    if key in _MIXES:
        _MIXES.move_to_end(key)
        return _MIXES[key]
    total = round(project.canvas.duration * RATE)
    out = np.zeros((2, total), np.float32)
    for clip in project.audio:
        first = round(clip.start * RATE)
        if first >= total:
            continue
        samples = clip_samples(clip)[:, : total - first]
        out[:, first : first + samples.shape[1]] += samples
    np.clip(out, -1.0, 1.0, out=out)
    _MIXES[key] = out
    while len(_MIXES) > 2:
        _MIXES.popitem(last=False)
    return out


def to_int16(samples: np.ndarray) -> bytes:
    """Interleaved little-endian 16-bit PCM (what a sound card and a WAV file take)."""
    return (np.clip(samples.T, -1.0, 1.0) * 32767).round().astype("<i2").tobytes()


def write_wav(samples: np.ndarray, path: Path) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(to_int16(samples))


def forget() -> None:
    """Drop decoded files and mixes (tests; a file rewritten within the same second)."""
    _DECODED.clear()
    _MIXES.clear()
    _probe.cache_clear()
    _peaks.cache_clear()
