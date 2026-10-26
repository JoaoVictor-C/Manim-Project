"""B70 - the sound of a long scene: memory and time of the mix per span (ADR 0034 amendment).

One synthetic 15-minute tone (44.1 kHz mono, 16 bit, ~79 MB) covering a 15-minute scene, and what
the editor does with it: open the project (probe, problems, the timeline's waveform), play 10 s from
5:00, move the sound (an audio edit heard while playing), read the level meter, and export 30 s of
the scene (5:00-5:30, a small picture so the sound dominates). Each step reports its time on the
calling thread and the peak extra memory (RSS sampled every 2 ms, above the RSS after imports).

It runs against whichever ``manim_studio`` is importable, so the same script measures the code
before spans (an older checkout's ``src`` on ``PYTHONPATH``) and after::

    python benchmarks/bench_audio_spans.py                 # 15 minutes
    python benchmarks/bench_audio_spans.py --minutes 2     # quicker
    PYTHONPATH=/path/to/old/src python benchmarks/bench_audio_spans.py   # before
"""

from __future__ import annotations

import argparse
import ctypes
import gc
import os
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MANIM_STUDIO_AUDIO", "0")

import numpy as np

from manim_studio.core.model.schema import AudioClip, Canvas, Layer, Project, Spec
from manim_studio.core.sound import audio, levels
from manim_studio.render.cairo_export import export_video
from manim_studio.render.options import RenderOptions

SPANS = hasattr(audio, "mix_span")


class _Counters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _memory() -> tuple[float, float]:
    """(RSS, peak RSS of the process) in MB."""
    if sys.platform == "win32":
        kernel, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Counters), ctypes.c_ulong]
        counters = _Counters()
        counters.cb = ctypes.sizeof(counters)
        psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return counters.WorkingSetSize / 2**20, counters.PeakWorkingSetSize / 2**20
    with open("/proc/self/statm", encoding="ascii") as handle:
        rss = int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20
    return rss, rss


class Sampler:
    """The highest RSS seen during a step (a thread reading the OS counter every 2 ms)."""

    def __init__(self) -> None:
        self.high = 0.0
        self._run = True
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while self._run:
            self.high = max(self.high, _memory()[0])
            time.sleep(0.002)

    def __enter__(self) -> Sampler:
        self.high = _memory()[0]
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._run = False
        self._thread.join()
        self.high = max(self.high, _memory()[0])


def write_tone(path: Path, seconds: float, rate: int = 44_100) -> None:
    """A quiet 220 Hz tone, mono, 16 bit (15 minutes at 44.1 kHz is ~79 MB)."""
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        total, chunk, done = round(seconds * rate), 60 * rate, 0
        while done < total:
            n = min(chunk, total - done)
            t = np.arange(done, done + n) / rate
            out.writeframes((0.05 * 32767 * np.sin(2 * np.pi * 220 * t)).astype("<i2").tobytes())
            done += n


def play(project: Project, t: float, seconds: float) -> tuple[float, float]:
    """What the player does to start at ``t`` and play ``seconds``: (ms to the first sound, ms in all)."""
    first = round(t * audio.RATE)
    if SPANS:
        from manim_studio.ui.playback.audio_player import MixDevice
    start = time.perf_counter()
    if SPANS:
        device = MixDevice(audio.source(project), first)
        ready = (time.perf_counter() - start) * 1000
        wanted = round(seconds * audio.RATE) * 4
        while wanted > 0:  # the sink pulls ~16 KB at a time
            wanted -= len(bytes(device.read(16_384)))
    else:  # before: the whole mix, then the rest of it as 16-bit PCM in a QBuffer
        data = audio.to_int16(audio.mix(project)[:, first:])
        ready = (time.perf_counter() - start) * 1000
        del data
    return ready, (time.perf_counter() - start) * 1000


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--minutes", type=float, default=15.0)
    args = parser.parse_args()
    seconds = args.minutes * 60
    folder = Path(tempfile.mkdtemp(prefix="bench-audio-spans-"))
    tone = folder / "tone.wav"
    write_tone(tone, seconds)
    print(
        f"B70 - {'spans' if SPANS else 'whole mix (before)'}: a {args.minutes:g}-minute 44.1 kHz mono tone, "
        f"{tone.stat().st_size / 2**20:.0f} MB on disk; {audio.__file__}"
    )
    canvas = Canvas(width_px=160, height_px=90, fps=10, duration=seconds)
    clip = AudioClip(id="tone", path=str(tone), duration=seconds - 1.0)
    project = Project(canvas=canvas, layers=[Layer(id="dot", spec=Spec(type="Dot"))], audio=[clip])
    audio.forget()
    gc.collect()
    base = _memory()[0]
    rows = []

    def step(name: str, action, note: str = "") -> None:
        gc.collect()
        with Sampler() as sampler:
            start = time.perf_counter()
            extra = action()
            took = (time.perf_counter() - start) * 1000
        rows.append((name, took, sampler.high - base, extra or note))

    def open_project() -> str:
        audio.probe(str(tone))
        audio.problems(project)
        if SPANS:  # the timeline: a long sound is scanned on a thread, its row flat meanwhile
            assert audio.peaks_ready(str(tone), 100) is None
            done = threading.Event()
            began = time.perf_counter()
            threading.Thread(target=lambda: (audio.scan(str(tone)), done.set()), daemon=True).start()
            open_project.background = (began, done)
            return "GUI thread; the waveform scan runs in the background"
        audio.peaks(str(tone), 100)  # before: decoded on the GUI thread by the first sync
        return "GUI thread, the waveform decoded on it"

    step("open (probe, problems, waveform)", open_project)
    if SPANS:
        began, done = open_project.background
        with Sampler() as sampler:
            done.wait()
        rows.append(
            (
                "  background waveform scan",
                (time.perf_counter() - began) * 1000,
                sampler.high - base,
                "off the GUI thread; until then a flat row",
            )
        )
    times = {}

    def play_10s() -> str:
        times["play"] = play(project, 300.0, 10.0)
        return f"first sound after {times['play'][0]:.1f} ms"

    step("play 10 s from 5:00", play_10s)
    moved = project.model_copy(update={"audio": [clip.model_copy(update={"start": 1.0})]})

    def edit() -> str:
        times["edit"] = play(moved, 305.0, 0.25)
        return f"first playable chunk after the edit {times['edit'][0]:.1f} ms"

    step("move the sound, heard while playing", edit)

    def meter() -> str:
        took = []
        for t in (10.0, 310.0, seconds - 5):
            start = time.perf_counter()
            levels.level_at(moved, t)
            took.append((time.perf_counter() - start) * 1000)
        return "level_at " + " / ".join(f"{ms:.2f}" for ms in took) + " ms"

    step("level meter at 3 times", meter)
    out = folder / "export.mp4"

    def export() -> str:
        audio.forget()  # the export runs in a fresh process
        export_video(moved, out, options=RenderOptions(start=300.0, end=330.0))
        return f"{out.stat().st_size / 2**10:.0f} KB, 300 frames 160x90 + 30 s AAC"

    step("export 5:00-5:30", export)
    peak = _memory()[1] - base
    print(f"RSS after imports {base:.0f} MB; process peak above it {peak:.0f} MB")
    print(f"{'step':40} {'ms':>9} {'peak extra MB':>14}  note")
    for name, took, extra, note in rows:
        print(f"{name:40} {took:9.1f} {extra:14.1f}  {note}")
    if SPANS:
        print(f"decoder: {audio.COUNTS}; decoded windows kept {audio.window_bytes() / 2**20:.1f} MB")


if __name__ == "__main__":
    main()
