"""The editor's icons (P6a, ADR 0040; Lumen, ADR 0063): semantic names drawn as Phosphor glyphs.

QtAwesome provides the glyphs as an icon font; it is imported on the first icon, so commands that never
open a window never load it. An icon is a ``QIcon`` with an engine that draws the glyph at the moment it is
painted, in the colours of the theme *then*, so a theme switch needs no one to set the icons again. Icons are
tinted with the theme's text colour (muted for the ones that sit quietly), and its disabled colour when their
widget is disabled.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap

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
    "search": "magnifying-glass",
    "undo": "arrow-u-up-left",
    "redo": "arrow-u-up-right",
    # workspace pages (ADR 0041)
    "compose": "layout",
    "animate": "chart-line",
    "code-page": "code",
    "audio": "speaker-high",
    "deliver": "rocket-launch",
    # destinations, queue rows, dialogs and the mix lanes (P17.4d)
    "film": "film-strip",
    "phone": "device-mobile",
    "image": "image",
    "gif": "gif",
    "check": "check",
    "done": "check-circle",
    "failed": "x-circle",
    "warning": "warning",
    "clock": "clock",
    "keyboard": "keyboard",
    "plugin": "puzzle-piece",
    "settings": "sliders-horizontal",
    "music": "music-notes",
    "effects": "lightning",
    "subtitles": "chat-text",
    "narration": "microphone",
    "mute": "speaker-slash",
    "python": "mdi6.language-python",
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
    # Lumen panels (P17.4a): carets, the filter, layer kinds
    "caret-down": "caret-down",
    "caret-right": "caret-right",
    "search": "magnifying-glass",
    "more": "dots-three",
    "lock": "lock-simple",
    "maths": "math-operations",
    "shape": "polygon",
    "circle": "circle",
    "line": "line-segment",
    "axes": "chart-line",
    "group": "selection-all",
    "image": "image",
    "number": "hash",
    "object": "cube",
    "part": "puzzle-piece",
    "trace": "path",
    "simulation": "atom",
    "scene": "film-strip",
    "presets": "squares-four",
}

# icons drawn in another theme colour than the text: Record's red dot, the Python logos, the helpers
TINTS: dict[str, str] = {
    "record": "danger",
    "py-object": "py_object",
    "py-scene": "py_scene",
    "helper": "success",
}

_drawn: dict[tuple, QIcon] = {}  # (theme, name, tint) -> the glyph in that colour


def _glyph(name: str, tint: str | None = None) -> QIcon:
    import qtawesome as qta  # the icon fonts load here, once

    colours = theme.THEME
    key = (colours.name, name, tint)
    cached = _drawn.get(key)
    if cached is None:
        ink = theme.qcolor(getattr(colours, tint or TINTS.get(name, "text")))
        glyph = NAMES[name]
        cached = qta.icon(
            glyph if "." in glyph else f"ph.{glyph}",
            color=ink,
            color_disabled=theme.qcolor(colours.disabled),
            color_active=ink,
        )
        _drawn[key] = cached
    return cached


class _ThemedEngine(QIconEngine):
    """Draws a glyph in the colours of the theme in use when it is painted."""

    def __init__(self, name: str, tint: str | None = None) -> None:
        super().__init__()
        self.name = name
        self.tint = tint

    def clone(self) -> QIconEngine:
        return _ThemedEngine(self.name, self.tint)

    def actualSize(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QSize:
        return size

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return _glyph(self.name, self.tint).pixmap(size, mode, state)

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        painter.drawPixmap(rect, self.pixmap(rect.size(), mode, state))


def icon(name: str, tint: str | None = None) -> QIcon:
    """The icon for a semantic ``name`` (KeyError for a name not in NAMES); ``tint`` names a theme token to
    draw it in instead of the usual one (``"muted"`` for an icon that sits quietly)."""
    if name not in NAMES:
        raise KeyError(name)
    return QIcon(_ThemedEngine(name, tint))


def refresh() -> None:
    """Forget the drawn glyphs (after a theme switch the engines draw them again in the new colours)."""
    _drawn.clear()
