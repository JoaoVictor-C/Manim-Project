"""Python tokens for the code editor's highlighting (P6b.3, ADR 0041) - no Qt.

``scan_line(text, state)`` splits one line into coloured spans and returns the state
the next line starts in, which is all a line-by-line highlighter needs: only a triple
quoted string runs over lines. It is a lexer, not a parser: it never raises, whatever
the text (code being typed is mostly invalid), and costs one pass over the line.

The kinds are ``keyword``, ``string``, ``number``, ``comment``, ``manim`` (the names
a Manim scene is made of) and ``definition`` (the name after ``def`` or ``class``).
"""

from __future__ import annotations

import keyword
import re

Span = tuple[int, int, str]  # start, length, kind

NORMAL = 0
IN_SINGLE_TRIPLE = 1  # inside '''...
IN_DOUBLE_TRIPLE = 2  # inside \"\"\"...

KEYWORDS = frozenset(keyword.kwlist) | {"self"}
DEFINERS = frozenset({"def", "class"})
STRING_PREFIXES = frozenset({"r", "u", "b", "f", "br", "rb", "fr", "rf"})

# The names a code layer uses most (the editor never imports Manim to colour them).
_MANIM_WORDS = """
    Scene ThreeDScene MovingCameraScene ZoomedScene Mobject VMobject Group VGroup VDict
    Circle Ellipse Annulus Dot Square Rectangle RoundedRectangle Triangle Polygon RegularPolygon Star
    Line DashedLine Arrow DoubleArrow Vector Arc ArcBetweenPoints CurvedArrow Sector Cross
    Text Tex MathTex Title Paragraph MarkupText DecimalNumber Integer Variable BulletedList
    Axes NumberPlane NumberLine ComplexPlane PolarPlane ThreeDAxes Brace BraceLabel SurroundingRectangle
    ImageMobject SVGMobject TracedPath ParametricFunction FunctionGraph VectorField StreamLines
    Create Uncreate Write Unwrite FadeIn FadeOut FadeTransform Transform ReplacementTransform
    TransformFromCopy ClockwiseTransform MoveToTarget Indicate Flash Circumscribe Wiggle FocusOn
    ShowPassingFlash ApplyWave GrowFromCenter GrowArrow GrowFromPoint SpinInFromNothing DrawBorderThenFill
    Rotate Rotating MoveAlongPath AnimationGroup LaggedStart LaggedStartMap Succession Wait
    ValueTracker ComplexValueTracker Animation UpdateFromFunc UpdateFromAlphaFunc always_redraw
    always_shift always_rotate ApplyMethod ApplyFunction
    UP DOWN LEFT RIGHT ORIGIN IN OUT UL UR DL DR PI TAU DEGREES
    RED GREEN BLUE YELLOW ORANGE PURPLE PINK TEAL GOLD MAROON WHITE BLACK GRAY GREY
    RED_A RED_B RED_C RED_D RED_E BLUE_A BLUE_B BLUE_C BLUE_D BLUE_E GREEN_A GREEN_B GREEN_C GREEN_D
    GREEN_E YELLOW_A YELLOW_B YELLOW_C YELLOW_D YELLOW_E DARK_BLUE LIGHT_GRAY DARK_GRAY
    linear smooth rush_into rush_from there_and_back there_and_back_with_pause double_smooth
    ease_in_sine ease_out_sine ease_in_out_sine ease_in_quad ease_out_quad ease_in_out_quad
    ease_in_cubic ease_out_cubic ease_in_out_cubic
"""
MANIM_NAMES = frozenset(_MANIM_WORDS.split())

_NUMBER = re.compile(
    r"0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d+)?[jJ]?"
)
_DIGITS = "0123456789"
_IDENTIFIER = re.compile(r"[^\W\d]\w*")
_DELIMITERS = {IN_SINGLE_TRIPLE: "'''", IN_DOUBLE_TRIPLE: '"""'}
_STATE_OF = {"'''": IN_SINGLE_TRIPLE, '"""': IN_DOUBLE_TRIPLE}


def _find_close(text: str, start: int, delimiter: str) -> int:
    """The index just after the closing ``delimiter`` at or after ``start`` (-1: not on this line)."""
    i, n = start, len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
        elif text.startswith(delimiter, i):
            return i + len(delimiter)
        else:
            i += 1
    return -1


def scan_line(text: str, state: int = NORMAL) -> tuple[list[Span], int]:
    """The spans of one line, and the state the next line starts in."""
    spans: list[Span] = []
    n = len(text)
    i = 0
    if state != NORMAL:  # the rest of a triple quoted string from an earlier line
        close = _find_close(text, 0, _DELIMITERS[state])
        if close < 0:
            return ([(0, n, "string")] if n else []), state
        spans.append((0, close, "string"))
        i = close
    after_definer = False
    while i < n:
        ch = text[i]
        if ch == "#":
            spans.append((i, n - i, "comment"))
            return spans, NORMAL
        if ch in "'\"":
            end, state = _string(text, i, i)
            spans.append((i, end - i, "string"))
            i = end
            if state != NORMAL:
                return spans, state
            continue
        if ch in _DIGITS or (ch == "." and i + 1 < n and text[i + 1] in _DIGITS):
            match = _NUMBER.match(text, i)
            spans.append((i, match.end() - i, "number"))
            i = match.end()
            continue
        match = _IDENTIFIER.match(text, i)
        if match is None:
            i += 1
            continue
        word, end = match.group(), match.end()
        if end < n and text[end] in "'\"" and word.lower() in STRING_PREFIXES:
            end, state = _string(text, i, end)  # a prefixed string: r"..", f'..'
            spans.append((i, end - i, "string"))
            i = end
            if state != NORMAL:
                return spans, state
            continue
        if after_definer:
            spans.append((i, end - i, "definition"))
        elif word in KEYWORDS:
            spans.append((i, end - i, "keyword"))
        elif word in MANIM_NAMES:
            spans.append((i, end - i, "manim"))
        after_definer = word in DEFINERS
        i = end
    return spans, NORMAL


def _string(text: str, start: int, quote_at: int) -> tuple[int, int]:
    """Where the string whose quote is at ``quote_at`` ends, and the state after it."""
    quote = text[quote_at]
    triple = quote * 3
    if text.startswith(triple, quote_at):
        close = _find_close(text, quote_at + 3, triple)
        return (close, NORMAL) if close >= 0 else (len(text), _STATE_OF[triple])
    close = _find_close(text, quote_at + 1, quote)
    return (close, NORMAL) if close >= 0 else (len(text), NORMAL)  # unterminated: to the line end


def scan(text: str) -> list[list[Span]]:
    """The spans of every line of ``text`` (for tests and measurements)."""
    state, lines = NORMAL, []
    for line in text.split("\n"):
        spans, state = scan_line(line, state)
        lines.append(spans)
    return lines
