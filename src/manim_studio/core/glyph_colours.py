"""Colour characters (ADR 0055): one colour per drawn glyph of a Text, MathTex or Tex - pure, no Qt.

A text object's ``glyph_colours`` param lists one entry per *drawn glyph*, in the order of the
built object's ``family_members_with_points()``: a colour (``#rgb`` / ``#rrggbb``) or None, the
object's own colour. Spaces and line breaks draw nothing, so they have no entry: the list is
indexed by glyph, not by position in the typed string (``adapter.glyph_labels`` names each
glyph). Extra entries are ignored when the text gets shorter, missing ones are None.

These helpers make such lists. Colours are mixed as plain RGB, rounded half up, so the readable
export (which writes the list itself) shows exactly what the editor shows.
"""

from __future__ import annotations

import colorsys
from collections.abc import Iterable, Sequence

from .schema import is_colour

PARAM = "glyph_colours"  # the spec param (Text, MathTex, Tex)
MAX_GLYPHS = 5000  # entries a list may have: far more than a readable text draws
Colours = list[str | None]


def problem(value: object) -> str | None:
    """Why ``value`` is not an acceptable ``glyph_colours`` list, or None."""
    if not isinstance(value, list):
        return "glyph_colours must be a list of colours (or null for the object's colour)"
    if len(value) > MAX_GLYPHS:
        return f"glyph_colours has {len(value)} entries: at most {MAX_GLYPHS} glyphs can be coloured"
    for index, colour in enumerate(value):
        if colour is not None and not is_colour(colour):
            return f"the colour of glyph {index + 1} must be like #ff0000 or null, not {colour!r}"
    return None


def normalised(colours: Iterable[str | None] | None) -> Colours | None:
    """``colours`` without trailing Nones; None when nothing is coloured (the param is left out)."""
    out = list(colours or [])
    while out and out[-1] is None:
        out.pop()
    return out or None


def resolved(colours: Sequence[str | None] | None, count: int) -> Colours:
    """Exactly ``count`` entries: extra ones dropped, missing ones None (the object's colour)."""
    out = list(colours or [])[:count]
    return out + [None] * (count - len(out))


def _rgb(colour: str) -> tuple[int, int, int]:
    if not is_colour(colour):
        raise ValueError(f"{colour!r} is not a colour like #ff0000")
    digits = colour[1:]
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)


def _hex(rgb: Iterable[float]) -> str:
    return "#" + "".join(f"{min(255, max(0, int(v + 0.5))):02x}" for v in rgb)


def mix(a: str, b: str, t: float) -> str:
    """The colour ``t`` of the way from ``a`` to ``b`` (0 is ``a``), in plain RGB."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(x + (y - x) * t for x, y in zip(ra, rb, strict=True))


def gradient(colours: Sequence[str], count: int, start: int = 0, end: int | None = None) -> Colours:
    """``count`` entries where glyphs ``start`` to ``end - 1`` (all by default) run through
    ``colours`` evenly, the first glyph on the first colour and the last on the last; the other
    entries are None."""
    if not colours:
        raise ValueError("a gradient needs at least one colour")
    for colour in colours:
        _rgb(colour)
    end = count if end is None else min(end, count)
    start = max(0, start)
    out: Colours = [None] * count
    span = end - start
    for i in range(span):
        if len(colours) == 1 or span == 1:
            out[start + i] = _hex(_rgb(colours[0]))
            continue
        position = i / (span - 1) * (len(colours) - 1)  # 0 .. len - 1 across the stops
        segment = min(int(position), len(colours) - 2)
        out[start + i] = mix(colours[segment], colours[segment + 1], position - segment)
    return out


def rainbow(count: int) -> list[str]:
    """One colour per glyph around the colour wheel, from red, fully saturated."""
    return [_hex(255 * v for v in colorsys.hsv_to_rgb(i / count, 1.0, 1.0)) for i in range(count)]


def alternate(count: int, colours: Sequence[str]) -> list[str]:
    """``colours`` repeated over ``count`` glyphs: the first, the second, ..., the first again."""
    if not colours:
        raise ValueError("alternate needs at least one colour")
    return [colours[i % len(colours)] for i in range(count)]


def apply_range(existing: Sequence[str | None], start: int, end: int, colour: str | None) -> Colours:
    """``existing`` with glyphs ``start`` to ``end - 1`` set to ``colour`` (a new list)."""
    out = list(existing) + [None] * max(0, end - len(existing))
    for i in range(max(0, start), end):
        out[i] = colour
    return out


def clear_range(existing: Sequence[str | None], start: int, end: int) -> Colours:
    """``existing`` with glyphs ``start`` to ``end - 1`` back to the object's colour."""
    out = list(existing)
    for i in range(max(0, start), min(end, len(out))):
        out[i] = None
    return out


def assign(existing: Sequence[str | None], indices: Sequence[int], values: Sequence[str | None]) -> Colours:
    """``existing`` with ``values[k]`` at glyph ``indices[k]`` (a selection in any order)."""
    out = list(existing)
    for index, value in zip(indices, values, strict=True):
        if index >= len(out):
            out += [None] * (index + 1 - len(out))
        out[index] = value
    return out
