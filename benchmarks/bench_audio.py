"""B47 — an audio track: decoding, mixing, waveforms, playback in Qt, muxing, Manim's add_sound.

1. Decode a 60 s stereo file (WAV, MP3 and AAC written with PyAV) to 48 kHz
   float32 stereo; mix three clips with gain and fades; waveform peaks.
2. Qt: the default audio output, how fast a QAudioSink starts and how far its
   clock drifts from the wall clock.
3. Mux: a short H.264 video with an AAC track; durations and the audio start.
4. Manim's ``Scene.add_sound(file, time_offset)``: where the sound lands.

Run: ``python benchmarks/bench_audio.py``.
"""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import av
import numpy as np

RATE = 48_000


def tone(seconds: float, rate: int = 44_100, freq: float = 440.0) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    left = 0.5 * np.sin(2 * np.pi * freq * t)
    right = 0.5 * np.sin(2 * np.pi * freq * 1.5 * t)
    return np.stack([left, right]).astype(np.float32)  # (channels, samples)


def write(path: Path, samples: np.ndarray, rate: int = 44_100) -> None:
    codec = {".wav": "pcm_s16le", ".mp3": "libmp3lame", ".m4a": "aac"}[path.suffix]
    with av.open(str(path), "w") as out:
        stream = out.add_stream(codec, rate=rate, layout="stereo")
        fmt = "s16" if codec == "pcm_s16le" else stream.codec_context.format.name
        resampler = av.AudioResampler(format=fmt, layout="stereo", rate=rate)
        for i in range(0, samples.shape[1], 4096):
            frame = av.AudioFrame.from_ndarray(
                samples[:, i : i + 4096].copy(), format="fltp", layout="stereo"
            )
            frame.sample_rate = rate
            for resampled in resampler.resample(frame):
                for packet in stream.encode(resampled):
                    out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)


def decode(path: Path) -> np.ndarray:
    """(2, n) float32 at 48 kHz."""
    chunks = []
    with av.open(str(path)) as container:
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=RATE)
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray())
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray())
    return np.concatenate(chunks, axis=1)


