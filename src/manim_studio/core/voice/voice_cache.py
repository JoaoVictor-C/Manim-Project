"""Where generated speech is kept (ADR 0060): one file per voice, speed and spoken text.

The file is named by the key of what it says (``narration.key_for``), so a cue that did not change
never generates again and two cues with the same words share a file. A project that is saved keeps
them in ``<project name>_voice/`` next to its file (so they travel with it); one that is not saved
yet uses the user cache folder.
"""

from __future__ import annotations

import os
from pathlib import Path

CACHE_ENV = "MANIM_STUDIO_VOICE_CACHE"


def default_folder() -> Path:
    value = os.environ.get(CACHE_ENV)
    return Path(value) if value else Path.home() / ".manim-studio" / "voice-cache"


def folder_for(project_path: Path | None) -> Path:
    if project_path is None:
        return default_folder()
    return project_path.with_name(f"{project_path.stem}_voice")


def path_for(folder: Path, key: str, extension: str) -> Path:
    return folder / f"{key}{extension}"
