"""Random-input ("monkey") stress harness for the real editor window.

Drives a real ``MainWindow`` (offscreen) with random input - menu actions, page switches, the Add menu,
mouse gestures on the canvas, the timeline and the layer list, key presses and shortcuts, undo/redo bursts,
junk typed into property fields, playback, the playhead, context menus, opening projects, the New project
dialog, exports started and cancelled - and watches for:

* exceptions that reach ``sys.excepthook`` (Qt slots), ``threading.excepthook``, ``sys.unraisablehook``,
  or that a direct call raises; errors the editor logs; Qt warnings and criticals (deduplicated);
* hangs: a step that takes more than 20 s dumps every thread's stack (``faulthandler``), more than
  ``HARD_LIMIT`` ends the run;
* data loss: the project must survive a JSON round trip (what Save writes must open again), a save must
  read back equal, and undo then redo must give the same project back;
* memory and CPU of the editor and every helper process below it (committed and working set, Windows API),
  and runaway CPU when the editor is left idle;
* at the end: closing the window must end every helper process.

Modal dialogs, message boxes and popup menus are answered by a timer that picks a random button or item
(or rejects); file dialogs are replaced by fakes that answer with files in the run's own folder. Nothing is
written outside ``.cache/stress-monkey/<run>``: settings, logs, recovery copies, the library, presets,
voices, plugins and trusted code all point there, exports to any other place are redirected there, and no
folder is ever opened on the desktop.

Phases (each in its own process; run them one by one, they print a summary and write ``results.json``):

    python benchmarks/stress_monkey.py --phase euler --seed 1 --steps 3000
    python benchmarks/stress_monkey.py --phase showcase --seed 2 --steps 3000
    python benchmarks/stress_monkey.py --phase angular --seed 5 --steps 500   # examples/angular_momentum
    python benchmarks/stress_monkey.py --phase soak --seed 3 --minutes 10      # >= 300 generated layers
    python benchmarks/stress_monkey.py --phase churn --seed 4 --iterations 200 --windows 50

Replay a failing run with the same ``--seed`` (``--stop-at N`` stops after step N; the editor's helper
processes answer asynchronously, so a replay can drift). The build worker and the frame renderer are the real helper processes; code layers
draw placeholders (``MANIM_STUDIO_CODE=0``, opening a project never trusts its code, and the code of
``examples/angular_momentum`` is never trusted) unless ``--code``. ``--fake-helpers`` builds in-process like
the tests. Run against a frozen tree with ``PYTHONPATH=<snapshot>/src``.
"""

from __future__ import annotations

import argparse
import collections
import ctypes
import faulthandler
import gc
import json
import math
import os
import random
import re
import shutil
import struct
import sys
import threading
import time
import traceback
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED_CACHE = ROOT / ".cache" / "manim"
BASE = ROOT / ".cache" / "stress-monkey"
HANG_SECONDS = 20  # a step longer than this dumps every thread's stack
HARD_LIMIT = 180  # a step longer than this ends the run (results are written first)
SLOW_STEP = 5.0  # a step longer than this is reported as a UI freeze

# -- junk -------------------------------------------------------------------------------------------

NUMBERS = [
    "", " ", "0", "-0", "-1", "1e308", "-1e308", "1e-320", "nan", "NaN", "inf", "-inf", "Infinity",
    "999999999999999999999", "-2147483649", "2147483648", "0x10", "1,5", "3.14.15", "1e", "--1", "+",
    "١٢٣", "１２", "1_000", " 12 ", "0.0000001", "-0.0", "1e5", "-99999",
]
TEXTS = [
    "", " ", "a", "Hello", "\U0001f600\U0001f3ac\U0001f525", "\U0001f469‍\U0001f469‍\U0001f467",
    "مرحبا بالعالم", "שלום",
    "abc‮def", "Z̷̢̛͓a̸l̶g̵o̴", "a\x00b", "line\nbreak",
    "tab\there", "​", "﻿", "<b>bold</b>", "%s%n%d", "{0}", "'; --", "\\", '"', "ção",
]
LATEX = [
    r"\frac{", r"{{{", r"}}}", "\\", r"\begin{align}", r"x^", r"_", r"$$", r"\left(", r"%", r"&&&",
    r"\def\x{\x}\x", r"a^{2", r"\sqrt[", r"\end{document}", r"\\\\\\", r"\frac{1}{0}", r"x_{_{_{_{",
    r"\unknowncommand", r"\color{nocolour}{x}", r"\text{\U0001f600}",
]
CODE = [
    "while True:\n    pass\n",
    "class S(Scene):\n    def construct(self):\n        self.add(Circle())\n",
    "class S(Scene):\n    def construct(self)\n",
    "raise SystemExit(3)\n",
    "1/0\n",
    "class S(Scene):\n    def construct(self):\n        self.wait(1e9)\n",
    "x = [0] * 10\n" * 50,
]
SAFE = [t for t in NUMBERS + TEXTS if "\\" not in t and "/" not in t and ".." not in t]  # dialog answers


def long_text(rng: random.Random) -> str:
    if rng.random() < 0.5:
        return "W" * 10_000
    alphabet = "abc XYZ 019 {}^_\\$ çשم\U0001f600"
    return "".join(rng.choice(alphabet) for _ in range(10_000))


def junk(rng: random.Random, kind: str = "any") -> str:
    if kind == "number":
        pool = NUMBERS
    elif kind == "safe":
        pool = SAFE
    elif kind == "code":
        pool = CODE + TEXTS
    else:
        pool = NUMBERS + TEXTS + LATEX
    if rng.random() < 0.06:
        return long_text(rng)
    return rng.choice(pool)


# -- environment (before the package is imported) ---------------------------------------------------


def prepare_environment(
    run_dir: Path, real_helpers: bool, idle_seconds: float | None, code: bool = False
) -> dict[str, Path]:
    places = {
        name: run_dir / name
        for name in ("plugins", "logs", "trust", "recovery", "library", "presets", "voices", "settings", "work")
    }
    for path in places.values():
        path.mkdir(parents=True, exist_ok=True)
    env = os.environ
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["MANIM_STUDIO_PLUGINS"] = str(places["plugins"])
    env["MANIM_STUDIO_LOG_DIR"] = str(places["logs"])
    env["MANIM_STUDIO_TRUST_FILE"] = str(places["trust"] / "trusted.json")
    env["MANIM_STUDIO_RECOVERY"] = str(places["recovery"])
    env["MANIM_STUDIO_LIBRARY"] = str(places["library"])
    env["MANIM_STUDIO_PRESETS"] = str(places["presets"] / "presets.json")
    env["MANIM_STUDIO_VOICE_CACHE"] = str(places["voices"])
    env["MANIM_STUDIO_SETTINGS"] = str(places["settings"] / "manim-studio.ini")
    env["MANIM_STUDIO_CACHE"] = str(run_dir.parent / "manim")  # never the user's cache folder
    env["MANIM_STUDIO_AUDIO"] = "0"
    env["MANIM_STUDIO_MOTION"] = "0"
    if real_helpers:
        for name in ("MANIM_STUDIO_WORKER", "MANIM_STUDIO_PREVIEW", "MANIM_STUDIO_CODE"):
            env.pop(name, None)
        if not code:  # code layers draw placeholders: no project code runs (--code renders them)
            env["MANIM_STUDIO_CODE"] = "0"
    else:
        env["MANIM_STUDIO_WORKER"] = "0"
        env["MANIM_STUDIO_PREVIEW"] = "0"
        env["MANIM_STUDIO_CODE"] = "0"
    if idle_seconds is not None:
        env["MANIM_STUDIO_IDLE_SECONDS"] = str(idle_seconds)
    return places


def prepare_cache() -> Path:
    """Manim's cache for the harness: inside the project (LaTeX fails under 8.3 temp paths), seeded with the
    shared cache's compiled LaTeX and text, and not shared with test runs."""
    cache = BASE / "manim"
    for folder in ("Tex", "texts"):
        if (SHARED_CACHE / folder).is_dir() and not (cache / folder).is_dir():
            shutil.copytree(SHARED_CACHE / folder, cache / folder, dirs_exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    return cache


# -- Windows process measurements -------------------------------------------------------------------


class WinProcs:
    """Committed memory, working set, CPU time, handles and command line of a process (Windows API)."""

    def __init__(self) -> None:
        from ctypes import wintypes as wt

        self.ok = sys.platform == "win32"
        if not self.ok:
            return

        class Counters(ctypes.Structure):
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

        class UnicodeString(ctypes.Structure):
            _fields_ = [("Length", ctypes.c_ushort), ("MaximumLength", ctypes.c_ushort), ("Buffer", ctypes.c_void_p)]

        self.Counters, self.UnicodeString = Counters, UnicodeString
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.ntdll = ctypes.WinDLL("ntdll")
        self.user32 = ctypes.WinDLL("user32")
        self.k32.OpenProcess.restype = wt.HANDLE
        self.k32.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
        self.k32.CloseHandle.argtypes = (wt.HANDLE,)
        self.k32.GetProcessTimes.argtypes = (wt.HANDLE,) + (ctypes.POINTER(ctypes.c_ulonglong),) * 4
        self.k32.GetProcessHandleCount.argtypes = (wt.HANDLE, ctypes.POINTER(wt.DWORD))
        self.psapi.GetProcessMemoryInfo.argtypes = (wt.HANDLE, ctypes.POINTER(Counters), wt.DWORD)
        self.ntdll.NtQueryInformationProcess.argtypes = (
            wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.ULONG, ctypes.POINTER(wt.ULONG),
        )  # fmt: skip
        self.user32.GetGuiResources.argtypes = (wt.HANDLE, wt.DWORD)
        self._roles: dict[int, str] = {}

    def _open(self, pid: int):
        return self.k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION

    def sample(self, pid: int) -> dict | None:
        """{commit, ws (MB), cpu (s), handles} or None when the process is gone."""
        if not self.ok:
            return None
        handle = self._open(pid)
        if not handle:
            return None
        try:
            counters = self.Counters()
            counters.cb = ctypes.sizeof(counters)
            if not self.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return None
            times = [ctypes.c_ulonglong() for _ in range(4)]
            self.k32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times])
            count = ctypes.c_ulong()
            from ctypes import wintypes as wt

            hc = wt.DWORD()
            self.k32.GetProcessHandleCount(handle, ctypes.byref(hc))
            del count
            return {
                "commit": counters.PrivateUsage / 2**20,
                "ws": counters.WorkingSetSize / 2**20,
                "peak_ws": counters.PeakWorkingSetSize / 2**20,
                "peak_commit": counters.PeakPagefileUsage / 2**20,
                "cpu": (times[2].value + times[3].value) / 1e7,
                "handles": int(hc.value),
            }
        finally:
            self.k32.CloseHandle(handle)

    def gui_objects(self) -> tuple[int, int]:
        """(GDI, USER) objects of this process."""
        if not self.ok:
            return (0, 0)
        me = ctypes.c_void_p(-1)  # GetCurrentProcess()
        return int(self.user32.GetGuiResources(me, 0)), int(self.user32.GetGuiResources(me, 1))

    def command_line(self, pid: int) -> str:
        if not self.ok:
            return ""
        handle = self._open(pid)
        if not handle:
            return ""
        try:
            size = ctypes.c_ulong(0)
            buffer = ctypes.create_string_buffer(65536)
            from ctypes import wintypes as wt

            got = wt.ULONG(0)
            status = self.ntdll.NtQueryInformationProcess(handle, 60, buffer, len(buffer), ctypes.byref(got))
            del size
            if status != 0:
                return ""
            text = self.UnicodeString.from_buffer(buffer)
            return ctypes.wstring_at(text.Buffer, text.Length // 2) if text.Buffer else ""
        finally:
            self.k32.CloseHandle(handle)

    def role(self, pid: int) -> str:
        if pid in self._roles:
            return self._roles[pid]
        command = self.command_line(pid)
        role = "?"
        for name in ("worker", "preview", "code_runner", "voice", "scene_recorder", "scene_probe", "helper_check"):
            if f"processes.{name}" in command:
                role = name
                break
        else:
            if "manim_studio" in command and " render " in f" {command} ":
                role = "export"
            elif command:
                role = Path(command.strip().split(" ")[0].strip('"')).stem.lower() or "?"
        if command:
            self._roles[pid] = role
        return role


# -- the harness ------------------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--phase", choices=["euler", "showcase", "graphs", "angular", "soak", "churn"], default="euler"
    )
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--steps", type=int, default=None, help="steps to run (default 3000; soak: unbounded)")
    parser.add_argument("--minutes", type=float, default=None, help="stop stepping after this long")
    parser.add_argument("--max-minutes", type=float, default=60.0, help="hard wall-clock cap for the process")
    parser.add_argument("--iterations", type=int, default=200, help="churn: projects opened in one window")
    parser.add_argument("--windows", type=int, default=50, help="churn: windows opened and closed")
    parser.add_argument("--layers", type=int, default=320, help="soak: layers in the generated project")
    parser.add_argument("--sample-every", type=int, default=25, help="memory/CPU sample every N steps")
    parser.add_argument("--stop-at", type=int, default=None, help="stop after this step (replay)")
    parser.add_argument("--actions", default="", help="comma-separated action names to restrict to")
    parser.add_argument("--fake-helpers", action="store_true", help="no helper processes (like the tests)")
    parser.add_argument("--code", action="store_true", help="run the code renderer (off: placeholders)")
    parser.add_argument("--idle-seconds", type=float, default=None, help="MANIM_STUDIO_IDLE_SECONDS")
    parser.add_argument("--idle-probe", type=float, default=45.0, help="seconds left idle before closing")
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--verbose", action="store_true", help="print every step")
    options = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    seed = options.seed if options.seed is not None else random.SystemRandom().randrange(1, 10**6)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path(options.run_dir) if options.run_dir else BASE / f"{options.phase}-s{seed}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    places = prepare_environment(run_dir, not options.fake_helpers, options.idle_seconds, options.code)
    os.chdir(places["work"])  # relative paths typed anywhere land in the run's folder
    print(f"stress_monkey phase={options.phase} seed={seed} run_dir={run_dir}", flush=True)
    harness = Harness(options, seed, run_dir, places)
    return harness.run()