def costs(folder: Path) -> np.ndarray:
    samples = tone(60.0)
    decoded = None
    for suffix in (".wav", ".mp3", ".m4a"):
        path = folder / f"tone{suffix}"
        write(path, samples)
        start = time.perf_counter()
        decoded = decode(path)
        ms = (time.perf_counter() - start) * 1000
        print(
            f"decode 60 s {suffix}: {ms:.0f} ms -> {decoded.shape[1] / RATE:.3f} s, {path.stat().st_size // 1024} KiB"
        )
    start = time.perf_counter()
    mix = np.zeros((2, 90 * RATE), np.float32)
    for begin in (0.0, 10.0, 25.0):
        part = decoded[:, : 50 * RATE] * (10 ** (-6 / 20))
        ramp = np.minimum(1.0, np.arange(part.shape[1]) / (0.5 * RATE))
        part = part * np.minimum(ramp, ramp[::-1])
        i = int(begin * RATE)
        mix[:, i : i + part.shape[1]] += part
    print(f"mix three 50 s clips (gain, fades) into 90 s: {(time.perf_counter() - start) * 1000:.0f} ms")
    start = time.perf_counter()
    mono = np.abs(decoded).max(axis=0)
    per = RATE // 100
    peaks = mono[: len(mono) // per * per].reshape(-1, per).max(axis=1)
    print(
        f"waveform peaks, 100 per second of 60 s: {(time.perf_counter() - start) * 1000:.1f} ms ({len(peaks)} peaks)"
    )
    return mix


def qt_audio(mix: np.ndarray) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QByteArray, QCoreApplication, QIODevice
    from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

    app = QCoreApplication.instance() or QCoreApplication([])
    device = QMediaDevices.defaultAudioOutput()
    if device.isNull():
        print("Qt: no audio output device")
        return
    fmt = QAudioFormat()
    fmt.setSampleRate(RATE)
    fmt.setChannelCount(2)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    print(f"Qt: default output {device.description()!r}, format supported: {device.isFormatSupported(fmt)}")
    data = (np.clip(mix[:, : 6 * RATE].T, -1, 1) * 32767).astype("<i2").tobytes()
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    sink = QAudioSink(device, fmt)
    sink.setVolume(0.0)  # silent probe
    start = time.perf_counter()
    sink.start(buffer)
    first = None
    samples = []
    while time.perf_counter() - start < 5.0:
        app.processEvents()
        played = sink.processedUSecs() / 1e6
        if first is None and played > 0:
            first = time.perf_counter() - start
        if first is not None:
            samples.append((time.perf_counter() - start) - played)
        time.sleep(0.01)
    sink.stop()
    lag = statistics.median(samples[: len(samples) // 5]), statistics.median(samples[-len(samples) // 5 :])
    print(
        f"QAudioSink: first audio after {first * 1000:.0f} ms; wall - audio clock: {lag[0] * 1000:.0f} ms early, "
        f"{lag[1] * 1000:.0f} ms after 5 s (state {sink.state() == QAudio.State.StoppedState})"
    )


def mux(folder: Path, mix: np.ndarray) -> None:
    path = folder / "muxed.mp4"
    start = time.perf_counter()
    with av.open(str(path), "w") as out:
        video = out.add_stream("libx264", rate=30)
        video.width, video.height, video.pix_fmt = 320, 180, "yuv420p"
        audio = out.add_stream("aac", rate=RATE, layout="stereo")
        for i in range(90):
            frame = av.VideoFrame.from_ndarray(np.full((180, 320, 3), i * 2 % 255, np.uint8), format="rgb24")
            for packet in video.encode(frame):
                out.mux(packet)
        resampler = av.AudioResampler(format=audio.codec_context.format.name, layout="stereo", rate=RATE)
        frame = av.AudioFrame.from_ndarray(
            np.ascontiguousarray(mix[:, : 3 * RATE]), format="fltp", layout="stereo"
        )
        frame.sample_rate = RATE
        frame.pts = 0
        for resampled in resampler.resample(frame):
            for packet in audio.encode(resampled):
                out.mux(packet)
        for stream in (video, audio):
            for packet in stream.encode(None):
                out.mux(packet)
    ms = (time.perf_counter() - start) * 1000
    with av.open(str(path)) as container:
        v, a = container.streams.video[0], container.streams.audio[0]
        first_audio = next(container.decode(audio=0))
        print(
            f"mux 3 s video + AAC: {ms:.0f} ms; video {float(v.duration * v.time_base):.3f} s, "
            f"audio {float(a.duration * a.time_base):.3f} s, first audio pts {float(first_audio.time):.3f} s"
        )


SCENE = """
from manim import *
class Sound(Scene):
    def construct(self):
        self.add_sound(r"{wav}", time_offset=0.5)
        self.play(FadeIn(Square()), run_time=1)
        self.wait(1)
"""


def manim_sound(folder: Path) -> None:
    wav = folder / "click.wav"
    click = np.zeros((2, 44_100), np.float32)
    click[:, :2000] = 0.8
    write(wav, click)
    scene = folder / "sound.py"
    scene.write_text(SCENE.format(wav=wav), encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "manim",
            "render",
            "-ql",
            str(scene),
            "Sound",
            "--media_dir",
            str(folder / "media"),
        ],
        capture_output=True,
        text=True,
        cwd=folder,
    )
    assert done.returncode == 0, done.stderr[-1500:]
    video = next((folder / "media").rglob("Sound.mp4"))
    with av.open(str(video)) as container:
        rate = container.streams.audio[0].rate
        samples = np.concatenate([f.to_ndarray().reshape(-1) for f in container.decode(audio=0)])
    onset = np.argmax(np.abs(samples) > 0.1) / rate / 2  # interleaved stereo or planar: approximate
    print(f"Manim add_sound(time_offset=0.5): audio stream at {rate} Hz, loud from ~{onset:.2f} s")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / ".cache") as tmp:
        folder = Path(tmp)
        mix = costs(folder)
        qt_audio(mix)
        mux(folder, mix)
        manim_sound(folder)
