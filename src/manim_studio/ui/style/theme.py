"""The design system (P6a, ADR 0040; Lumen, P17, ADR 0063): colour tokens, type, space and the application look.

Every colour the editor's own chrome uses comes from a ``Colours`` token set: the panels and widgets
(through a Fusion palette and one stylesheet generated from the tokens), the timeline's painted rows and
bars, the canvas overlays and the curve editor. Colours that belong to the document - layer styles, the
canvas background, marker and subtitle colours, the dashed placeholder Manim draws in the frame - are
content and never come from here: they are what the export renders.

Two sets exist, **Ink** (dark, the default) and **Paper** (light). ``THEME`` is the one in use; code reads
it through the module (``theme.THEME.panel``), never ``from theme import THEME``, so ``set_theme`` reaches
everything that paints. ``apply(app)`` is called by ``run()`` and by the tests' application fixture, so the
tests drive the widgets the user sees.

Type is bundled (Inter for the interface, JetBrains Mono for code and numbers, Newsreader for titles; all
SIL Open Font License, in ``fonts/``); if a file does not load the system fonts take over.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QStyleFactory, QWidget

SPACE = 4  # px: the spacing grid
RADIUS = 9  # px: corners of fields and buttons
RADIUS_CARD = 14  # px: panels (cards)
RADIUS_ROW = 10  # px: list rows
RADIUS_SMALL = 7  # px: small controls
GUTTER = 8  # px: between cards
UI_POINT_SIZE = 9  # 12 px at 96 dpi
FONT_DIR = Path(__file__).with_name("fonts")
UI_FAMILIES = ("Inter", "Segoe UI Variable", "Segoe UI", "Helvetica Neue", "Arial")
MONO_FAMILIES = ("JetBrains Mono", "Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono")
SERIF_FAMILIES = ("Newsreader 16pt", "Newsreader", "Georgia", "Times New Roman")
FONT_FILES = (
    "Inter-Regular.ttf",
    "Inter-Medium.ttf",
    "Inter-SemiBold.ttf",
    "Inter-Bold.ttf",
    "JetBrainsMono-Regular.ttf",
    "JetBrainsMono-Medium.ttf",
    "JetBrainsMono-Bold.ttf",
    "Newsreader16pt-Regular.ttf",
    "Newsreader16pt-Italic.ttf",
    "Newsreader16pt-MediumItalic.ttf",
)

# The type scale: role -> (pixel size, weight). Sizes are pixels at 96 dpi.
TYPE: dict[str, tuple[int, int]] = {
    "display": (52, 500),
    "title": (22, 650),
    "heading": (14, 650),
    "body": (12, 400),
    "label": (12, 500),
    "caption": (11, 500),
    "section": (11, 650),
}


@dataclass(frozen=True)
class Colours:
    """Colour roles as ``#rrggbb`` or ``#rrggbbaa`` (alpha last)."""

    name: str  # "ink" | "paper"
    dark: bool
    # chrome: surfaces step lighter as they rise (window < panel < raised < surface_3)
    window: str  # behind everything: the gutters between cards, the canvas around the frame
    panel: str  # cards and their contents
    raised: str  # headers, menus, buttons at rest
    surface_3: str  # hovered rows, segmented-control chips, popovers
    field: str  # line edits, spin boxes, lists, the code editor (recessed)
    stage: str  # the pasteboard around the video frame
    border: str
    divider: str
    line: str  # hairlines drawn over any surface (alpha)
    line_strong: str
    text: str
    muted: str  # secondary text, units, hints
    faint: str  # tertiary: placeholders and keyboard hints (never the only carrier of meaning)
    disabled: str
    accent: str  # selection, focus, the current item, the primary action
    accent_2: str  # the other end of the accent gradient (play, playhead, progress)
    accent_text: str  # the accent as text or an icon on a surface
    accent_soft: str  # a tinted background for the current row or chip
    accent_line: str  # the border that goes with it
    on_accent: str  # text on the accent
    hover: str  # a ghost control while hovered
    warning: str
    danger: str
    success: str
    tooltip: str
    shadow: str
    # the timeline
    track: str  # behind the rows
    ruler: str
    lifetime: str  # a layer's visible span
    playhead: str
    guide: str  # where a snapped drag rests (ADR 0037)
    bar_edge: str
    bar_selected: str
    bar_text: str
    content: str  # clip categories (ADR 0022)
    emphasis: str
    motion: str
    morph: str
    sound: str
    wave: str
    cue: str
    key: str
    key_selected: str
    key_edge: str
    # the canvas and the curve editor
    frame_border: str
    pasteboard_dim: str  # over what lies outside the video frame
    outline: str  # the selected object's outline
    motion_path: str  # ADR 0026
    badge: str  # behind the canvas's small labels
    badge_text: str
    curve: str
    curve_handle: str
    grid: str
    # the code editor (P6b.3): Python highlighting on the field colour, the current and the error line
    syntax_keyword: str
    syntax_string: str
    syntax_number: str
    syntax_comment: str
    syntax_manim: str  # Manim's own names: Scene, Circle, Create, ...
    syntax_definition: str  # the name after def and class
    code_line: str  # the line the cursor is on
    code_error_line: str  # the line a render error points at
    search_match: str  # every find match in the code editor
    search_current: str  # the match the find bar is on
    py_object: str  # the Python logo on a Python object (the logo's blue)
    py_scene: str  # the Python logo on a Manim scene (the logo's yellow)
    error_text: str  # error words on panels and the gutter
    # the graph editor's curves (P6b.2): one per keyed value, x red and y green as elsewhere
    curve_x: str
    curve_y: str
    curve_scale: str
    curve_width: str
    curve_height: str
    curve_rotation: str
    curve_opacity: str


