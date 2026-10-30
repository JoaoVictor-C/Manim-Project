"""Stress tests of the headless core: project model, evaluator, Cairo rendering and video export.

No Qt window. Each group is a subcommand; the drivers start every risky piece in its own child process
(with a time limit and, on Windows, a job-object memory cap) so a hang, a crash or a runaway allocation is
reported instead of taking the run down. Windows 11 is assumed for memory numbers and locking tests.

Run against a frozen copy of the sources with ``PYTHONPATH=<copy>/src``::

    PYTHONPATH=<snap>/src .venv313/Scripts/python.exe benchmarks/stress_engine.py <command> [options]

Commands (drivers print a table and write ``results-<command>.json`` into the work folder):

    scale        [--sizes 100 300 1000 2000 5000] [--hours 1]   layers x time: build, round trip, frames
    scale-edits  [--sizes 100 1000 5000]                        cost of one editor edit on a big project
    pathological [--only PREFIX ...] [--list]                   bad values, bad text/LaTeX, bad geometry
    corrupt                                                     broken/huge/deep project files via the CLI
    security                                                    LaTeX file read / shell escape, untrusted code
    export       [--projects euler graphs] [--sizes ...]        export matrix: time, memory, CPU
    leak         [--n 20] [--project euler]                     N exports in one process: memory slope
    paths                                                       unicode/long/missing/locked/read-only outputs
    cancel                                                      killing an export: partial files, orphans
    verify       FILE [--project NAME]                          decode a video fully and check it
    determinism  [--projects ...]                               same pixels in any order / on any run
    memory       [--sizes 1080 4k 8k]                           peak memory of an export, phase by phase
    all                                                         every group, in order

Internal (started by the drivers): ``scale-one``, ``edits-one``, ``cases``, ``export-one``, ``leak-one``,
``det-one``, ``memory-one``, ``paths-one``, ``holder``.

Everything is written under ``$STRESS_WORK`` (default: a folder in the temp directory). Nothing under src/,
tests/, docs/ or examples/ is touched, and the user's settings, logs and library are never read: the same
environment variables as tests/conftest.py point them at throwaway folders.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import gc
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable
from ctypes import wintypes as wt
from dataclasses import dataclass
from pathlib import Path

THIS = Path(__file__).resolve()
ROOT = THIS.parent.parent
WORK = Path(os.environ.get("STRESS_WORK") or Path(tempfile.gettempdir()) / "manim-studio-stress")
RESULT = "@@RESULT@@"
START = "@@START@@"
NAN, INF = float("nan"), float("inf")
EXAMPLES = ROOT / "examples"


# ---------------------------------------------------------------------------------------------------------
# environment, memory, processes
# ---------------------------------------------------------------------------------------------------------


def isolate_env() -> None:
    """The variables tests/conftest.py sets, so nothing touches the user's settings, logs or library.
    Idempotent: children started by a driver inherit the driver's throwaway folders."""
    if os.environ.get("STRESS_ISOLATED") == "1":
        return
    os.environ["STRESS_ISOLATED"] = "1"
    plugins = Path(tempfile.mkdtemp(prefix="stress-plugins-"))
    for source in (EXAMPLES / "plugins").glob("*.py"):  # simulations (ADR 0033) for the determinism group
        shutil.copy(source, plugins)
    os.environ["MANIM_STUDIO_PLUGINS"] = str(plugins)
    mk = lambda prefix: str(Path(tempfile.mkdtemp(prefix=prefix)))  # noqa: E731
    os.environ["MANIM_STUDIO_LOG_DIR"] = mk("stress-logs-")
    os.environ["MANIM_STUDIO_TRUST_FILE"] = str(Path(mk("stress-trust-")) / "trusted.json")
    os.environ["MANIM_STUDIO_RECOVERY"] = mk("stress-recovery-")
    os.environ["MANIM_STUDIO_CODE"] = "0"
    os.environ["MANIM_STUDIO_WORKER"] = "0"
    os.environ["MANIM_STUDIO_PREVIEW"] = "0"
    os.environ["MANIM_STUDIO_LIBRARY"] = mk("stress-library-")
    os.environ["MANIM_STUDIO_PRESETS"] = str(Path(mk("stress-presets-")) / "presets.json")
    os.environ["MANIM_STUDIO_AUDIO"] = "0"
    os.environ["MANIM_STUDIO_MOTION"] = "0"
    os.environ["MANIM_STUDIO_VOICE_CACHE"] = mk("stress-voices-")


def boot():
    """Isolate the environment and point Manim's cache at the repo's (LaTeX needs a non-8.3 path)."""
    isolate_env()
    from manim_studio.core.engine import adapter

    adapter.configure(ROOT / ".cache" / "manim")
    from manim import config

    config.verbosity = "WARNING"  # Manim's own INFO lines would bury the results
    return adapter


class _PMC(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wt.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wt.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wt.DWORD),
        ("SchedulingClass", wt.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("Basic", _BasicLimits),
        ("Io", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


MB = 2**20
if sys.platform == "win32":
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _psapi = ctypes.WinDLL("psapi", use_last_error=True)
    _k32.GetCurrentProcess.restype = wt.HANDLE
    _k32.OpenProcess.restype = wt.HANDLE
    _k32.CreateJobObjectW.restype = wt.HANDLE
    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
    _k32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
    _k32.QueryInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p]
    _k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
    _k32.GetProcessHandleCount.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    _psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_PMC), wt.DWORD]


def _counters(handle) -> _PMC | None:
    counters = _PMC()
    counters.cb = ctypes.sizeof(counters)
    if not _psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
        return None
    return counters


def mem_self() -> dict[str, float]:
    """This process's memory in MB: committed (private), working set and their peaks."""
    c = _counters(_k32.GetCurrentProcess())
    if c is None:
        return {"commit": 0.0, "ws": 0.0, "peak_commit": 0.0, "peak_ws": 0.0}
    return {
        "commit": round(c.PrivateUsage / MB, 1),
        "ws": round(c.WorkingSetSize / MB, 1),
        "peak_commit": round(c.PeakPagefileUsage / MB, 1),
        "peak_ws": round(c.PeakWorkingSetSize / MB, 1),
    }


def commit_now() -> float:
    c = _counters(_k32.GetCurrentProcess())
    return c.PrivateUsage / MB if c else 0.0


def handle_count() -> int:
    n = wt.DWORD()
    _k32.GetProcessHandleCount(_k32.GetCurrentProcess(), ctypes.byref(n))
    return n.value


class Sampler:
    """Polls this process's committed memory in a thread; keeps the peak overall and per named phase."""

    def __init__(self, every: float = 0.004) -> None:
        self.every = every
        self.phase_name = "start"
        self.peak = 0.0
        self.by_phase: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            now = commit_now()
            self.peak = max(self.peak, now)
            self.by_phase[self.phase_name] = max(self.by_phase.get(self.phase_name, 0.0), now)
            self._stop.wait(self.every)

    def phase(self, name: str) -> None:
        self.phase_name = name
        now = commit_now()
        self.by_phase[name] = max(self.by_phase.get(name, 0.0), now)

    def __enter__(self) -> Sampler:
        self.peak = commit_now()
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(1.0)
        self.peak = max(self.peak, commit_now())


def make_job(limit_mb: int):
    """A job object that caps each process's committed memory (the process gets MemoryError instead of
    thrashing the machine) and ends its processes when the handle closes."""
    job = _k32.CreateJobObjectW(None, None)
    info = _ExtendedLimits()
    info.Basic.LimitFlags = 0x100 | 0x2000  # PROCESS_MEMORY | KILL_ON_JOB_CLOSE
    info.ProcessMemoryLimit = limit_mb * MB
    _k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
    return job


def job_peak_mb(job) -> float:
    info = _ExtendedLimits()
    _k32.QueryInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info), None)
    return info.PeakProcessMemoryUsed / MB


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)


@dataclass
class Ran:
    code: int | None
    text: str
    timed_out: bool
    seconds: float
    peak_mb: float
    path: Path

    def results(self) -> list[dict]:
        return [json.loads(line[len(RESULT) :]) for line in self.text.splitlines() if line.startswith(RESULT)]

    def last_start(self) -> str | None:
        starts = [line[len(START) :].strip() for line in self.text.splitlines() if line.startswith(START)]
        return starts[-1] if starts else None

    def tail(self, n: int = 8) -> str:
        lines = [x for x in self.text.splitlines() if not x.startswith((RESULT, START))]
        return "\n".join(lines[-n:])


def run_proc(
    argv: list[str],
    timeout: float,
    limit_mb: int | None = 3072,
    env: dict[str, str] | None = None,
    stall: float | None = None,
) -> Ran:
    """Run a program with a time limit, an output file, and a memory cap. ``stall``: kill it when its
    output has not grown for that many seconds (a hang inside a batch of cases)."""
    WORK.mkdir(parents=True, exist_ok=True)
    log = WORK / f"run-{time.time_ns()}.log"
    full_env = {**os.environ, **(env or {}), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    started = time.monotonic()
    with open(log, "wb") as out:
        proc = subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, env=full_env, cwd=str(ROOT))
        job = None
        if limit_mb and sys.platform == "win32":
            job = make_job(limit_mb)
            _k32.AssignProcessToJobObject(job, int(proc._handle))
        timed_out = False
        last_size, last_change = 0, time.monotonic()
        while proc.poll() is None:
            now = time.monotonic()
            if now - started > timeout:
                timed_out = True
            if stall:
                size = log.stat().st_size
                if size != last_size:
                    last_size, last_change = size, now
                elif now - last_change > stall:
                    timed_out = True
            if timed_out:
                kill_tree(proc.pid)
                break
            time.sleep(0.15)
        proc.wait()
    peak = job_peak_mb(job) if job else 0.0
    if job:
        ctypes.WinDLL("kernel32").CloseHandle(wt.HANDLE(job))
    text = log.read_text(encoding="utf-8", errors="replace")
    return Ran(proc.returncode, text, timed_out, time.monotonic() - started, peak, log)


def me(*args: str) -> list[str]:
    return [sys.executable, "-u", str(THIS), *args]


def emit(obj: dict) -> None:
    print(RESULT + json.dumps(obj, default=str), flush=True)


def save(name: str, data) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / f"results-{name}.json").write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")


