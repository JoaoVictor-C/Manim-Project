"""B64 - a long scene: does a 10+ minute video scale? (golden path step G4)

The longest real project so far is 95 s (examples/explainer.json). This builds a synthetic 15-minute
explainer (900 s, 1280x720, 30 fps = 27 000 frames) laid out like a real one - a "slide" every 15 s
with a title (Text), an equation (MathTex, a handful of distinct formulas reused), 2-4 shapes that
enter with clips, one emphasis (Indicate) and exits (FadeOut), some layers keyframed with the
built-in "Pop in" preset - about 300 root layers, 660 clips, 200 subtitle cues and one sound that
covers the whole scene. Seeded, so two runs build the same project.

It then measures, and says what each number means: validation, JSON size, save and load, the
evaluator's first frame, the first (cold) seek deep into the scene, scrubbing, memory (RSS) before
and after, an edit end to end, the timeline (set document, paint, repaint after an edit), autosave,
the audio mix, the render-ahead store and the export's time per frame.

Run (each run on mains power for the full scene)::

    python benchmarks/bench_long_scene.py            # 15 minutes
    python benchmarks/bench_long_scene.py --quick    # 2 minutes, the same density (battery-friendly)
    python benchmarks/bench_long_scene.py --seconds 30
    python benchmarks/bench_long_scene.py --model-only   # 15 minutes, nothing built or drawn: seconds

``--model-only`` skips the texts, frames and export (the costs that are linear by construction) and
keeps what depends on the number of layers and clips: validation, save and load, edits, the
timeline, autosave, the audio mix, the evaluator's walk over the layers, the frame store.

The first run on a new machine also fills Manim's text cache (LaTeX for the formulas, Pango for the
titles and cues); the "warm-up" line says how long that took, and the numbers below it are warm, as
in an editor whose build worker has already seen the text.
"""

from __future__ import annotations

import argparse
import cProfile
import ctypes
import gc
import io
import json
import logging
import math
import os
import pstats
import random
import shutil
import statistics
import sys
import tempfile
import time
import wave
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SCRATCH = Path(tempfile.mkdtemp(prefix="bench-long-env-"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MANIM_STUDIO_PREVIEW", "0")
os.environ.setdefault("MANIM_STUDIO_AUDIO", "0")
os.environ.setdefault("MANIM_STUDIO_WORKER", "0")
os.environ.setdefault("MANIM_STUDIO_CODE", "0")
os.environ.setdefault("MANIM_STUDIO_SETTINGS", str(_SCRATCH / "settings.json"))
os.environ.setdefault("MANIM_STUDIO_RECOVERY", str(_SCRATCH / "recovery"))

import manim as m  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from manim_studio.core import adapter, audio, edits, frame_cache, levels, library, recovery  # noqa: E402
from manim_studio.core.evaluator import Evaluator  # noqa: E402
from manim_studio.core.schema import (  # noqa: E402
    AudioClip,
    Canvas,
    Clip,
    Cue,
    Easing,
    Layer,
    Project,
    Spec,
    Transform2D,
)
from manim_studio.render import cairo_export  # noqa: E402
from manim_studio.render.options import RenderOptions  # noqa: E402
from manim_studio.ui import theme  # noqa: E402
from manim_studio.ui.document import Document  # noqa: E402
from manim_studio.ui.timeline.model import TimeScale  # noqa: E402
from manim_studio.ui.timeline.view import TimelineView  # noqa: E402

SLIDE = 15.0  # seconds per slide
FULL_SECONDS = 900.0
CUES_PER_FULL = 200
SIZE = (1100, 620)  # a typical canvas widget (B41)
FORMULAS = [
    r"e^{i\pi}+1=0",
    r"a^2+b^2=c^2",
    r"\int_0^1 x^2\,dx=\tfrac13",
    r"\sum_{n=1}^\infty \frac1{n^2}=\frac{\pi^2}6",
    r"F=ma",
    r"E=mc^2",
    r"\det(A-\lambda I)=0",
    r"\lim_{x\to0}\frac{\sin x}x=1",
]
ADJECTIVES = ["Simple", "Hidden", "Local", "Global", "Smooth", "Sharp", "Linear", "Curved", "Stable", "Odd"]
NOUNS = ["limits", "slopes", "areas", "waves", "series", "angles", "orbits", "proofs", "maps", "rates"]
WORDS = "the a curve moves along its path while we watch how each part changes over time".split()  # noqa: SIM905
SHAPES = ["Circle", "Square", "Rectangle", "Triangle", "Star"]
PALETTE = ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#a855f7", "#14b8a6"]
RESULTS: dict[str, object] = {}
MODEL_ONLY = False  # --model-only: nothing is built or drawn, so a 15-minute scene costs seconds
PROFILE = False  # --profile: cProfile tops for the timeline's sync and an edit in the window
ASSUMED_FRAME_KB = 35  # a kept frame (zlib 1) when --model-only draws none: the quick run's mean


# -- helpers ----------------------------------------------------------------------------------------


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


def rss_mb() -> float:
    """Resident memory of this process in MB: psutil if installed, else the OS's own counter."""
    try:
        import psutil

        return psutil.Process().memory_info().rss / 2**20
    except ImportError:
        pass
    if sys.platform == "win32":
        kernel, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Counters), ctypes.c_ulong]
        counters = _Counters()
        counters.cb = ctypes.sizeof(counters)
        psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return counters.WorkingSetSize / 2**20
    with open("/proc/self/statm", encoding="ascii") as handle:  # Linux
        return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20