INK = Colours(
    name="ink",
    dark=True,
    window="#0a0c12",
    panel="#11141d",
    raised="#171b27",
    surface_3="#1e2332",
    field="#0d1018",
    stage="#07080d",
    border="#272c3b",
    divider="#1b1f2c",
    line="#ffffff12",
    line_strong="#ffffff1f",
    text="#e9ecf6",
    muted="#9aa2ba",
    faint="#7a829b",
    disabled="#5f6780",
    accent="#6e5ff0",
    accent_2="#4cc9f0",
    accent_text="#a79dff",
    accent_soft="#6e5ff029",
    accent_line="#6e5ff08c",
    on_accent="#ffffff",
    hover="#ffffff0d",
    warning="#ffb020",
    danger="#ff5c7a",
    success="#3ddc97",
    tooltip="#1e2332",
    shadow="#00000080",
    track="#0d1018",
    ruler="#141824",
    lifetime="#ffffff1a",
    playhead="#4cc9f0",
    guide="#facc15aa",
    bar_edge="#00000066",
    bar_selected="#ffffff",
    bar_text="#ffffff",
    content="#3e6fe8",
    emphasis="#cc4b0a",
    motion="#0a8460",
    morph="#9333ea",
    sound="#e11d48",
    wave="#ffe4ebc0",
    cue="#4b5470",
    key="#ffd166",
    key_selected="#ffffff",
    key_edge="#000000a0",
    frame_border="#596077",
    pasteboard_dim="#07080daa",
    outline="#7dd3fc",
    motion_path="#ffb020",
    badge="#0d1018",
    badge_text="#e9ecf6",
    curve="#7dd3fc",
    curve_handle="#ffd166",
    grid="#ffffff1f",
    syntax_keyword="#c792ea",
    syntax_string="#a5e075",
    syntax_number="#f78c6c",
    syntax_comment="#7c85a3",
    syntax_manim="#5ec8f5",
    syntax_definition="#82aaff",
    code_line="#6e5ff01f",
    code_error_line="#ff5c7a24",
    search_match="#ffb02044",
    search_current="#6e5ff0b0",
    py_object="#5b9bd5",
    py_scene="#ffd43b",
    error_text="#ff7b93",
    curve_x="#ff7b93",
    curve_y="#4ade80",
    curve_scale="#7aa2ff",
    curve_width="#fbbf24",
    curve_height="#fb7185",
    curve_rotation="#c792ea",
    curve_opacity="#2dd4bf",
)

