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
    # the welcome (P6d.1)
    "example": "sparkle",
    # the Code page (P6b.3)
    "revert": "arrow-counter-clockwise",
    # the Animate page (P7.3)
    "record": "record-fill",
    # the Code workspace (P12): the Python logo for .py code (from the Material Design icon font that
    # ships with QtAwesome), blue for a Python object and yellow for a Manim scene
    "py-object": "mdi6.language-python",
    "py-scene": "mdi6.language-python",
    "helper": "mdi6.function-variant",  # a helper: a module the code imports (ADR 0058)
    "sidebar": "mdi6.dock-left",
    "panel": "mdi6.dock-bottom",
    "outline": "mdi6.vector-selection",
    # the panel buttons and full screen (P12)
    "sidebar-right": "mdi6.dock-right",
    "fullscreen": "mdi6.fullscreen",
    "fullscreen-exit": "mdi6.fullscreen-exit",
    # the full-screen player's bar
    "player-start": "mdi6.skip-previous",
    "player-end": "mdi6.skip-next",
    "player-back": "mdi6.rewind-5",
    "player-forward": "mdi6.fast-forward-5",
    "player-loop": "mdi6.repeat",
    "player-loop-off": "mdi6.repeat-off",
    "player-volume": "mdi6.volume-high",
    "player-mute": "mdi6.volume-off",
}

# icons drawn in another theme colour than the text: Record's red dot, the Python logos, the helpers
TINTS: dict[str, str] = {
    "record": "danger",
    "py-object": "py_object",
    "py-scene": "py_scene",
    "helper": "success",
}


@cache
def icon(name: str) -> QIcon:
    """The icon for a semantic ``name`` (KeyError for a name not in NAMES)."""
    import qtawesome as qta  # the icon fonts load here, once

    colours = theme.THEME
    ink = theme.qcolor(getattr(colours, TINTS.get(name, "text")))
    glyph = NAMES[name]
    return qta.icon(
        glyph if "." in glyph else f"ph.{glyph}",
        color=ink,
        color_disabled=theme.qcolor(colours.disabled),
        color_active=ink,
    )
