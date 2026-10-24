"""What Manim offers, read from ``manim_names.json`` (P13.0).

The file is written by ``scripts/gen_manim_names.py`` from the installed Manim and shipped with the
package, so the editor can suggest names (did-you-mean in error hints, completion) without importing
Manim. Pure: no Qt, no Manim. The file is read once, on first use.
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Iterable
from functools import cache
from pathlib import Path

FILE = Path(__file__).with_name("manim_names.json")
CUTOFF = 0.6


@cache
def _table() -> dict:
    try:
        table = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # a missing or damaged file: no suggestions, never a crash
        return {}
    return table if isinstance(table, dict) else {}


@cache
def _name_set() -> frozenset[str]:
    return frozenset(names())


def version() -> str:
    """The Manim version the table was written for ("" when the file cannot be read)."""
    return str(_table().get("manim_version", ""))


def names() -> tuple[str, ...]:
    """The public names ``from manim import *`` gives, sorted."""
    return tuple(_table().get("names", ()))


@cache
def methods(class_name: str) -> tuple[str, ...]:
    """The public methods and attributes of a Manim class (its parents' included), sorted; () if unknown."""
    table = _table()
    entries, bases = table.get("methods", {}), table.get("bases", {})
    if class_name not in entries:
        return ()
    found: set[str] = set()
    seen: set[str] = set()
    current: str | None = class_name
    while current is not None and current not in seen:  # a cycle can only come from a damaged file
        seen.add(current)
        found.update(entries.get(current, ()))
        current = bases.get(current)
    return tuple(sorted(found))


def kwargs(callable_name: str) -> tuple[str, ...]:
    """The parameter names a Manim class or function takes (``*args`` / ``**kwargs`` left out)."""
    return tuple(_table().get("kwargs", {}).get(callable_name, ()))


def is_known(name: str) -> bool:
    """True when ``name`` is something ``from manim import *`` provides."""
    return name in _name_set()


def close_matches(word: str, pool: Iterable[str], n: int = 3, cutoff: float = CUTOFF) -> list[str]:
    """Up to ``n`` entries of ``pool`` that look like ``word``, best first.

    Spelling that differs only in case comes first (``circle`` finds ``Circle``); the rest are ranked by
    ``difflib`` similarity, ``cutoff`` (0.6) or better.
    """
    if not word or n <= 0:
        return []
    candidates = list(dict.fromkeys(pool))
    lowered = word.lower()
    found = [c for c in candidates if c.lower() == lowered and c != word]
    scored = []
    for candidate in candidates:
        if candidate == word or candidate in found:
            continue
        ratio = difflib.SequenceMatcher(None, lowered, candidate.lower()).ratio()
        if ratio >= cutoff:
            scored.append((-ratio, candidate))
    found.extend(candidate for _, candidate in sorted(scored))
    return found[:n]
