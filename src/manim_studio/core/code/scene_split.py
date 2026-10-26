"""Cutting a scene's code into chapters, moving statements to a new layer, and proving a split (ADR 0061).

``chapter_codes`` turns an ``Analysis`` into one program per chapter: the original source with the other
chapters' statements removed (by line range, so every kept line, comment and the module level stay exactly as
the user wrote them). ``move_selection`` does the same for statements the user picks. ``verify`` compares a
render of the whole scene with the renders of its chapters, frame by frame, pixel for pixel: a split is kept
only when they are equal. Pure: ``ast``, numpy and the code cache.
"""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from .code_cache import CodeClip
from .scene_analysis import Analysis, Statement, read_statements


@dataclass(frozen=True)
class ChapterCode:
    code: str
    start_frame: int
    end_frame: int | None  # None: to the end of the scene
    first_statement: int
    last_statement: int  # exclusive
    name: str = ""
    start_time: float = 0.0  # the whole scene's clock at start_frame, exactly


def _without(code: str, statements: list[Statement], keep: set[int]) -> str:
    """``code`` without the lines of the statements whose index is not in ``keep``."""
    lines = code.splitlines(keepends=True)
    drop: set[int] = set()
    for stmt in statements:
        if stmt.index not in keep:
            drop.update(range(stmt.first_line, stmt.last_line + 1))
    return "".join(line for number, line in enumerate(lines, 1) if number not in drop)


def chapter_codes(code: str, analysis: Analysis) -> list[ChapterCode]:
    """One program per chapter of ``analysis`` (an empty list when it is not split)."""
    if not analysis.splittable:
        return []
    prelude = set(range(analysis.prelude_end))
    out = []
    for number, chapter in enumerate(analysis.chapters, 1):
        keep = prelude | set(range(chapter.first, chapter.end))
        text = _without(code, analysis.statements, keep)
        ast.parse(text)  # a chapter that does not parse is a bug here, not the user's
        out.append(
            ChapterCode(
                text,
                chapter.start_frame,
                chapter.end_frame,
                chapter.first,
                chapter.end,
                f"chapter {number}",
                chapter.start_time,
            )
        )
    return out


# -- New layer from selection ----------------------------------------------------------------------


@dataclass
class Moved:
    kept: str = ""
    moved: str = ""
    warnings: list[str] = field(default_factory=list)
    problem: str = ""


def move_selection(code: str, first_line: int, last_line: int) -> Moved:
    """Split the scene in two: the top-level statements of ``construct`` that touch lines
    ``first_line``-``last_line`` go to ``moved`` (a scene of their own); the rest stays in ``kept``.
    Both keep the module level. Names one reads that only the other defines are warnings."""
    _name, statements, problem = read_statements(code)
    if problem:
        return Moved(problem=problem)
    picked = {s.index for s in statements if s.first_line <= last_line and s.last_line >= first_line}
    if not picked:
        return Moved(problem="select some statements of construct first")
    if len(picked) == len(statements):
        return Moved(problem="the selection is the whole scene: there is nothing left to separate")
    everything = {s.index for s in statements}
    moved = _without(code, statements, picked)  # keeps the picked statements only
    kept = _without(code, statements, everything - picked)  # keeps the others
    result = Moved(kept=kept, moved=moved)
    mine = [s for s in statements if s.index in picked]
    rest = [s for s in statements if s.index not in picked]
    defined_by_rest = set().union(*(s.defines for s in rest)) if rest else set()
    defined_by_mine = set().union(*(s.defines for s in mine))
    needs = set().union(*(s.reads | s.touches for s in mine))
    left_behind = sorted((needs & defined_by_rest) - defined_by_mine)
    if left_behind:
        result.warnings.append(
            "the moved statements use " + ", ".join(left_behind) + ", defined in what stays: they will fail"
        )
    needed_back = set().union(*(s.reads | s.touches for s in rest)) if rest else set()
    taken = sorted((needed_back & defined_by_mine) - defined_by_rest)
    if taken:
        result.warnings.append("what stays uses " + ", ".join(taken) + ", defined in the moved statements")
    for text in (kept, moved):
        try:
            ast.parse(text)
        except SyntaxError as error:
            return Moved(problem=f"the result would not parse ({error.msg}, line {error.lineno})")
    return result


# -- proving a split -------------------------------------------------------------------------------


@dataclass
class Verdict:
    ok: bool
    frames: int = 0
    checked: int = 0
    first_bad: int | None = None
    message: str = ""


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return (
        a.x == b.x and a.y == b.y and a.pixels.shape == b.pixels.shape and np.array_equal(a.pixels, b.pixels)
    )


def verify(
    whole: CodeClip,
    chapters: list[tuple[CodeClip, int]],
    progress: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Verdict:
    """Is every frame of ``whole`` the frame of the chapter that covers it?

    ``chapters`` are (clip, start_frame), in order. The chapter at ``start_frame`` shows its own frame
    ``f - start_frame``; the last one holds its last frame (as a layer does) past its end.
    """
    total = whole.frame_count
    if not chapters or chapters[0][1] != 0:
        return Verdict(False, total, 0, None, "the first chapter must start at frame 0")
    for number, (clip, start) in enumerate(chapters):
        end = chapters[number + 1][1] if number + 1 < len(chapters) else total
        if clip.frame_count != end - start:
            return Verdict(
                False,
                total,
                0,
                start,
                f"chapter {number + 1} has {clip.frame_count} frames but covers {end - start}: "
                "the code did not play the same way",
            )
    which = 0
    for frame in range(total):
        while which + 1 < len(chapters) and frame >= chapters[which + 1][1]:
            which += 1
        clip, start = chapters[which]
        if not _same(whole.crop(frame), clip.crop(frame - start)):
            return Verdict(
                False,
                total,
                frame,
                frame,
                f"frame {frame} (chapter {which + 1}) differs from the full render",
            )
        if progress is not None and frame % 25 == 0:
            progress(frame, total)
        if should_stop is not None and should_stop():
            return Verdict(False, total, frame, None, "stopped")
    return Verdict(True, total, total, None, f"all {total} frames are identical")
