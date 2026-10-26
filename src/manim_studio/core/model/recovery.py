"""Recovery copies of unsaved work (P5d, ADR 0038).

While a project has unsaved changes the editor writes it to a recovery folder every
30 s. Each copy is two files, both written to a temporary name and moved into place
with ``os.replace`` (the project first, the sidecar last):

* ``<stem>.json`` - the project, a normal project file;
* ``<stem>.meta.json`` - ``{"path": original path or null, "pid": owner, "saved_at": time}``.

``<stem>`` is ``<sha1 of the path, 16 hex digits>-<pid>``, or ``untitled-<pid>-<n>``
for a project never saved, so two running instances editing the same file each own
their copy. A copy is offered back only when its owner is no longer running and it
is newer than the saved file; copies older than the saved file are kept unoffered and
pruned after ``STALE_DAYS``, like project files left without a sidecar.

No Qt, no Manim: the window decides when to write and what to ask.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .schema import Project

STALE_DAYS = 14.0
META = ".meta.json"


@dataclass(frozen=True)
class Entry:
    """A recovery copy on disk."""

    stem: str
    folder: Path
    path: Path | None  # the project file it belongs to; None: never saved
    pid: int  # the process that wrote it
    saved_at: float  # when (seconds since the epoch)

    @property
    def project_file(self) -> Path:
        return self.folder / f"{self.stem}.json"

    @property
    def meta_file(self) -> Path:
        return self.folder / f"{self.stem}{META}"

    @property
    def name(self) -> str:
        return self.path.name if self.path is not None else "untitled"


def path_key(path: Path) -> str:
    """The same text for every spelling of one file (case and separators on Windows)."""
    return os.path.normcase(os.path.abspath(str(path)))


def stem_for(path: Path | None, pid: int, n: int) -> str:
    if path is None:
        return f"untitled-{pid}-{n}"
    digest = hashlib.sha1(path_key(path).encode("utf-8")).hexdigest()[:16]
    return f"{digest}-{pid}"


def write(folder: Path, stem: str, project: Project, path: Path | None, pid: int, now: float) -> Entry:
    """Write the project and its sidecar atomically; returns the entry."""
    folder.mkdir(parents=True, exist_ok=True)
    entry = Entry(stem, folder, path, pid, now)
    _replace(entry.project_file, project.model_dump_json(by_alias=True))
    meta = {"path": str(path) if path is not None else None, "pid": pid, "saved_at": now}
    _replace(entry.meta_file, json.dumps(meta))  # last: a sidecar always has its project
    return entry


def remove(folder: Path, stem: str) -> None:
    """Delete a copy (both files); missing files are fine."""
    for name in (f"{stem}{META}", f"{stem}.json"):
        with contextlib.suppress(FileNotFoundError):
            (folder / name).unlink()


def entries(folder: Path) -> list[Entry]:
    """Every readable copy in ``folder``, newest first."""
    out = []
    if not folder.is_dir():
        return out
    for meta_file in folder.glob(f"*{META}"):
        stem = meta_file.name[: -len(META)]
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            path = Path(meta["path"]) if meta.get("path") else None
            entry = Entry(stem, folder, path, int(meta["pid"]), float(meta["saved_at"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue  # someone else's file, or half written by a future version
        if entry.project_file.is_file():
            out.append(entry)
    return sorted(out, key=lambda e: e.saved_at, reverse=True)


def newer_than_saved(entry: Entry) -> bool:
    """Whether the copy holds work the saved file may not have."""
    if entry.path is None:
        return True
    try:
        return entry.saved_at > entry.path.stat().st_mtime
    except OSError:
        return True  # the file is gone: the copy is all there is


def offered(
    folder: Path,
    path: Path | None = None,
    alive: Callable[[int], bool] | None = None,
    own_pid: int | None = None,
) -> list[Entry]:
    """Copies to offer back, newest first: owner not running, newer than the saved file;
    only those of ``path`` when given."""
    alive = alive or pid_alive
    own_pid = os.getpid() if own_pid is None else own_pid
    found = []
    for entry in entries(folder):
        if path is not None and (entry.path is None or path_key(entry.path) != path_key(path)):
            continue
        if entry.pid == own_pid or alive(entry.pid):
            continue  # this instance's own copy, or another running one's: never touched
        if newer_than_saved(entry):
            found.append(entry)
    return found


def prune(
    folder: Path,
    now: float | None = None,
    alive: Callable[[int], bool] | None = None,
    own_pid: int | None = None,
) -> list[str]:
    """Delete copies of dead owners that are older than their saved file and than
    ``STALE_DAYS``, and project files left without a sidecar as long; returns their stems."""
    alive = alive or pid_alive
    own_pid = os.getpid() if own_pid is None else own_pid
    now = time.time() if now is None else now
    cutoff = now - STALE_DAYS * 86400
    gone = []
    known = set()
    for entry in entries(folder):
        known.add(entry.stem)
        if entry.pid == own_pid or alive(entry.pid) or newer_than_saved(entry):
            continue
        if entry.saved_at < cutoff:
            remove(folder, entry.stem)
            gone.append(entry.stem)
    if folder.is_dir():
        for file in folder.glob("*.json"):
            stem = file.name[: -len(".json")]
            if file.name.endswith(META) or stem in known:
                continue
            with contextlib.suppress(OSError):
                if file.stat().st_mtime < cutoff:
                    file.unlink()
                    gone.append(stem)
    return gone


def read_project(entry: Entry) -> Project:
    return Project.model_validate_json(entry.project_file.read_text(encoding="utf-8"))


def pid_alive(pid: int) -> bool:
    """Whether process ``pid`` is running (psutil if installed; never signals it)."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is not None:
        return bool(psutil.pid_exists(pid))
    if sys.platform == "win32":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)  # signal 0 checks without signalling (on Windows it would terminate!)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # someone else's process
    except OSError:
        return False
    return True


def _windows_pid_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    query_limited, still_active, access_denied = 0x1000, 259, 5
    handle = kernel32.OpenProcess(query_limited, False, pid)
    if not handle:
        return ctypes.get_last_error() == access_denied  # it exists, we may not look at it
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _replace(target: Path, text: str) -> None:
    temp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, target)
