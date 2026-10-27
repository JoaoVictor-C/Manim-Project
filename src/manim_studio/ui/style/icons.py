"""The editor's icons (P6a, ADR 0040; Lumen, ADR 0063): semantic names drawn as Phosphor glyphs.

The glyphs are the Phosphor icon font that QtAwesome ships, and a few from its Material Design font. Only
those two fonts are loaded, from QtAwesome's own files, on the first icon (so commands that never open a
window never touch them): QtAwesome itself loads a dozen icon fonts the editor does not use, about 40 MB of
memory. Where a font cannot be found, QtAwesome draws that icon as before. An icon is a ``QIcon`` with an
engine that draws the glyph at the moment it is painted, in the colours of the theme *then*, so a theme switch
needs no one to set the icons again. Icons are tinted with the theme's text colour (muted for the ones that
sit quietly), and its disabled colour when their widget is disabled.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QIconEngine, QPainter, QPixmap

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
    "more": "dots-three",
    "lock": "lock-simple",
    "maths": "math-operations",
    "shape": "polygon",
    "circle": "circle",
    "line": "line-segment",
    "axes": "chart-line",
    "group": "selection-all",
    "number": "hash",
    "object": "cube",
    "part": "puzzle-piece",
    "trace": "path",
    "simulation": "atom",
    "scene": "film-strip",
    "presets": "squares-four",
    # the Code page in Lumen (P17.4d): the kind chips of the explorer, the toolbar and the output
    "kind-scene": "code",
    "kind-object": "cube",
    "kind-helper": "brackets-curly",
    "kind-preset": "text-align-left",
    "editor-settings": "sliders-horizontal",
    "rename": "pencil-simple",
    "save-file": "floppy-disk",
    "convert": "squares-four",
    "stop": "stop",
    "error": "warning-circle",
    "history": "clock-counter-clockwise",
    "chapters": "film-strip",
    "import": "arrow-square-out",
    "collapse": "caret-down",
}

# icons drawn in another theme colour than the text: Record's red dot, the Python logos, the helpers
TINTS: dict[str, str] = {
    "record": "danger",
    "py-object": "py_object",
    "py-scene": "py_scene",
    "helper": "success",
    "error": "danger",
}

_drawn: dict[tuple, QIcon] = {}  # (theme, name, tint) -> QtAwesome's glyph in that colour (the fallback)
_pixmaps: dict[tuple, QPixmap] = {}  # (theme, name, tint, size, disabled) -> the glyph drawn at that size
_PIXMAP_LIMIT = 2000
# QtAwesome's prefix -> (its font file, its table of glyph names), found in its fonts folder
FONTS = {
    "ph": ("phosphor-[0-9]*.ttf", "phosphor-charmap-*.json"),
    "mdi6": ("materialdesignicons6-webfont-*.ttf", "materialdesignicons6-webfont-charmap-*.json"),
}
_fonts: dict[str, tuple[str, dict[str, str]] | None] = {}  # prefix -> (family, character of each glyph used)


def _split(glyph: str) -> tuple[str, str]:
    """``("ph", "plus")`` for ``"plus"`` (Phosphor), ``("mdi6", "dock-left")`` for ``mdi6.dock-left``."""
    prefix, _, short = glyph.rpartition(".")
    return prefix or "ph", short


def _font(prefix: str) -> tuple[str, dict[str, str]] | None:
    """A QtAwesome font, registered with Qt, and the character of each of its glyphs the editor uses; None
    when its file cannot be found (QtAwesome then draws those icons)."""
    if prefix not in _fonts:
        _fonts[prefix] = None
        if prefix in FONTS:
            try:
                spec = importlib.util.find_spec(
                    "qtawesome"
                )  # found, not imported: that would load every font
                folder = Path(next(iter(spec.submodule_search_locations))) / "fonts"
                font_file = next(folder.glob(FONTS[prefix][0]))
                table_file = next(folder.glob(FONTS[prefix][1]))
                families = QFontDatabase.applicationFontFamilies(
                    QFontDatabase.addApplicationFont(str(font_file))
                )
                table = json.loads(table_file.read_text(encoding="utf-8"))
                wanted = {short for p, short in map(_split, NAMES.values()) if p == prefix}
                if families:
                    _fonts[prefix] = (
                        families[0],
                        {n: chr(int(c, 16)) for n, c in table.items() if n in wanted},
                    )
            except (AttributeError, StopIteration, OSError, ValueError, TypeError):
                _fonts[prefix] = None
    return _fonts[prefix]


def _drawn_glyph(painter: QPainter, rect: QRect, name: str, tint: str | None, disabled: bool) -> bool:
    """Draw glyph ``name`` centred in ``rect`` the way QtAwesome does (the glyph at 7/8 of the height, to
    leave the font's bearings); False when its font is not there."""
    prefix, glyph = _split(NAMES[name])
    font_data = _font(prefix)
    if font_data is None or glyph not in font_data[1]:
        return False
    family, chars = font_data
    colours = theme.THEME
    ink = theme.qcolor(colours.disabled if disabled else getattr(colours, tint or TINTS.get(name, "text")))
    font = QFont(family)
    font.setPixelSize(round(0.875 * rect.height()))
    painter.setPen(ink)
    painter.setFont(font)
    painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter), chars[glyph])
    return True


def _qtawesome_glyph(name: str, tint: str | None = None) -> QIcon:
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
        if size.isEmpty():
            return QPixmap()
        disabled = mode == QIcon.Mode.Disabled
        key = (theme.THEME.name, self.name, self.tint, size.width(), size.height(), disabled)
        cached = _pixmaps.get(key)
        if cached is not None:
            return cached
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        drawn = _drawn_glyph(
            painter, QRect(0, 0, size.width(), size.height()), self.name, self.tint, disabled
        )
        painter.end()
        if not drawn:
            return _qtawesome_glyph(self.name, self.tint).pixmap(size, mode, state)
        if len(_pixmaps) >= _PIXMAP_LIMIT:
            _pixmaps.clear()
        _pixmaps[key] = pixmap
        return pixmap

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
    _pixmaps.clear()