class Harness:
    def __init__(self, options, seed: int, run_dir: Path, places: dict[str, Path]) -> None:
        self.options, self.seed, self.run_dir, self.places = options, seed, run_dir, places
        self.rng = random.Random(seed)
        self.dialog_rng = random.Random(seed * 7919 + 1)
        self.work = places["work"]
        self.procs = WinProcs()
        self.started = time.monotonic()
        self.hard_deadline = self.started + options.max_minutes * 60
        self.step = -1
        self.action = "setup"
        self.history: collections.deque[str] = collections.deque(maxlen=25)
        self.findings: dict[str, dict] = {}
        self.qt_messages: collections.Counter[str] = collections.Counter()
        self.qt_first: dict[str, tuple[int, str]] = {}
        self.action_counts: collections.Counter[str] = collections.Counter()
        self.samples: list[dict] = []
        self.helper_pids: dict[int, str] = {}
        self.redirected_exports: list[str] = []
        self.opened_urls: list[str] = []
        self.step_started = time.monotonic()
        self.in_step = False
        self.windows_recreated = 0
        self.phase_results: dict = {}
        self._last_cpu: dict[int, tuple[float, float]] = {}
        self.steps_log = open(run_dir / "steps.log", "w", encoding="utf-8", errors="replace")
        self.hang_path = run_dir / "hangs.txt"
        self.hang_file = open(self.hang_path, "w", encoding="utf-8", errors="replace")
        self.mouse_since: float | None = None
        self.mouse_target = None
        self.drag_rescues = 0
        self.dialogs_seen: collections.Counter[str] = collections.Counter()
        self._dialog_ages: dict[int, int] = {}
        self._killer_pending = False

    # -- setup ----------------------------------------------------------------------------------

    def setup(self) -> None:
        global QtCore, QtGui, QtWidgets, QTest, shiboken6, lifeline, adapter, Project, MainWindow, edits, children
        import shiboken6 as _shiboken6
        from PySide6 import QtCore as _QtCore
        from PySide6 import QtGui as _QtGui
        from PySide6 import QtWidgets as _QtWidgets
        from PySide6.QtTest import QTest as _QTest

        QtCore, QtGui, QtWidgets, QTest, shiboken6 = _QtCore, _QtGui, _QtWidgets, _QTest, _shiboken6
        import manim_studio
        from manim_studio import lifeline as _lifeline

        lifeline = _lifeline
        self.package = Path(manim_studio.__file__).resolve().parent
        candidates = [self.package.parent.parent / "examples", ROOT / "examples"]
        self.examples = next(p for p in candidates if (p / "euler.json").is_file())
        print(f"package: {self.package}\nexamples: {self.examples}", flush=True)
        from manim_studio.core.engine import adapter as _adapter

        adapter = _adapter
        adapter.configure(prepare_cache())
        from manim_studio.core.editing import edits as _edits
        from manim_studio.core.model.schema import Project as _Project

        edits, Project = _edits, _Project
        from manim_studio.logging_config import LOGGER_NAME, setup_logging

        self.install_hooks()
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([sys.argv[0]])
        self.app.setApplicationName("Manim Studio")
        QtCore.qInstallMessageHandler(self.on_qt_message)
        from manim_studio.ui.services import children as _children

        children = _children
        children.install(self.app)  # as ui.main_window.run does
        from manim_studio.ui.style import theme

        theme.apply(self.app)
        setup_logging()
        import logging

        logger = logging.getLogger(LOGGER_NAME)
        for handler in list(logger.handlers):
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                logger.removeHandler(handler)  # the log file stays; the console would flood the output
        logger.addHandler(_Capture(self))
        from manim_studio.ui.main_window import MainWindow as _MainWindow

        MainWindow = _MainWindow
        angular_source = self.examples / "angular_momentum" / "angular_momentum.json"
        self.protected_code = self.protected_pieces(angular_source) if angular_source.is_file() else []
        self.install_patches()
        self.make_fixtures()
        self.killer = QtCore.QTimer()
        self.killer.setInterval(40)
        self.killer.timeout.connect(self.killer_tick)
        self.killer.start()
        self.watchdog = threading.Thread(target=self.watch, name="monkey-watchdog", daemon=True)
        self.watchdog.start()

    def install_hooks(self) -> None:
        def excepthook(kind, value, tb):
            self.record_exception("excepthook", kind, value, tb)

        def thread_hook(args):
            self.record_exception(f"thread:{args.thread.name if args.thread else '?'}", args.exc_type,
                                  args.exc_value, args.exc_traceback)  # fmt: skip

        def unraisable(info):
            self.record_exception(f"unraisable:{info.err_msg or ''}"[:60], info.exc_type, info.exc_value,
                                  info.exc_traceback)  # fmt: skip

        sys.excepthook = excepthook
        threading.excepthook = thread_hook
        sys.unraisablehook = unraisable

    def install_patches(self) -> None:
        """Fakes for what would leave the run's folder: file dialogs, opening folders, the network, and
        exports to other places."""
        rng = self.dialog_rng
        work = self.work
        counter = [0]

        def fixture_for(filter_text: str) -> str:
            exts = {e.lower() for e in re.findall(r"\*\.(\w+)", filter_text or "")}
            files = [f for f in self.fixtures if not exts or f.suffix[1:].lower() in exts]
            if not files or rng.random() < 0.25:
                return ""
            return str(rng.choice(files))

        def get_open(parent=None, caption="", directory="", filter="", *a, **k):  # noqa: A002
            self.dialogs_seen[f"QFileDialog.getOpenFileName {caption!s:.40}"] += 1
            return (fixture_for(k.get("filter", filter)), "")

        def get_opens(parent=None, caption="", directory="", filter="", *a, **k):  # noqa: A002
            self.dialogs_seen[f"QFileDialog.getOpenFileNames {caption!s:.40}"] += 1
            chosen = [fixture_for(k.get("filter", filter)) for _ in range(rng.randint(0, 3))]
            return ([c for c in chosen if c], "")

        def get_save(parent=None, caption="", directory="", filter="", *a, **k):  # noqa: A002
            self.dialogs_seen[f"QFileDialog.getSaveFileName {caption!s:.40}"] += 1
            if rng.random() < 0.3:
                return ("", "")
            counter[0] += 1
            exts = re.findall(r"\*\.(\w+)", k.get("filter", filter) or "") or ["json"]
            target = work / "saves" / f"save_{counter[0]}.{exts[0]}"
            target.parent.mkdir(parents=True, exist_ok=True)
            return (str(target), "")

        def get_dir(parent=None, caption="", directory="", *a, **k):
            self.dialogs_seen[f"QFileDialog.getExistingDirectory {caption!s:.40}"] += 1
            if rng.random() < 0.4:
                return ""
            counter[0] += 1
            target = work / "dirs" / f"d{counter[0]}"
            target.mkdir(parents=True, exist_ok=True)
            return str(target)

        QFD = QtWidgets.QFileDialog
        QFD.getOpenFileName = staticmethod(get_open)
        QFD.getOpenFileNames = staticmethod(get_opens)
        QFD.getSaveFileName = staticmethod(get_save)
        QFD.getExistingDirectory = staticmethod(get_dir)

        def open_url(url, *a, **k):
            self.opened_urls.append(url.toString() if hasattr(url, "toString") else str(url))
            return True

        QtGui.QDesktopServices.openUrl = staticmethod(open_url)
        if hasattr(os, "startfile"):
            os.startfile = lambda *a, **k: self.opened_urls.append(f"startfile {a}")  # type: ignore[attr-defined]
        from manim_studio.core.exchange import preset_online

        def no_network(*a, **k):
            raise OSError("network disabled by the stress harness")

        preset_online._default_opener = no_network
        from manim_studio.ui.session import places

        places.documents = lambda: work
        places.default_folder = lambda recent: work
        from manim_studio.ui.deliver import export_job

        original = export_job.ExportJob.__init__
        safe_root = self.run_dir.resolve()

        def safe_init(job, project, output, cache_dir, *a, **k):
            out = Path(output)
            try:
                inside = out.resolve().is_relative_to(safe_root)
            except (OSError, ValueError):
                inside = False
            if not inside:
                counter[0] += 1
                self.redirected_exports.append(str(output)[:200])
                out = work / "exports" / f"redirected_{counter[0]}.mp4"
            original(job, project, out, cache_dir, *a, **k)

        export_job.ExportJob.__init__ = safe_init

        # The angular_momentum project's code is never trusted, so it never runs (in a renderer or an export):
        # its layers draw placeholders. Code that contains a long piece of it is refused too (edited copies).
        from manim_studio.core.code import trust as trust_module

        protected = self.protected_code
        original_trust = trust_module.TrustStore.trust

        def guarded_trust(store, codes, *a, **k):
            codes = [c for c in codes if not any(piece in str(c) for piece in protected)]
            if codes:
                return original_trust(store, codes, *a, **k)
            return None

        trust_module.TrustStore.trust = guarded_trust
        original_carry = trust_module.TrustStore.carry

        def guarded_carry(store, rewritten, *a, **k):
            pairs = [(old, new) for old, new in rewritten if not any(piece in str(new) for piece in protected)]
            return original_carry(store, pairs, *a, **k)

        trust_module.TrustStore.carry = guarded_carry
        MainWindow.ask_trust = lambda window, names: "skip"  # opening a project never runs its code

    def protected_pieces(self, project_file: Path) -> list[str]:
        data = json.loads(project_file.read_text(encoding="utf-8"))
        pieces = []
        for layer in data.get("layers", []):
            code = str(layer.get("spec", {}).get("params", {}).get("code", "") or "")
            if len(code) > 200:
                pieces.append(code[60:260])  # a stretch of the body, past the class line
        return pieces

    def copy_angular(self, fx: Path) -> Path | None:
        """examples/angular_momentum with its voice files, the sounds' absolute paths moved to the copy."""
        source = self.examples / "angular_momentum"
        if not (source / "angular_momentum.json").is_file():
            return None
        target = fx / "angular_momentum"
        target.mkdir(parents=True, exist_ok=True)
        if (source / "angular_momentum_voice").is_dir():
            shutil.copytree(source / "angular_momentum_voice", target / "angular_momentum_voice", dirs_exist_ok=True)
        data = json.loads((source / "angular_momentum.json").read_text(encoding="utf-8"))
        moved = [0]

        def move(value):
            if isinstance(value, dict):
                return {k: move(v) for k, v in value.items()}
            if isinstance(value, list):
                return [move(v) for v in value]
            if isinstance(value, str) and "angular_momentum_voice" in value and value[1:3] == ":\\":
                moved[0] += 1
                return str(target / "angular_momentum_voice" / Path(value).name)
            return value

        data = move(data)
        out = target / "angular_momentum.json"
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"angular_momentum copied ({moved[0]} sound paths moved into the run folder)", flush=True)
        return out

    def make_fixtures(self) -> None:
        fx = self.work / "fixtures"
        fx.mkdir(parents=True, exist_ok=True)
        image = QtGui.QImage(64, 48, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor("#3388ff"))
        image.save(str(fx / "img.png"))
        big = QtGui.QImage(3000, 3000, QtGui.QImage.Format.Format_RGB32)
        big.fill(QtGui.QColor("#aa2244"))
        big.save(str(fx / "big.jpg"))
        (fx / "notimage.png").write_bytes(b"not a png at all")
        (fx / "shape.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="red"/>'
            "</svg>",
            encoding="utf-8",
        )
        (fx / "broken.svg").write_text("<svg><path d='M 0 0 L'", encoding="utf-8")
        with wave.open(str(fx / "tone.wav"), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(22050)
            out.writeframes(
                b"".join(struct.pack("<h", int(8000 * math.sin(i * 440 * 2 * math.pi / 22050))) for i in range(22050))
            )
        (fx / "bad.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVEjunk")
        (fx / "subs.srt").write_text(
            "1\n00:00:00,500 --> 00:00:01,500\nHello\n\n2\n00:00:02,000 --> 00:00:03,000\nשלום"
            " \U0001f600\n\n",
            encoding="utf-8",
        )
        (fx / "junk.srt").write_text("1\n99:99:99,999 --> -1\n\n\n\x00\n", encoding="utf-8")
        (fx / "scene.py").write_text(
            "from manim import *\n\n\nclass Tiny(Scene):\n    def construct(self):\n        c = Circle()\n"
            "        self.play(Create(c), run_time=0.5)\n        self.wait(0.2)\n",
            encoding="utf-8",
        )
        (fx / "broken.py").write_text("class (:\n", encoding="utf-8")
        (fx / "bad.json").write_text("{not json", encoding="utf-8")
        (fx / "wrong.json").write_text('{"layers": 5, "canvas": "x"}', encoding="utf-8")
        for name in ("euler", "showcase", "graphs"):
            shutil.copy(self.examples / f"{name}.json", fx / f"{name}.json")
        self.fixtures = sorted(p for p in fx.iterdir() if p.is_file())
        self.pristine = {name: self.examples / f"{name}.json" for name in ("euler", "showcase", "graphs")}
        angular = self.copy_angular(fx)
        if angular is not None:
            self.pristine["angular"] = angular

    # -- recording ------------------------------------------------------------------------------

    def _finding(self, kind: str, key: str, text: str, severity: str) -> dict:
        full = f"{kind}|{key}"
        entry = self.findings.get(full)
        if entry is None:
            entry = self.findings[full] = {
                "kind": kind,
                "severity": severity,
                "key": key,
                "count": 0,
                "first_step": self.step,
                "first_action": self.action,
                "phase": self.options.phase,
                "text": text[:6000],
                "recent": list(self.history)[-12:],
                "steps": [],
            }
            print(f"\n*** NEW {severity} [{kind}] at step {self.step} ({self.action}): {key}\n{text[:1500]}\n",
                  flush=True)  # fmt: skip
        entry["count"] += 1
        if len(entry["steps"]) < 30:
            entry["steps"].append(self.step)
        return entry

    def record_exception(self, where: str, kind, value, tb) -> None:
        text = "".join(traceback.format_exception(kind, value, tb))
        frames = traceback.extract_tb(tb) if tb else []
        ours = [f for f in frames if "manim_studio" in f.filename.replace("\\", "/")]
        last = frames[-1] if frames else None
        product = bool(ours) and last is not None and "stress_monkey" not in last.filename
        site = f"{Path(ours[-1].filename).name}:{ours[-1].lineno}" if ours else (
            f"{Path(last.filename).name}:{last.lineno}" if last else "?")  # fmt: skip
        message = re.sub(r"0x[0-9a-fA-F]+|\d+", "#", str(value))[:80]
        key = f"{getattr(kind, '__name__', kind)} @ {site}: {message}"
        self._finding("exception" if product else "harness-error", f"{where}: {key}", text,
                      "exception" if product else "harness")  # fmt: skip

    def on_qt_message(self, mode, context, message: str) -> None:
        level = {0: "debug", 1: "warning", 2: "critical", 3: "fatal", 4: "info"}.get(int(mode.value), str(mode))
        if level in ("debug", "info") or message.startswith(OFFSCREEN_NOISE):
            return
        norm = re.sub(r"0x[0-9a-fA-F]+", "0x#", message)
        norm = re.sub(r"\d+", "#", norm)[:200]
        key = f"{level}: {norm}"
        self.qt_messages[key] += 1
        if key not in self.qt_first:
            self.qt_first[key] = (self.step, self.action)
        if level in ("critical", "fatal"):
            self._finding("qt-" + level, norm, message, "exception")

    def record_log(self, record) -> None:
        text = record.getMessage()
        if record.exc_info:
            text += "\n" + "".join(traceback.format_exception(*record.exc_info))
        norm = re.sub(r"0x[0-9a-fA-F]+|\d+(\.\d+)?", "#", record.getMessage())[:160]
        severity = "exception" if record.levelno >= 40 else "logged-warning"
        if record.levelno >= 40 or record.exc_info:
            self._finding(f"log-{record.levelname.lower()}", f"{record.name}: {norm}", text, severity)
        else:
            key = f"log-warning: {record.name}: {norm}"
            self.qt_messages[key] += 1
            if key not in self.qt_first:
                self.qt_first[key] = (self.step, self.action)

    def log_step(self, text: str) -> None:
        self.history.append(f"{self.step}: {text}")
        self.steps_log.write(f"{self.step}\t{time.monotonic() - self.started:8.2f}\t{text}\n")
        if self.options.verbose:
            print(f"{self.step}: {text}", flush=True)

    # -- watchdog -------------------------------------------------------------------------------

    def watch(self) -> None:
        while True:
            time.sleep(1.0)
            if self.in_step and time.monotonic() - self.step_started > HARD_LIMIT:
                self.hang_file.write(f"\n=== HARD LIMIT at step {self.step} ({self.action}) ===\n")
                faulthandler.dump_traceback(file=self.hang_file, all_threads=True)
                self.hang_file.flush()
                self._finding("hang", f"step over {HARD_LIMIT} s: {self.action}", "see hangs.txt", "hang")
                try:
                    self.write_results(aborted=True)
                finally:
                    os._exit(3)
            if time.monotonic() > self.hard_deadline + 600:
                self.hang_file.write("\n=== process cap exceeded ===\n")
                faulthandler.dump_traceback(file=self.hang_file, all_threads=True)
                self.hang_file.flush()
                try:
                    self.write_results(aborted=True)
                finally:
                    os._exit(4)

    # -- modal dialogs, popups and stuck drags ---------------------------------------------------

    def killer_tick(self) -> None:
        """Answer the dialog or popup that is open. What it does is deferred to a one-shot timer: Qt never
        runs a timer's slot again while it is still inside it, so a dialog opened by a menu item this tick
        chose could not be answered by this timer until the dialog closed (a dead lock)."""
        if self._killer_pending:
            return
        try:
            plan = self._kill()
        except Exception:
            kind, value, tb = sys.exc_info()
            self.record_exception("killer", kind, value, tb)
            return
        if plan is None:
            return
        widget, fn = plan
        self._killer_pending = True

        def run() -> None:
            self._killer_pending = False
            if widget is not None and not shiboken6.isValid(widget):
                return
            try:
                fn()
            except Exception:
                kind, value, tb = sys.exc_info()
                self.record_exception("killer", kind, value, tb)

        QtCore.QTimer.singleShot(0, run)

    def _age(self, widget) -> int:
        key = id(widget)
        age = self._dialog_ages.get(key, 0) + 1
        self._dialog_ages = {key: age}  # only the active one is tracked
        return age

    def _kill(self):
        """What to do now: (widget, callable), or None."""
        W, Qt = QtWidgets, QtCore.Qt
        rng = self.dialog_rng
        popup = W.QApplication.activePopupWidget()
        if popup is not None:
            age = self._age(popup)
            if age < 2:
                return None
            name = type(popup).__name__
            if isinstance(popup, W.QMenu):
                actions = [
                    a for a in popup.actions()
                    if a.isVisible() and a.isEnabled() and not a.isSeparator() and not EXCLUDE.search(a.text())
                ]  # fmt: skip
                if age > 12 or not actions or rng.random() < 0.2:
                    return popup, popup.close
                chosen = rng.choice(actions)
                self.dialogs_seen[f"menu item: {chosen.text()[:50]}"] += 1
                self.log_step(f"  popup menu -> {chosen.text()[:60]!r}")

                def pick(popup=popup, chosen=chosen) -> None:
                    if popup.isVisible() and shiboken6.isValid(chosen):
                        popup.setActiveAction(chosen)
                        QTest.keyClick(popup, Qt.Key.Key_Return)

                return popup, pick
            self.dialogs_seen[f"popup {name}"] += 1
            if age > 12:
                return popup, popup.close
            downs = rng.randint(0, 4)
            last = rng.choice([Qt.Key.Key_Return, Qt.Key.Key_Escape])

            def keys(popup=popup) -> None:
                for _ in range(downs):
                    QTest.keyClick(popup, Qt.Key.Key_Down)
                QTest.keyClick(popup, last)

            return popup, keys
        modal = W.QApplication.activeModalWidget()
        if modal is not None:
            age = self._age(modal)
            if age < 2:
                return None
            label = f"{type(modal).__name__} {modal.windowTitle()[:40]!r}"
            if age == 2:
                self.dialogs_seen[label] += 1
                self.log_step(f"  modal {label}")
            if age > 80:
                self._finding("cosmetic", f"modal would not close: {label}", label, "cosmetic")
                return modal, modal.hide
            if age > 30:
                return modal, (lambda m=modal: m.done(0)) if isinstance(modal, W.QDialog) else modal.close
            if isinstance(modal, W.QMessageBox):
                buttons = modal.buttons()
                if not buttons:
                    return modal, lambda m=modal: m.done(0)
                choice = rng.choice(buttons)
                self.log_step(f"  message box {label} {modal.text()[:60]!r} -> {choice.text()!r}")
                return modal, choice.click
            if isinstance(modal, W.QFileDialog):
                return modal, modal.reject
            if isinstance(modal, W.QInputDialog):
                mode = modal.inputMode()
                accept = rng.random() < 0.6
                text, number, real = junk(rng, "safe"), rng.randint(-10**6, 10**6), rng.uniform(-1e6, 1e6)

                def answer(m=modal) -> None:
                    if mode == W.QInputDialog.InputMode.TextInput:
                        m.setTextValue(text)
                    elif mode == W.QInputDialog.InputMode.IntInput:
                        m.setIntValue(number)
                    else:
                        m.setDoubleValue(real)
                    (m.accept() if accept else m.reject())

                self.log_step(f"  input {label} -> {text[:30]!r} {'accept' if accept else 'reject'}")
                return modal, answer
            if isinstance(modal, W.QColorDialog):
                colour = QtGui.QColor(rng.randrange(256), rng.randrange(256), rng.randrange(256))
                accept = rng.random() < 0.6

                def pick_colour(m=modal) -> None:
                    m.setCurrentColor(colour)
                    (m.accept() if accept else m.reject())

                return modal, pick_colour
            if isinstance(modal, W.QProgressDialog):
                return modal, modal.cancel
            if isinstance(modal, W.QDialog):
                r = rng.random()
                if age >= 10 or r < 0.3:
                    return modal, modal.reject
                if r < 0.5:
                    self.log_step(f"  accept {label}")
                    return modal, modal.accept
                if r < 0.75:
                    buttons = [b for b in modal.findChildren(W.QAbstractButton) if b.isVisible() and b.isEnabled()]
                    if buttons:
                        b = rng.choice(buttons)
                        self.log_step(f"  click {b.text()[:30]!r} in {label}")
                        return b, b.click
                    return None
                edits_ = [e for e in modal.findChildren(W.QLineEdit) if e.isVisible() and e.isEnabled()]
                text = junk(rng, "safe")
                key = rng.choice([Qt.Key.Key_Down, Qt.Key.Key_Tab])
                target = rng.choice(edits_) if edits_ else None

                def type_into(m=modal) -> None:
                    if target is not None and shiboken6.isValid(target):
                        target.setText(text)
                    QTest.keyClick(m, key)

                return modal, type_into
            return modal, modal.close
        self._dialog_ages = {}
        if self.mouse_since is not None and time.monotonic() - self.mouse_since > 2.0:
            # A drag (QDrag) runs its own loop waiting for the button to come up: let it go.
            self.drag_rescues += 1
            self.mouse_since = time.monotonic()
            window, pos = self.mouse_target or (None, None)

            def release() -> None:
                focus = W.QApplication.focusWidget()
                if focus is not None:
                    QTest.keyClick(focus, Qt.Key.Key_Escape)
                if window is not None:
                    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)

            return None, release
        return None

    # -- measurement ----------------------------------------------------------------------------

    def tree(self) -> list[int]:
        return lifeline.descendants(os.getpid())

    def sample(self, label: str = "") -> dict:
        now = time.monotonic()
        me = os.getpid()
        rows = []
        table = lifeline.process_table()
        below = lifeline.tree_below(table, me)
        roles = {pid: self.procs.role(pid) for pid in below}
        for pid in [me, *below]:
            s = self.procs.sample(pid)
            if s is None:
                continue
            role = "editor" if pid == me else roles.get(pid, "?")
            if pid != me and any(table.get(c) == pid and roles.get(c) == role for c in below):
                role += "-launcher"  # the venv's python.exe starts the real interpreter as its child
            if pid != me:
                self.helper_pids.setdefault(pid, role)
            last = self._last_cpu.get(pid)
            s["cpu_pct"] = round(100 * (s["cpu"] - last[1]) / max(1e-6, now - last[0]), 1) if last else None
            self._last_cpu[pid] = (now, s["cpu"])
            rows.append({"pid": pid, "role": role, **{k: round(v, 1) if isinstance(v, float) else v for k, v in s.items()}})
        gdi, user = self.procs.gui_objects()
        editor = rows[0] if rows and rows[0]["pid"] == me else {}
        entry = {
            "step": self.step,
            "t": round(now - self.started, 1),
            "label": label,
            "editor_commit": editor.get("commit"),
            "editor_ws": editor.get("ws"),
            "editor_handles": editor.get("handles"),
            "editor_cpu_pct": editor.get("cpu_pct"),
            "total_commit": round(sum(r["commit"] for r in rows), 1),
            "total_ws": round(sum(r["ws"] for r in rows), 1),
            "helpers": [(r["pid"], r["role"], r["commit"], r["ws"], r["cpu_pct"]) for r in rows[1:]],
            "gdi": gdi,
            "user": user,
            "threads": threading.active_count(),
            "toplevels": len(QtWidgets.QApplication.topLevelWidgets()),
            "gc_objects": len(gc.get_objects()),
        }
        self.samples.append(entry)
        return entry

    # -- the window -----------------------------------------------------------------------------

    def new_window(self):
        window = MainWindow()
        window.resize(1280, 820)
        window.show()
        window.activateWindow()
        self.pump(50)
        return window

    def ensure_window(self) -> None:
        w = getattr(self, "window", None)
        if w is not None and shiboken6.isValid(w) and w.isVisible():
            return
        if w is not None:
            self._finding("cosmetic", "the main window was closed or hidden by an action", self.action, "cosmetic")
        self.windows_recreated += 1
        self.window = self.new_window()
        self.open_project(self.main_project)

    def pump(self, ms: int = 0) -> None:
        QtCore.QCoreApplication.processEvents()
        if ms > 0:
            QTest.qWait(ms)
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete.value)
        QtCore.QCoreApplication.processEvents()

    def fresh_copy(self, name: str) -> Path:
        target = self.work / "projects" / f"{name}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.pristine[name], target)
        return target

    def open_project(self, name: str) -> None:
        path = self.fresh_copy(name)
        self.window.load(path)
        self.pump(20)

    # -- running --------------------------------------------------------------------------------

    def run(self) -> int:
        self.setup()
        phase = self.options.phase
        code = 0
        try:
            if phase in ("euler", "showcase", "graphs", "angular"):
                self.main_project = phase
                self.window = self.new_window()
                self.open_project(phase)
                self.sample("start")
                self.run_monkey(self.options.steps or 3000, self.options.minutes)
            elif phase == "soak":
                self.pristine["big"] = self.build_large(self.options.layers)
                self.main_project = "big"
                self.window = self.new_window()
                self.open_project("big")
                self.sample("start")
                self.run_monkey(self.options.steps or 10**9, self.options.minutes or 10.0)
            elif phase == "churn":
                self.run_churn()
            self.final_checks()
        except Exception:
            kind, value, tb = sys.exc_info()
            self.record_exception("run", kind, value, tb)
            traceback.print_exc()
            code = 2
        self.write_results()
        self.print_summary()
        return code

    ACTIONS = (
        ("menu_action", 10),
        ("any_action", 4),
        ("switch_page", 5),
        ("add_object", 7),
        ("canvas_mouse", 12),
        ("canvas_wheel", 3),
        ("timeline_mouse", 9),
        ("timeline_wheel", 2),
        ("layers_mouse", 5),
        ("key_press", 7),
        ("shortcut", 6),
        ("undo_burst", 5),
        ("edit_field", 13),
        ("click_button", 5),
        ("play", 4),
        ("playhead", 4),
        ("context_menu", 5),
        ("open_project", 1.2),
        ("new_project", 0.8),
        ("export_dialog", 0.5),
        ("deliver_export", 0.5),
        ("resize_window", 1),
        ("close_windows", 1),
        ("save_roundtrip", 1),
        ("undo_symmetry", 1.5),
    )

    def run_monkey(self, steps: int, minutes: float | None) -> None:
        names = [n for n, _ in self.ACTIONS]
        weights = [w for _, w in self.ACTIONS]
        if self.options.actions:
            wanted = set(self.options.actions.split(","))
            weights = [w if n in wanted else 0 for n, w in self.ACTIONS]
        deadline = time.monotonic() + minutes * 60 if minutes else float("inf")
        deadline = min(deadline, self.hard_deadline)
        executed = 0
        t0 = time.monotonic()
        for i in range(steps):
            if time.monotonic() > deadline:
                break
            self.step = i
            name = self.rng.choices(names, weights)[0]
            self.do_step(name)
            executed += 1
            if i % 10 == 0:
                self.check_round_trip()
            if i % self.options.sample_every == 0:
                s = self.sample()
                print(
                    f"step {i:5d}  t={s['t']:7.1f}s  editor {s['editor_commit']} MB commit / {s['editor_ws']} MB ws"
                    f"  total {s['total_commit']} / {s['total_ws']} MB  helpers {len(s['helpers'])}"
                    f"  findings {sum(1 for f in self.findings.values() if f['severity'] != 'harness')}",
                    flush=True,
                )
            if i and i % 500 == 0:
                self.idle_probe(4.0, f"idle probe at step {i}")
            if self.options.stop_at is not None and i >= self.options.stop_at:
                break
        self.phase_results["monkey"] = {
            "steps_executed": executed,
            "seconds": round(time.monotonic() - t0, 1),
            "actions": dict(self.action_counts),
        }

    def do_step(self, name: str) -> None:
        self.ensure_window()
        self.action = name
        self.action_counts[name] += 1
        self.in_step = True
        self.step_started = time.monotonic()
        self.hang_file.flush()
        before = os.path.getsize(self.hang_path)
        faulthandler.dump_traceback_later(HANG_SECONDS, repeat=False, file=self.hang_file)
        try:
            detail = getattr(self, "act_" + name)()
            self.log_step(f"{name} {detail or ''}")
        except Exception:
            kind, value, tb = sys.exc_info()
            self.log_step(f"{name} raised {kind.__name__}: {value}")
            self.record_exception("direct", kind, value, tb)
        finally:
            self.mouse_since = None
            try:
                self.pump(self.rng.choice([0, 0, 5, 20, 50]))
            except Exception:
                kind, value, tb = sys.exc_info()
                self.record_exception("pump", kind, value, tb)
            faulthandler.cancel_dump_traceback_later()
            self.in_step = False
        took = time.monotonic() - self.step_started
        self.hang_file.flush()
        if os.path.getsize(self.hang_path) != before:
            text = self.hang_path.read_bytes()[before:].decode("utf-8", "replace")[:5000]
            self._finding("hang", f"step over {HANG_SECONDS} s: {name}", text, "hang")
        elif took > SLOW_STEP and name not in ("export_dialog", "deliver_export", "play"):
            self._finding("slow", f"step took {took:.0f} s: {name}", "\n".join(list(self.history)[-5:]), "cosmetic")

    # -- checks ---------------------------------------------------------------------------------

    def check_round_trip(self) -> None:
        """What Save would write must open again, unchanged."""
        window = self.window
        if window.project is None:
            return
        project = window.document.project
        try:
            text = project.model_dump_json(indent=2, by_alias=True)
        except Exception as exc:
            self._finding("data-loss", f"the project cannot be saved: {type(exc).__name__}",
                          traceback.format_exc(), "data-loss")  # fmt: skip
            return
        try:
            again = Project.model_validate_json(text)
        except Exception as exc:
            first = str(exc).splitlines()[:6]
            self._finding("data-loss", "a saved project does not open again: " + " / ".join(first)[:160],
                          f"{exc}\n--- recent actions ---\n" + "\n".join(self.history), "data-loss")  # fmt: skip
            self.dump_project(text, "unopenable")
            return
        if again.model_dump_json(indent=2, by_alias=True) != text:
            self._finding("data-loss", "a saved project opens different", "\n".join(self.history), "data-loss")
            self.dump_project(text, "different")

    def dump_project(self, text: str, why: str) -> None:
        target = self.run_dir / f"project-{why}-step{self.step}.json"
        if not any(self.run_dir.glob(f"project-{why}-*.json")):
            target.write_text(text, encoding="utf-8")

    def idle_probe(self, seconds: float, label: str) -> dict:
        """Leave the editor alone for ``seconds`` and measure what each process does meanwhile."""
        window = self.window
        if window.play_timer.isActive():
            window.pause()
        self.sample(label + " (start)")
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.pump(100)
        return self.sample(label)

    # -- actions --------------------------------------------------------------------------------

    def _menu_actions(self) -> list[tuple[str, object]]:
        found: list[tuple[str, object]] = []

        def walk(menu, path: str, depth: int) -> None:
            if depth > 5:
                return
            try:
                menu.aboutToShow.emit()  # menus filled when they open (recent files, presets)
            except Exception:
                pass
            for action in menu.actions():
                if action.isSeparator():
                    continue
                text = action.text().replace("&", "")
                if action.menu() is not None:
                    walk(action.menu(), f"{path} > {text}", depth + 1)
                elif action.isEnabled() and not EXCLUDE.search(text):
                    found.append((f"{path} > {text}", action))

        for top in self.window.menuBar().actions():
            if top.menu() is not None:
                walk(top.menu(), top.text().replace("&", ""), 0)
        return found

    def act_menu_action(self) -> str:
        actions = self._menu_actions()
        path, action = self.rng.choice(actions)
        self.log_step(f"menu {path}")
        self.action = f"menu_action {path}"
        action.trigger()
        return path

    def act_any_action(self) -> str:
        actions = [
            a for a in self.window.findChildren(QtGui.QAction)
            if a.isEnabled() and a.text() and not EXCLUDE.search(a.text())
        ]  # fmt: skip
        action = self.rng.choice(actions)
        text = action.text().replace("&", "")
        owner = type(action.parent()).__name__ if action.parent() is not None else "?"
        self.action = f"any_action {owner}/{text}"
        self.log_step(f"action {owner}/{text}")
        action.trigger()
        return f"{owner}/{text}"

    def act_switch_page(self) -> str:
        names = list(self.window.pages.pages)
        index = self.rng.randrange(len(names))
        if self.rng.random() < 0.5:
            self.window.show_page(names[index])
        else:
            mod = self.rng.choice([QtCore.Qt.KeyboardModifier.ControlModifier, QtCore.Qt.KeyboardModifier.ShiftModifier])
            QTest.keyClick(self.window, getattr(QtCore.Qt.Key, f"Key_{index + 1}"), mod)
        return names[index]

    def act_add_object(self) -> str:
        layers = self.window.layers
        if self.rng.random() < 0.2:
            self.mouse_click_widget(layers.add_button)  # the popup goes to the dialog timer
            return "via the Add button"
        actions = [a for a in layers.library_menu.actions() if not a.isSeparator() and a.isEnabled()]
        action = self.rng.choice(actions)
        self.action = f"add_object {action.text()}"
        action.trigger()
        return action.text()

    # mouse helpers

    def _to_window(self, widget, point) -> tuple[object, object]:
        top = widget.window()
        handle = top.windowHandle()
        p = widget.mapTo(top, QtCore.QPoint(int(point.x()), int(point.y())))
        return handle, p

    def mouse_click_widget(self, widget, button=None) -> None:
        button = button or QtCore.Qt.MouseButton.LeftButton
        self.mouse_since = time.monotonic()
        QTest.mouseClick(widget, button)
        self.mouse_since = None

    def gesture(self, widget, points: list, button=None, modifiers=None, kind: str = "drag") -> None:
        """A press, moves and a release through the window (as the system would deliver them)."""
        Qt = QtCore.Qt
        button = button or Qt.MouseButton.LeftButton
        modifiers = modifiers if modifiers is not None else Qt.KeyboardModifier.NoModifier
        if not widget.isVisible():
            return
        handle, first = self._to_window(widget, points[0])
        if handle is None:
            return
        self.mouse_target = (handle, first)
        self.mouse_since = time.monotonic()
        try:
            if kind == "dclick":
                QTest.mouseDClick(handle, button, modifiers, first)
                return
            if kind == "click":
                QTest.mouseClick(handle, button, modifiers, first)
                return
            QTest.mousePress(handle, button, modifiers, first)
            last = first
            for point in points[1:]:
                if not widget.isVisible() or not shiboken6.isValid(widget):
                    break
                _, last = self._to_window(widget, point)
                self.mouse_target = (handle, last)
                QTest.mouseMove(handle, last)
            QTest.mouseRelease(handle, button, modifiers, last)
        finally:
            self.mouse_since = None

    def random_point(self, widget, margin: int = 2):
        w, h = max(1, widget.width()), max(1, widget.height())
        return QtCore.QPointF(self.rng.uniform(margin, max(margin + 1, w - margin)),
                              self.rng.uniform(margin, max(margin + 1, h - margin)))  # fmt: skip

    def path_from(self, widget, start):
        end = self.random_point(widget) if self.rng.random() < 0.7 else QtCore.QPointF(
            start.x() + self.rng.uniform(-30, 30), start.y() + self.rng.uniform(-30, 30))  # fmt: skip
        n = self.rng.randint(2, 10)
        return [start] + [
            QtCore.QPointF(start.x() + (end.x() - start.x()) * k / n + self.rng.uniform(-3, 3),
                           start.y() + (end.y() - start.y()) * k / n + self.rng.uniform(-3, 3))
            for k in range(1, n + 1)
        ]  # fmt: skip

    def random_modifiers(self):
        M = QtCore.Qt.KeyboardModifier
        return self.rng.choice([M.NoModifier] * 6 + [M.ShiftModifier, M.ControlModifier, M.AltModifier,
                                                      M.ControlModifier | M.ShiftModifier])  # fmt: skip

    def mouse_gesture(self, widget, hot_points: list) -> str:
        Qt = QtCore.Qt
        rng = self.rng
        start = rng.choice(hot_points) if hot_points and rng.random() < 0.6 else self.random_point(widget)
        start = QtCore.QPointF(start.x() + rng.uniform(-2, 2), start.y() + rng.uniform(-2, 2))
        kind = rng.choices(["click", "drag", "dclick", "right", "middle"], [4, 6, 1.5, 1, 1])[0]
        mods = self.random_modifiers()
        if kind == "click":
            self.gesture(widget, [start], modifiers=mods, kind="click")
        elif kind == "dclick":
            self.gesture(widget, [start], modifiers=mods, kind="dclick")
        elif kind == "right":
            self.gesture(widget, [start], button=Qt.MouseButton.RightButton, modifiers=mods, kind="click")
        elif kind == "middle":
            self.gesture(widget, self.path_from(widget, start), button=Qt.MouseButton.MiddleButton, modifiers=mods)
        else:
            self.gesture(widget, self.path_from(widget, start), modifiers=mods)
        return f"{kind} at ({start.x():.0f},{start.y():.0f}) mods={int(mods.value) if hasattr(mods, 'value') else mods}"

    def ensure_canvas_page(self) -> None:
        if not self.window.canvas.isVisible() and self.window.project is not None:
            self.window.show_page(self.rng.choice(["compose", "animate"]))
            self.pump(10)

    def act_canvas_mouse(self) -> str:
        self.ensure_canvas_page()
        canvas = self.window.canvas
        hot = []
        outline = canvas.outline
        if outline is not None and canvas._canvas is not None:
            rect = canvas.units_transform().mapRect(outline.bounds)
            hot = [rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight(), rect.center(),
                   QtCore.QPointF(rect.center().x(), rect.top()), QtCore.QPointF(rect.right(), rect.center().y()),
                   QtCore.QPointF(rect.center().x(), rect.top() - 25)]  # fmt: skip
            hot = [QtCore.QPointF(p) for p in hot]
        return self.mouse_gesture(canvas, hot)

    def wheel(self, widget) -> str:
        rng = self.rng
        pos = self.random_point(widget)
        delta = rng.choice([120, -120, 240, -240, 1200, -1200, 15, -15, 120 * 50])
        horizontal = rng.random() < 0.2
        mods = rng.choice([QtCore.Qt.KeyboardModifier.NoModifier, QtCore.Qt.KeyboardModifier.ControlModifier,
                           QtCore.Qt.KeyboardModifier.ShiftModifier, QtCore.Qt.KeyboardModifier.AltModifier])  # fmt: skip
        angle = QtCore.QPoint(delta, 0) if horizontal else QtCore.QPoint(0, delta)
        event = QtGui.QWheelEvent(
            pos, QtCore.QPointF(widget.mapToGlobal(pos.toPoint())), QtCore.QPoint(0, 0), angle,
            QtCore.Qt.MouseButton.NoButton, mods, QtCore.Qt.ScrollPhase.NoScrollPhase, False,
        )  # fmt: skip
        QtWidgets.QApplication.sendEvent(widget, event)
        return f"delta={delta} horizontal={horizontal} mods={mods}"

    def act_canvas_wheel(self) -> str:
        self.ensure_canvas_page()
        return self.wheel(self.window.canvas)

    def timeline_hot_points(self) -> list:
        view = self.window.timeline
        points = []
        try:
            items = list(view.clip_items())[:200] + list(view.key_items())[:200]
        except Exception:
            items = []
        for item in self.rng.sample(items, min(6, len(items))):
            rect = view.mapFromScene(item.sceneBoundingRect()).boundingRect()
            points += [QtCore.QPointF(rect.left() + 1, rect.center().y()), QtCore.QPointF(rect.center()),
                       QtCore.QPointF(rect.right() - 1, rect.center().y())]  # fmt: skip
        points.append(QtCore.QPointF(self.rng.uniform(0, view.viewport().width()), 6))  # the ruler
        return points

    def ensure_timeline(self) -> None:
        if not self.window.timeline.isVisible():
            self.window.show_page(self.rng.choice(["compose", "animate"]))
            self.pump(10)

    def act_timeline_mouse(self) -> str:
        self.ensure_timeline()
        view = self.window.timeline
        target = view.viewport() if self.rng.random() < 0.85 else view
        return self.mouse_gesture(target, self.timeline_hot_points() if target is view.viewport() else [])

    def act_timeline_wheel(self) -> str:
        self.ensure_timeline()
        return self.wheel(self.window.timeline.viewport())

    def act_layers_mouse(self) -> str:
        layers = self.window.layers
        if not layers.isVisible():
            self.window.show_page("compose")
            self.pump(10)
        tree = layers.list
        items = layers.items()
        hot = []
        for item in self.rng.sample(items, min(5, len(items))):
            rect = tree.visualItemRect(item)
            if rect.isValid():
                hot += [QtCore.QPointF(rect.center()), QtCore.QPointF(rect.right() - 8, rect.center().y()),
                        QtCore.QPointF(rect.left() + 6, rect.center().y())]  # fmt: skip
        detail = self.mouse_gesture(tree.viewport(), hot)
        if "dclick" in detail and self.rng.random() < 0.7:  # a rename editor may be open
            focus = QtWidgets.QApplication.focusWidget()
            if isinstance(focus, QtWidgets.QLineEdit):
                focus.setText(junk(self.rng))
                QTest.keyClick(focus, self.rng.choice([QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Escape]))
                detail += " + renamed"
        return detail

    KEYS = (
        "Delete", "Backspace", "Left", "Right", "Up", "Down", "Space", "Escape", "Return", "Tab", "Home", "End",
        "PageUp", "PageDown", "A", "C", "D", "F", "G", "K", "M", "S", "T", "V", "X", "Z", "Y", "BracketLeft",
        "BracketRight", "Plus", "Minus", "Equal", "0", "1", "2", "5", "F1", "F2", "F5", "F11", "Insert",
    )  # fmt: skip

    def key_target(self):
        rng = self.rng
        candidates = [QtWidgets.QApplication.focusWidget(), self.window.canvas, self.window.timeline,
                      self.window.layers.list, self.window]  # fmt: skip
        candidates = [c for c in candidates if c is not None and c.isVisible()]
        return rng.choice(candidates) if candidates else self.window

    def act_key_press(self) -> str:
        name = self.rng.choice(self.KEYS)
        key = getattr(QtCore.Qt.Key, f"Key_{name}")
        mods = self.random_modifiers()
        target = self.key_target()
        count = self.rng.choice([1, 1, 1, 2, 5])
        for _ in range(count):
            QTest.keyClick(target, key, mods)
        return f"{name} x{count} mods={mods} to {type(target).__name__}"

    def act_shortcut(self) -> str:
        sequences = []
        for action in self.window.findChildren(QtGui.QAction):
            if EXCLUDE.search(action.text()):
                continue
            for seq in action.shortcuts():
                if not seq.isEmpty():
                    sequences.append((seq, action.text()))
        seq, text = self.rng.choice(sequences)
        combo = seq[0]
        target = self.key_target()
        self.action = f"shortcut {seq.toString()} ({text})"
        QTest.keyClick(target, combo.key(), combo.keyboardModifiers())
        return f"{seq.toString()} ({text.replace('&', '')}) to {type(target).__name__}"

    def act_undo_burst(self) -> str:
        Qt = QtCore.Qt
        n = self.rng.randint(1, 40)
        m = self.rng.randint(0, n + 5)
        target = self.window if self.rng.random() < 0.7 else self.key_target()
        for _ in range(n):
            QTest.keyClick(target, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        for _ in range(m):
            if self.rng.random() < 0.5:
                QTest.keyClick(target, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
            else:
                QTest.keyClick(target, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        return f"undo x{n}, redo x{m} to {type(target).__name__}"

    def input_widgets(self, root) -> list:
        W = QtWidgets
        kinds = (W.QLineEdit, W.QPlainTextEdit, W.QTextEdit, W.QAbstractSpinBox, W.QComboBox, W.QCheckBox, W.QSlider)
        found = []
        for w in root.findChildren(W.QWidget):
            if not isinstance(w, kinds) or not w.isVisible() or not w.isEnabled():
                continue
            if isinstance(w, W.QLineEdit) and isinstance(w.parent(), (W.QAbstractSpinBox, W.QComboBox)):
                continue
            found.append(w)
        return found

    def act_edit_field(self) -> str:
        W, Qt, rng = QtWidgets, QtCore.Qt, self.rng
        root = self.window.properties if rng.random() < 0.65 and self.window.properties.isVisible() else self.window
        widgets = self.input_widgets(root) or self.input_widgets(self.window)
        if not widgets:
            return "no field"
        w = rng.choice(widgets)
        name = f"{type(w).__name__}({w.objectName() or w.accessibleName() or ''})"
        self.action = f"edit_field {name}"
        w.setFocus(Qt.FocusReason.MouseFocusReason)
        if isinstance(w, W.QAbstractSpinBox):
            edit = w.findChild(W.QLineEdit)
            r = rng.random()
            if r < 0.6 and edit is not None:
                text = junk(rng, "number") if rng.random() < 0.8 else junk(rng)
                edit.selectAll()
                if len(text) > 200:
                    edit.setText(text)
                else:
                    QTest.keyClicks(edit, text)
                QTest.keyClick(edit, rng.choice([Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab]))
                detail = f"typed {text[:40]!r}"
            elif r < 0.8:
                key = rng.choice([Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown])
                count = rng.choice([1, 3, 30])
                for _ in range(count):
                    QTest.keyClick(w, key)
                detail = f"{key} x{count}"
            else:
                detail = "wheel " + self.wheel(w)
        elif isinstance(w, W.QLineEdit):
            text = junk(rng)
            if rng.random() < 0.5 or len(text) > 200:
                w.setText(text)
            else:
                w.selectAll()
                QTest.keyClicks(w, text)
            end = rng.choice([Qt.Key.Key_Return, Qt.Key.Key_Return, Qt.Key.Key_Tab, Qt.Key.Key_Escape])
            QTest.keyClick(w, end)
            detail = f"text {text[:40]!r} then {end}"
        elif isinstance(w, (W.QPlainTextEdit, W.QTextEdit)):
            text = junk(rng, "code" if rng.random() < 0.3 else "any")
            if rng.random() < 0.5 or len(text) > 200:
                (w.setPlainText(text) if isinstance(w, W.QPlainTextEdit) else w.setText(text))
            else:
                QTest.keyClicks(w, text)
            if rng.random() < 0.6:
                QTest.keyClick(w, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
            else:
                self.window.canvas.setFocus()  # focus out commits
            detail = f"text {text[:40]!r}"
        elif isinstance(w, W.QComboBox):
            key = rng.choice([Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Home, Qt.Key.Key_End])
            count = rng.randint(1, 4)
            for _ in range(count):
                QTest.keyClick(w, key)
            detail = f"{key} x{count} -> {w.currentText()[:30]!r}"
        elif isinstance(w, W.QCheckBox):
            w.click()
            detail = f"toggled -> {w.isChecked()}"
        else:  # QSlider
            key = rng.choice([Qt.Key.Key_PageUp, Qt.Key.Key_PageDown, Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_Left])
            QTest.keyClick(w, key)
            detail = f"{key}"
        return f"{name}: {detail}"

    def act_click_button(self) -> str:
        W = QtWidgets
        buttons = [
            b for b in self.window.findChildren(W.QAbstractButton)
            if b.isVisible() and b.isEnabled() and not EXCLUDE.search(b.text() or "")
        ]  # fmt: skip
        if not buttons:
            return "no button"
        b = self.rng.choice(buttons)
        label = b.text() or b.toolTip()[:40] or b.accessibleName() or type(b).__name__
        self.action = f"click_button {label!r}"
        self.log_step(f"click {label!r}")
        self.mouse_click_widget(b)
        return label

    def act_play(self) -> str:
        window = self.window
        if self.rng.random() < 0.15:
            window.set_play_speed(self.rng.choice([0.05, 0.25, 2.0, 16.0, 1.0]))
        if self.rng.random() < 0.1:
            window._set_loop(not window.loop_playback)
        if self.rng.random() < 0.5:
            QTest.keyClick(window, QtCore.Qt.Key.Key_Space)
        else:
            window.toggle_play()
        wait = self.rng.randint(30, 1500)
        self.pump(wait)
        if self.rng.random() < 0.7:
            window.toggle_play()
        return f"played {wait} ms, playing={window.play_timer.isActive()}"

    def act_playhead(self) -> str:
        rng = self.rng
        r = rng.random()
        if r < 0.4:
            self.ensure_timeline()
            vp = self.window.timeline.viewport()
            start = QtCore.QPointF(rng.uniform(0, vp.width()), rng.uniform(2, 14))
            points = [start] + [QtCore.QPointF(rng.uniform(-50, vp.width() + 50), rng.uniform(-5, 20)) for _ in range(rng.randint(1, 8))]
            self.gesture(vp, points)
            return "ruler drag"
        if r < 0.7:
            slider = self.window.slider
            if slider.isVisible():
                start = self.random_point(slider)
                self.gesture(slider, self.path_from(slider, start))
                return "slider drag"
        key = rng.choice([QtCore.Qt.Key.Key_Left, QtCore.Qt.Key.Key_Right, QtCore.Qt.Key.Key_Home,
                          QtCore.Qt.Key.Key_End, QtCore.Qt.Key.Key_BracketLeft, QtCore.Qt.Key.Key_BracketRight])  # fmt: skip
        n = rng.randint(1, 20)
        for _ in range(n):
            QTest.keyClick(self.window, key)
        return f"key {key} x{n}"

    def act_context_menu(self) -> str:
        rng = self.rng
        choices = [self.window.timeline.viewport(), self.window.layers.list.viewport(), self.window.canvas]
        visible = [c for c in choices if c.isVisible()] or [self.window.canvas]
        widget = rng.choice(visible)
        hot = self.timeline_hot_points() if widget is self.window.timeline.viewport() else []
        pos = rng.choice(hot) if hot and rng.random() < 0.6 else self.random_point(widget)
        self.gesture(widget, [pos], button=QtCore.Qt.MouseButton.RightButton, kind="click")
        # Some widgets only answer the context-menu event itself
        if rng.random() < 0.5 and widget.isVisible():
            event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Reason.Mouse, pos.toPoint(),
                                            widget.mapToGlobal(pos.toPoint()))  # fmt: skip
            QtWidgets.QApplication.sendEvent(widget, event)
        return f"{type(widget).__name__} at ({pos.x():.0f},{pos.y():.0f})"

    def act_open_project(self) -> str:
        rng = self.rng
        r = rng.random()
        if r < 0.5:
            name = self.main_project if rng.random() < 0.7 else rng.choice(list(self.pristine))
            self.open_project(name)
            return f"load {name}"
        if r < 0.75:
            self.window.open_dialog()  # the fake dialog answers with a fixture
            return "File > Open"
        if r < 0.85:
            self.window.open_example()
            return "Open Example"
        if r < 0.95:
            recent = self.window.recent_paths()
            if recent:
                self.window.open_recent(rng.choice(recent))
                return "Open Recent"
        target = rng.choice([f for f in self.fixtures if f.suffix == ".json"])
        self.window.load(target)
        return f"load fixture {target.name}"

    def act_new_project(self) -> str:
        if self.rng.random() < 0.7:
            for path, action in self._menu_actions():
                if path.startswith("File > New"):
                    action.trigger()
                    return "File > New"
        from manim_studio.ui.shell.new_project_dialog import available_templates

        key = self.rng.choice([t.key for t in available_templates()])
        self.window.new_project(key)
        return f"new_project({key})"

    def wait_export(self, running, max_seconds: float) -> bool:
        end = time.monotonic() + max_seconds
        while running() and time.monotonic() < end:
            self.pump(50)
        return not running()

    def act_export_dialog(self) -> str:
        window = self.window
        if window.project is None:
            return "no project"
        window.show_export_dialog()
        dialog = window.export_dialog
        if dialog is None:
            return "no dialog"
        if dialog.running:
            dialog.cancel()
            return "cancelled a running export"
        out = self.work / "exports" / f"dialog_{self.step}.mp4"
        dialog.path.setText(str(out))
        dialog.start()
        wait = self.rng.uniform(0.1, 8.0)
        self.wait_export(lambda: dialog.running, wait)
        if dialog.running:
            if self.rng.random() < 0.85 or window.project.canvas.duration > 12:  # long scenes: always cancel
                dialog.cancel()
                time.sleep(0.05)
                partial_left = [p.name for p in out.parent.glob(out.stem + "*")]
                return f"cancelled after {wait:.1f} s; left: {partial_left}"
            done = self.wait_export(lambda: dialog.running, 150)
            if not done:
                self._finding("slow", "an export dialog render took over 150 s", self.action, "cosmetic")
                dialog.cancel()
        result = dialog.status.text()
        if "failed" in result.lower():
            self._finding("export-failed", re.sub(r"\d+", "#", result)[:160], result, "exception")
        return f"finished: {result[:100]!r}"

    def act_deliver_export(self) -> str:
        window, rng = self.window, self.rng
        if window.project is None:
            return "no project"
        window.show_page("deliver")
        self.pump(10)
        page = window.pages.pages["deliver"]
        r = rng.random()
        if page.busy and r < 0.6:
            page.cancel_selected()
            return "cancel selected"
        if r < 0.1:
            page.clear_finished()
            return "clear finished"
        page.choose_destination(rng.choice(["draft", "draft", "web", "python"]))
        if page._destination.key == "python":
            return "python destination"
        page.fps.setValue(rng.choice([5, 10, 12]))
        index = page.range.findData("times")
        if index >= 0:
            page.range.setCurrentIndex(index)
            page.start.setValue(0.0)
            page.end.setValue(min(window.project.canvas.duration, rng.uniform(0.2, 2.0)))
        page.path.setText(str(self.work / "exports" / f"deliver_{self.step}.mp4"))
        page.render_now()
        wait = rng.uniform(0.2, 10.0)
        self.wait_export(lambda: page.busy, wait)
        if page.busy:
            if rng.random() < 0.7:
                page.cancel_selected()
                return f"cancelled after {wait:.1f} s"
            done = self.wait_export(lambda: page.busy, 120)
            if not done:
                self._finding("slow", "a short draft render on Deliver took over 120 s", self.action, "cosmetic")
                page.cancel_all()
        status = page.queue_status.text()
        if "failed" in status.lower():
            self._finding("export-failed", re.sub(r"\d+", "#", status)[:160], status, "exception")
        return f"done: {status[:100]!r}"

    def act_resize_window(self) -> str:
        rng, window = self.rng, self.window
        r = rng.random()
        if r < 0.15:
            window.showMaximized()
            return "maximized"
        if r < 0.25:
            window.showNormal()
            window.resize(1280, 820)
            return "normal"
        size = (rng.randint(200, 2400), rng.randint(150, 1500))
        window.resize(*size)
        return f"{size}"

    def act_close_windows(self) -> str:
        others = [
            w for w in QtWidgets.QApplication.topLevelWidgets()
            if w is not self.window and w.isVisible() and not w.isModal()
        ]  # fmt: skip
        if not others:
            if self.rng.random() < 0.3:
                QTest.keyClick(self.window, QtCore.Qt.Key.Key_Escape)
            return "nothing to close"
        w = self.rng.choice(others)
        label = f"{type(w).__name__} {w.windowTitle()[:30]!r}"
        w.close()
        return label

    def act_save_roundtrip(self) -> str:
        window = self.window
        if window.project is None or window.path is None:
            return "nothing to save"
        try:
            inside = window.path.resolve().is_relative_to(self.run_dir.resolve())
        except (OSError, ValueError):
            inside = False
        if not inside:
            return f"not saving outside the run folder: {window.path}"
        via_keys = self.rng.random() < 0.5
        if via_keys:
            QTest.keyClick(window, QtCore.Qt.Key.Key_S, QtCore.Qt.KeyboardModifier.ControlModifier)
        else:
            window.save()
        self.pump(10)
        if not window.document.undo_stack.isClean():
            return f"save did not happen (via {'Ctrl+S' if via_keys else 'save()'})"
        on_disk = Project.model_validate_json(window.path.read_text(encoding="utf-8"))
        if on_disk != window.document.project:
            self._finding("data-loss", "the saved file differs from the project in the editor", self.action, "data-loss")
        return f"saved and read back {window.path.name}"

    def act_undo_symmetry(self) -> str:
        window = self.window
        stack = window.document.undo_stack
        if window.project is None or window.builds.busy or window.document.dragging:
            return "busy"
        n = self.rng.randint(1, 15)
        before = window.document.project
        index = stack.index()
        for _ in range(n):
            stack.undo()
        undone = index - stack.index()
        for _ in range(undone):
            stack.redo()
        self.pump(0)
        after = window.document.project
        if stack.index() != index:
            self._finding("data-loss", "redo did not return to the same history position", self.action, "data-loss")
        elif after != before:
            diff = self.describe_difference(before, after)
            self._finding("data-loss", f"undo then redo changed the project: {diff[:120]}",
                          diff + "\n--- recent ---\n" + "\n".join(self.history), "data-loss")  # fmt: skip
        return f"undo/redo x{undone}"

    def describe_difference(self, a, b) -> str:
        da, db = a.model_dump(), b.model_dump()
        out = []

        def walk(x, y, path):
            if len(out) > 5:
                return
            if type(x) is not type(y):
                out.append(f"{path}: {x!r:.80} != {y!r:.80}")
            elif isinstance(x, dict):
                for key in sorted(set(x) | set(y), key=str):
                    walk(x.get(key), y.get(key), f"{path}.{key}")
            elif isinstance(x, list):
                if len(x) != len(y):
                    out.append(f"{path}: length {len(x)} != {len(y)}")
                for i, (u, v) in enumerate(zip(x, y)):
                    walk(u, v, f"{path}[{i}]")
            elif x != y and not (isinstance(x, float) and math.isnan(x) and math.isnan(y)):
                out.append(f"{path}: {x!r:.80} != {y!r:.80}")

        walk(da, db, "project")
        return "; ".join(out)

    # -- the large project (soak) -----------------------------------------------------------------

    def build_large(self, count: int) -> Path:
        from manim_studio.core.model.schema import Canvas, Spec

        rng = random.Random(self.seed)
        p = Project(canvas=Canvas(width_px=1280, height_px=720, fps=30, background="#101820", duration=24.0))

        def apply(edit):
            nonlocal p
            p = edit.project

        kinds = ["Square", "Circle", "Star", "Dot", "Rectangle", "Triangle", "Line", "Arrow", "Text",
                 "MathTex", "DecimalNumber", "RightTriangle"]  # fmt: skip
        texts = ["alpha", "beta", "gamma", "ção", "Hello", "World"]
        tex = [r"a^2+b^2=c^2", r"e^{i\pi}+1=0", r"\int_0^1 x\,dx", r"\sum_{n=1}^\infty \frac{1}{n^2}"]
        entrances = ["FadeIn", "Create", "GrowFromCenter", "Write", "DrawBorderThenFill"]
        for i in range(count):
            kind = kinds[i % len(kinds)]
            extra = {}
            if kind == "Text":
                extra = {"text": rng.choice(texts)}
            elif kind == "MathTex":
                extra = {"text": rng.choice(tex)}
            spec = adapter.default_spec(kind, **extra)
            layer_id = f"L{i:03d}"
            apply(edits.add_layer(p, spec, layer_id=layer_id))
            x, y = -6.5 + (i % 20) * 0.68, 3.5 - (i // 20) * 0.45
            apply(edits.update_layer(p, layer_id, base={"position": (x, y), "scale": 0.3}))
            start = rng.uniform(0, 20)
            kind_in = rng.choice(entrances if kind in ("Text", "MathTex") else entrances[:3])
            try:
                apply(edits.add_clip(p, layer_id, kind_in, start, rng.uniform(0.3, 1.5)))
            except Exception:
                pass
            if i % 3 == 0:
                apply(edits.set_key(p, layer_id, "position", start + 1, (x, y)))
                apply(edits.set_key(p, layer_id, "position", start + 2.5, (x + rng.uniform(-1, 1), y - 0.5)))
            if i % 5 == 0:
                apply(edits.set_key(p, layer_id, "rotation", 1.0, 0.0))
                apply(edits.set_key(p, layer_id, "rotation", 20.0, 360.0))
        path = self.work / "fixtures" / "big.json"
        path.write_text(p.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
        print(f"generated {path} with {len(p.layers)} layers", flush=True)
        return path

    # -- churn ------------------------------------------------------------------------------------

    CHURN_EDITS = ("add_object", "edit_field", "canvas_mouse", "timeline_mouse", "undo_burst", "key_press",
                   "layers_mouse", "playhead")  # fmt: skip

    def run_churn(self) -> None:
        rng = self.rng
        names = [n for n in ("euler", "graphs", "showcase", "angular") if n in self.pristine]
        # (A) one window: open a project, change it a little, open the next (the last one is given back)
        self.main_project = "euler"
        self.window = self.new_window()
        self.window.ask_unsaved = lambda: "discard"
        self.window.ask_recover = lambda entries: "later"
        churn_a = []
        t0 = time.monotonic()
        for it in range(self.options.iterations):
            if time.monotonic() > self.hard_deadline:
                break
            self.step = it
            name = names[it % len(names)]
            self.action = f"churn-A open {name}"
            self.open_project(name)
            self.pump(150)
            for _ in range(rng.randint(2, 5)):
                self.do_step(rng.choice(self.CHURN_EDITS))
            self.ensure_window()
            self.window.ask_unsaved = lambda: "discard"
            self.window.ask_recover = lambda entries: "later"
            self.pump(100)
            gc.collect()
            self.pump(20)
            s = self.sample(f"churn-A {it}")
            churn_a.append((it, s["editor_commit"], s["editor_ws"], s["total_commit"], s["gc_objects"], len(s["helpers"])))
            if it % 10 == 0:
                print(f"churn A {it:4d}: editor {s['editor_commit']} MB commit / {s['editor_ws']} ws,"
                      f" total {s['total_commit']}, gc objects {s['gc_objects']}, helpers {len(s['helpers'])}",
                      flush=True)  # fmt: skip
        self.phase_results["churn_a"] = {"iterations": len(churn_a), "seconds": round(time.monotonic() - t0, 1),
                                         "rows": churn_a}  # fmt: skip
        self.final_close(self.window, "churn-A window")
        # (B) windows: open a window, a project, change it, close the window
        churn_b = []
        survivors_total = []
        t0 = time.monotonic()
        for it in range(self.options.windows):
            if time.monotonic() > self.hard_deadline:
                break
            self.step = 10_000 + it
            self.action = f"churn-B window {it}"
            self.window = self.new_window()
            self.window.ask_unsaved = lambda: "discard"
            self.window.ask_recover = lambda entries: "later"
            self.open_project(names[it % len(names)])
            self.pump(300)
            for _ in range(rng.randint(2, 4)):
                self.do_step(rng.choice(self.CHURN_EDITS))
            self.pump(rng.choice([200, 1500, 4000]))  # sometimes the helpers are still starting
            before = set(self.tree())
            w = self.window
            if shiboken6.isValid(w):
                w.ask_unsaved = lambda: "discard"
                w.ask_stop_export = lambda: "stop"
                w.close()
                w.deleteLater()
            self.pump(50)
            end = time.monotonic() + 10
            alive = [p for p in before if lifeline.process_alive(p)]
            while alive and time.monotonic() < end:
                self.pump(100)
                alive = [p for p in before if lifeline.process_alive(p)]
            if alive:
                survivors_total.append((it, [(p, self.procs.role(p)) for p in alive]))
                self._finding("leak", "helper processes outlived a closed window (10 s)",
                              f"window {it}: {[(p, self.procs.role(p)) for p in alive]}", "leak")  # fmt: skip
            gc.collect()
            self.pump(20)
            s = self.sample(f"churn-B {it}")
            churn_b.append((it, s["editor_commit"], s["editor_ws"], s["total_commit"], s["gc_objects"], len(before)))
            if it % 5 == 0:
                print(f"churn B {it:4d}: editor {s['editor_commit']} MB commit / {s['editor_ws']} ws,"
                      f" helpers before close {len(before)}, top-levels {s['toplevels']}", flush=True)  # fmt: skip
        self.phase_results["churn_b"] = {"windows": len(churn_b), "seconds": round(time.monotonic() - t0, 1),
                                         "rows": churn_b, "survivors": survivors_total}  # fmt: skip
        self.window = self.new_window()  # for the final checks
        self.main_project = "euler"
        self.open_project("euler")

    # -- the end ----------------------------------------------------------------------------------

    def final_checks(self) -> None:
        self.ensure_window()
        window = self.window
        # stop anything running so the idle probe measures rest
        if window.export_dialog is not None and window.export_dialog.running:
            window.export_dialog.cancel()
        window.pages.pages["deliver"].cancel_all()
        probe_seconds = self.options.idle_probe
        print(f"idle probe: {probe_seconds:.0f} s", flush=True)
        self.step = 10**6
        self.action = "idle probe"
        self.sample("idle probe start")
        end = time.monotonic() + probe_seconds
        mid = None
        while time.monotonic() < end:
            self.pump(200)
            if mid is None and time.monotonic() > end - min(15.0, probe_seconds / 2):
                mid = self.sample("idle probe (last 15 s start)")
        last = self.sample("idle probe end")
        hot = [(pid, role, cpu) for pid, role, _c, _w, cpu in last["helpers"] if cpu is not None and cpu > 10]
        if last["editor_cpu_pct"] is not None and last["editor_cpu_pct"] > 10:
            hot.append((os.getpid(), "editor", last["editor_cpu_pct"]))
        self.phase_results["idle_probe"] = {"last": last, "hot": hot}
        if hot:
            self._finding("runaway-cpu", "a process kept a core busy while the editor was idle",
                          json.dumps(hot), "leak")  # fmt: skip
        self.final_close(window, "final")

    def final_close(self, window, label: str) -> None:
        """Close the window: every helper it started must end."""
        if not shiboken6.isValid(window):
            return
        helpers = [(p, self.procs.role(p)) for p in self.tree()]
        window.ask_unsaved = lambda: "discard"
        window.ask_stop_export = lambda: "stop"
        started = time.monotonic()
        window.close()
        took = time.monotonic() - started
        self.pump(50)
        end = time.monotonic() + 15
        alive = [h for h in helpers if lifeline.process_alive(h[0])]
        while alive and time.monotonic() < end:
            self.pump(100)
            alive = [h for h in helpers if lifeline.process_alive(h[0])]
        after_window = list(alive)
        children.stop_all()  # what aboutToQuit does
        self.pump(50)
        time.sleep(0.5)
        alive_after_quit = [h for h in helpers if lifeline.process_alive(h[0])]
        result = {
            "helpers_before_close": helpers,
            "close_seconds": round(took, 2),
            "alive_15s_after_close": after_window,
            "alive_after_stop_all": alive_after_quit,
        }
        self.phase_results[f"close:{label}"] = result
        print(f"close ({label}): helpers {helpers}, close took {took:.2f} s, alive after close {after_window},"
              f" after stop_all {alive_after_quit}", flush=True)  # fmt: skip
        if after_window:
            self._finding("leak", f"helpers outlived the closed window ({label})", json.dumps(result), "leak")
        if took > 5:
            self._finding("slow", f"closing the window took {took:.1f} s ({label})", json.dumps(result), "cosmetic")
        for pid, _role in alive_after_quit:  # never leave a process behind
            lifeline.kill_tree(pid)
        window.deleteLater()
        self.pump(20)

    # -- results ----------------------------------------------------------------------------------

    def slope(self, xs: list[float], ys: list[float]) -> float | None:
        pts = [(x, y) for x, y in zip(xs, ys) if y is not None]
        if len(pts) < 3:
            return None
        n = len(pts)
        mx = sum(x for x, _ in pts) / n
        my = sum(y for _, y in pts) / n
        den = sum((x - mx) ** 2 for x, _ in pts)
        return sum((x - mx) * (y - my) for x, y in pts) / den if den else None

    def memory_summary(self) -> dict:
        monkey = [s for s in self.samples if s["label"] == "" and s["step"] >= 0]
        out = {}
        if monkey:
            tail = monkey[len(monkey) // 10:]  # skip the warm-up tenth
            xs = [s["step"] for s in tail]
            for key in ("editor_commit", "editor_ws", "total_commit", "total_ws", "gc_objects", "editor_handles"):
                value = self.slope(xs, [s[key] for s in tail])
                out[f"{key}_per_1000_steps"] = round(value * 1000, 2) if value is not None else None
        all_samples = [s for s in self.samples if s["editor_commit"] is not None]
        if all_samples:
            out["peak_editor_commit"] = max(s["editor_commit"] for s in all_samples)
            out["peak_editor_ws"] = max(s["editor_ws"] for s in all_samples)
            out["peak_total_commit"] = max(s["total_commit"] for s in all_samples)
            out["peak_total_ws"] = max(s["total_ws"] for s in all_samples)
            out["peak_helpers"] = max(len(s["helpers"]) for s in all_samples)
            out["start"] = {k: all_samples[0][k] for k in ("editor_commit", "editor_ws", "total_commit", "total_ws")}
            out["end"] = {k: all_samples[-1][k] for k in ("editor_commit", "editor_ws", "total_commit", "total_ws")}
            out["max_gdi_user"] = (max(s["gdi"] for s in all_samples), max(s["user"] for s in all_samples))
            out["max_toplevels"] = max(s["toplevels"] for s in all_samples)
        for name, index in (("churn_a", 1), ("churn_b", 1)):
            rows = self.phase_results.get(name, {}).get("rows")
            if rows and len(rows) > 25:
                tail = rows[20:]
                for col, key in ((1, "editor_commit"), (2, "editor_ws"), (3, "total_commit"), (4, "gc_objects")):
                    value = self.slope([r[0] for r in tail], [r[col] for r in tail])
                    out[f"{name}_{key}_per_iteration"] = round(value, 3) if value is not None else None
                out[f"{name}_first_last_editor_commit"] = (rows[0][1], rows[19][1], rows[-1][1])
        roles = collections.Counter(self.helper_pids.values())
        out["distinct_helper_pids_by_role"] = dict(roles)
        return out

    def write_results(self, aborted: bool = False) -> None:
        try:
            result = {
                "phase": self.options.phase,
                "seed": self.seed,
                "aborted": aborted,
                "argv": sys.argv,
                "package": str(getattr(self, "package", "")),
                "real_helpers": not self.options.fake_helpers,
                "seconds": round(time.monotonic() - self.started, 1),
                "last_step": self.step,
                "phase_results": self.phase_results,
                "memory": self.memory_summary(),
                "findings": sorted(self.findings.values(), key=lambda f: (f["severity"], f["first_step"])),
                "qt_and_log_warnings": [
                    {"message": k, "count": v, "first": self.qt_first.get(k)} for k, v in self.qt_messages.most_common()
                ],
                "dialogs_seen": dict(self.dialogs_seen.most_common()),
                "drag_rescues": self.drag_rescues,
                "windows_recreated": self.windows_recreated,
                "redirected_exports": self.redirected_exports[:50],
                "opened_urls": self.opened_urls[:50],
                "samples": self.samples,
            }
            (self.run_dir / "results.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
            self.steps_log.flush()
        except Exception:
            traceback.print_exc()

    def print_summary(self) -> None:
        print("\n" + "=" * 100)
        print(f"phase {self.options.phase}  seed {self.seed}  {time.monotonic() - self.started:.0f} s  run dir {self.run_dir}")
        for key, value in self.phase_results.items():
            if isinstance(value, dict) and "rows" in value:
                value = {k: v for k, v in value.items() if k != "rows"}
            print(f"  {key}: {json.dumps(value, default=str)[:600]}")
        print("  memory: " + json.dumps(self.memory_summary(), default=str))
        print(f"  drag rescues {self.drag_rescues}, windows recreated {self.windows_recreated},"
              f" redirected exports {len(self.redirected_exports)}, opened urls {len(self.opened_urls)}")  # fmt: skip
        print("  findings:")
        for f in sorted(self.findings.values(), key=lambda f: (f["severity"], f["first_step"])):
            print(f"   [{f['severity']}] x{f['count']} first step {f['first_step']} ({f['first_action'][:60]}): {f['key'][:160]}")
        print("  top Qt/log warnings:")
        for k, v in self.qt_messages.most_common(25):
            print(f"   x{v}  {k[:160]}  (first {self.qt_first.get(k)})")
        print("=" * 100, flush=True)


EXCLUDE = re.compile(r"\b(quit|exit)\b", re.IGNORECASE)
OFFSCREEN_NOISE = ("This plugin does not support",)  # the offscreen platform, not the editor


class _Capture:
    """A logging handler that hands warnings and errors to the harness."""

    def __init__(self, harness: Harness) -> None:
        import logging

        self.harness = harness
        self.level = logging.WARNING
        self._handler = logging.Handler(logging.WARNING)
        self._handler.emit = self.emit  # type: ignore[method-assign]

    def __getattr__(self, name):
        return getattr(self._handler, name)

    def handle(self, record) -> bool:
        if record.levelno >= self.level:
            self.emit(record)
        return True

    def emit(self, record) -> None:
        try:
            self.harness.record_log(record)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
