"""Helper processes that end with the editor, and native thread pools that stay small.

The editor runs helper processes: the build worker, the frame renderer, code renderers, exports, the voice
and import helpers. Each is a Python process with Manim loaded, so each is worth a hundred megabytes while
it lives and none may outlive the editor - not when it is closed, and not when it is killed or crashes.
Three layers hold that, from the outside in:

* **a job object** (Windows): every helper the editor starts is put in one job that the operating system
  closes when the editor's process ends, however it ends; closing it ends every process in it, the helpers'
  own children (LaTeX, ffmpeg) included. ``adopt(pid)``.
* **a watcher in each helper** (every platform): ``die_with_editor()`` ends the helper when the editor that
  started it (``MANIM_STUDIO_EDITOR_PID``) is gone. It covers a platform without job objects and a helper that
  could not be put in the job.
* **the editor's own bookkeeping**: it stops what it started when its window closes
  (``ui.services.children``), and ``kill_tree`` ends a helper together with everything it started.

Separately, ``limit_native_threads()`` keeps numpy's BLAS and OpenMP from starting one thread per processor
core: each of those threads reserves tens of megabytes of address space the moment numpy loads (about
700 MB per process on a twelve-core machine, five or more processes at once), for work that is a few
hundred numbers at a time here. ``MANIM_STUDIO_NATIVE_THREADS=N`` raises it; a pool variable already set
is left alone.

Nothing here imports the rest of the package: it is used by the editor, the helpers and the package itself.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
import time

EDITOR_PID = "MANIM_STUDIO_EDITOR_PID"  # set for every helper: the editor that started it
SWITCH = "MANIM_STUDIO_LIFELINE"  # "0": no job object and no watcher (to debug a helper that must outlive it)
NATIVE_THREADS = "MANIM_STUDIO_NATIVE_THREADS"  # how many threads numpy's libraries may start (default 1)
POOLS = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)
POLL_SECONDS = 1.0  # how often a helper looks for its editor where it cannot wait for it (not Windows)

# win32 constants
_SYNCHRONIZE = 0x00100000
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_QUERY_LIMITED = 0x1000
_WAIT_TIMEOUT = 258
_ERROR_ACCESS_DENIED = 5
_KILL_ON_JOB_CLOSE = 0x2000
_JOB_EXTENDED_LIMITS = 9
_SNAPSHOT_PROCESSES = 0x2

_job: object | None = None  # the handle of the editor's job (kept for as long as the editor lives)
_win: object | None = None


# -- native thread pools --------------------------------------------------------------------------


def limit_native_threads() -> None:
    """Cap numpy's native thread pools (before numpy is imported); variables already set win."""
    count = os.environ.get(NATIVE_THREADS, "1")
    if not count.isdigit() or int(count) < 1:
        count = "1"
    for name in POOLS:
        os.environ.setdefault(name, count)


# -- the editor's id ------------------------------------------------------------------------------


def editor_environment() -> dict[str, str]:
    """What a helper needs to know about the editor that starts it."""
    return {EDITOR_PID: str(os.getpid())}


# -- is a process there ---------------------------------------------------------------------------


def process_alive(pid: int) -> bool:
    """Whether a process with this id is running."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        win = _windows()
        handle = win.kernel32.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED, False, pid)
        if not handle:
            return win.ctypes.get_last_error() == _ERROR_ACCESS_DENIED  # there, but not ours to open
        try:
            return win.kernel32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
        finally:
            win.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return not _is_zombie(pid)


def _is_zombie(pid: int) -> bool:
    """A finished child nobody has waited for yet still answers ``kill(pid, 0)`` (Linux)."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as handle:
            return handle.read().rpartition(")")[2].split()[0] == "Z"
    except (OSError, IndexError):
        return False


# -- a helper ends with its editor ----------------------------------------------------------------