def settled_rss() -> float:
    gc.collect()
    return rss_mb()


def timed(work, repeat: int = 1) -> list[float]:
    """Milliseconds of each of ``repeat`` runs of ``work``."""
    out = []
    for _ in range(repeat):
        start = time.perf_counter()
        work()
        out.append((time.perf_counter() - start) * 1000)
    return out


def median(samples: list[float]) -> float:
    return statistics.median(samples)


def p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]


def report(key: str, label: str, value: str, meaning: str = "") -> None:
    RESULTS[key] = value
    print(f"  {label:<46} {value:>22}  {meaning}", flush=True)


def section(title: str) -> None:
    print(f"\n== {title}", flush=True)


def profile_call(label: str, work, lines: int = 14) -> None:
    """With ``--profile``: the cProfile top (by cumulative time) of one run of ``work``."""
    if not PROFILE:
        return
    profiler = cProfile.Profile()
    profiler.runcall(work)
    print(f"\n  -- cProfile: {label}")
    stream = io.StringIO()
    pstats.Stats(profiler, stream=stream).sort_stats("cumulative").print_stats(lines)
    print("\n".join("     " + row for row in stream.getvalue().splitlines() if row.strip()))


def clear_builds() -> None:
    """Forget every object the adapter built in this process (the disk cache stays warm)."""
    for value in vars(adapter).values():
        if hasattr(value, "cache_clear"):
            value.cache_clear()


# -- the synthetic project --------------------------------------------------------------------------


def write_tone(path: Path, seconds: float) -> None:
    """A quiet 220 Hz tone, mono, 22 050 Hz, 16 bit (a 15-minute one is ~40 MB)."""
    rate = 22050
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        total, chunk, done = round(seconds * rate), 60 * rate, 0
        while done < total:
            n = min(chunk, total - done)
            t = (np.arange(done, done + n) / rate).astype(np.float64)
            out.writeframes((0.05 * 32767 * np.sin(2 * np.pi * 220 * t)).astype("<i2").tobytes())
            done += n


