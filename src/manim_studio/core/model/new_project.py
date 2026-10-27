"""What a new project is made of: the canvas presets the New project dialog offers, a safe file name,
and the blank project those choices describe.

Nothing here knows about the window: the dialog (``ui/shell/new_project_dialog``) fills a
``NewProjectSettings`` and the window turns it into a ``Project`` and a file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .schema import Canvas, Project

# (label, width, height): the sizes people ask for. The first is the long-standing default.
SIZES: tuple[tuple[str, int, int], ...] = (
    ("HD  1280 x 720", 1280, 720),
    ("Full HD  1920 x 1080", 1920, 1080),
    ("4K  3840 x 2160", 3840, 2160),
    ("Draft  854 x 480", 854, 480),
    ("Vertical  1080 x 1920", 1080, 1920),
    ("Square  1080 x 1080", 1080, 1080),
)
FRAME_RATES: tuple[int, ...] = (24, 30, 60)
BACKGROUNDS: tuple[tuple[str, str], ...] = (
    ("Black", "#000000"),
    ("Midnight", "#10142a"),
    ("Slate", "#2b303b"),
    ("Chalkboard", "#1f3a34"),
    ("Paper", "#f6f3ea"),
)
MIN_SECONDS, MAX_SECONDS = 1.0, 600.0
EXTENSION = ".json"

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class NewProjectSettings:
    """Everything the New project dialog asks. ``folder`` None means "untitled": nothing is written yet."""

    name: str = "Untitled"
    folder: Path | None = None
    template: str = "blank"
    morph_matching: str = "smart"
    width_px: int = 1280
    height_px: int = 720
    fps: int = 30
    duration: float = 5.0
    background: str = "#000000"

    @property
    def path(self) -> Path | None:
        return None if self.folder is None else self.folder / (self.name.strip() + EXTENSION)

    def canvas(self) -> Canvas:
        return Canvas(
            width_px=self.width_px,
            height_px=self.height_px,
            fps=self.fps,
            duration=min(max(self.duration, MIN_SECONDS), MAX_SECONDS),
            background=self.background,
        )

    def blank_project(self) -> Project:
        return Project(canvas=self.canvas(), morph_matching=self.morph_matching)  # type: ignore[arg-type]


def name_problem(name: str) -> str:
    """Why ``name`` cannot be a project's file name ("" when it can)."""
    text = name.strip()
    if not text:
        return "Give the project a name."
    if _ILLEGAL.search(text):
        return 'A name cannot contain < > : " / \\ | ? or *.'
    if text.endswith(".") or text.split(".")[0].lower() in _RESERVED:
        return "That name is not allowed as a file name."
    if len(text) > 120:
        return "That name is too long."
    return ""


def location_problem(folder: Path | str, name: str) -> str:
    """Why a project called ``name`` cannot be created in ``folder`` ("" when it can)."""
    problem = name_problem(name)
    if problem:
        return problem
    if not str(folder).strip():
        return "Choose where the project goes."
    folder = Path(folder)
    if folder.exists() and not folder.is_dir():
        return "That location is a file, not a folder."
    if (folder / (name.strip() + EXTENSION)).exists():
        return "A project with this name already exists there."
    return ""


def free_name(folder: Path | str, base: str = "Untitled") -> str:
    """``base``, or ``base 2``, ``base 3``... the first that does not exist in ``folder``."""
    folder = Path(folder)
    candidate, number = base, 1
    while (folder / (candidate + EXTENSION)).exists():
        number += 1
        candidate = f"{base} {number}"
    return candidate