def die_with_editor(poll: float = POLL_SECONDS) -> bool:
    """In a helper: end this process when the editor that started it is gone.

    Does nothing (False) when started by hand, with no editor named. Starts a daemon thread otherwise (True);
    on Windows it sleeps in the operating system until the editor's process ends, so it costs nothing."""
    raw = os.environ.get(EDITOR_PID, "")
    if not raw.isdigit() or int(raw) in (0, os.getpid()) or os.environ.get(SWITCH) == "0":
        return False
    editor = int(raw)
    if sys.platform == "win32":
        win = _windows()
        handle = win.kernel32.OpenProcess(_SYNCHRONIZE, False, editor)
        if not handle:
            if win.ctypes.get_last_error() == _ERROR_ACCESS_DENIED:
                return False  # cannot watch it from here; the job object is still there
            os._exit(1)  # the editor is already gone

        def wait() -> None:
            win.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
            os._exit(1)

        threading.Thread(target=wait, name="editor-watch", daemon=True).start()
        return True
    if not process_alive(editor):
        os._exit(1)

    def poll_loop() -> None:
        stop = threading.Event()
        while not stop.wait(poll):
            if not process_alive(editor):
                os._exit(1)

    threading.Thread(target=poll_loop, name="editor-watch", daemon=True).start()
    return True


# -- the job (Windows) ----------------------------------------------------------------------------


def adopt(pid: int) -> bool:
    """Tie the process ``pid`` (and what it will start) to this one: it ends when this process does.

    Windows: puts it in the editor's job, whose handle only the editor holds. False where that cannot be
    done (another platform, a refused job): the helper's own watcher is then what ends it."""
    if sys.platform != "win32" or pid <= 0 or os.environ.get(SWITCH) == "0":
        return False
    win = _windows()
    job = _editor_job()
    if not job:
        return False
    handle = win.kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(win.kernel32.AssignProcessToJobObject(job, handle))
    finally:
        win.kernel32.CloseHandle(handle)


def _editor_job() -> int | None:
    global _job
    if _job is None:
        win = _windows()
        job = win.kernel32.CreateJobObjectW(None, None)
        if job:
            info = win.ExtendedLimits()
            info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
            if not win.kernel32.SetInformationJobObject(
                job, _JOB_EXTENDED_LIMITS, win.ctypes.byref(info), win.ctypes.sizeof(info)
            ):
                win.kernel32.CloseHandle(job)
                job = None
        _job = job or 0
    return _job or None


# -- trees of processes ---------------------------------------------------------------------------


def process_table() -> dict[int, int]:
    """Every running process: id -> parent id."""
    if sys.platform == "win32":
        return _windows_table()
    if os.path.isdir("/proc"):
        return _proc_table()
    return _ps_table()


def tree_below(table: dict[int, int], root: int) -> list[int]:
    """The processes below ``root`` in a process table, nearest first (``root`` itself is not in it)."""
    children: dict[int, list[int]] = {}
    for pid, parent in table.items():
        if pid != parent:
            children.setdefault(parent, []).append(pid)
    found: list[int] = []
    queue = [root]
    seen = {root}
    while queue:
        for pid in children.get(queue.pop(0), ()):
            if pid not in seen:
                seen.add(pid)
                found.append(pid)
                queue.append(pid)
    return found


def descendants(pid: int) -> list[int]:
    """The processes ``pid`` started and those they started, nearest first."""
    return tree_below(process_table(), pid)


def kill_tree(pid: int) -> None:
    """End a process and everything below it, at once. Missing processes are not an error."""
    if pid <= 0 or pid == os.getpid():
        return
    victims: list[int] = []
    for _ in range(3):  # what a process starts while the tree is being cut is found by the next pass
        found = [p for p in tree_below(process_table(), pid) if p not in victims and p != os.getpid()]
        if not found:
            break
        victims += found
        for victim in reversed(found):  # the youngest first: nothing is left to start more
            _terminate(victim)
    _terminate(pid)


