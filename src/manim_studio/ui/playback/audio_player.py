"""Plays the project's sound (P4d, ADR 0034); the time it has played is the playback clock.

The mix from ``core.audio`` is handed to a ``QAudioSink`` from the playhead on,
pulled in spans of a quarter second as the device asks for them (``MixDevice``,
B70): no whole mix is made, and an edit is heard after its first span. The sink's
processed time advances every ~10 ms and never drifts from what is
heard (B47), so frames follow it; until the device starts (~0.1 s, ~0.5 s for
the first sound of a session) the clock stays at the start and the first frame
holds. Without a device, or with ``MANIM_STUDIO_AUDIO=0`` (tests), there is no
player and playback keeps the wall clock.
"""

from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import QIODevice, QObject

from ...core.sound import audio
from ...logging_config import get_logger

log = get_logger(__name__)


class _ArraySource:
    """A whole mix already in memory, read like ``audio.MixSource``."""

    def __init__(self, samples: np.ndarray) -> None:
        self.samples = samples
        self.length = samples.shape[1]

    def span(self, start: int, count: int) -> np.ndarray:
        return self.samples[:, start : start + count]


class MixDevice(QIODevice):
    """The mix as 16-bit PCM from a sample on, made a span at a time when it is read: the bytes are
    those of ``audio.to_int16`` of the whole mix from that sample."""

    SPAN = audio.SPAN  # samples made at a time (0.25 s)

    def __init__(self, source, first: int, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._source = source
        self._pos = min(max(first, 0), source.length)
        self._pending = b""
        self._fill(1)  # the first span is ready before the device starts
        self.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Unbuffered)

    def _fill(self, size: int) -> None:
        while len(self._pending) < size and self._pos < self._source.length:
            n = min(self.SPAN, self._source.length - self._pos)
            self._pending += audio.to_int16(self._source.span(self._pos, n))
            self._pos += n

    def isSequential(self) -> bool:
        return True

    def bytesAvailable(self) -> int:
        return len(self._pending) + 4 * (self._source.length - self._pos) + super().bytesAvailable()

    def atEnd(self) -> bool:
        return not self._pending and self._pos >= self._source.length

    def readData(self, maxlen: int) -> bytes:
        self._fill(maxlen)
        out, self._pending = self._pending[:maxlen], self._pending[maxlen:]
        return out

    def writeData(self, data) -> int:
        return -1


class AudioPlayer(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sink = None
        self._buffer: MixDevice | None = None
        self._start = 0.0
        self.volume = 1.0  # 0..1, kept between plays
        self.muted = False

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))
        self._apply_volume()

    def set_muted(self, muted: bool) -> None:
        self.muted = muted
        self._apply_volume()

    def _apply_volume(self) -> None:
        if self._sink is not None:
            self._sink.setVolume(0.0 if self.muted else self.volume)

    @staticmethod
    def available() -> bool:
        if os.environ.get("MANIM_STUDIO_AUDIO") == "0":
            return False
        try:
            from PySide6.QtMultimedia import QMediaDevices
        except ImportError:  # Qt built without multimedia
            return False
        return not QMediaDevices.defaultAudioOutput().isNull()

    def play(self, samples, t: float) -> None:
        """Play ``samples`` (the project's mix: an ``audio.MixSource`` or a whole array) from ``t``
        seconds."""
        from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

        self.stop()
        fmt = QAudioFormat()
        fmt.setSampleRate(audio.RATE)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        source = _ArraySource(samples) if isinstance(samples, np.ndarray) else samples
        self._buffer = MixDevice(source, round(t * audio.RATE), self)
        self._sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt, self)
        self._apply_volume()
        self._sink.start(self._buffer)
        self._start = t
        log.debug("sound from %.3f s", t)

    def position(self) -> float:
        """Where the sound is: the start until the device plays, then the time it has played."""
        played = self._sink.processedUSecs() / 1e6 if self._sink is not None else 0.0
        return self._start + played

    def stop(self) -> None:
        if self._sink is not None:
            self._sink.stop()
            self._sink.deleteLater()
            self._sink = None
        if self._buffer is not None:
            self._buffer.close()
            self._buffer.deleteLater()
            self._buffer = None


class FakePlayer(QObject):
    """A player for tests: ``elapsed`` is the time the 'device' has played."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.started: list[tuple[np.ndarray, float]] = []
        self.elapsed = 0.0
        self.stopped = 0
        self._start = 0.0
        self.volume = 1.0
        self.muted = False

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))

    def set_muted(self, muted: bool) -> None:
        self.muted = muted

    def play(self, samples: np.ndarray, t: float) -> None:
        self.started.append((samples, t))
        self._start, self.elapsed = t, 0.0

    def position(self) -> float:
        return self._start + self.elapsed

    def stop(self) -> None:
        self.stopped += 1


def make_audio_player(parent: QObject | None = None) -> AudioPlayer | None:
    return AudioPlayer(parent) if AudioPlayer.available() else None
