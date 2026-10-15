"""The design system (P6a, ADR 0040): colour tokens, spacing, fonts and the application look.

Every colour the editor's own chrome uses comes from a ``Colours`` token set: the
panels and widgets (through a Fusion palette and one stylesheet generated from the
tokens), the timeline's painted rows and bars, the canvas overlays and the curve
editor. Colours that belong to the document - layer styles, the canvas background,
marker and subtitle colours, the dashed placeholder Manim draws in the frame - are
content and never come from here: they are what the export renders.

``apply(app)`` is called by ``run()`` and by the tests' application fixture, so the
tests drive the widgets the user sees. One dark "Studio" set exists; the token
structure allows a second one.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyleFactory

SPACE = 4  # px: the spacing grid
RADIUS = 4  # px: corners of fields, buttons, menus
UI_POINT_SIZE = 9
MONO_FAMILIES = ("Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono")


@dataclass(frozen=True)
class Colours:
    """Colour roles as ``#rrggbb`` or ``#rrggbbaa`` (alpha last)."""

    # chrome
    window: str  # behind everything (the main window, the canvas around the frame)
    panel: str  # docks and their contents
    raised: str  # buttons, headers, the ruler, menus
    field: str  # line edits, spin boxes, lists
    border: str
    divider: str
    text: str
    muted: str  # secondary text, units, hints
    disabled: str
    accent: str  # selection, focus, the current item
    on_accent: str  # text on the accent
    warning: str
    danger: str
    success: str
    tooltip: str
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
    error_text: str  # error words on panels and the gutter (danger itself is 4.3:1 on a panel)
    # the graph editor's curves (P6b.2): one per keyed value, x red and y green as elsewhere
    curve_x: str
    curve_y: str
    curve_scale: str
    curve_rotation: str
    curve_opacity: str


STUDIO = Colours(
    window="#18181b",
    panel="#202024",
    raised="#2a2a2f",
    field="#141417",
    border="#3a3a41",
    divider="#2d2d33",
    text="#e7e7ea",
    muted="#a3a3ad",
    disabled="#6c6c75",
    accent="#2f6fe4",
    on_accent="#ffffff",
    warning="#f59e0b",
    danger="#ef4444",
    success="#22c55e",
    tooltip="#30303a",
    track="#1b1b1f",
    ruler="#26262c",
    lifetime="#ffffff1c",
    playhead="#ef4444",
    guide="#facc15aa",
    bar_edge="#0000005a",
    bar_selected="#ffffff",
    bar_text="#ffffff",
    content="#2563eb",
    emphasis="#b45309",
    motion="#15803d",
    morph="#9333ea",
    sound="#0f766e",
    wave="#ccfbf1be",
    cue="#854d0e",
    key="#e5e7eb",
    key_selected="#fde047",
    key_edge="#000000a0",
    frame_border="#52525b",
    pasteboard_dim="#18181baa",
    outline="#38bdf8",
    motion_path="#f59e0b",
    badge="#0f172a",
    badge_text="#e2e8f0",
    curve="#38bdf8",
    curve_handle="#fde047",
    grid="#ffffff28",
    syntax_keyword="#c792ea",
    syntax_string="#a5d6a7",
    syntax_number="#f0a878",
    syntax_comment="#8b8b98",
    syntax_manim="#5ec8f5",
    syntax_definition="#f2d58a",
    code_line="#ffffff0f",
    code_error_line="#ef444438",
    error_text="#f87171",
    curve_x="#f87171",
    curve_y="#4ade80",
    curve_scale="#60a5fa",
    curve_rotation="#c084fc",
    curve_opacity="#2dd4bf",
)

THEME = STUDIO  # the token set in use


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


def palette(c: Colours = THEME) -> QPalette:
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: c.panel,
        QPalette.ColorRole.WindowText: c.text,
        QPalette.ColorRole.Base: c.field,
        QPalette.ColorRole.AlternateBase: c.panel,
        QPalette.ColorRole.Text: c.text,
        QPalette.ColorRole.PlaceholderText: c.muted,
        QPalette.ColorRole.Button: c.raised,
        QPalette.ColorRole.ButtonText: c.text,
        QPalette.ColorRole.BrightText: c.on_accent,
        QPalette.ColorRole.Highlight: c.accent,
        QPalette.ColorRole.HighlightedText: c.on_accent,
        QPalette.ColorRole.ToolTipBase: c.tooltip,
        QPalette.ColorRole.ToolTipText: c.text,
        QPalette.ColorRole.Link: c.accent,
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


