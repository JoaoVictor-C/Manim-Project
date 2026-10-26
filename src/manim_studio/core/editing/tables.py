"""The Audio page's tables, without Qt (P6b.4, ADR 0041): how a cell shows a sound or a subtitle,
and the ``Edit`` a cell's text makes - or the reason it is refused.

Every edit goes through ``core/editing/edits.py`` (``update_audio``, ``update_cue``), so a cell edit is
validated like a Properties edit and the page applies it as one undo step. A refusal is an
``EditError`` whose text is shown in the status bar; nothing else changes.
"""

from __future__ import annotations

import math
from typing import Any, NamedTuple

from pydantic import ValidationError

from ..model.schema import AudioClip, Cue, Project
from . import edits

LINE_BREAK = " ↵ "  # a subtitle's line break, shown (and typed) in one line


class Column(NamedTuple):
    key: str  # the model field
    title: str
    tip: str
    editable: bool = True
    undo: str = ""  # the undo step's name


SOUND_COLUMNS = (
    Column("name", "Name", "The sound's name", undo="Rename sound"),
    Column("path", "File", "The sound file (a warning if it is missing)", editable=False),
    Column("start", "Start (s)", "Where it starts on the timeline", undo="Move sound"),
    Column("offset", "Trim start (s)", "Seconds of the file skipped", undo="Trim sound"),
    Column("duration", "Duration (s)", "Seconds of the file played", undo="Trim sound"),
    Column("gain", "Gain (dB)", "Level change, in decibels", undo="Change gain"),
    Column("fade_in", "Fade in (s)", "Linear fade-in length", undo="Change fade"),
    Column("fade_out", "Fade out (s)", "Linear fade-out length", undo="Change fade"),
)
CUE_COLUMNS = (
    Column("start", "Start (s)", "When the subtitle appears", undo="Move subtitle"),
    Column("end", "End (s)", "When it disappears", undo="Move subtitle"),
    Column("text", "Text", "What it says (a line break is shown as ↵)", undo="Edit subtitle"),
)
# A subtitle's own silence before it when the subtitles follow their speech (ADR 0060); blank: the default.
PAUSE_COLUMN = Column(
    "pause_before",
    "Pause before (s)",
    "Silence before this subtitle when following speech; blank for the narration's pause",
    undo="Pause before subtitle",
)
_SECONDS = {"start", "offset", "duration", "fade_in", "fade_out", "end", "pause_before"}


def column(columns: tuple[Column, ...], key: str) -> Column:
    return next(c for c in columns if c.key == key)


# -- numbers ---------------------------------------------------------------------------------


def format_seconds(value: float) -> str:
    return f"{value:.3f}"


def format_db(value: float) -> str:
    return f"{value:.1f}"


def parse_number(text: str) -> float:
    """A number as people type it: ``1.5``, ``1,5``, ``1.5 s``, ``-6 dB``, ``1:02.5`` (minutes and
    seconds) or ``1:02:03``; anything else is an ``EditError``."""
    raw = text.strip().lower().replace(",", ".")
    for unit in ("db", "s"):
        raw = raw.removesuffix(unit).strip()
    sign = -1.0 if raw.startswith("-") else 1.0
    raw = raw[1:] if raw[:1] in ("+", "-") else raw
    try:
        parts = [float(part) for part in raw.split(":")]
        if not raw or len(parts) > 3 or any(p < 0 for p in parts) or "_" in raw:
            raise ValueError(raw)
        value = 0.0
        for part in parts:
            value = value * 60 + part
    except ValueError:
        raise edits.EditError(f"{text.strip()!r} is not a number") from None
    if not math.isfinite(value):
        raise edits.EditError(f"{text.strip()!r} is not a number")
    return sign * value


# -- sounds ------------------------------------------------------------------------------


def sound_cell(clip: AudioClip, key: str) -> str:
    """What a sound's cell shows (and starts an edit with)."""
    if key == "name":
        return clip.name or clip.id
    if key == "path":
        return clip.path.replace("\\", "/").rsplit("/", 1)[-1]
    value = getattr(clip, key)
    return format_db(value) if key == "gain" else format_seconds(value)


def sound_edit(project: Project, clip_id: str, key: str, text: str) -> edits.Edit:
    """The edit that typing ``text`` in a sound's cell makes; raises ``EditError`` (or the
    validation error of the edit) with the reason it is refused."""
    col = column(SOUND_COLUMNS, key)
    if not col.editable:
        raise edits.EditError(f"{col.title} cannot be edited")
    value: Any = text.strip() if key == "name" else parse_number(text)
    return _validated(col, lambda: edits.update_audio(project, clip_id, **{key: value}))


# -- subtitles ---------------------------------------------------------------------------


def cue_cell(cue: Cue, key: str) -> str:
    if key == "text":
        return cue.text.replace("\n", LINE_BREAK)
    value = getattr(cue, key)
    return "" if value is None else format_seconds(value)


def cue_edit(project: Project, cue_id: str, key: str, text: str) -> edits.Edit:
    col = next((c for c in (*CUE_COLUMNS, PAUSE_COLUMN) if c.key == key), None)
    if col is None:
        raise edits.EditError(f"{key} cannot be edited")
    value: Any
    if key == "text":
        value = "\n".join(line.strip() for line in text.split(LINE_BREAK.strip())).strip()
    elif key == "pause_before" and not text.strip():
        value = None
    else:
        value = parse_number(text)
    return _validated(col, lambda: edits.update_cue(project, cue_id, **{key: value}))


# -- refusals ------------------------------------------------------------------------------


def _validated(col: Column, make: Any) -> edits.Edit:
    try:
        return make()
    except ValidationError as exc:
        raise edits.EditError(reason(exc, col.title)) from None


def reason(exc: Exception, title: str = "") -> str:
    """One line saying why an edit was refused (the first validation error, without its prefix)."""
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        message = first["msg"].removeprefix("Value error, ")
        return f"{title}: {message}" if title and first["loc"] else message
    return str(exc)
