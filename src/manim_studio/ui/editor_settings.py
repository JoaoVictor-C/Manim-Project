"""How the Code page's text editor behaves (P12): font size, tabs, wrapping, the gutter, the
line tint, visible whitespace, auto-closing brackets and trimming trailing whitespace.

Plain data and helpers without Qt: ``EditorSettings`` is frozen, ``clamp`` brings every value
into its allowed range, and ``to_json`` / ``from_json`` turn it into the text kept in the
preferences file. ``from_json`` never raises: anything it cannot use falls back to the
default of that one field.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace

MIN_FONT_SIZE = 7
MAX_FONT_SIZE = 32
TAB_WIDTHS = (2, 4, 8)


@dataclass(frozen=True)
class EditorSettings:
    font_size: int = 10  # points
    tab_width: int = 4  # columns per indent: 2, 4 or 8
    word_wrap: bool = False
    line_numbers: bool = True  # the gutter
    highlight_line: bool = True  # tint the line the cursor is on
    show_whitespace: bool = False  # draw spaces and tabs
    auto_close_brackets: bool = True  # ( [ { " ' typed as pairs
    trim_trailing_whitespace: bool = False  # drop it from ``CodeEditor.trimmed_text()``
    suggest_names: bool = (
        True  # offer Manim and the code's own names while typing, and describe them on hover
    )


def clamp(settings: EditorSettings) -> EditorSettings:
    """``settings`` with the font size in 7..32 and the tab width one of 2, 4, 8 (the nearest)."""
    size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, int(settings.font_size)))
    tab = min(TAB_WIDTHS, key=lambda width: (abs(width - int(settings.tab_width)), width))
    return replace(settings, font_size=size, tab_width=tab)


def to_json(settings: EditorSettings) -> str:
    """The settings as one line of JSON (one key per field)."""
    return json.dumps({f.name: getattr(settings, f.name) for f in fields(settings)}, sort_keys=True)


def from_json(text: str) -> EditorSettings:
    """The settings ``text`` holds; every field that is missing or of the wrong type is the default,
    unknown keys are ignored and a text that is not a JSON object gives all defaults."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return EditorSettings()
    if not isinstance(data, dict):
        return EditorSettings()
    defaults = EditorSettings()
    values = {}
    for f in fields(defaults):
        value, default = data.get(f.name), getattr(defaults, f.name)
        # bool is an int in Python: a number is never a flag and a flag is never a number
        right_type = (
            isinstance(value, bool)
            if isinstance(default, bool)
            else (isinstance(value, int) and not isinstance(value, bool))
        )
        values[f.name] = value if right_type else default
    return clamp(EditorSettings(**values))
