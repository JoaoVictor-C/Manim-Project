"""Subtitles (P5a, ADR 0035): wrapping, .srt files, placing a new cue, what an edit changes.

Pure Python, no Manim: the cue lines are built and drawn by ``adapter`` and the
evaluator. A line is wrapped at word boundaries to a character budget derived
from the style (about 0.18 scene units per character at size 26, B48); the
built line is scaled down if it is still too wide.
"""

from __future__ import annotations

import re

from .schema import Cue, Project, Spec, SubtitleStyle

UNITS_PER_CHAR = 0.18  # at font size 26 (B48)
NEW_CUE_SECONDS = 2.0

_TIME = re.compile(r"(\d+):(\d{1,2}):(\d{1,2})(?:[,.](\d{1,3}))?")
_TAGS = re.compile(r"<[^>]*>|\{\\[^}]*\}")  # <i>...</i>, <font ...>, {\an8}


def wrap(text: str, style: SubtitleStyle) -> list[str]:
    """The lines a cue is drawn in: its own line breaks kept, long lines broken between words."""
    budget = max(8, int(style.max_width / (UNITS_PER_CHAR * style.font_size / 26)))
    lines: list[str] = []
    for paragraph in text.strip().split("\n"):
        words = paragraph.split()
        line = ""
        for word in words:
            if line and len(line) + 1 + len(word) > budget:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}" if line else word
        if line:
            lines.append(line)
    return lines


def line_specs(text: str, style: SubtitleStyle) -> list[Spec]:
    """The Text objects a cue's text is built from (what the build worker warms, ADR 0015)."""
    return [
        Spec(type="Text", params={"text": line, "font_size": style.font_size}) for line in wrap(text, style)
    ]


def visible(project: Project, t: float) -> Cue | None:
    """The subtitle at ``t``, if any (drawn when burned in and not empty)."""
    for cue in project.subtitles:
        if cue.start <= t < cue.end:
            return cue
    return None


def opacity(cue: Cue, style: SubtitleStyle, t: float) -> float:
    """1 while shown, ramping over ``style.fade`` at both ends."""
    if style.fade <= 0:
        return 1.0
    fade = min(style.fade, (cue.end - cue.start) / 2)
    return max(0.0, min(1.0, (t - cue.start) / fade, (cue.end - t) / fade))


def place_cue(project: Project, t: float) -> tuple[float, float] | None:
    """Where Edit > Add Subtitle puts a new cue: from ``t`` (or the end of the cue under it)
    for 2 s, stopping at the next cue and the end of the video; None when there is no room."""
    start = t
    for cue in project.subtitles:
        if cue.start <= start < cue.end:
            start = cue.end
    end = min(start + NEW_CUE_SECONDS, project.canvas.duration)
    for cue in project.subtitles:
        if cue.start >= start - 1e-9:
            end = min(end, cue.start)
    if end - start < 1 / project.canvas.fps - 1e-9:
        return None
    return start, end


def changed_spans(old: Project, new: Project) -> list[tuple[float, float]]:
    """The times whose subtitles can differ between ``old`` and ``new`` (render-ahead, ADR 0028)."""
    if old.subtitle_style != new.subtitle_style:
        return [(c.start, c.end) for c in [*old.subtitles, *new.subtitles]]
    before = {cue.id: cue for cue in old.subtitles}
    after = {cue.id: cue for cue in new.subtitles}
    spans = []
    for cue_id in before.keys() | after.keys():
        a, b = before.get(cue_id), after.get(cue_id)
        if a != b:
            spans += [(c.start, c.end) for c in (a, b) if c is not None]
    return spans


# -- .srt files ---------------------------------------------------------------------------


def _seconds(match: re.Match) -> float:
    hours, minutes, seconds, millis = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int((millis or "0").ljust(3, "0")) / 1000


def read_srt(text: str) -> list[Cue]:
    """Cues from an .srt file. Tolerant: a byte-order mark, CRLF, missing indices, comma or dot
    milliseconds and formatting tags are accepted; overlapping cues are trimmed into one lane."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")  # a byte-order mark only precedes an index
    found: list[tuple[float, float, str]] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue
        times = list(_TIME.finditer(lines[timing]))
        if len(times) < 2:
            continue
        words = "\n".join(_TAGS.sub("", line).strip() for line in lines[timing + 1 :]).strip()
        start, end = _seconds(times[0]), _seconds(times[1])
        if words and end > start:
            found.append((start, end, words))
    found.sort(key=lambda item: item[0])
    cues: list[Cue] = []
    for start, end, words in found:
        if cues and start < cues[-1].end:  # overlapping: the earlier one ends where this starts
            previous = cues.pop()
            if start > previous.start:
                cues.append(previous.model_copy(update={"end": start}))
        cues.append(Cue(id=f"cue-{len(cues) + 1}", start=start, end=end, text=words))
    return [cue.model_copy(update={"id": f"cue-{i}"}) for i, cue in enumerate(cues, start=1)]


def _timestamp(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{i}\n{_timestamp(cue.start)} --> {_timestamp(cue.end)}\n{cue.text.strip()}"
        for i, cue in enumerate((c for c in cues if c.text.strip()), start=1)
    ]
    return "\n\n".join(blocks) + ("\n" if blocks else "")
