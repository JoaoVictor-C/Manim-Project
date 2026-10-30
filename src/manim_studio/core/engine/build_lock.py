"""A lock between processes that build into one Manim cache (ADR 0065).

Manim names a LaTeX or text file after the hash of what it holds and reuses it when it is there. Two processes
that need the same object before it exists would both compile it into the same files, and on Windows the
second fails (the first has them open). One process at a time does not meet this: the editor's build worker
warms the cache before a build, and an export draws only what was warmed. The processes that draw one
export's frames side by side (``render.farm``) can: all of them reach a title for the first time together.
Each takes this lock around a build that may compile, so the second finds the first's files and reads them.

The lock is a byte of a file in the cache folder, held by the operating system: it is let go when the
process ends, however it ends.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

POLL_SECONDS = 0.02


class BuildLock:
    """``with lock:`` waits for every other process using the same file, and is re-entrant."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._file: int | None = None
        self._depth = 0

    def __enter__(self) -> BuildLock:
        if self._depth == 0:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = os.open(self.path, os.O_RDWR | os.O_CREAT)
            _acquire(self._file)
        self._depth += 1
        return self

    def __exit__(self, *_exc) -> None:
        self._depth -= 1
        if self._depth == 0 and self._file is not None:
            file, self._file = self._file, None
            try:
                _release(file)
            finally:
                os.close(file)


if sys.platform == "win32":
    import msvcrt

    def _acquire(file: int) -> None:
        while True:
            try:
                msvcrt.locking(file, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(POLL_SECONDS)

    def _release(file: int) -> None:
        os.lseek(file, 0, os.SEEK_SET)
        msvcrt.locking(file, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _acquire(file: int) -> None:
        fcntl.flock(file, fcntl.LOCK_EX)

    def _release(file: int) -> None:
        fcntl.flock(file, fcntl.LOCK_UN)
