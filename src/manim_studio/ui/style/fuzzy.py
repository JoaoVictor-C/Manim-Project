"""Matching by letters in order (shared by the command palette; ``code/quick_open`` has the same rule)."""

from __future__ import annotations


def score(query: str, text: str) -> int | None:
    """How well ``query``'s letters appear in order in ``text`` (higher is better); None: they do not."""
    query, text = query.casefold(), text.casefold()
    if not query:
        return 0
    position, total, last = 0, 0, -2
    for letter in query:
        found = text.find(letter, position)
        if found < 0:
            return None
        total += 10
        if found == last + 1:
            total += 8  # letters next to each other
        if found == 0:
            total += 12  # the start
        elif not text[found - 1].isalnum():
            total += 6  # the start of a word
        total -= min(found - position, 5)  # a long gap costs a little
        last = found
        position = found + 1
    return total - len(text) // 8  # a shorter name is a closer match
