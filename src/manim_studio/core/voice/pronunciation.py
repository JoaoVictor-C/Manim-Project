"""The pronunciation dictionary (ADR 0060): what is written -> what is spoken.

Math reads badly aloud ("F = dp/dt" is not a sentence), so a project can say how a written text is
pronounced. The subtitle keeps the written text; only the voice gets the spoken one.
"""

from __future__ import annotations

import re


def spoken(text: str, dictionary: dict[str, str]) -> str:
    """``text`` with each key of ``dictionary`` replaced (longest first, whole words where the key
    starts or ends with a letter or digit, never a replacement inside an earlier replacement), and
    line breaks and runs of spaces turned into single spaces."""
    text = " ".join(text.split())
    keys = sorted((k for k in dictionary if k), key=len, reverse=True)
    if not keys:
        return text
    parts = []
    for key in keys:
        before = r"(?<!\w)" if key[0].isalnum() or key[0] == "_" else ""
        after = r"(?!\w)" if key[-1].isalnum() or key[-1] == "_" else ""
        parts.append(f"{before}{re.escape(key)}{after}")
    pattern = re.compile("|".join(parts))
    return " ".join(pattern.sub(lambda m: dictionary[m.group(0)], text).split())