PAPER = Colours(
    name="paper",
    dark=False,
    window="#e4e7f0",
    panel="#ffffff",
    raised="#f4f5fa",
    surface_3="#e9ebf4",
    field="#eff1f8",
    stage="#d9dde9",
    border="#d5d9e6",
    divider="#e8eaf2",
    line="#14182d14",
    line_strong="#14182d26",
    text="#171a2b",
    muted="#555d78",
    faint="#6f7790",
    disabled="#a3a9bd",
    accent="#5b4bea",
    accent_2="#0b8fbf",
    accent_text="#4b3bd6",
    accent_soft="#5b4bea1f",
    accent_line="#5b4bea80",
    on_accent="#ffffff",
    hover="#14182d0d",
    warning="#96590a",
    danger="#cf2148",
    success="#0f8a5a",
    tooltip="#ffffff",
    shadow="#1e24462e",
    track="#f3f4fa",
    ruler="#eceef6",
    lifetime="#14182d14",
    playhead="#d62950",
    guide="#b45309aa",
    bar_edge="#0000003a",
    bar_selected="#171a2b",
    bar_text="#ffffff",
    content="#3e6fe8",
    emphasis="#cc4b0a",
    motion="#0a8460",
    morph="#9333ea",
    sound="#e11d48",
    wave="#ffe4ebc0",
    cue="#4b5470",
    key="#d99a00",
    key_selected="#171a2b",
    key_edge="#00000060",
    frame_border="#9aa1b8",
    pasteboard_dim="#d9dde9e0",
    outline="#2563eb",
    motion_path="#b45309",
    badge="#171a2b",
    badge_text="#ffffff",
    curve="#2563eb",
    curve_handle="#b45309",
    grid="#14182d1f",
    syntax_keyword="#7c3aed",
    syntax_string="#1f7a4a",
    syntax_number="#b3470a",
    syntax_comment="#5e6684",
    syntax_manim="#0b6f96",
    syntax_definition="#2f55d4",
    code_line="#5b4bea14",
    code_error_line="#cf214824",
    search_match="#b4530944",
    search_current="#5b4bea66",
    py_object="#306998",
    py_scene="#b38600",
    error_text="#cf2148",
    curve_x="#cf2148",
    curve_y="#15803d",
    curve_scale="#2563eb",
    curve_width="#b45309",
    curve_height="#be123c",
    curve_rotation="#7c3aed",
    curve_opacity="#0f766e",
)

STUDIO = INK  # the name the first design system gave the dark set
THEMES: dict[str, Colours] = {"ink": INK, "paper": PAPER}

THEME = INK  # the token set in use


class _Signals(QObject):
    themeChanged = Signal(str)


signals = _Signals()  # ``theme.signals.themeChanged``: after set_theme, repaint what is painted by hand


def qcolor(token: str) -> QColor:
    """A token as a QColor (``#rrggbbaa`` carries alpha last, unlike Qt's own ``#aarrggbb``)."""
    if len(token) == 9:
        colour = QColor(token[:7])
        colour.setAlpha(int(token[7:], 16))
        return colour
    return QColor(token)


def css(token: str) -> str:
    """A token for a stylesheet: ``rgba(...)`` when it has alpha."""
    if len(token) == 9:
        c = qcolor(token)
        return f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()})"
    return token


def luminance(token: str) -> float:
    """Relative luminance (WCAG 2.1) of a colour token, ignoring alpha."""

    def channel(value: int) -> float:
        v = value / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    c = qcolor(token)
    return 0.2126 * channel(c.red()) + 0.7152 * channel(c.green()) + 0.0722 * channel(c.blue())


