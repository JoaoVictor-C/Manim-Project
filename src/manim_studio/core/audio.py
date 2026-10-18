"""The project's sound (P4d, ADR 0034): one mix for playback, the export and exported scenes.

A project's audio clips are mixed into stereo float samples at 48 kHz, exactly
as long as the canvas: each clip plays ``duration`` seconds of its file from
``offset``, starting at ``start``, scaled by its gain (dB) and faded in and out
linearly; the sum is clipped to [-1, 1]. A file that is missing or cannot be
read is silent; ``problems`` says why.

The mix is computed per span (ADR 0034 amendment, B70): ``mix_span`` gives any
samples of it, bit-identical to the same slice of the whole mix, from the parts
of the files under them. Files are decoded on demand in windows of ``CHUNK``
samples, kept in a cache bounded in bytes (``WINDOW_BYTES``); no file is held
decoded whole. A window deep in a file is reached by seeking: the decoder starts
``WARM_SECONDS`` early and the resampler restarts on a sample where its phase is
the whole decode's, ``WARM_OUTPUT`` samples early, so the window's samples are
the whole decode's. That is trusted for PCM and FLAC in their own containers
(tested at many rates); any other format seeks only once ``scan`` - one
streaming pass that also gives the waveform peaks - has recorded a hash of each
window, and every sought window is checked against it: a format that does not
decode identically after a seek (AAC) is then always decoded from the start.
No Qt here.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import wave
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from math import gcd
from pathlib import Path

import av
import numpy as np

from ..logging_config import get_logger
from .schema import AudioClip, Project

log = get_logger(__name__)

RATE = 48_000  # samples per second, per channel
MISSING = "missing"
CHUNK = 61_440  # samples per decoded window (1.28 s, 480 KB): a whole number of 1/100 s peaks
PEAK_STEP = RATE // 100  # the scan's peaks: the loudest sample of each 1/100 s
WINDOW_BYTES = 64 << 20  # decoded windows kept, all files together
WARM_SECONDS = 3.0  # decoded and dropped before a sought window (the codec's state)
WARM_OUTPUT = 4096  # resampled and dropped before a sought window (the resampler's filter)
READERS = 4  # open decoders kept positioned where they stopped
SPAN = 12_000  # samples per span when a long stretch of the mix is made (0.25 s)
TRUSTED = {"wav", "w64", "aiff", "flac"}  # containers whose PCM / FLAC seeks are sample-exact

_DECODED: OrderedDict[tuple[str, str], np.ndarray | None] = OrderedDict()  # decode(): tests, small files
_DECODED_KEEP = 4  # files kept decoded by decode()
_DECODED_MAX_BYTES = 16 << 20  # a larger decode is returned, never kept
_MIXES: OrderedDict[str, np.ndarray] = OrderedDict()  # no longer filled: the mix is made per span

COUNTS = {"seeks": 0, "refused": 0, "mismatches": 0, "windows": 0}  # decoder activity (tests, benchmarks)
_lock = threading.RLock()
_WINDOWS: OrderedDict[tuple[str, str, int], np.ndarray] = OrderedDict()
_window_bytes = 0
_READER_POOL: list[_Reader] = []
_INFOS: OrderedDict[tuple[str, str], _Info | None] = OrderedDict()
_SCANS: OrderedDict[tuple[str, str], Scan | None] = OrderedDict()
_KEEP_INFOS = 64


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
    found = scan(path)  # no duration in the header: measure it, streaming
    return None if found is None else found.length / RATE


# -- the whole decode: the reference ------------------------------------------------------------


def decode(path: str) -> np.ndarray | None:
    """A file's sound as ``(2, n)`` float32 at ``RATE``; None if it cannot be read. The reference
    the windows are tested against; the engine reads windows (``file_span``). A long file's decode
    is returned and never kept."""
    key = (path, signature(path))
    if key in _DECODED:
        _DECODED.move_to_end(key)
        return _DECODED[key]
    samples = None if key[1] == MISSING else _decode(path)
    if samples is None or samples.nbytes <= _DECODED_MAX_BYTES:
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


# -- decoding on demand -------------------------------------------------------------------------


class _Unreadable(Exception):
    """The file failed to decode: it is silent, as a file the whole decode could not read."""


class _NoSeek(Exception):
    """A seek did not land where its samples can be trusted: decode from the start instead."""


@dataclass
class _Info:
    """What seeking in a file needs, read once per signature."""

    rate: int  # the decoded frames' sample rate
    pts0: int | None  # the first frame's timestamp: sample 0 of the whole decode
    time_base: Fraction | None
    trusted: bool  # a PCM / FLAC file in its own container: seeks are sample-exact
    seekable: bool = True  # False once a sought window differed from the scan
    unreadable: bool = False


@dataclass
class Scan:
    """One streaming pass over a file: its decoded length, a hash of each window, its peaks."""

    length: int  # samples at RATE
    hashes: list[bytes]  # of each CHUNK of the whole decode
    peaks: np.ndarray  # the loudest sample of each PEAK_STEP


def _info(path: str, sig: str) -> _Info | None:
    key = (path, sig)
    with _lock:
        if key in _INFOS:
            _INFOS.move_to_end(key)
            found = _INFOS[key]
            return None if found is None or found.unreadable else found
    found = None
    if sig != MISSING:
        try:
            with av.open(path) as container:
                stream = container.streams.audio[0]
                codec = stream.codec_context.name
                trusted = container.format.name in TRUSTED and (codec.startswith("pcm_") or codec == "flac")
                rate, pts0, time_base = stream.codec_context.sample_rate, None, None
                for frame in container.decode(stream):
                    rate, pts0, time_base = frame.sample_rate, frame.pts, frame.time_base
                    break
                found = _Info(rate, pts0, Fraction(time_base) if time_base else None, trusted)
        except (av.FFmpegError, IndexError, OSError) as exc:
            log.info("cannot read %s: %s", path, exc)
    with _lock:
        _INFOS[key] = found
        while len(_INFOS) > _KEEP_INFOS:
            _INFOS.popitem(last=False)
    return found


def _mark_unreadable(path: str, sig: str, exc: Exception) -> None:
    log.info("cannot decode %s: %s", path, exc)
    with _lock:
        info = _INFOS.get((path, sig))
        if info is not None:
            info.unreadable = True
        for k in [k for k in _WINDOWS if k[:2] == (path, sig)]:
            _drop_window(k)


class _Reader:
    """Decodes a file forward, window after window, from a window it was opened at (by a seek
    when allowed, else from the file's start)."""

    def __init__(self, path: str, sig: str, info: _Info, window: int, seek: bool) -> None:
        self.key = (path, sig)
        self.pos = window * CHUNK  # the next sample read() returns
        self.sought = False
        self._info = info
        self._pending: list[np.ndarray] = []
        self._have = 0  # the index of the first pending sample
        self._next_input: int | None = None  # after a seek: the input sample the next frame must start at
        self._eof = False
        try:
            self._container = av.open(path)
            self._stream = self._container.streams.audio[0]
            self._frames = self._container.decode(self._stream)
        except (av.FFmpegError, IndexError, OSError) as exc:
            raise _Unreadable(exc) from exc
        self._resampler = av.AudioResampler(format="fltp", layout="stereo", rate=RATE)
        if seek and self.pos > 0:
            try:
                self._seek(self.pos)
            except BaseException:
                self.close()
                raise

    def close(self) -> None:
        self._container.close()

    def _seek(self, target: int) -> None:
        info = self._info
        if info.pts0 is None or info.time_base is None:
            raise _NoSeek("no timestamps")
        rate = info.rate
        common = gcd(rate, RATE)
        period_out, period_in = RATE // common, rate // common  # the resampler's phase repeats
        start_out = (target - WARM_OUTPUT) // period_out * period_out
        if start_out <= 0:
            return  # close to the start: decode from it
        start_in = start_out // period_out * period_in
        early = Fraction(start_in, rate) - Fraction(WARM_SECONDS)
        if early <= 0:
            return
        self._container.seek(
            info.pts0 + int(early / info.time_base), stream=self._stream, backward=True, any_frame=False
        )
        self._frames = self._container.decode(self._stream)
        warmed = False
        for frame in self._frames:
            first = self._input_index(frame)
            if not warmed:
                if first > start_in - rate * WARM_SECONDS / 2:
                    raise _NoSeek(f"landed at input sample {first}, wanted before {start_in}")
                warmed = True
            self._next_input = first + frame.samples
            if first + frame.samples <= start_in:
                continue  # the codec warms up on it
            cut = frame.to_ndarray()
            skip = start_in - first
            cut = cut[:, skip:] if frame.format.is_planar else cut[:, skip * len(frame.layout.channels) :]
            head = av.AudioFrame.from_ndarray(
                np.ascontiguousarray(cut), format=frame.format.name, layout=frame.layout.name
            )
            head.sample_rate = frame.sample_rate
            self._have = start_out
            self.sought = True
            COUNTS["seeks"] += 1
            self._resample(head)
            return
        raise _NoSeek("nothing after the seek")

    def _input_index(self, frame) -> int:
        info = self._info
        if frame.pts is None:
            raise _NoSeek("a frame without a timestamp")
        index = (frame.pts - info.pts0) * info.time_base * info.rate
        if index.denominator != 1 or (self._next_input is not None and index != self._next_input):
            raise _NoSeek(f"frame at {float(index)}, expected {self._next_input}")
        return int(index)

    def _resample(self, frame) -> None:
        for out in self._resampler.resample(frame):
            self._keep(out.to_ndarray())

    def _keep(self, samples: np.ndarray) -> None:
        end = self._have + sum(p.shape[1] for p in self._pending) + samples.shape[1]
        if end <= self.pos:  # still before the window wanted: dropped
            self._have = end
            self._pending.clear()
            return
        self._pending.append(samples)

    def _pump(self) -> None:
        try:
            frame = next(self._frames)
        except StopIteration:
            for out in self._resampler.resample(None):
                self._keep(out.to_ndarray())
            self._eof = True
            return
        except av.FFmpegError as exc:
            raise _Unreadable(exc) from exc
        if self.sought:
            self._next_input = self._input_index(frame) + frame.samples
        self._resample(frame)

    def read(self) -> np.ndarray:
        """The window at ``pos`` (shorter at the end of the file, empty past it); moves on."""
        target = self.pos + CHUNK
        try:
            while not self._eof and self._have + sum(p.shape[1] for p in self._pending) < target:
                self._pump()
        except (av.FFmpegError, OSError) as exc:
            raise _Unreadable(exc) from exc
        data = (
            np.concatenate(self._pending, axis=1) if self._pending else np.zeros((2, 0), np.float32)
        )
        lo = self.pos - self._have
        window = np.ascontiguousarray(data[:, lo : lo + CHUNK], dtype=np.float32)
        rest = data[:, lo + CHUNK :]
        self.pos += CHUNK
        self._pending = [rest] if rest.shape[1] else []
        self._have = self.pos  # (past the end once the file has ended: nothing more comes)
        return window


def _hash(window: np.ndarray) -> bytes:
    return hashlib.blake2b(window.tobytes(), digest_size=16).digest()


def _matches(checked: Scan, k: int, window: np.ndarray) -> bool:
    """Window ``k`` is the scan's (an empty window past the file's end matches nothing scanned)."""
    if k >= len(checked.hashes):
        return not window.shape[1]
    return _hash(window) == checked.hashes[k]


def _store(key: tuple[str, str, int], window: np.ndarray) -> None:
    global _window_bytes
    with _lock:
        if key in _WINDOWS:
            return
        _WINDOWS[key] = window
        _window_bytes += window.nbytes
        while _window_bytes > WINDOW_BYTES and len(_WINDOWS) > 1:
            _drop_window(next(iter(_WINDOWS)))


def _drop_window(key: tuple[str, str, int]) -> None:
    global _window_bytes
    _window_bytes -= _WINDOWS.pop(key).nbytes


def _take_reader(path: str, sig: str, window: int, may_seek: bool) -> _Reader | None:
    """An open reader that can go on to ``window``: at it, or behind it (only a few windows
    behind when a seek is the other way). Without seeking, only a reader that started at the
    file's start."""
    with _lock:
        best = None
        for reader in _READER_POOL:
            if reader.key != (path, sig) or reader.pos > window * CHUNK or (reader.sought and not may_seek):
                continue
            gap = window - reader.pos // CHUNK
            if may_seek and gap > 3:
                continue
            if best is None or reader.pos > best.pos:
                best = reader
        if best is not None:
            _READER_POOL.remove(best)
        return best


def _give_back(reader: _Reader) -> None:
    with _lock:
        _READER_POOL.append(reader)
        while len(_READER_POOL) > READERS:
            _READER_POOL.pop(0).close()


def _window(path: str, sig: str, k: int) -> np.ndarray | None:
    """Window ``k`` of a file's whole decode (CHUNK samples from ``k × CHUNK``), or None."""
    key = (path, sig, k)
    with _lock:
        if key in _WINDOWS:
            _WINDOWS.move_to_end(key)
            return _WINDOWS[key]
    info = _info(path, sig)
    if info is None:
        return None
    with _lock:
        checked = _SCANS.get((path, sig))
    may_seek = info.seekable and (info.trusted or checked is not None)
    for attempt in (may_seek, False):
        reader = _take_reader(path, sig, k, attempt)
        try:
            if reader is None:
                try:
                    reader = _Reader(path, sig, info, k, seek=attempt)
                except _NoSeek as why:
                    log.debug("no seek in %s: %s", path, why)
                    COUNTS["refused"] += 1
                    info.seekable = False
                    reader = _Reader(path, sig, info, k, seek=False)
            while reader.pos < k * CHUNK:
                reader.read()
            window = reader.read()
        except _NoSeek as why:
            log.debug("no seek in %s: %s", path, why)
            COUNTS["refused"] += 1
            info.seekable = False
            if reader is not None:
                reader.close()
            continue
        except _Unreadable as exc:
            if reader is not None:
                reader.close()
            _mark_unreadable(path, sig, exc)
            return None
        COUNTS["windows"] += 1
        if reader.sought and checked is not None and not _matches(checked, k, window):
            log.info("%s does not decode identically after a seek: read from its start", path)
            COUNTS["mismatches"] += 1
            info.seekable = False
            reader.close()
            continue
        _give_back(reader)
        _store(key, window)
        return window
    return None


def file_span(path: str, start: int, count: int) -> np.ndarray | None:
    """Samples ``start`` to ``start + count`` of the file's whole decode - ``decode(path)[:, start :
    start + count]``, shorter past the file's end - from the windows under them; None if the file
    is missing or cannot be read."""
    sig = signature(path)
    if sig == MISSING or _info(path, sig) is None:
        return None
    parts = []
    k, end = start // CHUNK, start + count
    while k * CHUNK < end:
        window = _window(path, sig, k)
        if window is None:
            return None
        lo = max(start - k * CHUNK, 0)
        parts.append(window[:, lo : end - k * CHUNK])
        if window.shape[1] < CHUNK:
            break  # the end of the file
        k += 1
    if not parts:
        return np.zeros((2, 0), np.float32)
    return parts[0] if len(parts) == 1 else np.concatenate(parts, axis=1)


def window_bytes() -> int:
    """The bytes of decoded windows kept now (at most about ``WINDOW_BYTES``)."""
    return _window_bytes


# -- the scan: length, window hashes and peaks in one streaming pass ----------------------------


def scan(path: str) -> Scan | None:
    """Decode a file once from its start, window by window, keeping only its length, a hash of each
    window and its peaks (kept per signature); None if it cannot be read. Seconds for a long file:
    the editor runs it in the background."""
    sig = signature(path)
    key = (path, sig)
    with _lock:
        if key in _SCANS:
            return _SCANS[key]
    info = _info(path, sig)
    found = None
    if info is not None:
        try:
            found = _scan(path, sig, info)
        except _Unreadable as exc:
            _mark_unreadable(path, sig, exc)
    with _lock:
        _SCANS[key] = found
        while len(_SCANS) > _KEEP_INFOS:
            _SCANS.popitem(last=False)
    return found


def _scan(path: str, sig: str, info: _Info) -> Scan:
    reader = _Reader(path, sig, info, 0, seek=False)
    hashes, peaks, length = [], [], 0
    try:
        while True:
            window = reader.read()
            if window.shape[1]:
                hashes.append(_hash(window))
                loud = np.abs(window).max(axis=0)
                peaks.append(np.pad(loud, (0, -len(loud) % PEAK_STEP)).reshape(-1, PEAK_STEP).max(axis=1))
                length += window.shape[1]
            if window.shape[1] < CHUNK:
                break
    finally:
        reader.close()
    return Scan(length, hashes, np.concatenate(peaks) if peaks else np.zeros(0, np.float32))


def peaks(path: str, per_second: int = 100) -> np.ndarray:
    """The loudest sample of each 1/``per_second`` of the file (both channels), for waveforms;
    computed by a streaming pass, never from the whole decode."""
    return _peaks(path, signature(path), per_second)


def peaks_ready(path: str, per_second: int = 100) -> np.ndarray | None:
    """The peaks if they cost nothing now (the file was scanned, or is missing), else None."""
    sig = signature(path)
    with _lock:
        known = (path, sig) in _SCANS or sig == MISSING
    return _peaks(path, sig, per_second) if known else None


@lru_cache(maxsize=64)
def _peaks(path: str, sig: str, per_second: int) -> np.ndarray:
    step = RATE // per_second
    if step % PEAK_STEP == 0:  # grouped from the scan's: the same maxima over the same samples
        found = scan(path) if sig != MISSING else None
        if found is None or not found.length:
            return np.zeros(0, np.float32)
        group = step // PEAK_STEP
        return np.pad(found.peaks, (0, -len(found.peaks) % group)).reshape(-1, group).max(axis=1)
    info = _info(path, sig)
    if info is None:
        return np.zeros(0, np.float32)
    out, carry = [], np.zeros(0, np.float32)
    try:
        reader = _Reader(path, sig, info, 0, seek=False)
    except _Unreadable:
        return np.zeros(0, np.float32)
    try:
        while True:
            window = reader.read()
            loud = np.concatenate([carry, np.abs(window).max(axis=0)]) if window.shape[1] else carry
            whole = len(loud) // step * step
            if whole:
                out.append(loud[:whole].reshape(-1, step).max(axis=1))
            carry = loud[whole:]
            if window.shape[1] < CHUNK:
                break
    except _Unreadable:
        return np.zeros(0, np.float32)
    finally:
        reader.close()
    if len(carry):
        out.append(np.array([carry.max()], np.float32))
    return np.concatenate(out) if out else np.zeros(0, np.float32)


# -- problems -----------------------------------------------------------------------------------


def problem(clip: AudioClip) -> str | None:
    """Why a sound is silent, or None (opening the file and decoding its first frame)."""
    sig = signature(clip.path)
    if sig == MISSING:
        return "file not found"
    if _info(clip.path, sig) is None:
        return "cannot read the file"
    return None


def problems(project: Project) -> dict[str, str]:
    return {clip.id: why for clip in project.audio if (why := problem(clip)) is not None}


# -- the mix ------------------------------------------------------------------------------------


def clip_samples(clip: AudioClip) -> np.ndarray:
    """A clip's own sound, ``round(duration × RATE)`` samples: trimmed, gained, faded (silence past
    the file's end, or for a file that cannot be read). The reference for ``mix_span``'s per-clip
    arithmetic; the engine never builds a whole clip."""
    length = round(clip.duration * RATE)
    return _clip_span(clip, 0, length, length)


def envelope(clip: AudioClip, lo: int, hi: int) -> np.ndarray:
    """Samples ``lo`` to ``hi`` of the clip's gain-and-fades envelope, float32, with the whole
    clip's arithmetic: the gain, times the fade-in ramp, times the fade-out ramp, where the ramp at
    ``k`` is ``(float32(k) + 0.5) / n`` for an integer index ``k`` (a float32 range starting mid-clip
    would round differently past 2**24 samples)."""
    length = round(clip.duration * RATE)
    out = np.full(hi - lo, 10 ** (clip.gain / 20), np.float32)
    n_in = min(length, round(clip.fade_in * RATE))
    if n_in and lo < n_in:
        k = np.arange(lo, min(hi, n_in))
        out[: len(k)] *= (k.astype(np.float32) + 0.5) / n_in
    n_out = min(length, round(clip.fade_out * RATE))
    if n_out and hi > length - n_out:
        a = max(lo, length - n_out)
        k = (length - 1) - np.arange(a, hi)  # the ramp counts down to the clip's last sample
        out[a - lo :] *= (k.astype(np.float32) + 0.5) / n_out
    return out


def _clip_span(clip: AudioClip, lo: int, hi: int, length: int) -> np.ndarray:
    """Samples ``lo`` to ``hi`` of the clip's own sound, computed for that slice only."""
    out = np.zeros((2, hi - lo), np.float32)
    part = file_span(clip.path, round(clip.offset * RATE) + lo, hi - lo)
    if part is None:
        return out
    out[:, : part.shape[1]] = part
    return out * envelope(clip, lo, hi)


def mix_span(project: Project, start: int, count: int) -> np.ndarray:
    """Samples ``start`` to ``start + count`` of the project's mix: ``(2, n)`` float32 in [-1, 1],
    equal to ``mix(project)[:, start : start + count]`` sample for sample (shorter past the end):
    each clip under the span adds its slice in the clips' order, then the sum is clipped - the
    whole mix's arithmetic on fewer samples."""
    total = round(project.canvas.duration * RATE)
    start = max(0, start)
    end = min(start + max(0, count), total)
    out = np.zeros((2, max(0, end - start)), np.float32)
    for clip in project.audio:
        first = round(clip.start * RATE)
        if first >= total:
            continue
        length = round(clip.duration * RATE)
        a, b = max(start, first), min(end, first + min(length, total - first))
        if a < b:
            out[:, a - start : b - start] += _clip_span(clip, a - first, b - first, length)
    np.clip(out, -1.0, 1.0, out=out)
    return out


def mix_signature(project: Project) -> str:
    """What the mix depends on: the clips, their files' signatures and the canvas duration."""
    clips = [(clip.model_dump(), signature(clip.path)) for clip in project.audio]
    return json.dumps([project.canvas.duration, clips], sort_keys=True)


def mix(project: Project) -> np.ndarray:
    """The project's whole sound: ``(2, round(duration × RATE))`` float32 in [-1, 1], made of spans
    (for a file of the whole mix, the exact Python scene's; playback and the export read spans)."""
    total = round(project.canvas.duration * RATE)
    out = np.empty((2, total), np.float32)
    for start in range(0, total, CHUNK):
        out[:, start : start + CHUNK] = mix_span(project, start, CHUNK)
    return out


def mix_chunks(project: Project, start: int, stop: int, span: int = SPAN) -> Iterator[np.ndarray]:
    """Samples ``start`` to ``stop`` of the mix in pieces of ``span``, silence past the mix's end."""
    for first in range(start, stop, span):
        n = min(span, stop - first)
        piece = mix_span(project, first, n)
        if piece.shape[1] < n:
            piece = np.pad(piece, ((0, 0), (0, n - piece.shape[1])))
        yield piece


class MixSource:
    """The project's mix read in spans (playback); ``np.asarray`` of it is the whole mix."""

    def __init__(self, project: Project) -> None:
        self.project = project
        self.length = round(project.canvas.duration * RATE)

    def span(self, start: int, count: int) -> np.ndarray:
        return mix_span(self.project, start, count)

    def __array__(self, dtype=None, copy=None) -> np.ndarray:
        whole = mix(self.project)
        return whole if dtype is None else whole.astype(dtype)


def source(project: Project) -> MixSource:
    return MixSource(project)


def to_int16(samples: np.ndarray) -> bytes:
    """Interleaved little-endian 16-bit PCM (what a sound card and a WAV file take)."""
    return (np.clip(samples.T, -1.0, 1.0) * 32767).round().astype("<i2").tobytes()


def write_wav(samples: np.ndarray, path: Path) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(to_int16(samples))


def forget_windows() -> None:
    """Drop the decoded windows and close the open readers (keep what files are)."""
    with _lock:
        _WINDOWS.clear()
        global _window_bytes
        _window_bytes = 0
        for reader in _READER_POOL:
            reader.close()
        _READER_POOL.clear()


def forget() -> None:
    """Drop everything decoded or learned about files (tests; a file rewritten within the same
    second)."""
    forget_windows()
    with _lock:
        _DECODED.clear()
        _MIXES.clear()
        _INFOS.clear()
        _SCANS.clear()
        for name in COUNTS:
            COUNTS[name] = 0
    _probe.cache_clear()
    _peaks.cache_clear()
