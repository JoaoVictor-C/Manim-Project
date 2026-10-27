"""B74 - what the editor and its helper processes hold in memory.

Starts the real editor (without a screen) three ways and prints, for each process below it, the committed
(private) memory and the working set, then their sums:

* **welcome** - no project: the welcome page runs no helper;
* **project** - ``examples/euler.json`` open, every helper up (build worker, frame renderer);
* **released** - the same, a while after the helpers were released for having nothing to do
  (``MANIM_STUDIO_IDLE_SECONDS``).

``--threads N`` sets ``MANIM_STUDIO_NATIVE_THREADS`` (the default 1 is the editor's; 0 leaves numpy's own
choice, one thread pool per processor core). Committed memory is what the system must back with RAM or the
page file; the working set is only what is resident now, and a trimmed one has not been freed.

    python benchmarks/bench_editor_memory.py [--threads N] [--only welcome project released]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from manim_studio import lifeline

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "euler.json"
RELEASE_AFTER = 8  # seconds of rest before a helper is released in the "released" run


def memory(pid: int) -> tuple[float, float]:
    """(committed MB, working set MB) of a process; (0, 0) when it cannot be read."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes as wt

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

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.OpenProcess.restype = wt.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(Counters), wt.DWORD]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # query limited information
        if not handle:
            return 0.0, 0.0
        try:
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return 0.0, 0.0
            return counters.PrivateUsage / 2**20, counters.WorkingSetSize / 2**20
        finally:
            kernel32.CloseHandle(handle)
    try:  # Linux: resident anonymous memory is the private part
        fields = dict(
            line.split(":", 1) for line in Path(f"/proc/{pid}/status").read_text().splitlines() if ":" in line
        )
        kb = lambda name: float(fields[name].split()[0]) / 1024  # noqa: E731
        return kb("RssAnon"), kb("VmRSS")
    except (OSError, KeyError):
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout
        rss = float(out.strip() or 0) / 1024
        return rss, rss


def role(pid: int) -> str:
    """What a process is: the module it runs, or its program."""
    if sys.platform == "win32":
        command = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
            ],
            capture_output=True,
            text=True,
        ).stdout
    else:
        command = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True
        ).stdout
    for name in ("processes.worker", "processes.preview", "processes.code_runner", "processes.voice"):
        if name in command:
            return name.split(".")[1]
    if "manim_studio" in command and " edit" in command:
        return "editor"
    return Path(command.strip().split(" ")[0].strip('"')).name or "?"


def run(label: str, threads: int, project: Path | None, idle: int | None, wait: float) -> tuple[float, float]:
    scratch = Path(tempfile.mkdtemp(prefix="manim-studio-bench-memory-"))
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "MANIM_STUDIO_SETTINGS": str(scratch / "settings.ini"),
        "MANIM_STUDIO_LOG_DIR": str(scratch / "logs"),
        "MANIM_STUDIO_RECOVERY": str(scratch / "recovery"),
        "MANIM_STUDIO_AUDIO": "0",
        "MANIM_STUDIO_MOTION": "0",
    }
    for name in lifeline.POOLS:  # importing manim_studio here set them: the editor sets its own
        env.pop(name, None)
    if threads:
        env["MANIM_STUDIO_NATIVE_THREADS"] = str(threads)
    else:
        for name in lifeline.POOLS:  # numpy's own choice: a pool per core
            env[name] = str(os.cpu_count() or 1)
    if idle:
        env["MANIM_STUDIO_IDLE_SECONDS"] = str(idle)
    command = [sys.executable, "-m", "manim_studio", "edit", *([str(project)] if project else [])]
    editor = subprocess.Popen(
        command, env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        time.sleep(wait)
        pids = [editor.pid, *lifeline.descendants(editor.pid)]
        rows = [(pid, role(pid), *memory(pid)) for pid in pids]
        rows = [row for row in rows if row[2] > 0]
        print(f"\n{label}")
        for pid, name, committed, working in rows:
            print(f"  {pid:>7}  {name:<12} committed {committed:7.0f} MB   working set {working:7.0f} MB")
        total = sum(row[2] for row in rows), sum(row[3] for row in rows)
        print(f"  {'':>7}  {'total':<12} committed {total[0]:7.0f} MB   working set {total[1]:7.0f} MB")
        return total
    finally:
        lifeline.kill_tree(editor.pid)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--threads", type=int, default=1, help="native threads per process (0: numpy's default)"
    )
    parser.add_argument("--only", nargs="+", choices=["welcome", "project", "released"])
    options = parser.parse_args()
    wanted = options.only or ["welcome", "project", "released"]
    if "welcome" in wanted:
        run("welcome page (no project)", options.threads, None, None, 12)
    if "project" in wanted:
        run("project open, helpers up", options.threads, EXAMPLE, None, 30)
    if "released" in wanted:
        run(
            f"project open, helpers released ({RELEASE_AFTER} s idle)",
            options.threads,
            EXAMPLE,
            RELEASE_AFTER,
            60,
        )


if __name__ == "__main__":
    main()