def contrast(a: str, b: str) -> float:
    """The WCAG contrast ratio of two colour tokens (1 to 21)."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def readable_on(colour: str) -> str:
    """Black or white, whichever reads better on ``colour`` (a document colour's swatch)."""
    try:
        return "black" if contrast("#000000", colour) >= contrast("#ffffff", colour) else "white"
    except (TypeError, ValueError):
        return "white"


def mix(a: str, b: str, amount: float) -> str:
    """``a`` moved ``amount`` (0..1) of the way to ``b``, as a ``#rrggbb`` token (alpha ignored)."""
    ca, cb = qcolor(a), qcolor(b)
    t = max(0.0, min(1.0, amount))
    parts = [
        round(x + (y - x) * t)
        for x, y in ((ca.red(), cb.red()), (ca.green(), cb.green()), (ca.blue(), cb.blue()))
    ]
    return "#{:02x}{:02x}{:02x}".format(*parts)


# -- fonts ----------------------------------------------------------------------------------------

_loaded = False
_families: dict[str, str] = {}  # "ui" | "mono" | "serif" -> the family in use


def load_fonts() -> dict[str, str]:
    """Register the bundled fonts (once) and decide the families in use; the system's when a file is missing."""
    global _loaded
    if not _loaded:
        _loaded = True
        for name in FONT_FILES:
            path = FONT_DIR / name
            if path.is_file():
                QFontDatabase.addApplicationFont(str(path))
    available = set(QFontDatabase.families())
    for role, wanted in (("ui", UI_FAMILIES), ("mono", MONO_FAMILIES), ("serif", SERIF_FAMILIES)):
        _families[role] = next((f for f in wanted if f in available), "")
    return dict(_families)


def family(role: str) -> str:
    """The font family for ``"ui"``, ``"mono"`` or ``"serif"`` (an empty string: the system default)."""
    if not _families:
        load_fonts()
    return _families.get(role, "")


def font(role: str = "body", *, kind: str = "ui") -> QFont:
    """A font from the type scale: ``role`` in ``TYPE``; ``kind`` ``"ui"``, ``"mono"`` or ``"serif"``."""
    pixels, weight = TYPE[role]
    f = QFont(family(kind) or QFont().family())
    f.setPixelSize(pixels)
    f.setWeight(_weight(weight))
    if kind == "mono":
        f.setStyleHint(QFont.StyleHint.Monospace)
    return f


def _weight(value: int) -> QFont.Weight:
    if value >= 700:
        return QFont.Weight.Bold
    if value >= 600:
        return QFont.Weight.DemiBold
    return QFont.Weight.Medium if value >= 500 else QFont.Weight.Normal


def mono_font(point_size: int = UI_POINT_SIZE) -> QFont:
    """A monospace font for code and time readouts (JetBrains Mono, else the first family installed)."""
    name = family("mono")
    f = QFont(name) if name else QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    f.setPointSize(point_size)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


# -- the palette and the stylesheet ---------------------------------------------------------------


def palette(c: Colours | None = None) -> QPalette:
    c = c or THEME
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: c.panel,
        QPalette.ColorRole.WindowText: c.text,
        QPalette.ColorRole.Base: c.field,
        QPalette.ColorRole.AlternateBase: c.panel,
        QPalette.ColorRole.Text: c.text,
        QPalette.ColorRole.PlaceholderText: c.faint,
        QPalette.ColorRole.Button: c.raised,
        QPalette.ColorRole.ButtonText: c.text,
        QPalette.ColorRole.BrightText: c.on_accent,
        QPalette.ColorRole.Highlight: c.accent,
        QPalette.ColorRole.HighlightedText: c.on_accent,
        QPalette.ColorRole.ToolTipBase: c.tooltip,
        QPalette.ColorRole.ToolTipText: c.text,
        QPalette.ColorRole.Link: c.accent_text,
        QPalette.ColorRole.Light: c.border,
        QPalette.ColorRole.Midlight: c.raised,
        QPalette.ColorRole.Mid: c.muted,
        QPalette.ColorRole.Dark: c.window,
        QPalette.ColorRole.Shadow: c.window,
    }
    for role, token in roles.items():
        pal.setColor(role, qcolor(token))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, qcolor(c.disabled))
    return pal