def wait_gone(pids: list[int], timeout: float = 3.0, step: float = 0.01) -> bool:
    """Wait until none of ``pids`` is running (True), or ``timeout`` seconds have passed (False).

    A process that was killed lets go of its files a moment later, on Windows: deleting a file it had open
    fails until then, so whoever kills a render and then removes its output waits for it here first."""
    end = time.monotonic() + timeout
    left = [pid for pid in pids if pid > 0]
    while True:
        left = [pid for pid in left if process_alive(pid)]
        if not left or time.monotonic() >= end:
            return not left
        time.sleep(step)


def _terminate(pid: int) -> None:
    if sys.platform == "win32":
        win = _windows()
        handle = win.kernel32.OpenProcess(_PROCESS_TERMINATE, False, pid)
        if handle:
            win.kernel32.TerminateProcess(handle, 1)
            win.kernel32.CloseHandle(handle)
        return
    import signal

    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGKILL)


def _proc_table() -> dict[int, int]:
    table: dict[int, int] = {}
    for name in os.listdir("/proc"):
        if name.isdigit():
            try:
                with open(f"/proc/{name}/stat", encoding="utf-8", errors="replace") as handle:
                    table[int(name)] = int(handle.read().rpartition(")")[2].split()[1])
            except (OSError, ValueError, IndexError):
                continue
    return table


def _ps_table() -> dict[int, int]:
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    table: dict[int, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and all(part.isdigit() for part in parts):
            table[int(parts[0])] = int(parts[1])
    return table


# -- win32 bindings, made once and only on Windows ------------------------------------------------


def _windows():
    global _win
    if _win is None:
        _win = _Win32()
    return _win


class _Win32:
    """The few kernel32 calls above, with their types declared (a 64-bit handle must not become an int)."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        handle, dword = wintypes.HANDLE, wintypes.DWORD
        k.OpenProcess.restype = handle
        k.OpenProcess.argtypes = (dword, wintypes.BOOL, dword)
        k.CloseHandle.argtypes = (handle,)
        k.CreateJobObjectW.restype = handle
        k.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        k.SetInformationJobObject.argtypes = (handle, ctypes.c_int, ctypes.c_void_p, dword)
        k.AssignProcessToJobObject.argtypes = (handle, handle)
        k.WaitForSingleObject.argtypes = (handle, dword)
        k.TerminateProcess.argtypes = (handle, wintypes.UINT)
        k.CreateToolhelp32Snapshot.restype = handle
        k.CreateToolhelp32Snapshot.argtypes = (dword, dword)
        k.Process32FirstW.argtypes = (handle, ctypes.c_void_p)
        k.Process32NextW.argtypes = (handle, ctypes.c_void_p)
        self.kernel32 = k

        class Basic(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                ("LimitFlags", dword),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", dword),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", dword),
                ("SchedulingClass", dword),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]  # fmt: skip

        class Extended(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", Basic),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class ProcessEntry(ctypes.Structure):
            _fields_ = [
                ("dwSize", dword),
                ("cntUsage", dword),
                ("th32ProcessID", dword),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", dword),
                ("cntThreads", dword),
                ("th32ParentProcessID", dword),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", dword),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        self.ExtendedLimits = Extended
        self.ProcessEntry = ProcessEntry


def _windows_table() -> dict[int, int]:
    win = _windows()
    snapshot = win.kernel32.CreateToolhelp32Snapshot(_SNAPSHOT_PROCESSES, 0)
    table: dict[int, int] = {}
    if not snapshot or snapshot == win.ctypes.c_void_p(-1).value:
        return table
    try:
        entry = win.ProcessEntry()
        entry.dwSize = win.ctypes.sizeof(entry)
        more = win.kernel32.Process32FirstW(snapshot, win.ctypes.byref(entry))
        while more:
            table[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            more = win.kernel32.Process32NextW(snapshot, win.ctypes.byref(entry))
    finally:
        win.kernel32.CloseHandle(snapshot)
    return table