def table(rows: list[dict], columns: list[str], title: str = "") -> None:
    if title:
        print(f"\n== {title}")
    if not rows:
        print("(no rows)")
        return
    widths = [max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns]
    print("  ".join(c.ljust(w) for c, w in zip(columns, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(w) for c, w in zip(columns, widths)))


def short(exc_or_text, limit: int = 260) -> str:
    text = str(exc_or_text).strip().replace("\r", "")
    text = " | ".join(line.strip() for line in text.splitlines() if line.strip())
    return text if len(text) <= limit else text[: limit - 1] + "..."


def where(exc: BaseException) -> str:
    """The innermost frame inside manim_studio (src path relative), else the innermost frame."""
    frames = traceback.extract_tb(exc.__traceback__)
    ours = [f for f in frames if f"{os.sep}manim_studio{os.sep}" in f.filename and "stress_engine" not in f.filename]
    frame = (ours or frames or [None])[-1]
    if frame is None:
        return "?"
    name = frame.filename.split(f"{os.sep}manim_studio{os.sep}")[-1] if ours else Path(frame.filename).name
    return f"{name.replace(os.sep, '/')}:{frame.lineno} {frame.name}"


def ms(seconds: float) -> float:
    return round(seconds * 1000, 1)


# ---------------------------------------------------------------------------------------------------------
# project generators
# ---------------------------------------------------------------------------------------------------------

SHAPE_KINDS = ("Circle", "Square", "Rectangle", "Star", "Dot", "Triangle", "Line", "Arrow")
TEX_POOL = (
    r"x^2+y^2=z^2",
    r"\int_0^1 x\,dx=\frac12",
    r"e^{i\pi}+1=0",
    r"\sum_{k=1}^{n}k=\frac{n(n+1)}{2}",
    r"\frac{a}{b}+\frac{c}{d}",
    r"\sqrt{a^2+b^2}",
    r"\alpha+\beta=\gamma",
    r"\lim_{x\to0}\frac{\sin x}{x}=1",
    r"\nabla\cdot E=\rho",
    r"F=ma",
)
GRAPH_POOL = ("sin(x)", "x**2/10-1", "cos(x)*x/3", "exp(x/3)-2", "abs(x)-2", "sqrt(abs(x))-1")
PALETTE = ("#f43f5e", "#6366f1", "#22d3ee", "#facc15", "#10b981", "#f97316", "#a855f7", "#e2e8f0")


def shape_spec(rng: random.Random, kind: str | None = None) -> dict:
    kind = kind or rng.choice(SHAPE_KINDS)
    params: dict = {
        "Circle": {"radius": round(rng.uniform(0.2, 1.0), 2)},
        "Square": {"side_length": round(rng.uniform(0.3, 1.5), 2)},
        "Rectangle": {"width": round(rng.uniform(0.4, 2.0), 2), "height": round(rng.uniform(0.3, 1.2), 2)},
        "Star": {"n": rng.randint(3, 9), "outer_radius": round(rng.uniform(0.3, 1.0), 2)},
        "Dot": {"radius": round(rng.uniform(0.05, 0.3), 2)},
        "Triangle": {},
        "Line": {"start": [-0.8, 0.0], "end": [0.8, round(rng.uniform(-0.5, 0.5), 2)]},
        "Arrow": {"start": [-0.8, 0.0], "end": [0.8, 0.3], "buff": 0.1},
    }[kind]
    colour = rng.choice(PALETTE)
    style = {"stroke": colour, "stroke_width": 3} if kind in ("Line", "Arrow") else {"fill": colour, "fill_opacity": 0.6}
    return {"type": kind, "params": params, "style": style}


def gen_project(
    n: int,
    hours: float = 1.0,
    camera3d: bool = False,
    spread: bool = False,
    seed: int = 1,
    fps: int = 30,
    size: tuple[int, int] = (1280, 720),
) -> dict:
    """A project dict of at least ``n`` layers: shapes, Text, MathTex, axes with a graph, groups of shapes;
    most keyed (position, opacity), most with clips. ``spread``: each layer lives a short window of the
    hour (a typical long scene); otherwise every layer is alive for the whole duration."""
    rng = random.Random(seed)
    duration = 3600.0 * hours
    layers: list[dict] = []

    def pos() -> list[float]:
        return [round(rng.uniform(-6, 6), 3), round(rng.uniform(-3.4, 3.4), 3)]

    def window() -> tuple[dict | None, float, float]:
        if not spread:
            return None, 0.5, duration - 1.5
        w = max(10.0, duration / 50)
        a = round(rng.uniform(1.0, duration - w - 1.0), 3)
        return {"in": a, "out": round(a + w, 3)}, a, round(a + w, 3)

    def placed(lid: str, spec: dict, life: bool = True) -> dict:
        lifetime, a, b = window()
        layer = {
            "id": lid,
            "spec": spec,
            "base": {
                "position": pos(),
                "scale": round(rng.uniform(0.4, 1.1), 3),
                "rotation": round(rng.uniform(-60, 60), 1),
                "opacity": 1.0,
            },
        }
        if life and lifetime:
            layer["lifetime"] = lifetime
        mid = (a + b) / 2
        layer["tracks"] = {
            "position": [{"t": a, "value": pos()}, {"t": mid, "value": pos()}, {"t": b, "value": pos()}],
            "opacity": [{"t": a, "value": 0.2}, {"t": mid, "value": 1.0}],
        }
        layer["clips"] = [
            {"id": f"{lid}-in", "kind": "FadeIn", "start": a, "duration": 1.0},
            {"id": f"{lid}-out", "kind": "FadeOut", "start": b - 1.0, "duration": 1.0},
        ]
        if rng.random() < 0.2:
            layer["clips"].insert(1, {"id": f"{lid}-ind", "kind": "Indicate", "start": mid, "duration": 1.0})
        return layer

    i = 0
    while len(layers) < n:
        pick = i % 10
        lid = f"L{i}"
        if pick <= 4:
            layers.append(placed(lid, shape_spec(rng)))
        elif pick <= 6:
            text = f"Label {rng.randrange(30)}"
            layers.append(placed(lid, {"type": "Text", "params": {"text": text, "font_size": 28}, "style": {"fill": "#ffffff"}}))
        elif pick == 7:
            layers.append(placed(lid, {"type": "MathTex", "params": {"text": rng.choice(TEX_POOL), "font_size": 44}}))
        elif pick == 8:
            axes = {
                "type": "Axes",
                "params": {
                    "x_range": [-5.0, 5.0],
                    "y_range": [-3.0, 3.0],
                    "x_length": round(rng.choice((3.0, 4.0, 5.0)), 1),
                    "y_length": 2.5,
                    "numbers": rng.choice(("no", "yes")),
                },
            }
            layers.append(placed(lid, axes))
            layers.append(
                {
                    "id": f"{lid}g",
                    "parent_id": lid,
                    "spec": {
                        "type": "Graph",
                        "params": {"expression": rng.choice(GRAPH_POOL), "x_range": [-5.0, 5.0]},
                        "style": {"stroke": rng.choice(PALETTE), "stroke_width": 4},
                    },
                }
            )
        else:
            lifetime, a, b = window()
            group = {
                "id": lid,
                "spec": {"type": "Group"},
                "base": {"position": pos()},
                "tracks": {"position": [{"t": a, "value": pos()}, {"t": b, "value": pos()}]},
            }
            if lifetime:
                group["lifetime"] = lifetime
            layers.append(group)
            for k in range(3):
                layers.append(
                    {
                        "id": f"{lid}m{k}",
                        "parent_id": lid,
                        "spec": shape_spec(rng, rng.choice(("Circle", "Square", "Star"))),
                        "base": {"position": [k - 1.0, 0.0]},
                    }
                )
        i += 1
    return {
        "schema_version": 1,
        "canvas": {
            "width_px": size[0],
            "height_px": size[1],
            "fps": fps,
            "duration": duration,
            "background": "#0f172a",
            "frame_height": 8.0,
        },
        "camera": {"phi": 55.0, "theta": -70.0, "gamma": 0.0} if camera3d else {"phi": 0.0, "theta": -90.0, "gamma": 0.0},
        "layers": layers,
    }


def base_dict(w: int = 640, h: int = 360, fps: int = 30, duration: float = 2.0) -> dict:
    """The small project the pathological cases start from: a keyed, clipped circle and a square."""
    return {
        "schema_version": 1,
        "canvas": {"width_px": w, "height_px": h, "fps": fps, "duration": duration, "background": "#101820", "frame_height": 8.0},
        "layers": [
            {
                "id": "c",
                "spec": {"type": "Circle", "params": {"radius": 1.0}, "style": {"fill": "#f43f5e", "fill_opacity": 0.8}},
                "base": {"position": [0.0, 0.0], "scale": 1.0, "rotation": 0.0, "opacity": 1.0},
                "tracks": {
                    "position": [{"t": 0.0, "value": [-2.0, 0.0]}, {"t": 2.0, "value": [2.0, 0.0]}],
                    "scale": [{"t": 0.0, "value": 1.0}, {"t": 2.0, "value": 1.5}],
                    "rotation": [{"t": 0.0, "value": 0.0}, {"t": 2.0, "value": 90.0}],
                    "opacity": [{"t": 0.0, "value": 1.0}, {"t": 2.0, "value": 0.5}],
                },
                "clips": [{"id": "c-1", "kind": "FadeIn", "start": 0.0, "duration": 0.5}],
            },
            {
                "id": "s",
                "spec": {"type": "Square", "params": {"side_length": 1.0}, "style": {"fill": "#6366f1", "fill_opacity": 0.6}},
                "base": {"position": [2.0, 1.0]},
            },
        ],
    }


def put(d: dict, path: str, value) -> dict:
    """``put(d, "layers.0.base.scale", v)``: set a nested value (lists by index)."""
    node = d
    parts = path.split(".")
    for key in parts[:-1]:
        node = node[int(key)] if isinstance(node, list) else node[key]
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value
    return d


def example_path(name: str) -> Path:
    """examples/NAME.json, or examples/NAME/NAME.json (angular_momentum), or a path to a .json file."""
    if Path(name).suffix == ".json":
        return Path(name)
    nested = EXAMPLES / name / f"{name}.json"
    return nested if nested.exists() else EXAMPLES / f"{name}.json"


def load_example(name: str):
    from manim_studio.core.model.schema import Project

    return Project.model_validate_json(example_path(name).read_text(encoding="utf-8"))


def with_canvas(project, **changes):
    return project.model_copy(update={"canvas": project.canvas.model_copy(update=changes)})


# ---------------------------------------------------------------------------------------------------------
# 1. scale
# ---------------------------------------------------------------------------------------------------------


def timed(fn, *a, **k):
    t0 = time.perf_counter()
    value = fn(*a, **k)
    return value, time.perf_counter() - t0


def scale_one(args) -> None:
    """One project size: build, validate, round trip, evaluate+render at start/middle/end, a 60-frame stretch."""
    boot()
    from manim_studio.core.engine.evaluator import Evaluator
    from manim_studio.core.model.schema import Project
    from manim_studio.render.cairo_export import make_camera, render_frame

    out: dict = {"n_requested": args.n, "spread": args.spread, "camera3d": args.camera3d, "hours": args.hours}
    sampler = Sampler().__enter__()
    data, s = timed(gen_project, args.n, args.hours, args.camera3d, args.spread)
    out["layers"] = len(data["layers"])
    out["gen_ms"] = ms(s)
    text, s = timed(json.dumps, data)
    out["json_mb"] = round(len(text) / MB, 2)
    project, s = timed(Project.model_validate_json, text)
    out["validate_json_ms"] = ms(s)
    _, s = timed(Project.model_validate, data)
    out["validate_dict_ms"] = ms(s)
    dumped, s = timed(project.model_dump_json, by_alias=True)
    out["dump_ms"] = ms(s)
    again, s = timed(Project.model_validate_json, dumped)
    out["roundtrip_equal"] = again == project
    path = WORK / f"scale-{args.n}.json"
    WORK.mkdir(parents=True, exist_ok=True)
    _, s = timed(path.write_text, dumped, encoding="utf-8")
    _, s = timed(lambda: Project.model_validate_json(path.read_text(encoding="utf-8")))
    out["load_file_ms"] = ms(s)
    out["commit_after_model_mb"] = round(commit_now())
    try:
        ev, s = timed(Evaluator, project)
        out["evaluator_init_ms"] = ms(s)
        camera = make_camera(project.canvas, project.camera)
        duration, fps = project.canvas.duration, project.canvas.fps
        frames = {}
        for label, t in (("start", 1.0), ("mid", duration / 2), ("end", duration - 2 / fps)):
            layers, e_cold = timed(lambda t=t: [mob for _, mob in ev.frame_layers(t)])
            img, r_cold = timed(render_frame, camera, layers, ev.overlay(t))
            layers, e_warm = timed(lambda t=t: [mob for _, mob in ev.frame_layers(t)])
            img, r_warm = timed(render_frame, camera, layers, ev.overlay(t))
            frames[label] = {
                "alive": len(layers),
                "eval_cold_ms": ms(e_cold),
                "render_cold_ms": ms(r_cold),
                "eval_warm_ms": ms(e_warm),
                "render_warm_ms": ms(r_warm),
                "nonbg_px": int((img[:, :, :3] != img[0, 0, :3]).any(axis=2).sum()),
            }
        out["frames"] = frames
        rng = random.Random(7)
        for k in range(2):
            start = rng.uniform(2.0, max(2.5, duration - 3.0))
            e_total = r_total = 0.0
            budget = time.perf_counter()
            done = 0
            for i in range(60):
                t = start + i / fps
                layers, e = timed(lambda t=t: [mob for _, mob in ev.frame_layers(t)])
                _, r = timed(render_frame, camera, layers, ev.overlay(t))
                e_total, r_total, done = e_total + e, r_total + r, done + 1
                if time.perf_counter() - budget > 240:
                    out["stretch_cut"] = True
                    break
            out[f"stretch{k}_eval_ms_per_frame"] = ms(e_total / done)
            out[f"stretch{k}_render_ms_per_frame"] = ms(r_total / done)
        out["build_errors"] = len(ev.build_errors())
    except BaseException as exc:  # noqa: BLE001 - the harness reports whatever happened
        out["error"] = f"{type(exc).__name__}: {short(exc)} @ {where(exc)}"
    sampler.__exit__()
    out["mem"] = mem_self()
    out["sampler_peak_mb"] = round(sampler.peak)
    emit(out)


def edits_one(args) -> None:
    """What one editor edit costs on a project of ``n`` layers (the editor re-validates the whole project)."""
    boot()
    from manim_studio.core.editing import edits
    from manim_studio.core.engine.evaluator import Evaluator
    from manim_studio.core.model.schema import Project, Spec

    data = gen_project(args.n, 1.0, False, True)
    project = Project.model_validate(data)
    ids = [layer.id for layer in project.layers if layer.parent_id is None and layer.spec.type not in ("Group", "Axes")]
    a, b = ids[10], ids[11]
    out: dict = {"n": len(project.layers)}

    def best(fn, runs=3):
        times = []
        for _ in range(runs):
            _, s = timed(fn)
            times.append(s)
        return ms(min(times))

    out["add_layer_ms"] = best(lambda: edits.add_layer(project, Spec(type="Circle"), layer_id="zz"))
    out["update_layer_move_ms"] = best(lambda: edits.update_layer(project, a, base={"position": (1.0, 1.0)}))
    out["set_key_ms"] = best(lambda: edits.set_key(project, a, "position", 1234.0, (1.0, 2.0)))
    out["remove_layer_ms"] = best(lambda: edits.remove_layer(project, b))
    out["group_2_ms"] = best(lambda: edits.group_layers(project, [a, b]))
    out["move_layer_ms"] = best(lambda: edits.move_layer(project, a, 0))
    added = edits.add_layer(project, Spec(type="Circle"), layer_id="zz")
    out["add_clip_ms"] = best(lambda: edits.add_clip(added.project, "zz", "FadeIn", 0.0, 1.0))
    ev, s = timed(Evaluator, project)
    out["evaluator_init_ms"] = ms(s)
    edit = edits.update_layer(project, a, base={"position": (1.0, 1.0)})
    out["evaluator_apply_move_ms"] = best(lambda: ev.apply(edit), runs=1)
    # building the project one add_layer at a time (the editor's Add menu), time-boxed
    p = Project()
    t0 = time.perf_counter()
    marks = {}
    count = 0
    target = min(args.n, 5000)
    for count in range(1, target + 1):
        p = edits.add_layer(p, Spec(type="Circle", params={"radius": 0.5}), layer_id=f"a{count}").project
        if count in (100, 300, 1000, 2000, 3000, 5000):
            marks[count] = round(time.perf_counter() - t0, 2)
        if time.perf_counter() - t0 > 120:
            out["add_loop_cut_at"] = count
            break
    out["add_loop_s"] = marks
    out["add_loop_total_s"] = round(time.perf_counter() - t0, 2)
    out["mem"] = mem_self()
    emit(out)


def cmd_scale(args) -> None:
    rows = []
    plan = []
    for n in args.sizes:
        plan.append((n, True, False))
        plan.append((n, False, False))
    for n in (100, 1000):
        plan.append((n, True, True))
    if args.sizes and max(args.sizes) >= 5000:
        plan.append((5000, False, True))
    for n, spread, cam3d in plan:
        argv = ["scale-one", "--n", str(n), "--hours", str(args.hours)]
        argv += ["--spread"] if spread else []
        argv += ["--camera3d"] if cam3d else []
        label = f"N={n} {'spread' if spread else 'alive '} {'3D' if cam3d else '2D'}"
        print(f"running {label} ...", flush=True)
        ran = run_proc(me(*argv), timeout=args.timeout, limit_mb=args.cap)
        got = ran.results()
        row = {"label": label, "exit": ran.code, "wall_s": round(ran.seconds, 1), "timed_out": ran.timed_out, "job_peak_mb": round(ran.peak_mb)}
        if got:
            r = got[0]
            row.update(
                layers=r.get("layers"),
                validate_ms=r.get("validate_json_ms"),
                dump_ms=r.get("dump_ms"),
                json_mb=r.get("json_mb"),
                rt=r.get("roundtrip_equal"),
                ev_init_ms=r.get("evaluator_init_ms"),
                error=r.get("error", ""),
                peak_commit=r.get("mem", {}).get("peak_commit"),
                peak_ws=r.get("mem", {}).get("peak_ws"),
            )
            for lab in ("start", "mid", "end"):
                f = r.get("frames", {}).get(lab)
                if f:
                    row[f"{lab}_alive"] = f["alive"]
                    row[f"{lab}_eval_c/w"] = f"{f['eval_cold_ms']}/{f['eval_warm_ms']}"
                    row[f"{lab}_render_c/w"] = f"{f['render_cold_ms']}/{f['render_warm_ms']}"
            row["60f_eval_ms"] = r.get("stretch0_eval_ms_per_frame")
            row["60f_render_ms"] = r.get("stretch0_render_ms_per_frame")
            row["60f_eval2"] = r.get("stretch1_eval_ms_per_frame")
            row["60f_render2"] = r.get("stretch1_render_ms_per_frame")
            row["raw"] = r
        else:
            row["tail"] = ran.tail()
        rows.append(row)
    table(rows, ["label", "layers", "exit", "wall_s", "validate_ms", "dump_ms", "json_mb", "rt", "ev_init_ms", "peak_commit", "peak_ws", "error"], "scale: model")
    table(
        rows,
        ["label", "start_alive", "start_eval_c/w", "start_render_c/w", "mid_alive", "mid_eval_c/w", "mid_render_c/w", "end_eval_c/w", "end_render_c/w", "60f_eval_ms", "60f_render_ms", "60f_eval2", "60f_render2"],
        "scale: frames (ms; cold/warm = first call / repeat)",
    )
    for row in rows:
        if row.get("tail"):
            print(f"-- {row['label']} output tail:\n{row['tail']}")
    save("scale", rows)


def cmd_scale_edits(args) -> None:
    rows = []
    for n in args.sizes:
        print(f"edits N={n} ...", flush=True)
        ran = run_proc(me("edits-one", "--n", str(n)), timeout=900, limit_mb=args.cap)
        got = ran.results()
        rows.append(got[0] if got else {"n": n, "error": ran.tail(), "exit": ran.code})
    keys = ["n", "add_layer_ms", "update_layer_move_ms", "set_key_ms", "add_clip_ms", "remove_layer_ms", "group_2_ms", "move_layer_ms", "evaluator_init_ms", "evaluator_apply_move_ms", "add_loop_total_s", "add_loop_cut_at", "error"]
    table(rows, keys, "edits on a project of N layers (best of 3, ms)")
    for r in rows:
        print(f"N={r.get('n')}: add_layer loop cumulative seconds {r.get('add_loop_s')}")
    save("scale-edits", rows)



def real_one(args) -> None:
    """examples/angular_momentum: the user's 5-minute project (7 large Code layers drawn as placeholders - nothing
    is trusted, no code runs - 7 Text layers, 44 sounds and subtitles): model, frames inside each scene, sound mix."""
    boot()
    from manim_studio.core.engine.evaluator import Evaluator
    from manim_studio.core.model.schema import Project
    from manim_studio.core.sound import audio
    from manim_studio.render.cairo_export import AUDIO_SPAN, make_camera, render_frame

    path = example_path("angular_momentum")
    out: dict = {"file_mb": round(path.stat().st_size / MB, 3)}
    sampler = Sampler().__enter__()
    text = path.read_text(encoding="utf-8")
    project, s = timed(Project.model_validate_json, text)
    out["validate_ms"] = ms(s)
    dumped, s = timed(project.model_dump_json, by_alias=True)
    out["dump_ms"] = ms(s)
    again = Project.model_validate_json(dumped)
    out["roundtrip_equal"] = again == project
    out["layers"] = len(project.layers)
    out["commit_after_model_mb"] = round(commit_now())
    ev, s = timed(Evaluator, project)
    out["evaluator_init_ms"] = ms(s)
    camera = make_camera(project.canvas, project.camera)
    fps, duration = project.canvas.fps, project.canvas.duration
    frames = {}
    for label, t in (("t=1", 1.0), ("hook 10", 10.0), ("momentum 50", 50.0), ("torque 100", 100.0), ("inertia 150", 150.0), ("angular 190", 190.0), ("conservation 230", 230.0), ("recap 260", 260.0), ("end", duration - 2 / fps)):
        layers, e_cold = timed(lambda t=t: [mob for _, mob in ev.frame_layers(t)])
        img, r_cold = timed(render_frame, camera, layers, ev.overlay(t))
        layers, e_warm = timed(lambda t=t: [mob for _, mob in ev.frame_layers(t)])
        img, r_warm = timed(render_frame, camera, layers, ev.overlay(t))
        frames[label] = {"alive": len(layers), "eval_cold_ms": ms(e_cold), "eval_warm_ms": ms(e_warm), "render_cold_ms": ms(r_cold), "render_warm_ms": ms(r_warm), "nonbg_px": int((img[:, :, :3] != img[0, 0, :3]).any(axis=2).sum())}
    out["frames"] = frames
    for k, start in enumerate((60.0, 150.0)):
        e_total = r_total = 0.0
        for i in range(60):
            t = start + i / fps
            layers, e = timed(lambda t=t: [mob for _, mob in ev.frame_layers(t)])
            _, r = timed(render_frame, camera, layers, ev.overlay(t))
            e_total, r_total = e_total + e, r_total + r
        out[f"stretch_{int(start)}s_eval_ms_per_frame"] = ms(e_total / 60)
        out[f"stretch_{int(start)}s_render_ms_per_frame"] = ms(r_total / 60)
    out["build_errors"] = {k: short(v, 120) for k, v in ev.build_errors().items()}
    out["audio_problems"] = {k: short(v, 100) for k, v in list(audio.problems(project).items())[:3]}
    for label, (lo, hi) in {"30s_60-90": (60, 90), "whole_scene": (0, duration)}.items():
        t0 = time.perf_counter()
        samples = 0
        for chunk in audio.mix_chunks(project, round(lo * audio.RATE), round(hi * audio.RATE), AUDIO_SPAN):
            samples += chunk.shape[1]
        out[f"mix_{label}_s"] = round(time.perf_counter() - t0, 2)
        out[f"mix_{label}_seconds_of_sound"] = round(samples / audio.RATE, 2)
    sampler.__exit__()
    out["mem"] = mem_self()
    out["sampler_peak_mb"] = round(sampler.peak)
    emit(out)


def cmd_real(args) -> None:
    ran = run_proc(me("real-one"), timeout=1200, limit_mb=args.cap)
    got = ran.results()
    if not got:
        print("no result:", ran.tail(10))
        return
    r = got[0]
    print({k: v for k, v in r.items() if k != "frames"})
    rows = [{"time": k, **v} for k, v in r["frames"].items()]
    table(rows, ["time", "alive", "eval_cold_ms", "eval_warm_ms", "render_cold_ms", "render_warm_ms", "nonbg_px"], "angular_momentum frames (ms)")
    save("real", r)


# ---------------------------------------------------------------------------------------------------------
# 2. pathological values
# ---------------------------------------------------------------------------------------------------------


@dataclass
class Case:
    name: str
    fn: Callable[[], dict]
    timeout: float = 90.0
    mem_mb: int = 3072


CASES: dict[str, Case] = {}


def case(name: str, timeout: float = 90.0, mem: int = 3072):
    def deco(fn):
        CASES[name] = Case(name, fn, timeout, mem)
        return fn

    return deco


def pipeline(d, times=(0.0, 1.0, 1.9), export: bool | float = False, build_probe: bool = False) -> dict:
    """validate -> JSON round trip -> evaluate -> render -> (export). Reports the first stage that failed."""
    from pydantic import ValidationError

    from manim_studio.core.engine.evaluator import Evaluator
    from manim_studio.core.model.schema import Project
    from manim_studio.render.cairo_export import export_video, make_camera, render_frame
    from manim_studio.render.options import RenderOptions

    stage = "validate"
    out: dict = {}
    try:
        t0 = time.perf_counter()
        project = Project.model_validate(d) if isinstance(d, dict) else d
        out["validate_ms"] = ms(time.perf_counter() - t0)
    except ValidationError as exc:
        return {"outcome": "rejected", "stage": "validate", "msg": short(exc, 220)}
    except Exception as exc:  # noqa: BLE001
        return {"outcome": "FAILED", "stage": "validate", "exc": type(exc).__name__, "msg": short(exc), "at": where(exc)}
    try:
        stage = "roundtrip"
        text = project.model_dump_json(by_alias=True)
        try:
            again = Project.model_validate_json(text)
            out["roundtrip"] = "ok" if again.model_dump_json(by_alias=True) == text else "LOSSY"
        except Exception as exc:  # noqa: BLE001
            out["roundtrip"] = f"UNREADABLE: {short(exc, 120)}"
        ev = Evaluator(project)
        camera = make_camera(project.canvas, project.camera)
        shown = []
        for t in times:
            stage = "evaluate"
            layers = [mob for _, mob in ev.frame_layers(t)]
            stage = "render"
            image = render_frame(camera, layers, ev.overlay(t))
            shown.append(int((image[:, :, :3] != image[0, 0, :3]).any(axis=2).sum()))
        out["nonbg_px"] = shown
        errors = ev.build_errors()
        if errors:
            out["build_errors"] = {k: short(v, 160) for k, v in list(errors.items())[:3]}
        if export:
            stage = "export"
            target = WORK / "pathological-out" / f"{time.time_ns()}.mp4"
            end = None if export is True else float(export)
            res = export_video(project, target, options=RenderOptions(end=end))
            out["export_bytes"] = Path(res.path).stat().st_size
            Path(res.path).unlink(missing_ok=True)
        out["outcome"] = "ok"
        out["stage"] = "done"
    except BaseException as exc:  # noqa: BLE001
        return {**out, "outcome": "FAILED", "stage": stage, "exc": type(exc).__name__, "msg": short(exc), "at": where(exc)}
    return out


def _register_value_cases() -> None:
    values = {"nan": NAN, "inf": INF, "ninf": -INF, "huge": 1e308, "big": 1e30, "neg": -3.0, "zero": 0.0, "tiny": 1e-300}
    targets: dict[str, Callable[[dict, float], None]] = {
        "base.position": lambda d, v: put(d, "layers.0.base.position", [v, 0.5]),
        "base.scale": lambda d, v: put(d, "layers.0.base.scale", v),
        "base.rotation": lambda d, v: put(d, "layers.0.base.rotation", v),
        "base.opacity": lambda d, v: put(d, "layers.0.base.opacity", v),
        "base.anchor": lambda d, v: put(d, "layers.0.base.anchor", [v, 0.0]),
        "key.position": lambda d, v: put(d, "layers.0.tracks.position.1.value", [v, v]),
        "key.scale": lambda d, v: put(d, "layers.0.tracks.scale.1.value", v),
        "key.rotation": lambda d, v: put(d, "layers.0.tracks.rotation.1.value", v),
        "key.opacity": lambda d, v: put(d, "layers.0.tracks.opacity.1.value", v),
        "key.time": lambda d, v: put(d, "layers.0.tracks.position.1.t", v),
        "key.bezier_y": lambda d, v: put(d, "layers.0.tracks.position.0.ease", {"name": None, "bezier": [0.3, v, 0.7, v]}),
        "clip.start": lambda d, v: put(d, "layers.0.clips.0.start", v),
        "clip.duration": lambda d, v: put(d, "layers.0.clips.0.duration", v),
        "lifetime.in": lambda d, v: put(d, "layers.0.lifetime", {"in": v}),
        "lifetime.out": lambda d, v: put(d, "layers.0.lifetime", {"out": v}),
        "canvas.duration": lambda d, v: put(d, "canvas.duration", v),
        "canvas.frame_height": lambda d, v: put(d, "canvas.frame_height", v),
        "param.radius": lambda d, v: put(d, "layers.0.spec.params.radius", v),
        "param.side_length": lambda d, v: put(d, "layers.1.spec.params.side_length", v),
        "style.stroke_width": lambda d, v: put(d, "layers.0.spec.style.stroke_width", v),
        "style.fill_opacity": lambda d, v: put(d, "layers.0.spec.style.fill_opacity", v),
    }
    for tname, setter in targets.items():
        for vname, value in values.items():
            name = f"val/{tname}/{vname}"

            def run(setter=setter, value=value):
                d = base_dict()
                setter(d, value)
                return pipeline(d)

            case(name, timeout=60)(run)


_register_value_cases()


def _int_cases() -> None:
    for fps in (1, 2, 1000, 100000):
        case(f"int/fps/{fps}", timeout=120)(lambda fps=fps: pipeline(put(base_dict(fps=fps), "canvas.fps", fps), export=0.25))
    for w, h in ((1, 1), (2, 2), (3, 3), (1, 4000), (4000, 1), (641, 361), (7, 5)):
        case(f"int/size/{w}x{h}", timeout=120)(lambda w=w, h=h: pipeline(base_dict(w, h), times=(0.0, 1.0), export=0.2))
    for w, h in ((4096, 2160), (7680, 4320), (8192, 8192)):
        case(f"int/size/{w}x{h}", timeout=300, mem=6144)(lambda w=w, h=h: pipeline(base_dict(w, h), times=(0.0,), export=0.1))
    for w, h in ((16384, 16384), (20000, 20000), (65536, 65536), (100000, 100000)):
        case(f"int/size/{w}x{h}", timeout=300, mem=6144)(lambda w=w, h=h: pipeline(base_dict(w, h), times=(0.0,), export=0.05))
    for dur in (1e-9, 0.001, 0.034):
        case(f"int/duration/{dur}", timeout=60)(lambda dur=dur: pipeline(put(base_dict(), "canvas.duration", dur), times=(0.0,), export=True))
    for dur in (1e7, 1e9, 1e12, INF):
        case(f"int/duration_export_full/{dur}", timeout=120, mem=4096)(
            lambda dur=dur: pipeline(put(base_dict(w=64, h=36), "canvas.duration", dur), times=(0.0,), export=True)
        )
    for bg in ("bogus", "", "#12", "red", "#GGGGGG", "rgb(1,2,3)", "#ffffffff"):
        case(f"canvas/background/{bg or 'empty'}", timeout=60)(lambda bg=bg: pipeline(put(base_dict(), "canvas.background", bg)))
    for fh in (1e-9, 1e9):
        case(f"canvas/frame_height/{fh}", timeout=60)(lambda fh=fh: pipeline(put(base_dict(), "canvas.frame_height", fh)))
    case("canvas/frame_height/1e-300", timeout=60)(lambda: pipeline(put(base_dict(), "canvas.frame_height", 1e-300)))


_int_cases()


def _structure_cases() -> None:
    def dup_ids():
        d = base_dict()
        d["layers"][1]["id"] = "c"
        return pipeline(d)

    def dup_clip_ids():
        d = base_dict()
        d["layers"][0]["clips"].append({"id": "c-1", "kind": "FadeOut", "start": 1.0, "duration": 0.5})
        return pipeline(d)

    def overlapping():
        d = base_dict()
        d["layers"][0]["clips"].append({"id": "c-2", "kind": "FadeOut", "start": 0.25, "duration": 0.5})
        return pipeline(d)

    def out_of_order():
        d = base_dict()
        d["layers"][0]["clips"] = [
            {"id": "b", "kind": "FadeOut", "start": 1.5, "duration": 0.4},
            {"id": "a", "kind": "FadeIn", "start": 0.0, "duration": 0.5},
        ]
        return pipeline(d)

    def neg_clip():
        d = base_dict()
        d["layers"][0]["clips"][0]["duration"] = -1.0
        return pipeline(d)

    def zero_clip():
        d = base_dict()
        d["layers"][0]["clips"][0]["duration"] = 0.0
        return pipeline(d)

    def clip_past_end():
        d = base_dict()
        d["layers"][0]["clips"] = [{"id": "x", "kind": "FadeIn", "start": 50.0, "duration": 10.0}]
        return pipeline(d, export=True)

    def lifetime_reversed():
        d = base_dict()
        d["layers"][0]["lifetime"] = {"in": 1.5, "out": 0.5}
        return pipeline(d)

    def keys_same_time():
        d = base_dict()
        tr = d["layers"][0]["tracks"]["position"]
        tr.append({"t": 2.0, "value": [0.0, 3.0]})
        return pipeline(d)

    def keys_unsorted():
        d = base_dict()
        d["layers"][0]["tracks"]["position"] = [{"t": 2.0, "value": [2, 0]}, {"t": 0.0, "value": [-2, 0]}]
        return pipeline(d)

    def million_keys():
        d = base_dict()
        d["layers"][0]["tracks"]["position"] = [{"t": i / 1000.0, "value": [math.sin(i), 0.0]} for i in range(200_000)]
        return pipeline(d, times=(0.0, 1.0, 1.9))

    def morph_missing():
        d = base_dict()
        d["layers"][0]["clips"].append({"id": "m", "kind": "Transform", "start": 1.0, "duration": 0.5, "to_layer": "nope"})
        return pipeline(d)

    def morph_self():
        d = base_dict()
        d["layers"][0]["clips"].append({"id": "m", "kind": "Transform", "start": 1.0, "duration": 0.5, "to_layer": "c"})
        return pipeline(d)

    def path_missing():
        d = base_dict()
        d["layers"][0]["clips"].append({"id": "m", "kind": "MoveAlongPath", "start": 1.0, "duration": 0.5, "params": {"path": "zzz"}})
        return pipeline(d)

    def unknown_type():
        d = base_dict()
        d["layers"][1]["spec"] = {"type": "Bogus", "params": {}}
        return pipeline(d)

    def unknown_clip():
        d = base_dict()
        d["layers"][0]["clips"][0]["kind"] = "Explode"
        return pipeline(d)

    def spec_none_root():
        d = base_dict()
        d["layers"][1].pop("spec")
        return pipeline(d)

    def empty_id():
        d = base_dict()
        d["layers"][1]["id"] = ""
        return pipeline(d)

    def self_parent():
        d = base_dict()
        d["layers"][1]["parent_id"] = "s"
        return pipeline(d)

    def parent_cycle():
        d = base_dict()
        d["layers"][0]["parent_id"] = "s"
        d["layers"][1]["parent_id"] = "c"
        return pipeline(d)

    def groups_20_deep():
        d = base_dict()
        layers = []
        for i in range(20):
            layers.append({"id": f"g{i}", "spec": {"type": "Group"}, **({"parent_id": f"g{i - 1}"} if i else {})})
        layers.append({"id": "leaf", "parent_id": "g19", "spec": {"type": "Circle", "params": {"radius": 0.5}}})
        d["layers"] = layers
        return pipeline(d)

    def parent_chain_5000():
        d = base_dict()
        layers = [{"id": "g0", "spec": {"type": "Group"}}]
        for i in range(1, 5000):
            layers.append({"id": f"p{i}", "parent_id": f"p{i - 1}" if i > 1 else "g0", "spec": {"type": "Circle"}})
        d["layers"] = layers
        return pipeline(d, times=(0.0,))

    def group_with_clips():
        d = base_dict()
        d["layers"] = [{"id": "g", "spec": {"type": "Group"}, "clips": [{"id": "x", "kind": "FadeIn", "start": 0, "duration": 1}]}]
        return pipeline(d)

    def zero_layers():
        d = base_dict()
        d["layers"] = []
        return pipeline(d, export=0.2)

    def layers_1m_dup_check():
        d = base_dict()
        d["layers"] = [{"id": f"x{i}", "spec": {"type": "Dot", "params": {"radius": 0.1}}} for i in range(30000)]
        return pipeline(d, times=(0.0,))

    for fn in (
        dup_ids, dup_clip_ids, overlapping, out_of_order, neg_clip, zero_clip, clip_past_end, lifetime_reversed, keys_same_time,
        keys_unsorted, morph_missing, morph_self, path_missing, unknown_type, unknown_clip, spec_none_root, empty_id, self_parent,
        parent_cycle, groups_20_deep, parent_chain_5000, group_with_clips, zero_layers,
    ):
        case(f"struct/{fn.__name__}", timeout=90)(fn)
    case("struct/200k_keys_one_track", timeout=240)(million_keys)
    case("struct/30000_dots", timeout=240)(layers_1m_dup_check)


_structure_cases()


def _param_cases() -> None:
    """Spec params the UI limits but the file does not."""

    def with_layer(spec: dict, extra: dict | None = None, **pipe) -> dict:
        d = base_dict()
        d["layers"].append({"id": "x", "spec": spec, **(extra or {})})
        return pipeline(d, **pipe)

    cases = {
        "star_n_0": {"type": "Star", "params": {"n": 0}},
        "star_n_1": {"type": "Star", "params": {"n": 1}},
        "star_n_neg": {"type": "Star", "params": {"n": -4}},
        "star_n_float": {"type": "Star", "params": {"n": 3.5}},
        "star_n_1e6": {"type": "Star", "params": {"n": 1_000_000}},
        "circle_radius_str": {"type": "Circle", "params": {"radius": "abc"}},
        "circle_radius_none": {"type": "Circle", "params": {"radius": None}},
        "circle_radius_neg": {"type": "Circle", "params": {"radius": -1.0}},
        "circle_radius_1e300": {"type": "Circle", "params": {"radius": 1e300}},
        "circle_radius_nan": {"type": "Circle", "params": {"radius": NAN}},
        "rect_zero": {"type": "Rectangle", "params": {"width": 0.0, "height": 0.0}},
        "rect_huge": {"type": "Rectangle", "params": {"width": 1e9, "height": 1e9}},
        "dot_zero": {"type": "Dot", "params": {"radius": 0.0}},
        "line_same_point": {"type": "Line", "params": {"start": [1, 1], "end": [1, 1]}},
        "line_3_comp": {"type": "Line", "params": {"start": [1, 1, 1], "end": [1, 2, 3]}},
        "line_bad_point": {"type": "Line", "params": {"start": "a", "end": [1, 2]}},
        "line_nan_point": {"type": "Line", "params": {"start": [NAN, 1], "end": [1, 2]}},
        "arrow_buff_huge": {"type": "Arrow", "params": {"start": [0, 0], "end": [1, 0], "buff": 1e9}},
        "arrow_zero_len": {"type": "Arrow", "params": {"start": [0, 0], "end": [0, 0]}},
        "triangle_params": {"type": "Triangle", "params": {"zzz": 1}},
        "style_bad_colour": {"type": "Circle", "style": {"fill": "notacolour"}},
        "style_unknown_key": {"type": "Circle", "style": {"glow": 1}},
        "style_stroke_width_neg": {"type": "Circle", "style": {"stroke_width": -5}},
        "style_stroke_width_1e9": {"type": "Circle", "style": {"stroke_width": 1e9, "stroke": "#ffffff"}},
        "axes_xstep_0": {"type": "Axes", "params": {"x_step": 0.0}},
        "axes_xstep_1e-4": {"type": "Axes", "params": {"x_step": 1e-4, "numbers": "yes"}},
        "axes_range_reversed": {"type": "Axes", "params": {"x_range": [5, -5]}},
        "axes_range_equal": {"type": "Axes", "params": {"x_range": [1, 1]}},
        "axes_range_huge": {"type": "Axes", "params": {"x_range": [-1e9, 1e9], "x_step": 1.0}},
        "axes_len_0": {"type": "Axes", "params": {"x_length": 0.0}},
        "axes_len_1e9": {"type": "Axes", "params": {"x_length": 1e9}},
        "decimal_number_huge": {"type": "DecimalNumber", "params": {"number": 1e300, "num_decimal_places": 8}},
        "decimal_places_1e6": {"type": "DecimalNumber", "params": {"number": 1.5, "num_decimal_places": 1_000_000}},
        "decimal_nan": {"type": "DecimalNumber", "params": {"number": NAN}},
        "text_font_size_0": {"type": "Text", "params": {"text": "hi", "font_size": 0}},
        "text_font_size_neg": {"type": "Text", "params": {"text": "hi", "font_size": -10}},
        "text_font_size_1e6": {"type": "Text", "params": {"text": "hi", "font_size": 1_000_000}},
        "text_font_size_nan": {"type": "Text", "params": {"text": "hi", "font_size": NAN}},
        "text_font_unknown": {"type": "Text", "params": {"text": "hi", "font": "NoSuchFont-ZZ"}},
        "text_not_str": {"type": "Text", "params": {"text": 12345}},
        "text_none": {"type": "Text", "params": {"text": None}},
        "mathtex_font_size_1e6": {"type": "MathTex", "params": {"text": "x", "font_size": 1_000_000}},
        "image_missing": {"type": "ImageMobject", "params": {"path": "C:/does/not/exist.png"}},
        "image_dir": {"type": "ImageMobject", "params": {"path": str(ROOT)}},
        "image_empty_path": {"type": "ImageMobject", "params": {"path": ""}},
        "svg_missing": {"type": "SVGMobject", "params": {"path": "C:/does/not/exist.svg", "height": 2.0}},
        "svg_height_0": {"type": "SVGMobject", "params": {"path": str(EXAMPLES / "media" / "none.svg"), "height": 0.0}},
        "graph_no_parent": {"type": "Graph", "params": {"expression": "sin(x)"}},
        "traced_no_target": {"type": "TracedPath", "params": {"target": ""}},
        "connector_missing": {"type": "Connector", "params": {"source": "c", "target": "nope"}},
        "connector_same": {"type": "Connector", "params": {"source": "c", "target": "c"}},
    }
    for name, spec in cases.items():
        case(f"param/{name}", timeout=60, mem=2048)(lambda spec=spec: with_layer(spec))

    def graph_expr(expr: str):
        d = base_dict()
        d["layers"].append({"id": "ax", "spec": {"type": "Axes", "params": {}}})
        d["layers"].append({"id": "gr", "parent_id": "ax", "spec": {"type": "Graph", "params": {"expression": expr, "x_range": [-5, 5]}}})
        return pipeline(d)

    for name, expr in {
        "import": "__import__('os').system('echo hi')",
        "lambda": "(lambda: 1)()",
        "attr": "x.__class__",
        "div_zero": "1/0",
        "pow_tower": "x**x**x**x**x",
        "log_neg": "log(x-10)",
        "huge_pow": "x**1000000",
        "nested_250": "(" * 120 + "x" + ")" * 120,
        "unary_chain": "-" * 480 + "x",
        "too_long": "x+" * 300 + "1",
        "unicode": "sin(x) + \u00b2",
        "ints_overflow": "10**400",
    }.items():
        case(f"graph/{name}", timeout=60, mem=2048)(lambda expr=expr: graph_expr(expr))

    def camera_case(phi, theta, gamma):
        d = base_dict()
        d["camera"] = {"phi": phi, "theta": theta, "gamma": gamma}
        return pipeline(d)

    for phi, theta, gamma in ((90.0, -90.0, 0.0), (180.0, -90.0, 0.0), (0.0001, -90.0, 0.0), (89.9999, 0.0, 180.0), (-1.0, 0.0, 0.0), (45.0, 400.0, 0.0), (NAN, -90.0, 0.0)):
        case(f"camera/{phi}_{theta}_{gamma}", timeout=60, mem=2048)(lambda phi=phi, theta=theta, gamma=gamma: camera_case(phi, theta, gamma))


_param_cases()


def _text_cases() -> None:
    def text_layer(text: str, kind: str = "Text", size: float = 24.0, **pipe) -> dict:
        d = base_dict(w=640, h=360)
        d["layers"].append({"id": "t", "spec": {"type": kind, "params": {"text": text, "font_size": size}, "style": {"fill": "#ffffff"}}})
        return pipeline(d, times=(0.0, 1.0), **pipe)

    unique = lambda: f"{time.time_ns()}"  # noqa: E731 - defeats the on-disk cache where the point is a cold build

    for n, t_out, mem in ((1_000, 60, 2048), (10_000, 180, 3072), (100_000, 420, 4096)):
        case(f"text/words_{n}", timeout=t_out, mem=mem)(
            lambda n=n: text_layer(("lorem ipsum dolor sit amet " * (n // 27 + 1))[:n].replace("amet l", "amet\nl") + unique()[:3])
        )
    case("text/single_line_a_x100000", timeout=420, mem=4096)(lambda: text_layer("a" * 100_000))
    case("text/empty", timeout=60)(lambda: text_layer(""))
    case("text/spaces_only", timeout=60)(lambda: text_layer("   "))
    case("text/newlines_only", timeout=60)(lambda: text_layer("\n\n\n"))
    case("text/nul_char", timeout=60)(lambda: text_layer("a\x00b"))
    case("text/control_chars", timeout=60)(lambda: text_layer("a\x07\x1b[31m\x7fb"))
    case("text/emoji", timeout=90)(lambda: text_layer("😀🎉👨‍👩‍👧‍👦🏳️‍🌈 emoji"))
    case("text/rtl_arabic", timeout=90)(lambda: text_layer("مرحبا بالعالم 123 abc"))
    case("text/rtl_hebrew_mixed", timeout=90)(lambda: text_layer("שלום world עולם"))
    case("text/combining_marks", timeout=90)(lambda: text_layer("e\u0301\u0302\u0303\u0304" * 50 + "Z\u0300" * 200))
    case("text/zalgo_deep", timeout=120)(lambda: text_layer("Z" + "".join(chr(0x300 + i % 0x6F) for i in range(5000))))
    case("text/surrogate_lone", timeout=60)(lambda: text_layer("a\ud800b"))
    case("text/long_cjk", timeout=120)(lambda: text_layer("日本語のテキスト" * 200))
    case("text/markup_chars", timeout=60)(lambda: text_layer("<b>bold</b> & <i>x</i> &amp; <span foreground='red'>"))
    case("text/t2c_unknown_piece", timeout=60)(lambda: pipeline(_with_params({"type": "Text", "params": {"text": "abc", "t2c": {"zzz": "#ff0000"}}})))
    # LaTeX
    for name, tex in {
        "empty": "",
        "unbalanced_open": "{",
        "unbalanced_close": "}",
        "frac_open": r"\frac{1}{",
        "dollar": "$",
        "begin_no_end": r"\begin{aligned} a",
        "undefined_cs": r"\notacommand",
        "backslash_only": "\\",
        "percent_comment": "x % comment",
        "double_hash": "##",
        "large_sum": "+".join(f"x_{{{i}}}" for i in range(400)),
        "deep_braces": "{" * 200 + "x" + "}" * 200,
        "unicode_math": "∑ ∫ ≤ α 😀",
        "newline": "a\nb",
    }.items():
        case(f"tex/{name}", timeout=120)(lambda tex=tex: text_layer(tex + f" %{unique()}", "MathTex"))
    case("tex/big_100k_chars", timeout=300, mem=4096)(lambda: text_layer("x+" * 50_000 + "1", "MathTex"))
    case("tex/infinite_loop", timeout=60)(lambda: text_layer(r"\def\a{\a}\a " + f"%{unique()}", "MathTex"))
    case("tex/exp_blowup", timeout=90, mem=2048)(lambda: text_layer(r"\def\a{\a\a}\a " + f"%{unique()}", "MathTex"))
    case("tex/tex_kind_hello", timeout=90)(lambda: text_layer(r"Hello \LaTeX " + unique(), "Tex"))


def _with_params(spec: dict) -> dict:
    d = base_dict()
    d["layers"].append({"id": "t", "spec": spec})
    return d


_text_cases()


def _geometry_cases() -> None:
    def shape_points(n_points: int, pieces: int = 1) -> dict:
        import numpy as np

        rng = np.random.default_rng(3)
        per = n_points // pieces
        out = []
        for _ in range(pieces):
            walk = np.cumsum(rng.normal(0, 0.01, size=(per, 2)), axis=0)
            out.append({"points": walk.round(4).tolist(), "fill": [1, 0, 0, 0.3], "stroke": [1, 1, 1, 1], "stroke_width": 2.0})
        d = base_dict()
        d["layers"].append({"id": "sh", "spec": {"type": "Shape", "params": {"version": 1, "shapes": out}}})
        return d

    case("geom/shape_1M_points", timeout=240, mem=4096)(lambda: pipeline(shape_points(1_000_000)))
    case("geom/shape_300001_points", timeout=240, mem=4096)(lambda: pipeline(shape_points(300_001)))
    case("geom/shape_299999_points", timeout=300, mem=4096)(lambda: pipeline(shape_points(299_999), times=(0.0, 1.0)))
    case("geom/shape_30000_pieces", timeout=300, mem=4096)(lambda: pipeline(shape_points(30_000, 30_000), times=(0.0,)))
    case("geom/shape_300000_pieces_of_1_point", timeout=300, mem=4096)(lambda: pipeline(shape_points(300_000, 300_000), times=(0.0,)))

    def shape_path_follow() -> dict:
        d = shape_points(150_000)
        d["layers"].append(
            {
                "id": "dot",
                "spec": {"type": "Dot", "params": {"radius": 0.1}},
                "clips": [{"id": "mv", "kind": "MoveAlongPath", "start": 0.0, "duration": 1.5, "params": {"path": "sh"}}],
            }
        )
        return pipeline(d, times=(0.0, 0.7, 1.9))

    case("geom/move_along_150k_point_path", timeout=300, mem=4096)(shape_path_follow)

    def shape_bad(points) -> dict:
        d = base_dict()
        d["layers"].append(
            {"id": "sh", "spec": {"type": "Shape", "params": {"version": 1, "shapes": [{"points": points, "fill": [1, 0, 0, 1], "stroke": [1, 1, 1, 1], "stroke_width": 1}]}}}
        )
        return pipeline(d)

    case("geom/shape_one_point", timeout=60)(lambda: shape_bad([[0, 0]]))
    case("geom/shape_nan_points", timeout=60)(lambda: shape_bad([[0, 0], [NAN, 1], [1, 1], [2, 2]]))
    case("geom/shape_coincident_points", timeout=60)(lambda: shape_bad([[0, 0]] * 40))
    case("geom/shape_huge_coords", timeout=60)(lambda: shape_bad([[0, 0], [1e15, 1e15], [-1e15, 1e15], [0, 0]]))
    case("geom/shape_not_3n_plus_1", timeout=60)(lambda: shape_bad([[0, 0], [1, 1], [2, 0]]))

    def many_parts_morph() -> dict:
        d = base_dict()
        d["layers"].append({"id": "m1", "spec": {"type": "MathTex", "params": {"text": "+".join(f"x_{i}" for i in range(250)), "font_size": 20}}})
        d["layers"].append({"id": "m2", "spec": {"type": "MathTex", "params": {"text": "+".join(f"y_{i}" for i in range(250)), "font_size": 20}}})
        d["layers"][2]["clips"] = [{"id": "tm", "kind": "Transform", "start": 0.2, "duration": 1.0, "to_layer": "m2", "params": {"match": "smart"}}]
        return pipeline(d, times=(0.1, 0.7, 1.5))

    case("geom/smart_morph_250_glyphs_each", timeout=300, mem=3072)(many_parts_morph)


_geometry_cases()


def _code_cases() -> None:
    """Trusted code that misbehaves (the user's own code runs with --trust-code; limits still matter)."""

    def python_obj(code: str, trusted: bool = True) -> dict:
        from manim_studio.core.code import python_object

        python_object.trust_everything(trusted)
        d = base_dict()
        d["layers"].append({"id": "py", "spec": {"type": "Python", "params": {"code": code, "values": {}}}})
        return pipeline(d, times=(0.0,))

    case("code/python_endless_loop", timeout=100, mem=2048)(lambda: python_obj("PARAMS = {}\ndef build(p):\n    while True:\n        pass\n"))
    case("code/python_sleep_100", timeout=100, mem=2048)(lambda: python_obj("import time\nPARAMS = {}\ndef build(p):\n    time.sleep(100)\n    return Circle()\n"))
    case("code/python_native_busy", timeout=100, mem=2048)(lambda: python_obj("PARAMS = {}\ndef build(p):\n    sum(range(10**11))\n    return Circle()\n"))
    case("code/python_memory_bomb", timeout=100, mem=2048)(lambda: python_obj("PARAMS = {}\ndef build(p):\n    x = bytearray(10**10)\n    return Circle()\n"))
    case("code/python_returns_none", timeout=60)(lambda: python_obj("PARAMS = {}\ndef build(p):\n    return None\n"))
    case("code/python_returns_nan_points", timeout=60)(
        lambda: python_obj("PARAMS = {}\ndef build(p):\n    c = Circle()\n    c.points[:] = float('nan')\n    return c\n")
    )
    case("code/python_exit", timeout=60)(lambda: python_obj("import sys\nPARAMS = {}\ndef build(p):\n    sys.exit(3)\n"))
    case("code/python_kill_process", timeout=60)(lambda: python_obj("import os\nPARAMS = {}\ndef build(p):\n    os._exit(7)\n"))
    case("code/python_syntax_error", timeout=60)(lambda: python_obj("PARAMS = {\ndef build(:\n"))
    case("code/python_untrusted_does_not_run", timeout=60)(_untrusted_marker)


def _untrusted_marker() -> dict:
    from manim_studio.core.code import python_object

    python_object.trust_everything(False)
    marker = WORK / "untrusted-marker.txt"
    marker.unlink(missing_ok=True)
    code = f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\nPARAMS = {{}}\ndef build(p):\n    return Circle()\n"
    d = base_dict()
    d["layers"].append({"id": "py", "spec": {"type": "Python", "params": {"code": code, "values": {}}}})
    res = pipeline(d, times=(0.0,))
    res["marker_written"] = marker.exists()
    if marker.exists():
        res["outcome"] = "FAILED"
        res["msg"] = "UNTRUSTED PYTHON OBJECT CODE RAN WITHOUT TRUST"
    marker.unlink(missing_ok=True)
    return res


_code_cases()


def cases_child(names: list[str]) -> None:
    boot()
    for name in names:
        entry = CASES[name]
        print(START + name, flush=True)
        gc.collect()
        before = commit_now()
        t0 = time.perf_counter()
        sampler = Sampler().__enter__()
        try:
            res = entry.fn()
            res = res if isinstance(res, dict) else {"outcome": "ok", "value": res}
        except BaseException as exc:  # noqa: BLE001
            res = {"outcome": "FAILED", "stage": "case", "exc": type(exc).__name__, "msg": short(exc), "at": where(exc)}
        sampler.__exit__()
        res.update(name=name, seconds=round(time.perf_counter() - t0, 2), mem_peak_mb=round(sampler.peak), mem_delta_mb=round(sampler.peak - before))
        emit(res)
        if name.startswith("code/python_kill") or name.startswith("code/python_exit"):
            pass


ALONE = {  # expected to hang or to be killed: each runs in its own child with its own time limit
    "tex/infinite_loop",
    "tex/exp_blowup",
    "code/python_endless_loop",
    "code/python_sleep_100",
    "code/python_native_busy",
    "code/python_memory_bomb",
    "code/python_kill_process",
    "code/python_exit",
}


def _alone(name: str) -> bool:
    c = CASES[name]
    return name in ALONE or c.timeout > 100 or c.mem_mb > 3072 or name.startswith(("text/", "int/size/", "int/duration_export_full", "geom/"))


def run_cases(names: list[str]) -> list[dict]:
    """Run cases in child processes (light ones in batches); a hang, a crash or a memory-cap hit is recorded
    against the case that was running and the rest continue in a new child."""
    results: dict[str, dict] = {}
    remaining = list(names)
    while remaining:
        if _alone(remaining[0]):
            batch = [remaining[0]]
            limit, timeout, stall = CASES[batch[0]].mem_mb, CASES[batch[0]].timeout + 20, CASES[batch[0]].timeout
        else:
            batch = []
            for n in remaining:
                if _alone(n) or len(batch) >= 60:
                    break
                batch.append(n)
            limit, timeout, stall = 3072, 100.0 * len(batch) + 60, 60.0
        ran = run_proc(me("cases", "--names", ",".join(batch)), timeout=timeout, limit_mb=limit, stall=stall)
        for res in ran.results():
            results[res["name"]] = res
        unfinished = [n for n in batch if n not in results]
        if unfinished:
            current = ran.last_start()
            culprit = current if current in unfinished else unfinished[0]
            if ran.timed_out:
                results[culprit] = {"name": culprit, "outcome": "HANG", "msg": f"no result within {CASES[culprit].timeout:.0f} s; killed", "seconds": round(ran.seconds, 1), "mem_peak_mb": round(ran.peak_mb)}
            else:
                tail = ran.tail(6).replace(chr(10), " | ")
                results[culprit] = {"name": culprit, "outcome": "CRASH", "msg": f"process exited with code {ran.code}: {short(tail, 300)}", "mem_peak_mb": round(ran.peak_mb)}
        remaining = [n for n in remaining if n not in results]
    return [results[n] for n in names]


def cmd_pathological(args) -> None:
    names = [n for n in CASES if not args.only or any(n.startswith(p) for p in args.only)]
    if args.list:
        print("\n".join(names))
        return
    print(f"{len(names)} cases", flush=True)
    rows = run_cases(names)
    save("pathological", rows)
    summary: dict[str, int] = {}
    for r in rows:
        summary[r["outcome"]] = summary.get(r["outcome"], 0) + 1
    print("\noutcomes:", summary)
    for kind in ("HANG", "CRASH", "FAILED"):
        sel = [r for r in rows if r["outcome"] == kind]
        if sel:
            print(f"\n-- {kind} ({len(sel)})")
            for r in sel:
                print(f"  {r['name']}: stage={r.get('stage')} {r.get('exc', '')} {r.get('msg', '')}  @{r.get('at', '')}  [{r.get('seconds')}s, peak {r.get('mem_peak_mb')} MB]")
    odd = [r for r in rows if r["outcome"] == "ok" and (r.get("roundtrip", "ok") != "ok" or r.get("build_errors") or r.get("mem_peak_mb", 0) > 1200 or r.get("seconds", 0) > 20)]
    if odd:
        print(f"\n-- ok but notable ({len(odd)}): lossy/unreadable round trip, build errors, >1.2 GB or >20 s")
        for r in odd:
            print(f"  {r['name']}: roundtrip={r.get('roundtrip')} build_errors={r.get('build_errors')} {r.get('seconds')}s peak {r.get('mem_peak_mb')} MB nonbg={r.get('nonbg_px')}")
    rej = [r for r in rows if r["outcome"] == "rejected"]
    print(f"\n-- rejected with a validation message ({len(rej)}):")
    for r in rej:
        print(f"  {r['name']}: {r.get('msg', '')[:150]}")
    okc = [r for r in rows if r["outcome"] == "ok"]
    print(f"\n-- ok ({len(okc)}): " + ", ".join(r["name"] for r in okc))


# ---------------------------------------------------------------------------------------------------------
# 2b. security
# ---------------------------------------------------------------------------------------------------------


def cmd_security(args) -> None:
    """LaTeX reading arbitrary files / running programs from a project's formula, untrusted code not running."""
    WORK.mkdir(parents=True, exist_ok=True)
    secret = WORK / "secret-input.tex"
    secret.write_text("SECRETPASSWORD", encoding="utf-8")
    empty = WORK / "empty-input.tex"
    empty.write_text("", encoding="utf-8")
    marker_cmd = WORK / "write18-marker.txt"
    marker_cmd.unlink(missing_ok=True)
    marker_out = WORK / "openout-abs-marker.txt"
    marker_out.unlink(missing_ok=True)
    rel_marker = ROOT / ".cache" / "manim" / "Tex" / "stress-rel-marker.txt"
    rel_marker.unlink(missing_ok=True)
    fwd = lambda p: str(p).replace("\\", "/")  # noqa: E731
    uniq = f"%{time.time_ns()}"
    probes = {
        "baseline_empty_input": rf"\input{{{fwd(empty)}}} {uniq}a",
        "input_absolute_file": rf"\input{{{fwd(secret)}}} {uniq}b",
        "input_missing_file": rf"\input{{{fwd(WORK / 'zz-missing')}}} {uniq}c",
        "openin_read": rf"\openin1={fwd(secret)}\relax\read1 to\x\x {uniq}d",
        "include": rf"\include{{{fwd(secret)}}} {uniq}e",
        "write18_cmd": rf"\immediate\write18{{cmd /c echo pwned> {fwd(marker_cmd)}}} {uniq}f",
        "openout_absolute": rf"\immediate\openout3={fwd(marker_out)}\immediate\write3{{x}}\immediate\closeout3 {uniq}g",
        "openout_relative": rf"\immediate\openout3=stress-rel-marker.txt\immediate\write3{{x}}\immediate\closeout3 {uniq}h",
    }
    code = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, %r)
import stress_engine as S
S.boot()
from manim_studio.core.engine.evaluator import Evaluator
from manim_studio.core.model.schema import Project
probes = json.loads(Path(%r).read_text(encoding='utf-8'))
for name, tex in probes.items():
    print(S.START + name, flush=True)
    d = S.base_dict()
    d['layers'] = [{'id': 't', 'spec': {'type': 'MathTex', 'params': {'text': tex, 'font_size': 40}}}]
    p = Project.model_validate(d)
    ev = Evaluator(p)
    layers = [m for _, m in ev.frame_layers(1.0)]
    mob = ev.built(p.layers[0].spec)
    errs = ev.build_errors()
    S.emit({'name': name, 'glyphs': len(mob.submobjects), 'points': int(len(mob.points)), 'build_errors': {k: S.short(v, 300) for k, v in errs.items()}})
"""
    probe_file = WORK / "security-probes.json"
    probe_file.write_text(json.dumps(probes), encoding="utf-8")
    script = WORK / "security-child.py"
    script.write_text(code % (str(THIS.parent), str(probe_file)), encoding="utf-8")
    rows = []
    for name in probes:  # one process each: a hang in one cannot block the others
        sub = WORK / f"security-{name}.json"
        sub.write_text(json.dumps({name: probes[name]}), encoding="utf-8")
        script.write_text(code % (str(THIS.parent), str(sub)), encoding="utf-8")
        ran = run_proc([sys.executable, "-u", str(script)], timeout=75, limit_mb=2048, stall=70)
        res = ran.results()
        rows.append({**(res[0] if res else {"name": name, "error": ran.tail(4), "hang": ran.timed_out})})
    table(rows, ["name", "glyphs", "points", "build_errors", "error", "hang"], "LaTeX probes (glyphs > 0 with the secret file means its text was typeset)")
    print("write18 marker written:", marker_cmd.exists(), "| absolute \\openout marker written:", marker_out.exists(), "| relative \\openout marker (Tex cache dir):", rel_marker.exists())
    for p in (marker_cmd, marker_out, rel_marker):
        p.unlink(missing_ok=True)
    # the latex log for the secret probe: did TeX open the file?
    logs = sorted((ROOT / ".cache" / "manim" / "Tex").glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:12]
    hit = [p.name for p in logs if "secret-input" in p.read_text(errors="replace")]
    print("latex logs mentioning secret-input.tex:", hit)
    # untrusted code does not run
    ran = run_proc(me("cases", "--names", "code/python_untrusted_does_not_run"), timeout=90)
    print("untrusted Python object:", [{k: r.get(k) for k in ("outcome", "marker_written", "msg")} for r in ran.results()])
    save("security", rows)


# ---------------------------------------------------------------------------------------------------------
# 2c. corrupt project files, through the CLI (what a user sees)
# ---------------------------------------------------------------------------------------------------------


def cmd_corrupt(args) -> None:
    folder = WORK / "corrupt"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    good = (EXAMPLES / "euler.json").read_text(encoding="utf-8")
    files: dict[str, tuple[bytes | str, str]] = {
        "truncated_half": (good[: len(good) // 2], "json cut in half"),
        "truncated_1_char": (good[:1], "just {"),
        "empty": ("", "0 bytes"),
        "whitespace": ("   \n\t ", "blank"),
        "bom_prefixed": ("\ufeff" + good, "valid project with a UTF-8 BOM (Notepad's default)"),
        "utf16": (good.encode("utf-16"), "valid project saved as UTF-16"),
        "latin1_bytes": (good.replace("Euler", "Eul\xe9r").encode("latin-1"), "invalid UTF-8"),
        "nan_literal": (good.replace('"scale": 1.0', '"scale": NaN', 1), "NaN literal"),
        "wrong_version": (good.replace('"schema_version": 1', '"schema_version": 99'), "schema_version 99"),
        "top_level_list": ("[1,2,3]", "a list"),
        "top_level_null": ("null", "null"),
        "layers_not_list": ('{"layers": 5}', "layers is a number"),
        "binary_junk_1MB": (os.urandom(1 << 20), "1 MB random bytes"),
        "deep_nest_params_10k": ('{"layers":[{"id":"a","spec":{"type":"Circle","params":' + '{"a":' * 10_000 + "1" + "}" * 10_000 + "}}]}", "10 000 levels in params"),
        "deep_nest_params_100k": ('{"layers":[{"id":"a","spec":{"type":"Circle","params":' + '{"a":' * 100_000 + "1" + "}" * 100_000 + "}}]}", "100 000 levels"),
        "deep_nest_lists_1M": ("[" * 1_000_000 + "]" * 1_000_000, "1 000 000 levels of lists"),
        "huge_string_50MB_text": ('{"canvas":{"duration":1},"layers":[{"id":"a","spec":{"type":"Text","params":{"text":"' + "x" * (50 << 20) + '"}}}]}', "50 MB of text in a Text layer"),
    }
    for name, (content, _) in files.items():
        path = folder / f"{name}.json"
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8", errors="surrogatepass"))
    # 200 MB of junk, written in chunks
    with open(folder / "junk_200MB_A.json", "wb") as f:
        for _ in range(200):
            f.write(b"A" * (1 << 20))
    with open(folder / "junk_200MB_random.json", "wb") as f:
        for _ in range(200):
            f.write(os.urandom(1 << 20))
    with open(folder / "valid_prefix_then_200MB_spaces.json", "wb") as f:
        f.write(b'{"layers": [] , "pad": "')
        for _ in range(200):
            f.write(b" " * (1 << 20))
        f.write(b'"}')
    files["junk_200MB_A"] = (b"", "200 MB of 'A'")
    files["junk_200MB_random"] = (b"", "200 MB random bytes")
    files["valid_prefix_then_200MB_spaces"] = (b"", "valid JSON with a 200 MB string")
    rows = []
    for name, (_, note) in files.items():
        out = folder / f"{name}.mp4"
        argv = [sys.executable, "-m", "manim_studio", "render", str(folder / f"{name}.json"), str(out), "--size", "320x180", "--end", "0.2", "--cache-dir", str(ROOT / ".cache" / "manim")]
        ran = run_proc(argv, timeout=180, limit_mb=3072, env=None)
        text = ran.text.strip()
        traceback_seen = "Traceback (most recent call last)" in text
        rows.append(
            {
                "file": name,
                "note": note,
                "exit": ran.code,
                "seconds": round(ran.seconds, 1),
                "peak_mb": round(ran.peak_mb),
                "timeout": ran.timed_out,
                "traceback": traceback_seen,
                "last_line": short(text.splitlines()[-1] if text else "", 170),
            }
        )
        print(f"{name}: exit {ran.code} traceback={traceback_seen} {rows[-1]['last_line'][:100]}", flush=True)
    table(rows, ["file", "exit", "seconds", "peak_mb", "timeout", "traceback", "last_line"], "CLI render of broken project files (exit 2 + one 'error:' line is the clean outcome)")
    save("corrupt", rows)
    shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------------------------------------------------
# 3. export
# ---------------------------------------------------------------------------------------------------------


def export_one(args) -> None:
    boot()
    from manim_studio.render.cairo_export import export_video
    from manim_studio.render.options import RenderOptions, frame_window

    project = load_example(args.project)
    if args.seconds:
        project = with_canvas(project, duration=args.seconds)
    width, height = (int(x) for x in args.size.split("x")) if args.size else (None, None)
    if args.trust:
        from manim_studio import cli
        from manim_studio.core.code import python_object

        python_object.trust_everything()
        cli._render_code_layers(project.model_copy(update={"canvas": project.canvas.model_copy(update={"width_px": width or project.canvas.width_px, "height_px": height or project.canvas.height_px})}), True, "json")
    options = RenderOptions(width=width, height=height, fps=args.fps, crf=args.crf, start=args.start or 0.0, end=args.end)
    first, last = frame_window(project.canvas, options)
    out = Path(args.out) if args.out else WORK / "exports" / f"{args.project}-{args.size}-{time.time_ns()}.mp4"
    stamps: list[float] = []
    sampler = Sampler(0.01).__enter__()

    def progress(done: int, total: int) -> None:
        stamps.append(time.perf_counter())

    gc.collect()
    base = mem_self()
    t0 = time.perf_counter()
    cpu0 = time.process_time()
    try:
        res = export_video(project, out, progress, options=options)
        error = None
    except BaseException as exc:  # noqa: BLE001
        res, error = None, f"{type(exc).__name__}: {short(exc)} @ {where(exc)}"
    wall = time.perf_counter() - t0
    cpu = time.process_time() - cpu0
    sampler.__exit__()
    gaps = sorted(b - a for a, b in zip(stamps, stamps[1:]))
    n = len(stamps)
    result = {
        "project": args.project,
        "size": args.size or f"{project.canvas.width_px}x{project.canvas.height_px}",
        "fps": args.fps or project.canvas.fps,
        "seconds_of_video": round((last - first) / (args.fps or project.canvas.fps), 2),
        "frames": n,
        "expected_frames": last - first,
        "wall_s": round(wall, 2),
        "ms_per_frame": ms(wall / n) if n else None,
        "first_frame_ms": ms(stamps[0] - t0) if n else None,
        "p50_ms": ms(gaps[len(gaps) // 2]) if gaps else None,
        "p95_ms": ms(gaps[int(len(gaps) * 0.95)]) if gaps else None,
        "max_ms": ms(gaps[-1]) if gaps else None,
        "cpu_s": round(cpu, 2),
        "cpu_cores_avg": round(cpu / wall, 2) if wall else None,
        "commit_before_mb": base["commit"],
        "peak_commit_mb": mem_self()["peak_commit"],
        "peak_ws_mb": mem_self()["peak_ws"],
        "sampled_peak_mb": round(sampler.peak),
        "out": str(res.path) if res else None,
        "mp4_mb": round(Path(res.path).stat().st_size / MB, 2) if res else None,
        "warning": getattr(res, "warning", None),
        "error": error,
    }
    emit(result)


def cmd_export(args) -> None:
    sizes = {"720p": ("1280x720", 10.0, 30), "1080p": ("1920x1080", 20.0, 30), "4k": ("3840x2160", 5.0, 30)}
    rows = []
    ranges = {"720p": (60.0, 90.0), "1080p": (60.0, 80.0), "4k": (60.0, 65.0)}  # the real project: a range of its 5 minutes
    for project in args.projects:
        for label in args.sizes:
            size, seconds, fps = sizes[label]
            print(f"export {project} {size} {seconds}s @ {fps} ...", flush=True)
            if project == "angular_momentum":
                lo, hi = ranges[label]
                spec = ["--start", str(lo), "--end", str(hi)]
            else:
                spec = ["--seconds", str(seconds)]
            ran = run_proc(me("export-one", "--project", project, "--size", size, *spec, "--fps", str(fps)), timeout=1500, limit_mb=args.cap)
            got = ran.results()
            row = got[0] if got else {"project": project, "size": size, "error": f"exit {ran.code}: {ran.tail(4)}", "timed_out": ran.timed_out}
            row["job_peak_mb"] = round(ran.peak_mb)
            if row.get("out") and args.verify:
                ver = verify_video(Path(row["out"]), row["expected_frames"], row["fps"])
                row["verify_audio_minus_video_s"] = ver.get("audio_minus_video_s")
                row["verify"] = ver
                row["decodes"] = ver.get("ok")
                Path(row["out"]).unlink(missing_ok=True)
            rows.append(row)
    cols = ["project", "size", "seconds_of_video", "frames", "wall_s", "ms_per_frame", "first_frame_ms", "p50_ms", "p95_ms", "max_ms", "cpu_s", "cpu_cores_avg", "peak_commit_mb", "peak_ws_mb", "mp4_mb", "decodes", "error"]
    table(rows, cols, "export matrix")
    save("export", rows)


def leak_one(args) -> None:
    """N consecutive exports in one process; memory, handles, threads and Python objects after each."""
    boot()
    from manim_studio.render.cairo_export import export_video
    from manim_studio.render.options import RenderOptions

    projects = [load_example(p) for p in args.project.split(",")]
    rows = []
    for i in range(args.n):
        project = with_canvas(projects[i % len(projects)], duration=args.seconds)
        out = WORK / "leak" / f"leak-{i % 2}.mp4"  # replaced each time, like a user re-exporting
        t0 = time.perf_counter()
        export_video(project, out, options=RenderOptions(width=args.width, height=args.height))
        wall = time.perf_counter() - t0
        gc.collect()
        m = mem_self()
        rows.append(
            {
                "i": i + 1,
                "wall_s": round(wall, 2),
                "commit_mb": m["commit"],
                "ws_mb": m["ws"],
                "peak_commit_mb": m["peak_commit"],
                "handles": handle_count(),
                "threads": threading.active_count(),
                "py_objects": len(gc.get_objects()),
            }
        )
        print(json.dumps(rows[-1]), flush=True)

    def slope(key: str, skip: int = 3) -> float:
        xs = [r["i"] for r in rows][skip:]
        ys = [r[key] for r in rows][skip:]
        if len(xs) < 2:
            return 0.0
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sum((x - mx) ** 2 for x in xs) or 1)

    emit(
        {
            "rows": rows,
            "slope_commit_mb_per_export": round(slope("commit_mb"), 2),
            "slope_ws_mb_per_export": round(slope("ws_mb"), 2),
            "slope_handles_per_export": round(slope("handles"), 2),
            "slope_py_objects_per_export": round(slope("py_objects"), 1),
            "first_commit_mb": rows[0]["commit_mb"],
            "last_commit_mb": rows[-1]["commit_mb"],
        }
    )


def cmd_leak(args) -> None:
    ran = run_proc(me("leak-one", "--n", str(args.n), "--project", args.project, "--seconds", str(args.seconds), "--width", str(args.width), "--height", str(args.height)), timeout=1500, limit_mb=args.cap)
    got = ran.results()
    if not got:
        print("no result:", ran.tail(10))
        return
    r = got[0]
    table(r["rows"], ["i", "wall_s", "commit_mb", "ws_mb", "peak_commit_mb", "handles", "threads", "py_objects"], f"{args.n} exports of {args.project} in one process")
    print({k: v for k, v in r.items() if k != "rows"})
    save("leak-" + args.project.replace(",", "+"), r)


# ---------------------------------------------------------------------------------------------------------
# verification of a finished video
# ---------------------------------------------------------------------------------------------------------


def verify_video(path: Path, expected_frames: int | None, fps: int | None, expect_audio_seconds: float | None = None) -> dict:
    import av
    import numpy as np

    out: dict = {"path": str(path), "bytes": path.stat().st_size if path.exists() else None}
    try:
        with av.open(str(path)) as container:
            vs = container.streams.video[0]
            out["codec"] = vs.codec_context.name
            out["size"] = f"{vs.width}x{vs.height}"
            out["pix_fmt"] = vs.pix_fmt
            out["stream_fps"] = float(vs.average_rate) if vs.average_rate else None
            out["container_s"] = round(container.duration / 1e6, 3) if container.duration else None
            count, pts_prev, monotonic = 0, None, True
            first = last = None
            for frame in container.decode(video=0):
                count += 1
                if pts_prev is not None and frame.pts is not None and frame.pts <= pts_prev:
                    monotonic = False
                pts_prev = frame.pts
                if first is None:
                    first = frame.to_ndarray(format="rgb24")
                last = frame
            out["decoded_frames"] = count
            out["pts_monotonic"] = monotonic
            if last is not None:
                last = last.to_ndarray(format="rgb24")
            out["first_mean"] = round(float(first.mean()), 2) if first is not None else None
            out["last_mean"] = round(float(last.mean()), 2) if last is not None else None
            out["first_all_black"] = bool(first is not None and first.max() <= 6)
            out["last_all_black"] = bool(last is not None and last.max() <= 6)
            out["first_distinct_px"] = int(len(np.unique(first.reshape(-1, 3), axis=0))) if first is not None else None
            if expected_frames is not None:
                out["expected_frames"] = expected_frames
                out["frame_count_ok"] = count == expected_frames
        with av.open(str(path)) as container:
            if container.streams.audio:
                a = container.streams.audio[0]
                samples = 0
                for frame in container.decode(audio=0):
                    samples += frame.samples
                out["audio_s"] = round(samples / a.rate, 3)
                out["audio_rate"] = a.rate
                video_s = (expected_frames / fps) if expected_frames and fps else out.get("container_s")
                out["video_s"] = round(video_s, 3) if video_s else None
                if video_s:
                    out["audio_minus_video_s"] = round(out["audio_s"] - video_s, 3)
        out["ok"] = bool(out.get("decoded_frames")) and out.get("frame_count_ok", True) and out.get("pts_monotonic", True)
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {short(exc)}"
    return out


def cmd_verify(args) -> None:
    boot()
    expected = fps = None
    if args.project:
        project = load_example(args.project)
        fps = args.fps or project.canvas.fps
        expected = round((args.seconds or project.canvas.duration) * fps)
    res = verify_video(Path(args.file), args.frames or expected, fps)
    print(json.dumps(res, indent=1))


# ---------------------------------------------------------------------------------------------------------
# 3b. paths, locks, cancel
# ---------------------------------------------------------------------------------------------------------


def holder(args) -> None:
    """Hold ``path`` open (no sharing for rename/delete) until told to stop: stdin closes or time runs out."""
    mode = args.mode
    handle = None
    if mode == "python":
        handle = open(args.path, "ab" if Path(args.path).exists() else "wb")
    else:  # deny all sharing
        _k32.CreateFileW.restype = wt.HANDLE
        _k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
        handle = _k32.CreateFileW(args.path, 0x80000000 | 0x40000000, 0, None, 4, 0x80, None)  # GENERIC_READ|WRITE, no share, OPEN_ALWAYS
        if handle in (None, 0, 2**64 - 1):
            print("holder: cannot open", ctypes.get_last_error(), flush=True)
    print("HELD", flush=True)
    deadline = time.time() + args.seconds
    while time.time() < deadline:
        time.sleep(0.2)


def start_holder(path: Path, mode: str = "python", seconds: float = 60.0) -> subprocess.Popen:
    p = subprocess.Popen(me("holder", "--path", str(path), "--mode", mode, "--seconds", str(seconds)), stdout=subprocess.PIPE, text=True, cwd=str(ROOT))
    assert p.stdout.readline().strip() == "HELD"
    return p


def paths_one(args) -> None:
    """In-process export_video to many outputs: what comes back and what is left on disk."""
    boot()
    from manim_studio.render.cairo_export import export_video, partial_path
    from manim_studio.render.options import RenderOptions

    project = with_canvas(load_example("euler"), duration=1.0)
    from manim_studio.core.model.schema import Project

    project_subs = Project.model_validate({**json.loads(project.model_dump_json(by_alias=True)), "subtitles": [{"id": "s1", "start": 0.0, "end": 0.8, "text": "hello"}]})
    options = RenderOptions(width=320, height=180)
    base = WORK / "paths"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    results = []

    def attempt(name: str, out: Path, proj=None, opts=None, **kw) -> Path | None:
        t0 = time.perf_counter()
        rec: dict = {"case": name, "out": str(out)[:90]}
        try:
            res = export_video(proj or project, out, options=opts or options, **kw)
            rec.update(ok=True, path=str(res.path)[-60:], warning=res.warning, bytes=Path(res.path).stat().st_size)
        except BaseException as exc:  # noqa: BLE001
            rec.update(ok=False, exc=type(exc).__name__, msg=short(exc, 200), at=where(exc))
        rec["seconds"] = round(time.perf_counter() - t0, 2)
        leftovers = sorted(p.name for p in out.parent.glob("*") if ".partial" in p.name) if out.parent.exists() else []
        rec["partials_left"] = leftovers
        results.append(rec)
        print(json.dumps(rec, default=str), flush=True)

    attempt("plain", base / "plain.mp4")
    attempt("unicode_dir", base / "João Ünï 日本語 😀" / "vídeo.mp4")
    attempt("trailing_space_dot_dir", base / "dir. " / "x.mp4")
    attempt("repo_dir_with_non_ascii", ROOT / ".cache" / "stress-out" / "Programação" / "x.mp4")
    attempt("is_a_directory", base)
    attempt("parent_is_a_file", base / "plain.mp4" / "x.mp4")
    attempt("no_extension", base / "noext")
    attempt("ext_json", base / "out.json")
    attempt("ext_webm", base / "out.webm")
    attempt("ext_mkv", base / "out.mkv")
    attempt("ext_mov", base / "out.mov")
    attempt("ext_avi", base / "out.avi")
    attempt("ext_gif", base / "out.gif")
    attempt("device_name_NUL", base / "NUL.mp4")
    attempt("invalid_chars", base / "a<b>c|d?.mp4")
    attempt("name_300_chars", base / ("n" * 296 + ".mp4"))
    deep = base
    for i in range(12):
        deep = deep / ("d" * 24)
    attempt("path_over_300_chars_dirs", deep / "x.mp4")
    attempt("nonexistent_drive", Path("Q:/nope/x.mp4") if not Path("Q:/").exists() else Path("Z:/nope/x.mp4"))
    attempt("unc_nonexistent_host", Path(r"\\127.0.0.1\nosuchshare\x.mp4"))
    is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    if not is_admin:
        attempt("write_protected_dir_Windows", Path(r"C:\Windows\System32\config\stress.mp4"))
    else:
        results.append({"case": "write_protected_dir_Windows", "skipped": "elevated: would write there"})
    # an existing read-only target
    ro = base / "readonly.mp4"
    ro.write_bytes(b"old")
    os.chmod(ro, 0o444)
    attempt("existing_target_read_only", ro)
    with contextlib.suppress(OSError):
        os.chmod(ro, 0o666)
    # target locked by another process (python open) and (no sharing)
    for mode in ("python", "deny_all"):
        target = base / f"locked-{mode}.mp4"
        target.write_bytes(b"old video")
        h = start_holder(target, mode)
        attempt(f"existing_target_open_in_other_process_{mode}", target)
        h.kill()
        h.wait()
    # a stale partial left by a crash
    stale = partial_path(base / "stale.mp4")
    stale.write_bytes(b"junk from a crash")
    attempt("stale_partial_present", base / "stale.mp4")
    # the partial itself held by another process
    held = partial_path(base / "held-partial.mp4")
    held.write_bytes(b"x")
    h = start_holder(held, "deny_all")
    attempt("partial_path_held_by_other_process", base / "held-partial.mp4")
    h.kill()
    h.wait()
    # the srt beside the video held by another process
    srt = base / "withsubs.srt"
    srt.write_text("old", encoding="utf-8")
    h = start_holder(srt, "deny_all")
    attempt("srt_beside_video_locked", base / "withsubs.mp4", proj=project_subs)
    h.kill()
    h.wait()
    # progress callback raising: the partial must go
    def bad(done, total):
        if done == 5:
            raise KeyboardInterrupt

    attempt("progress_raises_KeyboardInterrupt", base / "kbi.mp4", progress=bad)

    def bad2(done, total):
        if done == 5:
            raise RuntimeError("cancelled by the UI")

    attempt("progress_raises_RuntimeError", base / "rt.mp4", progress=bad2)
    emit({"rows": results})


def concurrent_same_output() -> dict:
    out = WORK / "same-output" / "x.mp4"
    shutil.rmtree(out.parent, ignore_errors=True)
    out.parent.mkdir(parents=True)
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "manim_studio", "render", str(EXAMPLES / "euler.json"), str(out), "--size", "640x360", "--end", "2", "--cache-dir", str(ROOT / ".cache" / "manim")],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        for _ in range(2)
    ]
    outs = [p.communicate(timeout=300)[0] for p in procs]
    res = {"exit_codes": [p.returncode for p in procs], "tails": [short(o.strip().splitlines()[-1] if o.strip() else "") for o in outs], "files": sorted(p.name for p in out.parent.glob("*"))}
    if out.exists():
        res["verify"] = verify_video(out, None, None)
    return res


def cmd_paths(args) -> None:
    ran = run_proc(me("paths-one"), timeout=600, limit_mb=3072)
    got = ran.results()
    if not got:
        print("no result:", ran.tail(15))
        return
    rows = got[0]["rows"]
    table(
        [{"case": r["case"], "ok": r.get("ok", r.get("skipped")), "s": r.get("seconds"), "result": r.get("path") or f"{r.get('exc')}: {r.get('msg', '')}"[:110], "warn": short(r.get("warning") or "", 70), "partials_left": r.get("partials_left")} for r in rows],
        ["case", "ok", "s", "result", "warn", "partials_left"],
        "export_video to awkward outputs (in process)",
    )
    # the CLI's view of the same awkward outputs
    cli_rows = []
    for name, out in {
        "unicode_dir": WORK / "cli" / "João Ünï 日本語 😀" / "v.mp4",
        "nonexistent_drive": Path("Q:/nope/x.mp4"),
        "no_extension": WORK / "cli" / "noext",
        "ext_json": WORK / "cli" / "x.json",
        "output_is_the_project": WORK / "cli" / "copy.json",
        "is_a_directory": WORK / "cli",
        "name_300_chars": WORK / "cli" / ("n" * 296 + ".mp4"),
        "write_protected": Path(r"C:\Windows\System32\config\stress.mp4"),
    }.items():
        (WORK / "cli").mkdir(parents=True, exist_ok=True)
        source = EXAMPLES / "euler.json"
        if name == "output_is_the_project":
            shutil.copy(source, out)
            source = out
        if name == "write_protected" and ctypes.windll.shell32.IsUserAnAdmin():
            continue
        r = run_proc([sys.executable, "-m", "manim_studio", "render", str(source), str(out), "--size", "320x180", "--end", "0.5", "--cache-dir", str(ROOT / ".cache" / "manim")], timeout=120, limit_mb=2048)
        text = r.text.strip()
        row = {"case": name, "exit": r.code, "traceback": "Traceback" in text, "last_line": short(text.splitlines()[-1] if text else "", 150)}
        if name == "output_is_the_project":
            row["project_still_json"] = out.read_bytes()[:1] == b"{"
        cli_rows.append(row)
    table(cli_rows, ["case", "exit", "traceback", "last_line", "project_still_json"], "the same through the CLI")
    print("\nconcurrent exports to the same output path:", json.dumps(concurrent_same_output(), indent=1))
    save("paths", {"in_process": rows, "cli": cli_rows})


def cmd_cancel(args) -> None:
    """Kill an export while it runs; what is left on disk and in the process table."""
    from manim_studio import lifeline

    folder = WORK / "cancel"
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    findings = []

    def spawn(project: str, out: Path, size: str, extra: list[str], env_extra: dict | None = None):
        argv = [sys.executable, "-u", "-m", "manim_studio", "render", project, str(out), "--size", size, "--progress", "json", "--cache-dir", str(args.cache)] + extra
        return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT), env={**os.environ, **(env_extra or {})})

    def wait_frames(proc, n: int, timeout: float = 240) -> int:
        t0 = time.time()
        last = 0
        while time.time() - t0 < timeout:
            line = proc.stdout.readline()
            if not line:
                break
            if line.startswith("{") and '"frame"' in line:
                last = json.loads(line)["frame"]
                if last >= n:
                    return last
        return last

    def alive(pids):
        return [p for p in pids if lifeline.process_alive(p)]

    # A: kill the whole tree like the editor's Cancel does
    out = folder / "a.mp4"
    proc = spawn(str(EXAMPLES / "euler.json"), out, "1920x1080", [])
    frames = wait_frames(proc, 15)
    tree = lifeline.descendants(proc.pid)
    t0 = time.time()
    lifeline.kill_tree(proc.pid)
    gone = lifeline.wait_gone([proc.pid, *tree], timeout=5)
    time.sleep(1.0)
    findings.append({"scenario": "A kill_tree of the CLI during frames", "frames_done": frames, "tree": tree, "all_gone": gone, "survivors": alive([proc.pid, *tree]), "partials": sorted(p.name for p in folder.glob("*partial*")), "final_exists": out.exists(), "kill_s": round(time.time() - t0, 2)})
    for p in folder.glob("*partial*"):
        with contextlib.suppress(OSError):
            p.unlink()

    # B: the editor dies (a stand-in process named as MANIM_STUDIO_EDITOR_PID): the lifeline thread must end the CLI
    out = folder / "b.mp4"
    editor = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    proc = spawn(str(EXAMPLES / "euler.json"), out, "1920x1080", [], {"MANIM_STUDIO_EDITOR_PID": str(editor.pid)})
    frames = wait_frames(proc, 15)
    tree = lifeline.descendants(proc.pid)
    t0 = time.time()
    kill_tree_pid = editor.pid
    editor.kill()
    editor.wait()
    ended = lifeline.wait_gone([proc.pid, *tree], timeout=10)
    findings.append({"scenario": "B editor killed; CLI has MANIM_STUDIO_EDITOR_PID", "frames_done": frames, "tree": tree, "cli_ended_by_itself": ended, "seconds_to_end": round(time.time() - t0, 2), "survivors": alive([proc.pid, *tree]), "partials": sorted(p.name for p in folder.glob("*partial*")), "final_exists": out.exists()})
    for pid in alive([proc.pid, *tree]):
        kill_tree(pid)
    for p in folder.glob("*partial*"):
        with contextlib.suppress(OSError):
            p.unlink()
    del kill_tree_pid

    # C: the CLI killed (root only) while a code layer renders in a child: do the children go away on their own?
    cache = ROOT / ".cache" / f"stress-cancel-{os.getpid()}"
    out = folder / "c.mp4"
    proc = spawn(str(EXAMPLES / "showcase.json"), out, "1280x720", ["--trust-code"], {})
    proc_args = None  # noqa: F841
    t0 = time.time()
    seen_tree: list[int] = []
    while time.time() - t0 < 60:
        seen_tree = lifeline.descendants(proc.pid)
        children = [p for p in seen_tree if p != proc.pid]
        if len(seen_tree) >= 2 and proc.poll() is None:
            time.sleep(1.0)
            seen_tree = lifeline.descendants(proc.pid)
            break
        time.sleep(0.2)
    names = {}
    try:
        table_ = lifeline.process_table()
        names = {p: table_.get(p) for p in seen_tree}
    except Exception:  # noqa: BLE001
        pass
    # kill ONLY the CLI's own interpreter and its launcher (not the helpers below it)
    kill_set = seen_tree[:1] if seen_tree else []
    subprocess.run(["taskkill", "/F", "/PID", str(proc.pid)], capture_output=True)  # the launcher
    interpreters = [p for p in seen_tree if lifeline.process_table().get(p) == proc.pid]
    for pid in interpreters:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    time.sleep(6.0)
    orphans = alive([p for p in seen_tree if p not in interpreters])
    findings.append({"scenario": "C CLI interpreter killed (not its tree) while --trust-code renders a code layer", "tree_before_kill": seen_tree, "parents": names, "orphans_after_6s": orphans, "partials": sorted(p.name for p in folder.glob("*partial*"))})
    for pid in orphans:
        kill_tree(pid)
    kill_tree(proc.pid)
    shutil.rmtree(cache, ignore_errors=True)

    # D: stray processes of ours?
    time.sleep(1.0)
    for f in findings:
        print(json.dumps(f, default=str))
    save("cancel", findings)


# ---------------------------------------------------------------------------------------------------------
# 4. determinism
# ---------------------------------------------------------------------------------------------------------


def synthetic_sim_project() -> dict:
    """A simulation, a traced path, a connector, a counting number, a path follower and a morph."""
    d = base_dict(w=640, h=360, fps=30, duration=6.0)
    d["layers"] = [
        {"id": "pend", "spec": {"type": "SwingingPendulum", "params": {"length": 2.0, "angle": 70.0, "damping": 0.05, "bob": 0.2}}, "base": {"position": [-3.0, 3.0]}},
        {"id": "trail", "spec": {"type": "TracedPath", "params": {"target": "pend"}, "style": {"stroke": "#22d3ee", "stroke_width": 2}}},
        {"id": "ring", "spec": {"type": "Circle", "params": {"radius": 1.2}, "style": {"stroke": "#ffffff"}}, "base": {"position": [2.0, -1.0]}},
        {
            "id": "runner",
            "spec": {"type": "Dot", "params": {"radius": 0.15}, "style": {"fill": "#facc15", "fill_opacity": 1.0}},
            "clips": [{"id": "mv", "kind": "MoveAlongPath", "start": 0.5, "duration": 4.0, "params": {"path": "ring", "rotate": "along"}}],
        },
        {"id": "wire", "spec": {"type": "Connector", "params": {"source": "runner", "target": "ring"}, "style": {"stroke": "#f97316"}}},
        {
            "id": "count",
            "spec": {"type": "DecimalNumber", "params": {"number": 0.0, "num_decimal_places": 1, "font_size": 40}},
            "base": {"position": [-4.0, -2.5]},
            "clips": [{"id": "cnt", "kind": "ChangeDecimalToValue", "start": 0.5, "duration": 4.0, "params": {"target_number": 25.0}}],
        },
        {
            "id": "sq",
            "spec": {"type": "Square", "params": {"side_length": 1.2}, "style": {"fill": "#6366f1", "fill_opacity": 0.7}},
            "base": {"position": [-2.0, -1.0]},
            "tracks": {"rotation": [{"t": 0.0, "value": 0.0}, {"t": 6.0, "value": 270.0}]},
            "clips": [{"id": "tr", "kind": "Transform", "start": 2.0, "duration": 2.0, "to_layer": "st", "params": {"match": "smart"}}],
        },
        {"id": "st", "spec": {"type": "Star", "params": {"n": 5, "outer_radius": 1.0}, "style": {"fill": "#f43f5e", "fill_opacity": 0.8}}, "base": {"position": [-2.0, -1.0]}},
        {"id": "eq", "spec": {"type": "MathTex", "params": {"text": r"e^{i\pi}+1=0", "font_size": 48}}, "base": {"position": [3.0, 2.5]}, "clips": [{"id": "wr", "kind": "Write", "start": 0.3, "duration": 1.5}]},
    ]
    d["subtitles"] = [{"id": "q1", "start": 1.0, "end": 3.0, "text": "A traced pendulum and friends"}]
    return d


def det_target(name: str):
    from manim_studio.core.model.schema import Project

    if name == "sim":
        return Project.model_validate(synthetic_sim_project())
    return load_example(name)


def frame_hash(img) -> str:
    return hashlib.md5(img.tobytes()).hexdigest()


def det_one(args) -> None:
    """Hashes of every sampled frame: sequential walk, a fresh evaluator in random order, in reverse, and
    the walked evaluator again in random order; plus the hash list for cross-process comparison."""
    boot()
    import numpy as np

    from manim_studio.core.engine.evaluator import Evaluator
    from manim_studio.render.cairo_export import make_camera, render_frame
    from manim_studio.render.options import RenderOptions, apply_options

    project = det_target(args.project)
    if args.size:
        w, h = (int(x) for x in args.size.split("x"))
        project = apply_options(project, RenderOptions(width=w, height=h))
    if args.trust:
        from manim_studio import cli
        from manim_studio.core.code import python_object

        python_object.trust_everything()
        cli._render_code_layers(project, True, "json")
    canvas = project.canvas
    total = round(canvas.duration * canvas.fps)
    stride = max(1, args.stride)
    wanted = list(range(0, total, stride))
    camera = make_camera(canvas, project.camera)

    def render(ev: Evaluator, i: int):
        t = i / canvas.fps
        layers = [mob for _, mob in ev.frame_layers(t)]
        return render_frame(camera, layers, ev.overlay(t))

    # the sequential walk shows every frame (state-carrying layers need the history), keeping the sampled ones
    ev = Evaluator(project)
    seq: dict[int, str] = {}
    keep: dict[int, np.ndarray] = {}
    t0 = time.perf_counter()
    for i in range(total):
        img = render(ev, i)
        if i % stride == 0:
            seq[i] = frame_hash(img)
            if len(keep) < 40:
                keep[i] = img
    walk_s = time.perf_counter() - t0
    rng = random.Random(args.seed)
    order = wanted[:]
    rng.shuffle(order)
    modes = {}

    def check(label: str, evaluator: Evaluator, sequence: list[int]) -> None:
        bad = []
        diffs = {}
        for i in sequence:
            img = render(evaluator, i)
            if frame_hash(img) != seq[i]:
                bad.append(i)
                if i in keep and len(diffs) < 3:
                    delta = np.abs(img.astype(int) - keep[i].astype(int))
                    diffs[i] = {"px": int((delta.sum(axis=2) > 0).sum()), "max": int(delta.max())}
        modes[label] = {"frames": len(sequence), "mismatch": len(bad), "first_bad": sorted(bad)[:8], "sample_diffs": diffs}

    check("fresh_evaluator_random_order", Evaluator(project), order)
    check("fresh_evaluator_reverse", Evaluator(project), sorted(wanted, reverse=True))
    check("walked_evaluator_random_order", ev, order[: max(50, len(order) // 3)])
    # jump straight to a late frame on a fresh evaluator, then back to an early one
    rev = Evaluator(project)
    jump = [wanted[-1], wanted[0], wanted[len(wanted) // 2], wanted[1] if len(wanted) > 1 else wanted[0], wanted[-1]]
    check("fresh_evaluator_jump_end_start_mid", rev, jump)
    # the same time asked repeatedly on one evaluator
    check("same_frame_repeated", Evaluator(project), [wanted[len(wanted) // 2]] * 5)
    emit({"project": args.project, "frames_total": total, "sampled": len(wanted), "walk_s": round(walk_s, 1), "modes": modes, "hashes": seq if args.dump else None, "digest": hashlib.md5(json.dumps(sorted(seq.items())).encode()).hexdigest()})


def decoded_equal(a: Path, b: Path) -> dict:
    import av
    import numpy as np

    with av.open(str(a)) as ca, av.open(str(b)) as cb:
        fa, fb = ca.decode(video=0), cb.decode(video=0)
        n, bad, first_bad = 0, 0, None
        for x, y in zip(fa, fb):
            n += 1
            if not np.array_equal(x.to_ndarray(format="rgb24"), y.to_ndarray(format="rgb24")):
                bad += 1
                first_bad = n - 1 if first_bad is None else first_bad
        left = sum(1 for _ in fa) + sum(1 for _ in fb)
    return {"frames_compared": n, "frames_different": bad, "first_different": first_bad, "extra_frames_in_one": left}


def cmd_determinism(args) -> None:
    rows = []
    plan = [("euler", None, 1, False), ("graphs", None, 1, False), ("sim", None, 1, False), ("showcase", None, 1, True), ("explainer", "640x360", 6, False), ("angular_momentum", "640x360", 25, False)]
    plan = [p for p in plan if not args.projects or p[0] in args.projects]
    for name, size, stride, trust in plan:
        argv = ["det-one", "--project", name, "--stride", str(stride), "--seed", "5"] + (["--size", size] if size else []) + (["--trust"] if trust else [])
        print(f"determinism {name} ...", flush=True)
        a = run_proc(me(*argv), timeout=1500, limit_mb=4096)
        b = run_proc(me(*argv), timeout=1500, limit_mb=4096)
        ra, rb = (a.results() or [None])[0], (b.results() or [None])[0]
        if not ra or not rb:
            rows.append({"project": name, "error": (a.tail(6) if not ra else b.tail(6))})
            continue
        row = {"project": name, "sampled": ra["sampled"], "walk_s": ra["walk_s"], "cross_process_digest_equal": ra["digest"] == rb["digest"]}
        for label, mode in ra["modes"].items():
            row[label] = f"{mode['mismatch']}/{mode['frames']}"
        row["details"] = {k: v for k, v in ra["modes"].items() if v["mismatch"]}
        rows.append(row)
        print(json.dumps(row, default=str), flush=True)
    cols = ["project", "sampled", "walk_s", "cross_process_digest_equal", "fresh_evaluator_random_order", "fresh_evaluator_reverse", "walked_evaluator_random_order", "fresh_evaluator_jump_end_start_mid", "same_frame_repeated"]
    table(rows, cols, "determinism (mismatching frames / frames compared)")
    for r in rows:
        if r.get("details"):
            print(f"mismatch details {r['project']}: {json.dumps(r['details'])}")
    # two exports of the same project, decoded and compared
    exp = []
    for name, trust in (("euler", False), ("graphs", False), ("showcase", True)):
        paths = []
        for k in range(2):
            out = WORK / "det" / f"{name}-{k}.mp4"
            r = run_proc(me("export-one", "--project", name, "--size", "640x360", "--out", str(out)) + (["--trust"] if trust else []), timeout=600, limit_mb=3072)
            paths.append(out)
        if all(p.exists() for p in paths):
            cmp = decoded_equal(*paths)
            same_bytes = paths[0].read_bytes() == paths[1].read_bytes()
            exp.append({"project": name, **cmp, "files_byte_identical": same_bytes})
        else:
            exp.append({"project": name, "error": "export failed"})
    table(exp, ["project", "frames_compared", "frames_different", "first_different", "extra_frames_in_one", "files_byte_identical", "error"], "two exports of the same project (decoded frames compared bit for bit)")
    save("determinism", {"evaluators": rows, "exports": exp})


# ---------------------------------------------------------------------------------------------------------
# 5. memory per frame
# ---------------------------------------------------------------------------------------------------------


def memory_one(args) -> None:
    """The export's loop, phase by phase, with the committed memory peak of each phase."""
    boot()
    import av
    import numpy as np

    from manim_studio.core.engine.evaluator import Evaluator
    from manim_studio.render.cairo_export import make_camera, render_frame
    from manim_studio.render.options import RenderOptions, apply_options

    w, h = (int(x) for x in args.size.split("x"))
    project = apply_options(load_example(args.project), RenderOptions(width=w, height=h))
    canvas = project.canvas
    gc.collect()
    base = commit_now()
    sampler = Sampler(0.003).__enter__()
    sampler.phase("make_camera")
    camera = make_camera(canvas, project.camera)
    after_camera = commit_now()
    evaluator = Evaluator(project)
    out = WORK / "memory" / f"mem-{args.size}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    result: dict = {"size": args.size, "frames": args.frames, "mb_per_rgba": round(w * h * 4 / MB, 1), "mb_per_rgb": round(w * h * 3 / MB, 1), "mb_per_yuv420": round(w * h * 1.5 / MB, 1), "camera_mb": round(after_camera - base)}
    try:
        with av.open(str(out), mode="w") as container:
            stream = container.add_stream("libx264", rate=canvas.fps)
            stream.width, stream.height, stream.pix_fmt = w, h, "yuv420p"
            stream.options = {"crf": "18"}
            t_phase = {"evaluate": 0.0, "render_frame": 0.0, "rgb_copy": 0.0, "from_ndarray": 0.0, "encode": 0.0}
            for i in range(args.frames):
                t = args.start + i / canvas.fps
                a = time.perf_counter()
                sampler.phase("evaluate")
                layers = [mob for _, mob in evaluator.frame_layers(t)]
                over = evaluator.overlay(t)
                b = time.perf_counter()
                sampler.phase("render_frame")
                rgba = render_frame(camera, layers, over)
                c = time.perf_counter()
                sampler.phase("rgb_copy")
                rgb = rgba[:, :, :3].copy()
                d = time.perf_counter()
                sampler.phase("from_ndarray")
                frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
                e = time.perf_counter()
                sampler.phase("encode")
                container.mux(stream.encode(frame))
                f = time.perf_counter()
                for k, (x, y) in {"evaluate": (a, b), "render_frame": (b, c), "rgb_copy": (c, d), "from_ndarray": (d, e), "encode": (e, f)}.items():
                    t_phase[k] += y - x
                if i == 4:
                    result["commit_after_5_frames_mb"] = round(commit_now())
            sampler.phase("flush")
            container.mux(stream.encode())
        result["ms_per_frame_by_phase"] = {k: ms(v / args.frames) for k, v in t_phase.items()}
    except BaseException as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {short(exc)} @ {where(exc)}"
    sampler.__exit__()
    result["baseline_commit_mb"] = round(base)
    result["peak_by_phase_mb"] = {k: round(v) for k, v in sampler.by_phase.items()}
    result["sampled_peak_mb"] = round(sampler.peak)
    result["mem"] = mem_self()
    emit(result)


def cmd_memory(args) -> None:
    sizes = {"1080": ("1920x1080", 90), "4k": ("3840x2160", 60), "8k": ("7680x4320", 40)}
    rows = []
    for label in args.sizes:
        size, frames = sizes[label]
        print(f"memory {label} ({size}, {frames} frames) ...", flush=True)
        start = 60.0 if args.project == "angular_momentum" else 0.0
        ran = run_proc(me("memory-one", "--size", size, "--frames", str(frames), "--project", args.project, "--start", str(start)), timeout=1800, limit_mb=args.cap)
        got = ran.results()
        row = got[0] if got else {"size": size, "error": f"exit {ran.code} timed_out={ran.timed_out}: {ran.tail(4)}"}
        row["job_peak_mb"] = round(ran.peak_mb)
        # and the real export_video for the same frame count
        seconds = frames / 30
        window = ["--start", str(start), "--end", str(start + seconds)] if start else ["--seconds", str(seconds)]
        real = run_proc(me("export-one", "--project", args.project, "--size", size, *window, "--fps", "30"), timeout=1800, limit_mb=args.cap)
        r = (real.results() or [None])[0]
        row["export_video_peak_commit_mb"] = r["peak_commit_mb"] if r else None
        row["export_video_peak_ws_mb"] = r["peak_ws_mb"] if r else None
        row["export_video_ms_per_frame"] = r["ms_per_frame"] if r else None
        row["export_video_error"] = (r or {}).get("error") or ("" if r else f"exit {real.code}: {real.tail(3)}")
        rows.append(row)
        print(json.dumps(row, default=str), flush=True)
    table(rows, ["size", "mb_per_rgba", "baseline_commit_mb", "camera_mb", "commit_after_5_frames_mb", "sampled_peak_mb", "job_peak_mb", "export_video_peak_commit_mb", "export_video_peak_ws_mb", "export_video_ms_per_frame", "error", "export_video_error"], "memory per export")
    for r in rows:
        print(r["size"], "peak by phase (MB):", r.get("peak_by_phase_mb"), "| ms/frame by phase:", r.get("ms_per_frame_by_phase"))
    save("memory", rows)


# ---------------------------------------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("scale")
    s.add_argument("--sizes", type=int, nargs="+", default=[100, 300, 1000, 2000, 5000])
    s.add_argument("--hours", type=float, default=1.0)
    s.add_argument("--timeout", type=float, default=1500)
    s.add_argument("--cap", type=int, default=8192, help="memory cap per child, MB")
    s = sub.add_parser("scale-one")
    s.add_argument("--n", type=int, required=True)
    s.add_argument("--hours", type=float, default=1.0)
    s.add_argument("--spread", action="store_true")
    s.add_argument("--camera3d", action="store_true")
    s = sub.add_parser("scale-edits")
    s.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 5000])
    s.add_argument("--cap", type=int, default=8192)
    s = sub.add_parser("edits-one")
    s.add_argument("--n", type=int, required=True)
    s = sub.add_parser("pathological")
    s.add_argument("--only", nargs="*")
    s.add_argument("--list", action="store_true")
    s = sub.add_parser("cases")
    s.add_argument("--names", required=True)
    sub.add_parser("corrupt")
    sub.add_parser("security")
    s = sub.add_parser("export")
    s.add_argument("--projects", nargs="+", default=["euler", "graphs"])
    s.add_argument("--sizes", nargs="+", default=["720p", "1080p", "4k"], choices=["720p", "1080p", "4k"])
    s.add_argument("--cap", type=int, default=8192)
    s.add_argument("--verify", action="store_true", default=True)
    s = sub.add_parser("export-one")
    s.add_argument("--project", required=True)
    s.add_argument("--size")
    s.add_argument("--seconds", type=float)
    s.add_argument("--start", type=float)
    s.add_argument("--end", type=float)
    s.add_argument("--fps", type=int)
    s.add_argument("--crf", type=int, default=18)
    s.add_argument("--out")
    s.add_argument("--trust", action="store_true")
    s = sub.add_parser("leak")
    s.add_argument("--n", type=int, default=20)
    s.add_argument("--project", default="euler")
    s.add_argument("--seconds", type=float, default=2.0)
    s.add_argument("--width", type=int, default=1280)
    s.add_argument("--height", type=int, default=720)
    s.add_argument("--cap", type=int, default=6144)
    s = sub.add_parser("leak-one")
    s.add_argument("--n", type=int, default=20)
    s.add_argument("--project", default="euler")
    s.add_argument("--seconds", type=float, default=2.0)
    s.add_argument("--width", type=int, default=1280)
    s.add_argument("--height", type=int, default=720)
    sub.add_parser("paths")
    sub.add_parser("paths-one")
    s = sub.add_parser("holder")
    s.add_argument("--path", required=True)
    s.add_argument("--mode", default="python")
    s.add_argument("--seconds", type=float, default=60)
    s = sub.add_parser("cancel")
    s.add_argument("--cache", type=Path, default=ROOT / ".cache" / "manim")
    s = sub.add_parser("verify")
    s.add_argument("file")
    s.add_argument("--project")
    s.add_argument("--seconds", type=float)
    s.add_argument("--fps", type=int)
    s.add_argument("--frames", type=int)
    s = sub.add_parser("determinism")
    s.add_argument("--projects", nargs="*")
    s = sub.add_parser("det-one")
    s.add_argument("--project", required=True)
    s.add_argument("--size")
    s.add_argument("--stride", type=int, default=1)
    s.add_argument("--seed", type=int, default=5)
    s.add_argument("--trust", action="store_true")
    s.add_argument("--dump", action="store_true")
    s = sub.add_parser("memory")
    s.add_argument("--sizes", nargs="+", default=["1080", "4k", "8k"], choices=["1080", "4k", "8k"])
    s.add_argument("--project", default="euler")
    s.add_argument("--cap", type=int, default=12288)
    s = sub.add_parser("memory-one")
    s.add_argument("--size", required=True)
    s.add_argument("--frames", type=int, default=60)
    s.add_argument("--project", default="euler")
    s.add_argument("--start", type=float, default=0.0)
    s = sub.add_parser("real")
    s.add_argument("--cap", type=int, default=6144)
    sub.add_parser("real-one")
    sub.add_parser("all")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    WORK.mkdir(parents=True, exist_ok=True)
    isolate_env()
    cmd = args.command
    if cmd not in ("holder", "cases") and not cmd.endswith("-one"):
        import manim_studio

        print(f"[manim_studio from {manim_studio.__file__}]  work folder {WORK}", flush=True)
    table_of = {
        "scale": cmd_scale,
        "scale-one": scale_one,
        "scale-edits": cmd_scale_edits,
        "real": cmd_real,
        "real-one": real_one,
        "edits-one": edits_one,
        "pathological": cmd_pathological,
        "cases": lambda a: cases_child(a.names.split(",")),
        "corrupt": cmd_corrupt,
        "security": cmd_security,
        "export": cmd_export,
        "export-one": export_one,
        "leak": cmd_leak,
        "leak-one": leak_one,
        "paths": cmd_paths,
        "paths-one": paths_one,
        "holder": holder,
        "cancel": cmd_cancel,
        "verify": cmd_verify,
        "determinism": cmd_determinism,
        "det-one": det_one,
        "memory": cmd_memory,
        "memory-one": memory_one,
    }
    if cmd == "all":
        for name in ("scale", "scale-edits", "pathological", "corrupt", "security", "export", "leak", "paths", "cancel", "determinism", "memory"):
            sub_args = build_parser().parse_args([name])
            print(f"\n######## {name}", flush=True)
            table_of[name](sub_args)
        return 0
    table_of[cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
