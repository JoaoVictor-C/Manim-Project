"""Script to timeline (ADR 0069): a written script becomes subtitle cues, which narration speaks (ADR 0060).

``split_script`` cuts the text into the units a narrator reads - sentences, or whole paragraphs - and
``import_script`` places them one after another on the timeline: each cue lasts as long as it takes to read at
``words_per_second`` (never under ``MIN_SECONDS``), cues are ``GAP`` apart, paragraphs ``PARAGRAPH_GAP``. The
cues are ordinary subtitles, so they are edited, retimed, burned in and narrated like any other. With
``placeholders`` each paragraph also gets a Text layer, named for the paragraph and shown for as long as it is
read, to be replaced by the real visual. Markdown is understood only as far as it is not meant to be spoken:
headings become the placeholder's text, and emphasis marks, list bullets and quotes are dropped.

Pure model work: no Qt, no Manim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from ..model.scene_length import grow_to_fit
from ..model.schema import Cue, Layer, Lifetime, Project, Spec
from . import edits

MIN_SECONDS = 1.0
WORDS_PER_SECOND = 2.6  # a calm narrator: about 156 words a minute
GAP = 0.25  # between cues of one paragraph
PARAGRAPH_GAP = 0.7  # between paragraphs
LONG_WORDS = 40  # a sentence longer than this is reported: it is hard to read aloud and to subtitle
PLACEHOLDER_WORDS = 6
Unit = Literal["sentence", "paragraph"]

# Full stops that do not end a sentence
ABBREVIATIONS = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "sr",
        "jr",
        "st",
        "vs",
        "etc",
        "e.g",
        "i.e",
        "fig",
        "no",
        "approx",
        "eq",
    }
)
_END = re.compile(r"([.!?…]+[\"'”’)\]]*)(\s+)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_MARKS = re.compile(r"(\*\*|__|\*|_|`)")


@dataclass(frozen=True)
class Piece:
    """One unit to read: its text and the paragraph (0, 1, ...) it came from."""

    text: str
    paragraph: int


@dataclass
class Script:
    pieces: list[Piece] = field(default_factory=list)
    titles: dict[int, str] = field(default_factory=dict)  # paragraph -> its heading, if it had one


@dataclass(frozen=True)
class ScriptReport:
    cues: int
    paragraphs: int
    seconds: float  # the time the cues take, gaps included
    long_sentences: tuple[str, ...]  # texts above LONG_WORDS words
    layers: int = 0


def split_script(text: str, unit: Unit = "sentence") -> Script:
    """The script as units to read. Blank lines separate paragraphs; a heading names the next."""
    script = Script()
    paragraph = -1
    block: list[str] = []
    title: str | None = None

    def flush() -> None:
        nonlocal paragraph, title
        words = " ".join(block).strip()
        block.clear()
        if not words:
            return
        paragraph += 1
        if title:
            script.titles[paragraph] = title
            title = None
        units = _sentences(words) if unit == "sentence" else [words]
        script.pieces += [Piece(u, paragraph) for u in units if u]

    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        heading = _HEADING.match(raw)
        if heading:
            flush()
            title = _plain(heading.group(1)) or None
        elif not raw.strip():
            flush()
        else:
            block.append(_plain(raw))
    flush()
    return script


def _plain(line: str) -> str:
    line = _BULLET.sub("", line.strip())
    line = line.lstrip("> ").strip()
    return re.sub(r"\s+", " ", _MARKS.sub("", line)).strip()


def _sentences(text: str) -> list[str]:
    out, start = [], 0
    for match in _END.finditer(text):
        before = text[start : match.start(1)].split(" ")[-1].lower().rstrip(".")
        if before in ABBREVIATIONS or (len(before) == 1 and before.isalpha() and match.group(1) == "."):
            continue  # "Dr. Chen", "e.g. this", "J. Smith"
        out.append(text[start : match.end(1)].strip())
        start = match.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def import_script(
    project: Project,
    text: str,
    *,
    unit: Unit = "sentence",
    words_per_second: float = WORDS_PER_SECOND,
    start: float | None = None,
    placeholders: bool = False,
) -> tuple[edits.Edit, ScriptReport]:
    """Add the script's cues (and placeholder layers) after the subtitles already there, or from ``start``.

    One edit: the scene grows to fit what was added, and undo removes all of it."""
    if words_per_second <= 0:
        raise edits.EditError("the reading speed must be positive")
    script = split_script(text, unit)
    if not script.pieces:
        raise edits.EditError("the script has nothing to read")
    fps = project.canvas.fps
    taken = {x.id for x in project.layers} | {c.id for c in project.audio}
    taken |= {c.id for c in project.subtitles} | {m.id for m in project.markers}

    def free(prefix: str) -> str:
        n = 1
        while f"{prefix}-{n}" in taken:
            n += 1
        taken.add(f"{prefix}-{n}")
        return f"{prefix}-{n}"

    def frame(t: float) -> float:
        return round(t * fps) / fps

    t = frame(start if start is not None else max((c.end for c in project.subtitles), default=0.0))
    cues: list[Cue] = []
    spans: dict[int, list[float]] = {}  # paragraph -> [first start, last end]
    long_ones: list[str] = []
    previous: int | None = None
    for piece in script.pieces:
        if previous is not None:
            t += GAP if piece.paragraph == previous else PARAGRAPH_GAP
        words = len(piece.text.split())
        if words > LONG_WORDS:
            long_ones.append(piece.text)
        length = max(MIN_SECONDS, words / words_per_second)
        begin = frame(t)
        end = max(frame(t + length), begin + 1 / fps)
        cues.append(Cue(id=free("cue"), start=begin, end=end, text=piece.text))
        span = spans.setdefault(piece.paragraph, [begin, end])
        span[1] = end
        t, previous = end, piece.paragraph

    layers = list(project.layers)
    added = 0
    if placeholders:
        for paragraph, (begin, end) in spans.items():
            words = script.titles.get(paragraph) or " ".join(
                next(p.text for p in script.pieces if p.paragraph == paragraph).split()[:PLACEHOLDER_WORDS]
            )
            layers.append(
                Layer(
                    id=free("text"),
                    name=f"Beat {paragraph + 1}",
                    spec=Spec(type="Text", params={"text": words}),
                    lifetime=Lifetime(in_=begin, out=end),
                )
            )
            added += 1
    merged = sorted([*project.subtitles, *cues], key=lambda c: (c.start, c.end))
    new = grow_to_fit(edits._rebuilt(project, layers=layers, subtitles=merged))
    kind, touched = edits.classify(project, new)
    report = ScriptReport(len(cues), len(spans), cues[-1].end - cues[0].start, tuple(long_ones), added)
    return edits.Edit(new, kind, touched), report
