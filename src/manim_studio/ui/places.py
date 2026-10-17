"""Where the editor keeps and suggests files (GP, the golden path).

The editor used to put Manim's cache in ``.cache/manim`` under the folder it was started
from, and suggested saving and exporting there too - for an installed app that is an
arbitrary folder (the user's home, a shortcut's folder). Now:

* Manim's cache lives in the user's cache folder (``MANIM_STUDIO_CACHE`` overrides it);
* a project that was never saved is suggested next to the most recent project, else in
  ``Documents/Manim Studio`` when it exists, else in Documents, else the home folder;
  exports of such a project go there too.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths


def cache_folder() -> Path:
    """Manim's cache for the editor (Tex SVGs, text): the user's cache folder."""
    override = os.environ.get("MANIM_STUDIO_CACHE")
    if override:
        return Path(override)
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    return Path(base or Path.home() / ".manim-studio" / "cache") / "manim"


def documents() -> Path:
    found = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    return Path(found) if found else Path.home()


def default_folder(recent: list[Path]) -> Path:
    """Where to suggest a never-saved project and its exports."""
    for path in recent:
        if path.parent.is_dir():
            return path.parent
    for candidate in (documents() / "Manim Studio", documents(), Path.home()):
        if candidate.is_dir():
            return candidate
    return Path.home()
