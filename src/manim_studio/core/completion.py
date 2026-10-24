"""Names to complete while typing, and what to say when the mouse rests on a name (P13.6).

Pure: no Qt, nothing runs. The Manim side is the table in ``manim_names.json`` (``from manim import *``
and the methods and keyword arguments of its classes); the code side is what the text defines itself.
A suggestion is only ever a name that exists, never a guess about a type the code does not show: the
class of ``circle`` is known only from a line ``circle = Circle(...)`` in the text.
"""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass

from . import error_hints, manim_names

MAX_SUGGESTIONS = 40
MAX_HOVER_ARGS = 8
_CALL = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*$")
BUILTINS = (
    "print",
    "range",
    "len",
    "int",
    "float",
    "str",
    "list",
    "dict",
    "tuple",
    "enumerate",
    "zip",
    "min",
    "max",
)


@dataclass(frozen=True)
class Context:
    """Where the cursor is in a name: the letters typed so far, where they start, and the name before
    a dot (``circle`` in ``circle.mov|``) or ``""``."""

    prefix: str
    start: int
    receiver: str = ""


def context(text: str, position: int) -> Context:
    """The word being typed at ``position`` (an index into ``text``)."""
    position = max(0, min(position, len(text)))
    start = position
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
        start -= 1
    receiver = ""
    if start > 0 and text[start - 1] == ".":
        before = text[: start - 1]
        end = len(before)
        begin = end
        while begin > 0 and (before[begin - 1].isalnum() or before[begin - 1] == "_"):
            begin -= 1
        receiver = before[begin:end]
    return Context(text[start:position], start, receiver)


def enclosing_call(text: str, position: int) -> str:
    """The name of the call the cursor is inside (``Circle`` in ``Circle(rad|``), or ``""``."""
    depth = 0
    for index in range(min(position, len(text)) - 1, -1, -1):
        char = text[index]
        if char in ")]}":
            depth += 1
        elif char in "([{":
            if depth == 0:
                if char != "(":
                    return ""
                found = _CALL.search(text[:index])
                return found.group(1) if found else ""
            depth -= 1
    return ""


def class_of(source: str, name: str) -> str:
    """The class a name was made from in the text (``name = Circle(...)``), or ``""``."""
    if name == "self":
        return "Scene"
    found = ""
    for match in re.finditer(rf"^\s*{re.escape(name)}\s*=\s*([A-Za-z_]\w*)\s*\(", source, re.MULTILINE):
        found = match.group(1)
    return found if manim_names.is_known(found) else ""


def suggestions(source: str, position: int, *, force: bool = False) -> list[str]:
    """The names that fit the word at ``position``; none for fewer than two letters unless ``force``."""
    here = context(source, position)
    if len(here.prefix) < 2 and not force and not here.receiver:
        return []
    low = here.prefix.casefold()
    if here.receiver:
        cls = class_of(source, here.receiver)
        pool = [m for m in manim_names.methods(cls)] if cls else []
        return _pick(pool, low, here.prefix)
    ranked: list[str] = []
    call = enclosing_call(source, position)
    if call and manim_names.is_known(call):
        ranked += [f"{k}=" for k in manim_names.kwargs(call)]
    ranked += error_hints.defined_names(source)
    ranked += [*keyword.kwlist, *BUILTINS]
    ranked += manim_names.names()
    return _pick(ranked, low, here.prefix)


def _pick(pool: list[str], low: str, prefix: str) -> list[str]:
    out: list[str] = []
    for name in dict.fromkeys(pool):
        if name.startswith("_") and not prefix.startswith("_"):
            continue
        if name.casefold().startswith(low) and name != prefix and name.rstrip("=") != prefix:
            out.append(name)
        if len(out) >= MAX_SUGGESTIONS:
            break
    return out


def hover(source: str, word: str, receiver: str = "") -> str:
    """A line about ``word`` for a tooltip, or ``""`` when nothing is known."""
    if receiver:
        cls = class_of(source, receiver)
        if cls and word in manim_names.methods(cls):
            return f"{cls}.{word}"
        return ""
    if not manim_names.is_known(word):
        return ""
    args = manim_names.kwargs(word)
    if not args:
        return f"{word}: from Manim"
    shown = ", ".join(args[:MAX_HOVER_ARGS]) + (", ..." if len(args) > MAX_HOVER_ARGS else "")
    return f"{word}({shown})"