def _svg_dir(c: Colours) -> Path:
    """The few images a stylesheet needs (a check mark, chevrons), drawn in this theme's colours."""
    key = hashlib.sha1(f"{c.name}{c.text}{c.muted}{c.on_accent}{c.accent_text}".encode()).hexdigest()[:10]
    folder = Path(tempfile.gettempdir()) / f"manim-studio-ui-{key}"
    folder.mkdir(parents=True, exist_ok=True)
    images = {
        "check.svg": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="{c.on_accent[:7]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        "check-accent.svg": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="{c.accent_text[:7]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        "chevron-down.svg": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M4 6l4 4 4-4" fill="none" stroke="{c.muted[:7]}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        "chevron-right.svg": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M6 4l4 4-4 4" fill="none" stroke="{c.muted[:7]}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        "chevron-open.svg": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M4 6l4 4 4-4" fill="none" stroke="{c.muted[:7]}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        "radio.svg": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="3" fill="{c.on_accent[:7]}"/></svg>',
    }
    for name, text in images.items():
        target = folder / name
        if not target.is_file() or target.read_text(encoding="utf-8") != text:
            target.write_text(text, encoding="utf-8")
    return folder


def _url(path: Path) -> str:
    return "url(" + str(path).replace(chr(92), "/") + ")"


def image_url(name: str, c: Colours | None = None) -> str:
    """The stylesheet ``url(...)`` of one of the stylesheet's small images (``check.svg``, ``check-accent.svg``,
    ``chevron-down.svg``...), drawn in the colours of ``c`` (the theme in use)."""
    return _url(_svg_dir(c or THEME) / name)


_RULES: list = []  # functions ``(Colours) -> str``: stylesheet rules a module owns (see ``register_rules``)


def register_rules(rules) -> None:
    """Add a module's own stylesheet rules: ``rules(colours)`` returns QSS built from the tokens. They are
    appended to the application stylesheet now and after every theme switch, so a widget's look follows the
    theme without the module keeping colours of its own."""
    if rules not in _RULES:
        _RULES.append(rules)
        app = QApplication.instance()
        if app is not None and app.styleSheet():
            app.setStyleSheet(stylesheet(THEME))


def stylesheet(c: Colours | None = None) -> str:
    """The application stylesheet, generated from the tokens (no colour is written twice)."""
    c = c or THEME
    r, s, rc = RADIUS, SPACE, RADIUS_CARD
    img = _svg_dir(c)
    accent_grad = (
        f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {mix(c.accent, '#ffffff', 0.10)}, stop:1 {c.accent})"
    )
    track_grad = f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {c.accent}, stop:1 {c.accent_2})"
    return f"""
QMainWindow, QDialog {{ background: {c.window}; }}
QWidget {{ color: {c.text}; }}
QToolTip {{ background: {c.tooltip}; color: {c.text}; border: 1px solid {css(c.line_strong)}; border-radius: {RADIUS_SMALL}px; padding: {s}px {2 * s}px; }}
QMenuBar {{ background: transparent; border: 0; }}
QMenuBar::item {{ padding: 5px 9px; background: transparent; color: {c.muted}; border-radius: {RADIUS_SMALL}px; font-weight: 500; }}
QMenuBar::item:selected, QMenuBar::item:pressed {{ background: {c.raised}; color: {c.text}; }}
QMenu {{ background: {c.raised}; border: 1px solid {css(c.line_strong)}; border-radius: 12px; padding: 6px; }}
QMenu::item {{ padding: 7px 30px 7px 12px; border-radius: 8px; margin: 1px 0; }}
QMenu::item:selected {{ background: {css(c.accent_soft)}; color: {c.text}; }}
QMenu::item:disabled {{ color: {c.disabled}; }}
QMenu::icon {{ padding-left: 6px; }}
QMenu::indicator {{ width: 14px; height: 14px; margin-left: 6px; }}
QMenu::separator {{ height: 1px; background: {css(c.line)}; margin: 5px 8px; }}
QMenu::right-arrow {{ image: {_url(img / "chevron-right.svg")}; width: 12px; height: 12px; margin-right: 8px; }}
QStatusBar {{ background: transparent; color: {c.faint}; border: 0; }}
QStatusBar::item {{ border: 0; }}
QPushButton {{
    background: {c.surface_3}; color: {c.text}; border: 1px solid {css(c.line_strong)}; border-radius: {r}px;
    padding: 5px 13px; font-weight: 600; min-height: 18px;
}}
QPushButton:hover {{ background: {mix(c.surface_3, c.text, 0.07)}; }}
QPushButton:pressed {{ background: {mix(c.surface_3, c.window, 0.35)}; }}
QPushButton:disabled {{ color: {c.disabled}; background: transparent; border-color: {css(c.line)}; }}
QPushButton:focus {{ border-color: {c.accent}; }}
QPushButton[role="primary"], QPushButton[role="primary"]:default {{
    background: {accent_grad}; color: {c.on_accent}; border: 0; padding: 6px 14px;
}}
QPushButton[role="primary"]:hover {{ background: {mix(c.accent, "#ffffff", 0.14)}; }}
QPushButton[role="primary"]:pressed {{ background: {mix(c.accent, "#000000", 0.2)}; }}
QPushButton[role="primary"]:disabled {{ background: {c.surface_3}; color: {c.disabled}; }}
QPushButton[role="ghost"] {{ background: transparent; border-color: transparent; color: {c.muted}; }}
QPushButton[role="ghost"]:hover {{ background: {css(c.hover)}; color: {c.text}; }}
QPushButton[role="danger"] {{ color: {c.danger}; background: transparent; border-color: {css(c.line_strong)}; }}
QPushButton[role="link"] {{ background: transparent; border: 0; color: {c.accent_text}; text-align: left; padding: {s}px; }}
QPushButton[role="link"]:hover {{ text-decoration: underline; }}
QToolButton {{
    background: transparent; color: {c.text}; border: 1px solid transparent; border-radius: {r}px;
    padding: 4px 6px;
}}
QToolButton:hover {{ background: {css(c.hover)}; }}
QToolButton:pressed {{ background: {css(c.line)}; }}
QToolButton:checked {{ background: {css(c.accent_soft)}; border-color: {css(c.accent_line)}; }}
QToolButton:disabled {{ color: {c.disabled}; }}
QToolButton[role="outlined"] {{ border-color: {css(c.line_strong)}; background: {c.surface_3}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {c.field}; border: 1px solid {css(c.line)}; border-radius: {r}px; padding: 2px {s + 4}px;
    selection-background-color: {c.accent}; selection-color: {c.on_accent};
}}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {css(c.line_strong)}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus {{ border-color: {c.accent}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {c.disabled}; }}
QLineEdit[pending="true"], QSpinBox[pending="true"], QDoubleSpinBox[pending="true"],
QComboBox[pending="true"], QPlainTextEdit[pending="true"] {{ color: {c.muted}; font-style: italic; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 0; border: 0;
}}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ border: 0; width: 24px; }}
QComboBox::down-arrow {{ image: {_url(img / "chevron-down.svg")}; width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {c.raised}; border: 1px solid {css(c.line_strong)}; border-radius: 10px; padding: 4px;
    selection-background-color: {css(c.accent_soft)}; selection-color: {c.text}; outline: 0;
}}
QTreeView, QListView, QTreeWidget, QListWidget {{
    background: {c.field}; border: 1px solid {css(c.line)}; border-radius: {r}px; outline: 0;
}}
QTreeView::item, QListView::item {{ padding: 4px 6px; border-radius: {RADIUS_SMALL}px; margin: 1px 3px; }}
QTreeView::item:hover, QListView::item:hover {{ background: {css(c.hover)}; }}
QTreeView::item:selected, QListView::item:selected {{
    background: {css(c.accent_soft)}; color: {c.text};
}}
QTreeView::branch:has-children:closed {{ image: {_url(img / "chevron-right.svg")}; }}
QTreeView::branch:has-children:open {{ image: {_url(img / "chevron-open.svg")}; }}
QHeaderView::section {{
    background: {c.raised}; border: 0; border-right: 1px solid {css(c.line)}; padding: {s}px; color: {c.muted};
}}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border: 1px solid {css(c.line_strong)}; border-radius: 5px; background: {c.field};
}}
QCheckBox::indicator:hover {{ border-color: {c.accent}; }}
QCheckBox::indicator:checked {{ background: {c.accent}; border-color: {c.accent}; image: {_url(img / "check.svg")}; }}
QRadioButton::indicator {{
    width: 16px; height: 16px; border: 1px solid {css(c.line_strong)}; border-radius: 9px; background: {c.field};
}}
QRadioButton::indicator:checked {{ background: {c.accent}; border-color: {c.accent}; image: {_url(img / "radio.svg")}; }}
QScrollArea {{ border: 0; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {css(c.line_strong)}; border-radius: 3px; min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: {c.faint}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSlider::groove:horizontal {{ height: 4px; background: {c.surface_3}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {track_grad}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: #ffffff; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
    border: 1px solid {css(c.line_strong)};
}}
QSlider::handle:horizontal:hover {{ border-color: {c.accent}; }}
QProgressBar {{ background: {c.surface_3}; border: 0; border-radius: 2px; text-align: center; }}
QProgressBar::chunk {{ background: {track_grad}; border-radius: 2px; }}
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:hover {{ background: {css(c.accent_line)}; }}
QTabBar::tab {{
    background: transparent; color: {c.muted}; padding: {s + 3}px {3 * s}px; border: 0;
    border-bottom: 2px solid transparent; font-weight: 500;
}}
QTabBar::tab:selected {{ color: {c.text}; border-bottom-color: {c.accent}; }}
QTabBar::tab:hover {{ color: {c.text}; }}
QTabWidget::pane {{ border: 0; }}
QGroupBox {{
    border: 1px solid {css(c.line)}; border-radius: {RADIUS_ROW}px; margin-top: {3 * s}px; padding-top: {s}px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: {2 * s}px; color: {c.muted}; }}
QTabBar#pageBar {{ background: transparent; }}
QTabBar#pageBar::tab {{
    background: transparent; color: {c.muted}; padding: {s + 2}px {4 * s}px; min-width: 96px;
    border: 0; border-top: 2px solid transparent;
}}
QTabBar#pageBar::tab:selected {{ color: {c.text}; border-top-color: {c.accent}; }}
QTabBar#pageBar::tab:hover {{ color: {c.text}; }}
QFrame#card {{ background: {c.panel}; border: 1px solid {css(c.line)}; border-radius: {rc}px; }}
QFrame#cardHeader {{ background: transparent; border: 0; }}
QFrame#cardRule {{ background: {css(c.line)}; border: 0; }}
QFrame#pill {{ background: {css(mix(c.raised, c.window, 0.08) + "e6")}; border: 1px solid {css(c.line_strong)}; border-radius: 18px; }}
QLabel[chip="true"] {{
    background: {c.raised}; border: 1px solid {css(c.line)}; border-radius: 11px; padding: 2px 9px;
    color: {c.muted}; font-size: 11px; font-weight: 500;
}}
QLabel[chip="true"][tone="accent"] {{ background: {css(c.accent_soft)}; border-color: {css(c.accent_line)}; color: {c.accent_text}; }}
QLabel[chip="true"][tone="ok"] {{ color: {c.success}; }}
QLabel[chip="true"][tone="warn"] {{ color: {c.warning}; }}
QLabel[chip="true"][tone="bad"] {{ color: {c.error_text}; }}
QLabel[role="section"] {{ color: {c.muted}; font-weight: 650; }}
QLabel[role="readout"] {{ color: {c.text}; }}
QLabel[role="title"] {{ color: {c.text}; font-size: 22px; font-weight: 650; }}
QLabel[role="display"] {{ color: {c.text}; font-size: 52px; font-weight: 500; }}
QLabel[role="hint"] {{ color: {c.faint}; }}
QLabel[role="muted"] {{ color: {c.muted}; }}
""" + "".join(rule(c) for rule in _RULES)


