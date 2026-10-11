"""Plays the project's sound (P4d, ADR 0034); the time it has played is the playback clock.

The mix from ``core.audio`` is handed to a ``QAudioSink`` from the playhead on.
The sink's processed time advances every ~10 ms and never drifts from what is
heard (B47), so frames follow it; until the device starts (~0.1 s, ~0.5 s for
the first sound of a session) the clock stays at the start and the first frame
holds. Without a device, or with ``MANIM_STUDIO_AUDIO=0`` (tests), there is no
player and playback keeps the wall clock.
"""

from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject

from ..core import audio
from ..logging_config import get_logger

log = get_logger(__name__)


class AudioPlayer(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sink = None
        self._buffer: QBuffer | None = None
        self._start = 0.0

    @staticmethod
    def available() -> bool:
        if os.environ.get("MANIM_STUDIO_AUDIO") == "0":
            return False
        try:
            from PySide6.QtMultimedia import QMediaDevices
        except ImportError:  # Qt built without multimedia
            return False
        return not QMediaDevices.defaultAudioOutput().isNull()

    def play(self, samples: np.ndarray, t: float) -> None:
        """Play ``samples`` (the project's mix) from ``t`` seconds."""
        from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

        self.stop()
        fmt = QAudioFormat()
        fmt.setSampleRate(audio.RATE)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self._buffer = QBuffer(self)
        self._buffer.setData(QByteArray(audio.to_int16(samples[:, round(t * audio.RATE) :])))
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self._sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt, self)
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

    def play(self, samples: np.ndarray, t: float) -> None:
        self.started.append((samples, t))
        self._start, self.elapsed = t, 0.0

    def position(self) -> float:
        return self._start + self.elapsed

    def stop(self) -> None:
        self.stopped += 1


def make_audio_player(parent: QObject | None = None) -> AudioPlayer | None:
    return AudioPlayer(parent) if AudioPlayer.available() else None
