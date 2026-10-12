"""Autosave (P5d, ADR 0038): a recovery copy of unsaved work every 30 s.

The window owns one ``Autosave``. Its timer writes the document to the recovery
folder while it has unsaved changes (never in the middle of a drag, never the same
snapshot twice); the copy is deleted as soon as the document is clean again (Save,
undo back to the saved state, New, Open) and when the window closes after the user
discarded the changes. The file format lives in ``core.recovery``.
"""

from __future__ import annotations

import itertools
import os
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, QTimer

from ..core import recovery
from ..core.recovery import Entry
from ..core.schema import Project
from ..logging_config import get_logger
from .document import Document

log = get_logger(__name__)

INTERVAL_MS = 30_000
RECOVERY_ENV = "MANIM_STUDIO_RECOVERY"
_windows = itertools.count(1)  # untitled-<pid>-<n>: one n per window of this process


def recovery_dir() -> Path:
    """``MANIM_STUDIO_RECOVERY``, else ``<AppDataLocation>/recovery``."""
    override = os.environ.get(RECOVERY_ENV)
    if override:
        return Path(override)
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base or Path.home() / ".manim-studio") / "recovery"


class Autosave(QObject):
    def __init__(
        self,
        document: Document,
        path: Callable[[], Path | None],
        has_project: Callable[[], bool],
        parent: QObject | None = None,
        folder: Path | None = None,
        interval_ms: int = INTERVAL_MS,
    ) -> None:
        super().__init__(parent)
        self.document, self.path, self.has_project = document, path, has_project
        self.folder = folder if folder is not None else recovery_dir()
        self._n = next(_windows)
        self._written: Entry | None = None  # this window's copy on disk
        self._snapshot: Project | None = None  # the project in it
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.tick)
        document.undo_stack.cleanChanged.connect(self._on_clean_changed)

    @property
    def written(self) -> Entry | None:
        return self._written

    def stem(self) -> str:
        return recovery.stem_for(self.path(), os.getpid(), self._n)

    def tick(self) -> None:
        """Write a copy if there is unsaved work the last copy does not have."""
        if not self.has_project() or self.document.dragging or self.document.undo_stack.isClean():
            return
        written = self._written
        if written is not None and self._snapshot is self.document.project and written.stem == self.stem():
            return
        self.write_now()

    def write_now(self) -> Entry:
        """Write the current snapshot (replacing this window's previous copy)."""
        started = time.perf_counter()
        project, previous = self.document.project, self._written
        entry = recovery.write(self.folder, self.stem(), project, self.path(), os.getpid(), time.time())
        if previous is not None and previous.stem != entry.stem:
            recovery.remove(self.folder, previous.stem)  # saved under another name since
        self._written, self._snapshot = entry, project
        log.debug("recovery copy %s (%.1f ms)", entry.project_file, (time.perf_counter() - started) * 1000)
        return entry

    def discard(self) -> None:
        """Delete this window's copy: the work is saved, or the user threw it away."""
        if self._written is not None:
            recovery.remove(self.folder, self._written.stem)
            log.debug("recovery copy %s deleted", self._written.stem)
        self._written = self._snapshot = None

    def offered(self, path: Path | None = None) -> list[Entry]:
        """Other, dead instances' copies to offer back (of ``path`` only, when given)."""
        return recovery.offered(self.folder, path)

    def _on_clean_changed(self, clean: bool) -> None:
        if clean:
            self.discard()
