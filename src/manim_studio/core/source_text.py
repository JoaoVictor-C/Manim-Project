"""Positions in source text (P13.3) - pure.

The parser (``ast``) gives a position as a line and a column counted in **UTF-8 bytes**; editing a
Python ``str`` needs character offsets. ``SourceText`` converts, and finds the starts and ends of lines
for the three line endings Python reads (``\\n``, ``\\r\\n`` and a lone ``\\r``).
"""

from __future__ import annotations

import re

NEWLINE = re.compile(r"\r\n|\r|\n")


class SourceText:
    """A text with its line starts, to turn the parser's (line, column) into character offsets."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.starts = [0] + [m.end() for m in NEWLINE.finditer(text)]

    def offset(self, lineno: int, col: int) -> int:
        """The character offset of line ``lineno`` (1-based), column ``col`` (UTF-8 bytes)."""
        start = self.starts[lineno - 1]
        end = self.starts[lineno] if lineno < len(self.starts) else len(self.text)
        line = self.text[start:end].encode("utf-8")
        return start + len(line[:col].decode("utf-8", errors="ignore"))

    def line_start(self, offset: int) -> int:
        """The offset where the line holding ``offset`` starts."""
        return max(self.text.rfind("\n", 0, offset), self.text.rfind("\r", 0, offset)) + 1

    def line_end(self, offset: int) -> int:
        """The offset of the line ending that ends the line holding ``offset`` (or the text's end)."""
        match = NEWLINE.search(self.text, offset)
        return match.start() if match else len(self.text)

    def after_line(self, offset: int) -> int:
        """The offset just after the line ending of the line holding ``offset``."""
        match = NEWLINE.search(self.text, offset)
        return match.end() if match else len(self.text)