def apply(app: QApplication, colours: Colours | None = None) -> QStyle:
    """Give ``app`` the studio look: Fusion, the token palette, the stylesheet, the UI font.
    Returns the Fusion style (``app.style()`` is Qt's stylesheet wrapper around it)."""
    global THEME
    if colours is not None:
        THEME = colours
    load_fonts()
    style = QStyleFactory.create("Fusion")
    app.setStyle(style)
    app.setPalette(palette(THEME))
    ui = QFont(family("ui") or app.font().family())
    ui.setPointSize(UI_POINT_SIZE)
    ui.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(ui)
    app.setStyleSheet(stylesheet(THEME))
    install_popup_styler(app)
    return style


def resolve_appearance(name: str) -> str:
    """``ink`` or ``paper`` for a preference that may be ``system`` (the operating system's scheme)."""
    if name in THEMES:
        return name
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QGuiApplication

    hints = QGuiApplication.styleHints()
    return "paper" if hints is not None and hints.colorScheme() == _Qt.ColorScheme.Light else "ink"


def set_theme(app: QApplication, name: str) -> Colours:
    """Switch to the ``"ink"`` or ``"paper"`` set while running: palette, stylesheet and everything that
    paints from the tokens (listen to ``signals.themeChanged``)."""
    colours = THEMES.get(name)
    if colours is None:
        raise KeyError(name)
    if colours is not THEME:
        apply(app, colours)
        from . import icons

        icons.refresh()
        for widget in app.allWidgets():
            widget.update()
        for window in app.topLevelWidgets():
            style_titlebar(window)
        signals.themeChanged.emit(colours.name)
    return colours


