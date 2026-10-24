"""Checks on the user's code that need no running: its syntax (P13.1).

``syntax_problem(source)`` finds the first thing Python cannot read, with a plain-language message and a
position clamped to the text, for a marker in the editor while the person types. ``pending_string``
says when that problem is probably only "not finished yet" (a text block or bracket still open at the
end of the file), so the editor can wait or show it softly. Pure: no Qt, no Manim.
"""

from __future__ import annotations

import traceback as traceback_module
import warnings
from collections.abc import Mapping
from dataclasses import dataclass

from . import error_hints

BOM = "﻿"
TRACEBACK_LIMIT = 4096  # bytes: a traceback travels in a status message and is shown in a small area


@dataclass(frozen=True)
class SyntaxProblem:
    """Where and what: ``line`` and ``end_line`` count from 1, ``column`` and ``end_column`` from 0
    (like an editor cursor); ``end_column`` 0 means "to the end of the line"."""

    line: int
    column: int
    end_line: int
    message: str
    end_column: int = 0


def _compile(source: str) -> SyntaxError | ValueError | None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # invalid escape sequences are no reason to mark the code
        try:
            compile(source, "<code>", "exec", dont_inherit=True)
        except (SyntaxError, ValueError) as error:  # ValueError: older Pythons reject null bytes this way
            return error
        except RecursionError:  # a pathologically nested expression: not a syntax matter
            return None
    return None


def _clean(source: str) -> str:
    return source.removeprefix(BOM).replace("\r\n", "\n").replace("\r", "\n")


def pending_string(source: str) -> bool:
    """True when the problem is a text block (triple quotes) or a bracket still open at the end of the
    file - most likely something being typed. False when there is no problem or it is another one."""
    error = _compile(_clean(source))
    if not isinstance(error, SyntaxError):
        return False
    text = (error.msg or "").lower()
    return "unterminated triple-quoted" in text or "was never closed" in text


def syntax_problem(source: str) -> SyntaxProblem | None:
    """The first syntax problem in ``source``, or None when Python can read it."""
    text = _clean(source)
    error = _compile(text)
    if error is None:
        return None
    lines = text.split("\n")
    if "\x00" in text:
        before = text[: text.index("\x00")]
        line, column = before.count("\n") + 1, len(before.rsplit("\n", 1)[-1])
        return _clamped(
            lines,
            line,
            column,
            line,
            "There is a stray invisible (null) character here. Delete it.",
            column + 1,
        )
    if not isinstance(error, SyntaxError):
        return _clamped(lines, 1, 0, 1, _plain(type(error).__name__, str(error)))
    message = _plain(type(error).__name__, error.msg or "", text)
    line = error.lineno or 1
    column = max((error.offset or 1) - 1, 0)
    end_line = error.end_lineno or line
    end_column = max((error.end_offset or 1) - 1, 0)
    if (
        "unterminated triple-quoted" in (error.msg or "").lower()
    ):  # it is closed at the end, not where it opens
        message += f" (the block starts on line {line})"
        line = end_line = len(lines)
        column, end_column = len(lines[-1]), 0
    return _clamped(lines, line, column, end_line, message, end_column)


def _plain(error_type: str, message: str, source: str = "") -> str:
    found = error_hints.hint(error_type, message, source)
    return found.text if found is not None else message


def _clamped(
    lines: list[str], line: int, column: int, end_line: int, message: str, end_column: int = 0
) -> SyntaxProblem:
    last = len(lines)
    line = min(max(line, 1), last)
    end_line = min(max(end_line, line), last)
    column = min(max(column, 0), len(lines[line - 1]))
    end_column = min(max(end_column, 0), len(lines[end_line - 1]))
    if end_line == line and end_column and end_column <= column:
        end_column = 0
    return SyntaxProblem(line, column, end_line, message, end_column)


def user_traceback(error: BaseException, sources: Mapping[str, str], limit: int = TRACEBACK_LIMIT) -> str:
    """The traceback of ``error`` restricted to the user's own code, at most ``limit`` bytes.

    ``sources`` maps the file names the user's code was compiled under (``"<code layer>"``, a helper's
    name...) to its text: only frames from those files are listed, each with its line, so the app's
    own functions and Manim's never appear. Empty when no frame is the user's. When it is too long the
    oldest frames are dropped first.
    """
    frames = []
    for frame in traceback_module.extract_tb(error.__traceback__):
        if frame.filename in sources and frame.lineno:
            frames.append((frame.filename, frame.lineno, frame.name))
    if isinstance(error, SyntaxError) and error.filename in sources and error.lineno:
        frames.append((error.filename, error.lineno, "<module>"))
    if not frames:
        return ""
    cache = {name: text.splitlines() for name, text in sources.items()}
    entries = []
    for filename, lineno, name in frames:
        lines = cache[filename]
        code = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""
        entry = f"  line {lineno}, in {name}" if name != "<module>" else f"  line {lineno}"
        entries.append(entry + (f"\n    {code}" if code else ""))
    kind = type(error).__name__
    detail = str(error.msg if isinstance(error, SyntaxError) else error).strip()
    last = f"{kind}: {detail}".splitlines()[0] if detail else kind
    head = "Traceback (most recent call last):"
    while True:
        text = "\n".join([head, *entries, last])
        if len(text.encode("utf-8")) <= limit or len(entries) <= 1:
            break
        entries.pop(0)
    return text.encode("utf-8")[:limit].decode("utf-8", errors="ignore")