def stylesheet(c: Colours = THEME) -> str:
    """The application stylesheet, generated from the tokens (no colour is written twice)."""
    r, s = RADIUS, SPACE
    return f"""
QMainWindow, QDialog {{ background: {c.window}; }}
QWidget {{ color: {c.text}; }}
QToolTip {{ background: {c.tooltip}; color: {c.text}; border: 1px solid {c.border}; padding: {s}px; }}
QDockWidget {{ titlebar-close-icon: none; }}
QDockWidget::title {{
    background: {c.raised}; padding: {s}px {2 * s}px; border-bottom: 1px solid {c.divider};
}}
QDockWidget > QWidget {{ background: {c.panel}; }}
QMenuBar {{ background: {c.window}; border-bottom: 1px solid {c.divider}; }}
QMenuBar::item {{ padding: {s}px {2 * s}px; background: transparent; }}
QMenuBar::item:selected {{ background: {c.raised}; border-radius: {r}px; }}
QMenu {{ background: {c.raised}; border: 1px solid {c.border}; padding: {s}px; }}
QMenu::item {{ padding: {s}px {6 * s}px {s}px {4 * s}px; border-radius: {r}px; }}
QMenu::item:selected {{ background: {c.accent}; color: {c.on_accent}; }}
QMenu::item:disabled {{ color: {c.disabled}; }}
QMenu::separator {{ height: 1px; background: {c.divider}; margin: {s}px {2 * s}px; }}
QMenu::section {{ color: {c.muted}; padding: {s}px {2 * s}px; }}
QStatusBar {{ background: {c.window}; color: {c.muted}; border-top: 1px solid {c.divider}; }}
QPushButton, QToolButton {{
    background: {c.raised}; border: 1px solid {c.border}; border-radius: {r}px;
    padding: {s}px {2 * s + 2}px;
}}
QPushButton:hover, QToolButton:hover {{ border-color: {c.accent}; }}
QPushButton:pressed, QToolButton:pressed, QToolButton:checked {{
    background: {c.accent}; color: {c.on_accent};
}}
QPushButton:disabled, QToolButton:disabled {{ color: {c.disabled}; border-color: {c.divider}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {c.field}; border: 1px solid {c.border}; border-radius: {r}px; padding: 2px {s + 2}px;
    selection-background-color: {c.accent}; selection-color: {c.on_accent};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QComboBox:focus {{ border-color: {c.accent}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {c.disabled}; }}
QLineEdit[pending="true"], QSpinBox[pending="true"], QDoubleSpinBox[pending="true"],
QComboBox[pending="true"], QPlainTextEdit[pending="true"] {{ color: {c.muted}; font-style: italic; }}
QComboBox QAbstractItemView {{
    background: {c.raised}; border: 1px solid {c.border}; selection-background-color: {c.accent};
}}
QTreeView, QListView, QTreeWidget, QListWidget {{
    background: {c.field}; border: 1px solid {c.divider}; border-radius: {r}px; outline: 0;
}}
QTreeView::item, QListView::item {{ padding: 2px; }}
QTreeView::item:selected, QListView::item:selected {{ background: {c.accent}; color: {c.on_accent}; }}
QHeaderView::section {{
    background: {c.raised}; border: 0; border-right: 1px solid {c.divider}; padding: {s}px;
}}
QCheckBox::indicator {{
    width: 14px; height: 14px; border: 1px solid {c.border}; border-radius: 3px; background: {c.field};
}}
QCheckBox::indicator:checked {{ background: {c.accent}; border-color: {c.accent}; }}
QScrollArea {{ border: 0; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {c.border}; border-radius: 4px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: {c.muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSlider::groove:horizontal {{ height: 4px; background: {c.border}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {c.text}; width: 12px; margin: -5px 0; border-radius: 6px;
}}
QSplitter::handle {{ background: {c.divider}; }}
QSplitter::handle:hover {{ background: {c.accent}; }}
QTabBar::tab {{
    background: {c.window}; color: {c.muted}; padding: {s + 2}px {3 * s}px; border: 0;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {c.text}; border-bottom-color: {c.accent}; }}
QTabBar::tab:hover {{ color: {c.text}; }}
QGroupBox {{
    border: 1px solid {c.divider}; border-radius: {r}px; margin-top: {3 * s}px; padding-top: {s}px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: {2 * s}px; color: {c.muted}; }}
QTabBar#pageBar {{ background: {c.window}; }}
QTabBar#pageBar::tab {{
    background: transparent; color: {c.muted}; padding: {s + 2}px {4 * s}px; min-width: 96px;
    border: 0; border-top: 2px solid transparent;
}}
QTabBar#pageBar::tab:selected {{ color: {c.text}; border-top-color: {c.accent}; }}
QTabBar#pageBar::tab:hover {{ color: {c.text}; }}
QLabel[role="section"] {{ color: {c.muted}; font-weight: 600; }}
QLabel[role="readout"] {{ color: {c.text}; }}
QLabel[role="title"] {{ color: {c.text}; font-size: 24pt; font-weight: 600; }}
QLabel[role="hint"] {{ color: {c.muted}; }}
QPushButton[role="link"] {{
    background: transparent; border: 0; color: {c.outline}; text-align: left; padding: {s}px;
}}
QPushButton[role="link"]:hover {{ text-decoration: underline; }}
"""


def mono_font(point_size: int = UI_POINT_SIZE) -> QFont:
    """A monospace font for code and time readouts (the first family installed)."""
    families = set(QFontDatabase.families())
    family = next((f for f in MONO_FAMILIES if f in families), None)
    font = QFont(family) if family else QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(point_size)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


def apply(app: QApplication, colours: Colours = THEME) -> QStyle:
    """Give ``app`` the studio look: Fusion, the token palette, the stylesheet, the UI font.
    Returns the Fusion style (``app.style()`` is Qt's stylesheet wrapper around it)."""
    style = QStyleFactory.create("Fusion")
    app.setStyle(style)
    app.setPalette(palette(colours))
    font = app.font()
    font.setPointSize(UI_POINT_SIZE)
    app.setFont(font)
    app.setStyleSheet(stylesheet(colours))
    return style


def token_names() -> list[str]:
    return [f.name for f in fields(Colours)]