def token_names() -> list[str]:
    return [f.name for f in fields(Colours) if f.name not in ("name", "dark")]


# -- popups and the window frame ------------------------------------------------------------------


class _PopupStyler(QObject):
    """Rounded menus need a translucent window: set it as each QMenu is first polished."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Polish and isinstance(obj, QMenu) and not obj.property("lumenStyled"):
            obj.setProperty("lumenStyled", True)
            obj.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, False)
            obj.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        elif event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            if not isinstance(obj, QMenu):
                style_titlebar(obj)
        return False


_styler: _PopupStyler | None = None


def install_popup_styler(app: QApplication) -> None:
    global _styler
    if _styler is None:
        _styler = _PopupStyler(app)
        app.installEventFilter(_styler)


def style_titlebar(window: QWidget) -> None:
    """Make the operating system's title bar follow the theme (Windows 10 build 18985+ / 11); elsewhere a no-op."""
    if sys.platform != "win32" or not window.isWindow():
        return
    try:
        import ctypes

        hwnd = int(window.winId())
        dwm = ctypes.windll.dwmapi
        c = THEME
        dark = ctypes.c_int(1 if c.dark else 0)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), 4)  # DWMWA_USE_IMMERSIVE_DARK_MODE

        def colorref(token: str) -> ctypes.c_int:
            q = qcolor(token)
            return ctypes.c_int(q.red() | (q.green() << 8) | (q.blue() << 16))

        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colorref(c.window)), 4)  # DWMWA_CAPTION_COLOR
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(colorref(c.text)), 4)  # DWMWA_TEXT_COLOR
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(colorref(c.window)), 4)  # DWMWA_BORDER_COLOR
    except Exception:  # an old Windows, a missing attribute: the frame keeps the system look
        return
