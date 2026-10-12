"""B58 - the Audio page: what the level meter and the tables cost.

A 5-minute project with four 60 s sounds (gain and fades on each) and 200 subtitles:

1. the meter's two ways of reading the mix at the playhead: the whole mix (``audio.mix``, rebuilt after
   every edit because its cache key changes) sliced around the playhead, against ``levels.level_at``
   (the 100 ms window mixed straight from the decoded files) - and the decode that both pay once;
2. the page in the real window: one seek with the meter updating (the cost every playback tick adds),
   a table refresh after an edit (4 sounds, 200 cues), and a cell edit end to end (``setData`` ->
   undo step -> evaluator -> tables -> meter).

Run: ``python benchmarks/bench_audio_page.py``.
"""

from __future__ import annotations

import os
import random
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for name in ("MANIM_STUDIO_PREVIEW", "MANIM_STUDIO_WORKER", "MANIM_STUDIO_AUDIO", "MANIM_STUDIO_CODE"):
    os.environ.setdefault(name, "0")

import numpy as np  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from manim_studio.core import adapter, audio, levels  # noqa: E402
from manim_studio.core.schema import AudioClip, Canvas, Cue, Layer, Project, Spec  # noqa: E402
from manim_studio.ui import theme  # noqa: E402
from manim_studio.ui.main_window import MainWindow  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOUNDS, SOUND_SECONDS, CUES = 4, 60.0, 200


def best(fn, repeat: int = 15) -> float:
    """Median milliseconds of ``fn`` over ``repeat`` runs."""
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def make_project(folder: Path) -> Project:
    clips = []
    for i in range(SOUNDS):
        t = np.arange(round(SOUND_SECONDS * audio.RATE)) / audio.RATE
        wave = (0.3 * np.sin(2 * np.pi * (220 * (i + 1)) * t)).astype(np.float32)
        path = folder / f"tone{i}.wav"
        audio.write_wav(np.stack([wave, wave]), path)
        clips.append(
            AudioClip(
                id=f"audio-{i + 1}",
                name=f"tone{i}",
                path=str(path),
                start=i * 50.0,
                duration=SOUND_SECONDS,
                gain=-3.0,
                fade_in=2.0,
                fade_out=2.0,
            )
        )
    cues = [
        Cue(id=f"cue-{i + 1}", start=i * 1.4, end=i * 1.4 + 1.0, text=f"Line {i + 1}") for i in range(CUES)
    ]
    canvas = Canvas(width_px=320, height_px=180, fps=10, duration=300.0)
    return Project(
        canvas=canvas, layers=[Layer(id="dot", spec=Spec(type="Dot"))], audio=clips, subtitles=cues
    )


def main() -> None:
    app = QApplication(sys.argv)
    theme.apply(app)
    adapter.configure(ROOT / ".cache" / "manim")
    folder = Path(tempfile.mkdtemp(prefix="bench-audio-page-", dir=ROOT / ".cache"))
    try:
        project = make_project(folder)
        audio.forget()
        start = time.perf_counter()
        for clip in project.audio:
            audio.decode(clip.path)
        decode = (time.perf_counter() - start) * 1000
        print(f"decode {SOUNDS} files of {SOUND_SECONDS:.0f} s (once per file, cached): {decode:.0f} ms")

        t = 55.0  # inside two sounds' overlap and fades

        def full() -> None:
            audio._MIXES.clear()  # what any edit does: a new mix signature
            mixed = audio.mix(project)
            a = round((t - 0.05) * audio.RATE)
            window = mixed[:, a : a + round(0.1 * audio.RATE)].astype(np.float64)
            np.abs(window).max(axis=1), np.sqrt((window * window).mean(axis=1))

        print(f"level from the whole mix, rebuilt after an edit (300 s video): {best(full, 5):.1f} ms")
        audio.mix(project)
        mixed = audio.mix(project)
        a = round((t - 0.05) * audio.RATE)
        warm = best(lambda: np.abs(mixed[:, a : a + 4800]).max(axis=1))
        print(f"... and just slicing the cached whole mix: {warm:.2f} ms")
        window_ms = best(lambda: levels.level_at(project, t), 60)
        print(f"level_at, 100 ms window from the decoded files: {window_ms:.2f} ms")
        edge = best(lambda: levels.level_at(project, 0.0), 60)
        print(f"level_at at the start of the video (half window): {edge:.2f} ms")

        window = MainWindow()
        window.resize(1600, 1000)
        window.show()
        path = folder / "scene.json"
        path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
        window.load(path)
        window.show_page("audio")
        app.processEvents()
        page = window.pages.pages["audio"]

        frames = list(range(3000))  # every pass seeks to frames no pass before it showed (no frame cache)
        random.Random(58).shuffle(frames)

        def seek_cost() -> float:
            ticks = iter([frames.pop() / 10 for _ in range(60)])
            return best(lambda: (window.seek(next(ticks)), app.processEvents()), 60)

        print(f"seek with the meter, canvas and page repainted: {seek_cost():.1f} ms")
        window.playheadChanged.disconnect(page._on_playhead)
        print(f"... the same seek with the meter not updated: {seek_cost():.1f} ms")
        window.playheadChanged.connect(page._on_playhead)
        meter = best(lambda: (page.refresh_meter(), app.processEvents()), 60)
        print(f"the meter alone (level_at, readout, bars repainted): {meter:.2f} ms")
        window.show_page("compose")
        print(f"... the same seek on the Compose page: {seek_cost():.1f} ms")
        window.show_page("audio")
        app.processEvents()

        print(f"tables refreshed ({SOUNDS} sounds, {CUES} cues): {best(page.refresh, 30):.2f} ms")
        gains = iter(range(-3, -300, -1))

        def edit() -> None:
            page.sounds_model.setData(
                page.sounds_model.index(0, 5), str(-next(gains) / 100), Qt.ItemDataRole.EditRole
            )
            app.processEvents()

        print(f"a cell edit end to end (undo step, evaluator, tables, meter): {best(edit, 25):.1f} ms")
        window.document.undo_stack.setClean()  # closing would ask about the edits
        window.close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    main()
