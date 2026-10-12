"""The editor's icons (P6a, ADR 0040): semantic names drawn as Phosphor glyphs.

QtAwesome provides the glyphs as an icon font; it is imported on the first icon,
so commands that never open a window never load it. Icons are tinted with the
theme's text colour, and its disabled colour when their widget is disabled.
"""

from __future__ import annotations

from functools import cache

from PySide6.QtGui import QIcon

from . import theme

# semantic name -> Phosphor glyph (https://phosphoricons.com)
NAMES: dict[str, str] = {
    "add": "plus",
    "delete": "trash",
    "move-up": "arrow-up",
    "move-down": "arrow-down",
    "parts": "puzzle-piece",
    "play": "play",
    "pause": "pause",
    "step-back": "skip-back",
    "step-forward": "skip-forward",
    "keyframe": "diamond",
    "marker": "flag",
    "snap": "magnet",
    "export": "export",
    "open": "folder-open",
    "save": "floppy-disk",
    "zoom-in": "magnifying-glass-plus",
    "code": "code",
    "sound": "speaker-high",
    "text": "text-t",
    "visible": "eye",
    "hidden": "eye-slash",
    "folder": "folder",
    "close": "x",
    # workspace pages (ADR 0041)
    "compose": "layout",
    "animate": "chart-line",
    "code-page": "code",
    "audio": "speaker-high",
    "deliver": "rocket-launch",
}


@cache
def icon(name: str) -> QIcon:
    """The icon for a semantic ``name`` (KeyError for a name not in NAMES)."""
    import qtawesome as qta  # the icon fonts load here, once

    colours = theme.THEME
    return qta.icon(
        f"ph.{NAMES[name]}",
        color=theme.qcolor(colours.text),
        color_disabled=theme.qcolor(colours.disabled),
        color_active=theme.qcolor(colours.text),
    )
