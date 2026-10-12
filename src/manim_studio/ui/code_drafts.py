"""What the Code page remembers about text that is not in the project yet (P6b.3) - no Qt.

The project holds a code layer's *applied* code; the editor holds what is being typed.
The difference is a **draft**, kept per layer id so switching layers or pages never
loses typing. A layer is *dirty* exactly while its editor text differs from the
project's text (exact string equality - typing a letter and deleting it makes the
layer clean again, and one trailing space is a change, because Run would add an undo
step for it). A draft remembers the project text it was started from (``base``): when
the project's text has moved on since (an undo, a Properties edit), the page tells
the user instead of silently keeping or dropping the draft.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Draft:
    text: str
    cursor: int = 0
    base: str = ""  # the project's code when this text was started from it


class Drafts:
    """Unapplied editor text by layer id. Only texts that differ from the project are kept."""

    def __init__(self) -> None:
        self._drafts: dict[str, Draft] = {}

    def park(self, layer_id: str, text: str, cursor: int, base: str, document_text: str) -> None:
        """Remember the editor's text for ``layer_id``, or forget it when it is the project's text."""
        if text == document_text:
            self._drafts.pop(layer_id, None)
        else:
            self._drafts[layer_id] = Draft(text, cursor, base)

    def get(self, layer_id: str, document_text: str) -> Draft | None:
        """The draft to show for ``layer_id`` (None: show the project's text)."""
        draft = self._drafts.get(layer_id)
        if draft is None or draft.text == document_text:
            self._drafts.pop(layer_id, None)
            return None
        return draft

    def dirty(self, layer_id: str, document_text: str | None) -> bool:
        """Is there unapplied text for this layer (``document_text`` None: the layer is gone)."""
        draft = self._drafts.get(layer_id)
        return draft is not None and draft.text != document_text

    def discard(self, layer_id: str) -> None:
        self._drafts.pop(layer_id, None)

    def clear(self) -> int:
        """Forget everything (a new project): how many drafts were dropped."""
        dropped = len(self._drafts)
        self._drafts.clear()
        return dropped

    def __len__(self) -> int:
        return len(self._drafts)

    def __contains__(self, layer_id: str) -> bool:
        return layer_id in self._drafts


def moved_on(text: str, base: str, document_text: str) -> bool:
    """Did the project's code change underneath an unapplied ``text`` started from ``base``?"""
    return text != document_text and base != document_text


def clamp_line(line: int, line_count: int) -> int:
    """A 1-based line number kept inside a text of ``line_count`` lines (an error from the last
    run can point past the end of text that has been shortened since)."""
    return max(1, min(line, max(line_count, 1)))


def error_line(state: str, line: int | None) -> int | None:
    """The line an error points at (None: not an error, or the runner did not know)."""
    if state != "error" or not isinstance(line, int) or isinstance(line, bool) or line < 1:
        return None
    return line


def error_text(message: str, line: int | None) -> str:
    """The error as one clickable line: ``line 3: NameError: name 'x' is not defined``."""
    return f"line {line}: {message}" if line else message