def build_project(seconds: float, folder: Path, seed: int = 64) -> tuple[Project, dict[str, int]]:
    """The explainer: one slide per 15 s, built directly (an edit per layer would validate 300 times),
    then the keyframed layers through ``library.apply_preset`` like the editor does."""
    rng = random.Random(seed)
    slides = max(1, int(seconds // SLIDE))
    layers: list[Layer] = []
    pop_in: list[tuple[str, float]] = []  # (layer id, entry time) the "Pop in" preset is applied to

    def clip(cid: str, kind: str, start: float, duration: float) -> Clip:
        return Clip(id=cid, kind=kind, start=round(start, 3), duration=duration)

    for k in range(slides):
        s = k * SLIDE
        title_clips = [clip("out", "FadeOut", s + 14.0, 0.5)]
        title = Layer(
            id=f"title-{k + 1}",
            spec=Spec(
                type="Text",
                params={"text": f"{k + 1}. {rng.choice(ADJECTIVES)} {rng.choice(NOUNS)}", "font_size": 44},
            ),
            base=Transform2D(position=(0.0, 3.2)),
            clips=title_clips,
        )
        if k % 3 == 0:
            pop_in.append((title.id, s + 0.5))  # keyframed: the entrance is the preset's
        else:
            title.clips.insert(0, clip("in", "FadeIn", s + 0.5, 0.6))
        layers.append(title)

        emphasis_on_equation = k % 2 == 0
        equation_clips = [clip("in", "Write", s + 1.5, 1.5)]
        if emphasis_on_equation:
            equation_clips.append(clip("pulse", "Indicate", s + 8.0, 1.0))
        equation_clips.append(clip("out", "FadeOut", s + 14.0, 0.5))
        layers.append(
            Layer(
                id=f"equation-{k + 1}",
                spec=Spec(type="MathTex", params={"text": rng.choice(FORMULAS), "font_size": 56}),
                base=Transform2D(position=(0.0, 1.0)),
                clips=equation_clips,
            )
        )

        count = rng.randint(2, 4)
        for j in range(count):
            kind = SHAPES[rng.randrange(len(SHAPES))]
            params = {"Circle": {"radius": 0.6}, "Square": {"side_length": 1.1}}.get(kind, {})
            if kind == "Rectangle":
                params = {"width": 1.6, "height": 0.9}
            enter = s + 3.0 + 0.6 * j
            clips = []
            if k % 2 == 0 and j == 0:
                pop_in.append((f"shape-{k + 1}-{j + 1}", enter))
            else:
                clips.append(clip("in", ("GrowFromCenter", "FadeIn", "Create")[j % 3], enter, 0.6))
            if not emphasis_on_equation and j == 0:
                clips.append(clip("pulse", "Indicate", s + 8.0, 1.0))
            clips.append(clip("out", "FadeOut", s + 14.0 + 0.1 * j, 0.5))
            x = (j - (count - 1) / 2) * 3.0
            layers.append(
                Layer(
                    id=f"shape-{k + 1}-{j + 1}",
                    spec=Spec(type=kind, params=params, style={"fill": PALETTE[(k + j) % len(PALETTE)]}),
                    base=Transform2D(position=(x, -1.8)),
                    clips=clips,
                )
            )

    n_cues = max(1, round(CUES_PER_FULL * seconds / FULL_SECONDS))
    spacing = seconds / n_cues
    cues = [
        Cue(
            id=f"cue-{i + 1}",
            start=round(i * spacing + 0.2, 3),
            end=round(i * spacing + 0.2 + min(3.5, 0.8 * spacing), 3),
            text=f"Step {i + 1}: " + " ".join(rng.choice(WORDS) for _ in range(rng.randint(3, 7))),
        )
        for i in range(n_cues)
    ]
    tone = folder / "tone.wav"
    write_tone(tone, seconds)
    sound = AudioClip(
        id="audio-1",
        name="tone",
        path=str(tone),
        start=0.0,
        duration=seconds,
        gain=-6.0,
        fade_in=2.0,
        fade_out=2.0,
    )
    project = Project(
        canvas=Canvas(width_px=1280, height_px=720, fps=30, duration=seconds, background="#0f172a"),
        layers=layers,
        audio=[sound],
        subtitles=cues,
    )
    presets = {p.name: p for p in library.load_library([library.BUILTIN_FOLDER]).presets}
    for layer_id, t in pop_in:
        project = library.apply_preset(project, layer_id, presets["Pop in"], t).project
    info = {
        "slides": slides,
        "roots": len(project.roots()),
        "clips": sum(len(layer.clips) for layer in project.layers),
        "keyed": sum(1 for layer in project.layers if layer.tracks),
        "cues": len(project.subtitles),
        "frames": frame_cache.frame_count(project),
        "formulas": len(
            {layer.spec.params["text"] for layer in project.layers if layer.spec.type == "MathTex"}
        ),
    }
    return project, info


# -- drawing ----------------------------------------------------------------------------------------


def widget_camera(project: Project) -> m.Camera:
    return m.Camera(
        pixel_width=SIZE[0],
        pixel_height=SIZE[1],
        frame_width=project.canvas.frame_width,
        frame_height=project.canvas.frame_width * SIZE[1] / SIZE[0],
        background_color=m.ManimColor(project.canvas.background),
        background_opacity=1.0,
    )


def draw(camera: m.Camera | None, evaluator: Evaluator, t: float) -> np.ndarray | None:
    """Evaluate and draw a frame; with no camera (``--model-only``) only evaluate it."""
    frame = evaluator.frame(t)
    return cairo_export.render_frame(camera, frame) if camera is not None else None


def on_grid(project: Project, t: float) -> float:
    fps = project.canvas.fps
    return frame_cache.frame_time(frame_cache.frame_index(t, fps), fps)


# -- the sections -----------------------------------------------------------------------------------


def warm_up(project: Project) -> None:
    """Fill Manim's disk cache with every distinct text (cold: LaTeX and Pango; paid once per text)."""
    section("warm-up (the first run fills Manim's text cache; later runs find it)")
    specs = {
        json.dumps(layer.spec.model_dump(mode="json"), sort_keys=True): layer.spec for layer in project.layers
    }
    start = time.perf_counter()
    for spec in specs.values():
        if spec.type in ("Text", "MathTex"):
            adapter.build_mobject(spec)
    texts = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    for cue in project.subtitles:
        adapter.subtitle_mobject(cue.text, project.subtitle_style)
    cues = (time.perf_counter() - start) * 1000
    report(
        "warmup_texts",
        "titles and equations",
        f"{texts:,.0f} ms",
        "distinct Text/MathTex builds, cold or cached",
    )
    report(
        "warmup_cues", f"{len(project.subtitles)} subtitle cues", f"{cues:,.0f} ms", "one Text build per cue"
    )
    clear_builds()


def document_section(project: Project, folder: Path) -> Project:
    section("the document: validation, size, save, load")
    validate = timed(lambda: Project.model_validate(project.model_dump()), 5)
    report(
        "validate",
        "validation (dump + validate)",
        f"{median(validate):,.1f} ms",
        "what an edit's snapshot costs, linear",
    )
    saved = project.model_dump_json(indent=2, by_alias=True)
    report(
        "json_bytes",
        "JSON size (indent 2, as Save writes)",
        f"{len(saved) / 1024:,.0f} KB",
        "the file on disk",
    )
    target = folder / "long.json"
    save = timed(
        lambda: target.write_text(project.model_dump_json(indent=2, by_alias=True), encoding="utf-8"), 5
    )
    report("save_ms", "save (dump + write)", f"{median(save):,.1f} ms", "File > Save on the GUI thread")
    load = timed(lambda: Project.model_validate_json(target.read_text(encoding="utf-8")), 5)
    report(
        "load_ms",
        "load (read + parse + validate)",
        f"{median(load):,.1f} ms",
        "File > Open before the window reacts",
    )
    return Project.model_validate_json(target.read_text(encoding="utf-8"))


def slides_of(project: Project) -> int:
    return int(project.canvas.duration // SLIDE)


def gap_time(project: Project, slide: int = 0) -> float:
    """A time inside slide ``slide``'s first 0.5 s: no object of that slide is alive yet and the
    previous slide's are gone, so evaluating it builds nothing."""
    return on_grid(project, slide * SLIDE + 0.2)


def model_evaluator_section(project: Project) -> dict[str, object]:
    section("the evaluator, model side only (nothing is built or drawn)")
    start = time.perf_counter()
    ev = Evaluator(project)
    report(
        "ev_build",
        "Evaluator(project)",
        f"{(time.perf_counter() - start) * 1000:,.1f} ms",
        "indexes layers and morphs",
    )
    gaps = [gap_time(project, k) for k in range(int(project.canvas.duration // SLIDE))]
    samples = timed(lambda: ev.frame(gaps[len(gaps) // 2]), 30)
    report(
        "scrub_gap",
        "evaluate a frame with nothing alive",
        f"{median(samples):.2f} ms",
        "frame_layers() walks every layer and asks its lifetime: grows with the layer count",
    )
    scan = timed(ev.missing_checkpoints, 5)
    report(
        "missing_scan",
        f"missing_checkpoints() ({len(ev.missing_checkpoints())} missing)",
        f"{median(scan):.1f} ms",
        "run again before every idle checkpoint (one per idle tick)",
    )
    return {"evaluator": ev, "camera": None}


def evaluator_section(project: Project) -> dict[str, object]:
    section("the evaluator: first frame, deep seek, scrub, memory")
    duration = project.canvas.duration
    camera = widget_camera(project)
    clear_builds()
    base = settled_rss()
    report(
        "rss_base",
        "RSS before building the evaluator",
        f"{base:,.0f} MB",
        "the process with the project loaded",
    )
    start = time.perf_counter()
    ev = Evaluator(project)
    report(
        "ev_build",
        "Evaluator(project)",
        f"{(time.perf_counter() - start) * 1000:,.1f} ms",
        "indexes layers and morphs",
    )
    report(
        "first_t0",
        "first frame at t=0",
        f"{timed(lambda: ev.frame(0.0))[0]:,.1f} ms",
        "nothing is drawn yet; a pass over every layer",
    )
    t_open = on_grid(project, 4.0)
    report(
        "first_slide",
        "first frame with slide 1 on screen (t=4 s)",
        f"{timed(lambda: draw(camera, ev, t_open))[0]:,.0f} ms",
        "builds slide 1's five objects, then draws",
    )
    t_deep = on_grid(project, 0.95 * duration)
    cold = timed(lambda: ev.frame(t_deep))[0]
    report(
        "deep_cold",
        f"cold seek to 95 % (t={t_deep:.0f} s), evaluate",
        f"{cold:,.0f} ms",
        "builds that slide's objects and their clips",
    )
    report(
        "deep_cold_draw",
        "... and the frame drawn at widget size",
        f"{timed(lambda: draw(camera, ev, t_deep))[0]:,.1f} ms",
        "",
    )
    fresh = []
    for _ in range(3):
        other = Evaluator(project)
        fresh.append(timed(lambda other=other: other.frame(t_deep))[0])
    report(
        "deep_fresh",
        "same seek, new evaluator, builds warm",
        f"{median(fresh):,.1f} ms",
        "the evaluator's own cost deep in the scene",
    )
    after_open = settled_rss()
    report(
        "rss_open",
        "RSS after the open and deep seek",
        f"{after_open:,.0f} MB",
        f"+{after_open - base:,.0f} MB",
    )

    rng = random.Random(1)
    times = [on_grid(project, rng.uniform(0.0, duration - 0.1)) for _ in range(100)]
    scrub_eval = [timed(lambda t=t: ev.frame(t))[0] for t in times]
    scrub_draw = [timed(lambda t=t: draw(camera, ev, t))[0] for t in times]
    mid = settled_rss()
    report(
        "scrub_eval",
        "scrub 100 random frames: evaluate",
        f"{median(scrub_eval):.1f} / {p95(scrub_eval):.1f} ms",
        "median / p95 (the first visits build objects)",
    )
    report(
        "scrub_draw",
        "scrub 100 random frames: evaluate + draw",
        f"{median(scrub_draw):.1f} / {p95(scrub_draw):.1f} ms",
        "median / p95 at 1100x620 (the second pass over the same times)",
    )
    gap = gap_time(project, slides_of(project) // 2)
    report(
        "scrub_gap",
        "evaluate a frame with nothing alive",
        f"{median(timed(lambda: ev.frame(gap), 30)):.2f} ms",
        "frame_layers() walks every layer and asks its lifetime: grows with the layer count",
    )
    report("rss_scrub", "RSS after the scrub", f"{mid:,.0f} MB", f"+{mid - after_open:,.0f} MB")

    slides = slides_of(project)
    visit_times = [on_grid(project, k * SLIDE + 6.0) for k in range(slides)]
    start = time.perf_counter()
    for t in visit_times:
        draw(camera, ev, t)
    visit = (time.perf_counter() - start) * 1000
    visited = settled_rss()
    report(
        "visit_slides",
        f"visit every slide once ({slides} frames)",
        f"{visit:,.0f} ms",
        f"{visit / slides:.1f} ms per slide",
    )
    report(
        "rss_visit",
        "RSS after visiting every slide",
        f"{visited:,.0f} MB",
        f"+{visited - mid:,.0f} MB; +{visited - base:,.0f} MB over the base",
    )

    missing = ev.missing_checkpoints()
    scan = timed(ev.missing_checkpoints, 5)
    report(
        "missing_scan",
        f"missing_checkpoints() ({len(missing)} missing)",
        f"{median(scan):.1f} ms",
        "run again before every idle checkpoint (one per idle tick)",
    )
    start = time.perf_counter()
    for item in missing:
        ev.compute_checkpoint(*item)
    warm_ms = (time.perf_counter() - start) * 1000
    warmed = settled_rss()
    report(
        "checkpoints",
        f"idle pass: {len(missing)} missing checkpoints",
        f"{warm_ms:,.0f} ms",
        f"{warm_ms / max(1, len(missing)):.1f} ms each (the editor does one per idle tick)",
    )
    report(
        "rss_checkpoints",
        "RSS with every checkpoint computed",
        f"{warmed:,.0f} MB",
        f"+{warmed - visited:,.0f} MB; +{warmed - base:,.0f} MB over the base",
    )
    report(
        "caches",
        "evaluator caches (base/checkpoints/active/proxies)",
        f"{len(ev._base)}/{len(ev._checkpoints)}/{len(ev._active)}/{len(ev._proxies)}",
        "objects, kept clip states, begun animations, transform scratch copies",
    )
    after = timed(lambda: ev.frame(on_grid(project, 0.5 * duration + 6.0)), 5)
    report("scrub_warm", "a frame after the idle pass", f"{median(after):.1f} ms", "everything cached")
    return {"evaluator": ev, "camera": camera, "visit": visit_times}


def edit_section(project: Project, ev: Evaluator, camera: m.Camera) -> None:
    section("edits on the long project")
    k = slides_of(project) // 2
    layer_id = f"title-{k + 1}"
    t_edit = gap_time(project, k) if MODEL_ONLY else on_grid(project, k * SLIDE + 6.0)
    ev.invalidate(project, set(), "timing")  # the evaluator on the unedited project, caches kept
    draw(camera, ev, t_edit)
    state = {"project": project, "i": 0}

    def move() -> None:
        state["i"] += 1
        x = 0.01 * (state["i"] % 9 + 1)
        edit = edits.update_layer(state["project"], layer_id, base={"position": (x, 3.2)})
        state["project"] = edit.project
        ev.apply(edit)
        draw(camera, ev, t_edit)

    total = timed(move, 15)
    steps = {"update": [], "apply": [], "frame": []}
    for i in range(15):
        a = time.perf_counter()
        edit = edits.update_layer(state["project"], layer_id, base={"position": (0.02 * (i % 9 + 1), 3.1)})
        b = time.perf_counter()
        ev.apply(edit)
        c = time.perf_counter()
        draw(camera, ev, t_edit)
        d = time.perf_counter()
        state["project"] = edit.project
        steps["update"].append((b - a) * 1000)
        steps["apply"].append((c - b) * 1000)
        steps["frame"].append((d - c) * 1000)
    report(
        "edit_move",
        "move one layer, end to end",
        f"{median(total):.1f} ms",
        "update_layer + evaluator.apply + a drawn frame (a drag step)",
    )
    report(
        "edit_parts",
        "  update_layer / apply / frame",
        " / ".join(f"{median(v):.1f}" for v in steps.values()) + " ms",
        "the snapshot's validation, the evaluator's cache pass, the drawn frame",
    )
    clip_layer = f"equation-{k + 1}"
    clip_id = project.layer(clip_layer).clips[0].id
    start = project.layer(clip_layer).clips[0].start

    def retime() -> None:
        state["i"] += 1
        edit = edits.move_clip(state["project"], clip_layer, clip_id, start + 0.1 * (state["i"] % 3))
        state["project"] = edit.project
        ev.apply(edit)
        draw(camera, ev, t_edit)

    report(
        "edit_retime",
        "move one clip, end to end",
        f"{median(timed(retime, 15)):.1f} ms",
        "a timeline drag step (timing edit)",
    )

    def reease() -> None:
        state["i"] += 1
        name = "linear" if state["i"] % 2 else "smooth"
        edit = edits.update_clip(state["project"], clip_layer, clip_id, ease=Easing(name=name))
        state["project"] = edit.project
        ev.apply(edit)
        draw(camera, ev, t_edit if MODEL_ONLY else t_edit + 1.0)

    report(
        "edit_clip",
        "change one clip's easing, end to end",
        f"{median(timed(reease, 15)):.1f} ms",
        "drops that layer's checkpoints, redraws",
    )
    base = state["project"]
    add = timed(lambda: edits.add_layer(base, Spec(type="Dot")), 9)
    report(
        "add_layer",
        "edits.add_layer",
        f"{median(add):.1f} ms",
        "a structural edit: validate + classify (B53)",
    )
    remove = timed(lambda: edits.remove_layer(base, f"shape-{k + 1}-1"), 9)
    report("remove_layer", "edits.remove_layer", f"{median(remove):.1f} ms", "")

    for label, key, make in (
        (
            "move one layer",
            "spans_move",
            lambda: edits.update_layer(base, layer_id, base={"position": (1.0, 3.0)}).project,
        ),
        ("add a layer", "spans_add", lambda: edits.add_layer(base, Spec(type="Dot")).project),
        (
            "change a clip's easing",
            "spans_clip",
            lambda: edits.update_clip(base, clip_layer, clip_id, ease=Easing(name="there_and_back")).project,
        ),
    ):
        other = make()
        samples = timed(lambda other=other: frame_cache.changed_spans(base, other), 9)
        spans = frame_cache.changed_spans(base, other)
        frames = (
            len(frame_cache.span_indices(spans, base.canvas.fps, frame_cache.frame_count(base)))
            if spans is not None
            else frame_cache.frame_count(base)
        )
        report(
            key,
            f"changed_spans, {label}",
            f"{median(samples):.1f} ms",
            f"{frames} frames dropped from the cache",
        )


def autosave_section(project: Project, folder: Path) -> None:
    section("autosave")
    samples = timed(
        lambda: recovery.write(folder / "recovery", "bench", project, None, os.getpid(), time.time()), 9
    )
    report(
        "autosave",
        "recovery.write",
        f"{median(samples):.1f} ms",
        "every 30 s on the GUI thread while there are unsaved changes (B51)",
    )


def audio_section(project: Project) -> None:
    section("audio: one sound over the whole scene")
    seconds = project.canvas.duration
    path = project.audio[0].path
    audio.forget()
    base = settled_rss()
    report(
        "wav_bytes",
        "the sound's file (mono 22.05 kHz, 16 bit)",
        f"{os.path.getsize(path) / 2**20:,.1f} MB",
        "on disk",
    )
    report(
        "decode_cold",
        "decode (to the mix rate, stereo float32)",
        f"{timed(lambda: audio.decode(path))[0]:,.0f} ms",
        "once per file; the waveform on the timeline pays it too",
    )
    decoded = settled_rss()
    report(
        "rss_decode",
        "RSS after decoding",
        f"{decoded:,.0f} MB",
        f"+{decoded - base:,.0f} MB held by the decoded file",
    )
    report(
        "peaks",
        "timeline peaks (100 per second)",
        f"{timed(lambda: audio.peaks(path, 100))[0]:,.0f} ms",
        "once per file",
    )

    def rebuild() -> None:
        audio._MIXES.clear()  # what any audio edit does: a new mix signature
        audio.mix(project)

    first = timed(rebuild)[0]
    mixed = settled_rss()
    report(
        "mix_first", "audio.mix after an edit (decode warm)", f"{first:,.0f} ms", "B58: ~120 ms for 5 minutes"
    )
    report("mix_repeat", "... median of 5 rebuilds", f"{median(timed(rebuild, 5)):,.0f} ms", "")
    out = audio.mix(project)
    report(
        "mix_bytes",
        "the mix in memory",
        f"{out.nbytes / 2**20:,.0f} MB",
        f"{out.nbytes / 2**20 / seconds * FULL_SECONDS:,.0f} MB at 900 s; the cache keeps up to two",
    )
    report(
        "rss_mix", "RSS with the mix cached", f"{mixed:,.0f} MB", f"+{mixed - decoded:,.0f} MB over decode"
    )
    level = timed(lambda: levels.level_at(project, 0.5 * seconds), 30)
    report(
        "level_at",
        "levels.level_at (meter, 100 ms window)",
        f"{median(level):.2f} ms",
        f"p95 {p95(level):.2f} ms",
    )
    signature = timed(lambda: audio.mix_signature(project), 30)
    report(
        "mix_sig",
        "audio.mix_signature",
        f"{median(signature):.2f} ms",
        "computed on every playback tick and edit",
    )
    audio.forget()


def timeline_section(project: Project, app: QApplication) -> None:
    section("the timeline: set document, paint, repaint after an edit")
    view = TimelineView()
    view.resize(1600, 600)
    document = Document(Project())
    view.set_document(document)
    view.show()
    app.processEvents()
    audio.forget()  # a freshly started editor: the sound is decoded for its waveform on the first sync

    def open_document() -> None:
        document.replace(project)  # what File > Open does: reset -> fit -> sync
        app.processEvents()

    opened = timed(open_document)[0]
    items = len(view.scene().items())
    report(
        "tl_open_cold",
        "set document, sound not decoded yet",
        f"{opened:,.0f} ms",
        f"{items} graphics items, {len(view.rows())} rows; includes decoding the sound for its waveform",
    )
    report(
        "tl_open",
        "set document again (reset, fit, sync)",
        f"{median(timed(open_document, 3)):,.0f} ms",
        "the sound is decoded and its peaks kept",
    )
    sync = timed(view.sync, 5)
    report(
        "tl_sync",
        "view.sync() alone",
        f"{median(sync):,.1f} ms",
        "rebuilds the scene; runs on EVERY document change, a drag step included",
    )
    profile_call("TimelineView.sync()", view.sync)
    scene = view.scene().sceneRect()
    image = QImage(int(scene.width()) + 1, int(scene.height()) + 1, QImage.Format.Format_ARGB32_Premultiplied)

    def paint_scene() -> None:
        image.fill(0)
        painter = QPainter(image)
        view.scene().render(painter, QRectF(image.rect()), scene)
        painter.end()

    report(
        "tl_scene",
        "paint the whole timeline into a QImage",
        f"{median(timed(paint_scene, 3)):,.0f} ms",
        f"{image.width()}x{image.height()} px at the fit zoom, every item drawn",
    )
    grab = timed(view.grab, 5)
    report(
        "tl_grab",
        "repaint the window (fit zoom, whole scene)",
        f"{median(grab):,.0f} ms",
        "view.grab(): viewport, ruler and header",
    )
    view.scale = TimeScale(px_per_second=120.0)
    view.sync()
    view.horizontalScrollBar().setValue(int(view.scale.x(project.canvas.duration / 2)))
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum() // 2)
    app.processEvents()
    zoom = timed(view.grab, 5)
    report(
        "tl_zoom",
        "repaint at 120 px/s, mid scene",
        f"{median(zoom):,.0f} ms",
        "a scroll or playhead tick when zoomed in",
    )
    state = {"project": project, "i": 0}
    layer_id = f"title-{int(project.canvas.duration // SLIDE) // 2 + 1}"

    def edit_and_repaint() -> None:
        state["i"] += 1
        edit = edits.update_layer(
            state["project"], layer_id, base={"position": (0.01 * (state["i"] % 9 + 1), 3.2)}
        )
        state["project"] = edit.project
        document.apply(edit, "move")  # undo step -> changed -> view.sync()
        view.grab()

    after = timed(edit_and_repaint, 9)
    report(
        "tl_edit",
        "an edit, then the timeline repainted",
        f"{median(after):,.0f} ms",
        "Document.apply (undo step, sync) + grab",
    )
    document.undo_stack.setClean()
    view.close()


def render_ahead_section(project: Project, ev: Evaluator, camera: m.Camera, edit_base: Project) -> None:
    section("render-ahead: the frame store for the whole scene")
    fps, total = project.canvas.fps, frame_cache.frame_count(project)
    rng = random.Random(41)
    indices = sorted(rng.sample(range(total), min(40, total)))
    sizes, pack = [], []
    for i in indices if camera is not None else ():
        pixels = draw(camera, ev, frame_cache.frame_time(i, fps))
        start = time.perf_counter()
        sizes.append(len(zlib.compress(pixels.tobytes(), 1)))  # as preview.py sends them (B41)
        pack.append((time.perf_counter() - start) * 1000)
    mean = statistics.mean(sizes) if sizes else ASSUMED_FRAME_KB * 1024
    whole = mean * total / 2**20
    budget = frame_cache.BUDGET
    if sizes:
        report(
            "ra_frame",
            "a kept frame (zlib 1, 1100x620)",
            f"{mean / 1024:,.0f} KB",
            f"mean of {len(sizes)}; largest {max(sizes) / 1024:,.0f} KB; compress {median(pack):.1f} ms",
        )
    else:
        report(
            "ra_frame",
            "a kept frame (zlib 1, 1100x620)",
            f"{mean / 1024:,.0f} KB",
            "ASSUMED (the quick run measured it); no frame was drawn in --model-only",
        )
    report(
        "ra_whole",
        f"the whole scene ({total} frames)",
        f"{whole:,.0f} MB",
        f"budget {budget / 2**20:.0f} MB -> {min(1.0, budget / (whole * 2**20)):.0%} of it fits",
    )
    store = frame_cache.FrameStore(total=total)
    payload = bytes(
        int(mean)
    )  # one object shared by every frame: the accounting is len(), the RAM is not spent
    start = time.perf_counter()
    for i in range(total):
        if store.nbytes + len(payload) > store.budget:  # the editor stops asking here (missing())
            break
        store.accept(0, 0, i, payload, playhead=0)
    fill = (time.perf_counter() - start) * 1000
    kept = len(store)
    report(
        "ra_fill",
        f"fill the store in order ({kept} kept)",
        f"{fill:,.0f} ms",
        f"{fill / max(1, min(total, kept)):.3f} ms per frame; {store.nbytes / 2**20:,.0f} MB counted",
    )
    if kept < total:
        later = [(i % total) for i in range(kept, kept + 100)]
        start = time.perf_counter()
        for i in later:
            store.accept(0, 0, i, payload, playhead=kept // 2)
        evict = (time.perf_counter() - start) * 1000 / len(later)
        report(
            "ra_evict",
            "accept one frame into a full store",
            f"{evict:.2f} ms",
            "evicts the farthest: a max() over every kept frame",
        )
    miss = timed(lambda: store.missing(total // 3, 60), 9)
    report("ra_missing", "FrameStore.missing(60)", f"{median(miss):.2f} ms", "asked again as frames arrive")
    spans = frame_cache.changed_spans(project, edit_base)
    indices_dropped = frame_cache.span_indices(spans or [], fps, total)
    inv = timed(lambda: store.invalidate(indices_dropped), 3)
    report(
        "ra_invalidate", f"invalidate an edit's {len(indices_dropped)} frames", f"{median(inv):.2f} ms", ""
    )


def window_section(project: Project, app: QApplication, folder: Path) -> None:
    """The real window (1600x1000, Compose page): every panel reacting, not just the pieces above."""
    from manim_studio.ui.main_window import MainWindow

    section("the real window (Compose page, 1600x1000, offscreen)")
    window = MainWindow()
    window.resize(1600, 1000)
    window.show()
    app.processEvents()
    path = folder / "window.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")

    def settle() -> None:
        window.idle_timer.stop()  # the idle checkpoint pass is background work: not part of the step
        app.processEvents()

    def open_project() -> None:
        window.load(path)
        settle()

    report(
        "win_open",
        "File > Open (layers, timeline, canvas, panels)",
        f"{timed(open_project)[0]:,.0f} ms",
        "load -> Document.replace -> every panel rebuilt, the first frame drawn",
    )
    slides = slides_of(project)
    if MODEL_ONLY:
        times = [gap_time(project, k) for k in range(slides)]
    else:
        rng = random.Random(7)
        times = [on_grid(project, rng.uniform(0.0, project.canvas.duration - 0.1)) for _ in range(30)]

    def seek(t: float) -> None:
        window.seek(t)
        settle()

    seeks = [timed(lambda t=t: seek(t))[0] for t in times]
    report(
        "win_seek",
        f"seek in the window ({len(times)} {'slide starts' if MODEL_ONLY else 'random frames'})",
        f"{median(seeks):.1f} / {p95(seeks):.1f} ms",
        "median / p95: playhead, canvas, properties, readout (the first visits build objects)",
    )
    layer_id = f"title-{slides // 2 + 1}"
    state = {"i": 0}

    def edit_in_window() -> None:
        state["i"] += 1
        edit = edits.update_layer(
            window.project, layer_id, base={"position": (0.01 * (state["i"] % 9 + 1), 3.2)}
        )
        window.document.apply(edit, "move")
        settle()

    seek(times[len(times) // 2])
    report(
        "win_edit",
        "move one layer in the window, end to end",
        f"{median(timed(edit_in_window, 9)):.1f} ms",
        "Document.apply -> undo step -> evaluator, timeline, layers panel, properties, canvas",
    )
    profile_call("a layer moved in the window", edit_in_window, 22)
    window.document.undo_stack.setClean()  # closing would ask about the edits
    window.close()


def release_section(holders: dict[str, object]) -> None:
    """What the evaluator and the adapter's build caches hold: drop them and see what RSS gives back."""
    section("memory held by the evaluator (what dropping it gives back)")
    gc.collect()
    before = settled_rss()
    holders.clear()
    clear_builds()
    after = settled_rss()
    report(
        "rss_release",
        "RSS after dropping the evaluator and build caches",
        f"{after:,.0f} MB",
        f"{before - after:,.0f} MB given back (a lower bound: the allocator keeps some)",
    )


def export_section(project: Project, folder: Path, frames: int = 60) -> None:
    section("export: 60 frames at 1280x720")
    plain = project.model_copy(update={"audio": []})
    fps, duration = project.canvas.fps, project.canvas.duration
    total = frame_cache.frame_count(project)
    k = int(duration // SLIDE) // 2
    start_t = on_grid(project, k * SLIDE + 3.0)  # shapes entering: clips running
    options = RenderOptions(start=start_t, end=start_t + frames / fps)
    out = folder / "export.mp4"
    elapsed = timed(lambda: cairo_export.export_video(plain, out, options=options))[0]
    per = elapsed / frames
    report(
        "export_60",
        f"export {frames} frames (no sound)",
        f"{elapsed / 1000:,.2f} s",
        f"{per:.1f} ms per frame including the encoder's start",
    )
    whole = per * total / 1000
    report(
        "export_scene",
        f"... times {total} frames",
        f"{whole / 60:,.1f} min",
        "linear extrapolation; subtitles burned in, x264",
    )
    seconds = min(60.0, duration)
    samples = audio.mix(project)[:, : round(seconds * audio.RATE)]
    import av

    def encode_audio() -> None:
        with av.open(str(folder / "sound.m4a"), mode="w") as container:
            stream = container.add_stream("aac", rate=audio.RATE, layout="stereo")
            cairo_export._encode_audio(container, stream, samples)

    aac = timed(encode_audio)[0]
    report(
        "export_aac",
        f"AAC encode of {seconds:.0f} s of the mix",
        f"{aac:,.0f} ms",
        f"{aac / seconds * duration / 1000:,.1f} s for the whole scene",
    )
    audio.forget()


# -- main -------------------------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true", help="a 2-minute scene with the same density")
    parser.add_argument("--seconds", type=float, help="the scene's length in seconds (default 900)")
    parser.add_argument(
        "--model-only",
        action="store_true",
        help="skip everything that builds or draws objects (text, frames, export): the model-side costs "
        "of a long scene in seconds",
    )
    parser.add_argument("--json", type=Path, help="also write the results to this file")
    parser.add_argument(
        "--profile", action="store_true", help="print cProfile tops for the timeline and window edits"
    )
    args = parser.parse_args()
    global MODEL_ONLY, PROFILE
    MODEL_ONLY, PROFILE = args.model_only, args.profile
    seconds = args.seconds or (120.0 if args.quick else FULL_SECONDS)

    app = QApplication(sys.argv)
    theme.apply(app)
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    adapter.configure(cache / "manim")
    m.config.verbosity = "ERROR"
    logging.getLogger("manim_studio").setLevel(logging.WARNING)  # the export logs a line at INFO
    folder = Path(tempfile.mkdtemp(prefix="bench-long-", dir=cache))
    try:
        started = time.perf_counter()
        project, info = build_project(seconds, folder)
        if MODEL_ONLY:  # no cue text may be built when a seek lands on a cue
            project = project.model_copy(
                update={"subtitle_style": project.subtitle_style.model_copy(update={"burn_in": False})}
            )
        built = (time.perf_counter() - started) * 1000
        print(
            f"B64 long scene: {seconds:.0f} s at {project.canvas.width_px}x{project.canvas.height_px}, "
            f"{project.canvas.fps} fps"
        )
        print(
            f"  {info['slides']} slides, {info['roots']} root layers, {info['clips']} clips, "
            f"{info['keyed']} keyframed layers, {info['cues']} cues, {info['formulas']} distinct formulas, "
            f"{info['frames']} frames (built in {built / 1000:.1f} s)"
        )
        RESULTS.update(seconds=seconds, **info)
        if not MODEL_ONLY:
            warm_up(project)
        project = document_section(project, folder)
        state = model_evaluator_section(project) if MODEL_ONLY else evaluator_section(project)
        ev, camera = state["evaluator"], state["camera"]
        edit_section(project, ev, camera)
        autosave_section(project, folder)
        audio_section(project)
        timeline_section(project, app)
        k = slides_of(project) // 2
        edited = edits.update_layer(project, f"title-{k + 1}", base={"position": (1.0, 3.0)}).project
        render_ahead_section(project, ev, camera, edited)
        if not MODEL_ONLY:
            export_section(project, folder)
        ev = camera = None  # the state dict is the last holder: release_section drops it
        report(
            "rss_end",
            "RSS before dropping the evaluator",
            f"{settled_rss():,.0f} MB",
            "the whole run, audio and timeline included",
        )
        release_section(state)
        window_section(project, app, folder)
        if args.json:
            args.json.write_text(json.dumps(RESULTS, indent=1), encoding="utf-8")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        shutil.rmtree(_SCRATCH, ignore_errors=True)


if __name__ == "__main__":
    main()
