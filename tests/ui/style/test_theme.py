"""The design system (P6a, ADR 0040): tokens with measured contrast, a stylesheet Qt parses
without complaint, icons that resolve, no colour written outside the tokens, and document
colours left alone."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QColor, QPalette

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.style import icons, theme

pytestmark = pytest.mark.ui

UI = Path(theme.__file__).resolve().parents[1]  # the whole ui package, not just ui/style
T = theme.THEME


@pytest.mark.parametrize("surface", ["window", "panel", "raised", "field"])
def test_text_is_legible_on_every_surface(surface) -> None:
    background = getattr(T, surface)
    assert theme.contrast(T.text, background) >= 7.0
    assert theme.contrast(T.muted, background) >= 4.5


@pytest.mark.parametrize(
    "token",
    [
        "syntax_keyword",
        "syntax_string",
        "syntax_number",
        "syntax_comment",
        "syntax_manim",
        "syntax_definition",
    ],
)
def test_code_colours_are_legible_on_the_editor_field(token) -> None:
    assert theme.contrast(getattr(T, token), T.field) >= 4.5  # P6b.3: the Code page's highlighting


def test_error_words_and_the_line_numbers_are_legible_on_the_panel_and_the_field() -> None:
    for surface in (T.panel, T.field):
        assert theme.contrast(T.error_text, surface) >= 4.5
        assert theme.contrast(T.muted, surface) >= 4.5
        assert theme.contrast(T.warning, surface) >= 4.5
        assert theme.contrast(T.outline, surface) >= 4.5  # the error's line link


@pytest.mark.parametrize("bar", ["content", "emphasis", "motion", "morph", "sound", "cue"])
def test_clip_labels_are_legible_on_their_bars(bar) -> None:
    assert theme.contrast(T.bar_text, getattr(T, bar)) >= 4.5


def test_text_on_the_accent_and_tooltips_is_legible() -> None:
    assert theme.contrast(T.on_accent, T.accent) >= 4.5
    assert theme.contrast(T.text, T.tooltip) >= 7.0


def test_contrast_follows_the_wcag_formula() -> None:
    assert theme.contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert theme.contrast("#777777", "#777777") == pytest.approx(1.0)
    assert theme.contrast("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)


def test_every_token_is_a_colour() -> None:
    for name in theme.token_names():
        token = getattr(T, name)
        assert re.fullmatch(r"#[0-9a-f]{6}([0-9a-f]{2})?", token), name
        assert theme.qcolor(token).isValid(), name
    assert theme.qcolor("#ff000080").alpha() == 128 and theme.qcolor("#ff000080").red() == 255
    assert theme.css("#ff000080") == "rgba(255, 0, 0, 128)" and theme.css("#123456") == "#123456"


def test_the_stylesheet_parses_and_the_window_shows_without_warnings(qt_app) -> None:
    messages = []

    def handler(kind, context, text):
        if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg):
            messages.append(text)

    previous = qInstallMessageHandler(handler)
    try:
        theme.apply(qt_app)
        window = MainWindow()
        window.show()
        qt_app.processEvents()
        window.close()
    finally:
        qInstallMessageHandler(previous)
    assert not [m for m in messages if "style" in m.lower() or "parse" in m.lower()], messages


def test_apply_sets_fusion_the_palette_and_the_font(qt_app) -> None:
    from PySide6.QtWidgets import QStyleFactory

    qt_app.setStyleSheet("")
    qt_app.setStyle(QStyleFactory.create("Windows"))
    font = qt_app.font()
    font.setPointSize(14)
    qt_app.setFont(font)
    assert theme.apply(qt_app).objectName() == "fusion"
    sheet = qt_app.styleSheet()
    qt_app.setStyleSheet("")  # under its stylesheet wrapper, the application's own style
    assert qt_app.style().objectName() == "fusion"
    qt_app.setStyleSheet(sheet)
    disabled = qt_app.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
    assert disabled == theme.qcolor(T.disabled)
    assert qt_app.palette().color(QPalette.ColorRole.Window) == theme.qcolor(T.panel)
    assert qt_app.palette().color(QPalette.ColorRole.Highlight) == theme.qcolor(T.accent)
    assert qt_app.font().pointSize() == theme.UI_POINT_SIZE
    assert T.accent in qt_app.styleSheet()
    assert theme.mono_font().styleHint() == theme.mono_font().StyleHint.Monospace


def test_icons_are_tinted_and_dimmed_when_disabled(qt_app) -> None:
    from PySide6.QtGui import QIcon

    def ink(mode) -> QColor:
        image = icons.icon("delete").pixmap(24, 24, mode).toImage()
        pixels = [image.pixelColor(x, y) for x in range(24) for y in range(24)]
        return max(pixels, key=lambda c: c.alpha())

    normal, disabled = ink(QIcon.Mode.Normal), ink(QIcon.Mode.Disabled)
    assert abs(normal.lightness() - theme.qcolor(T.text).lightness()) < 20
    assert abs(disabled.lightness() - theme.qcolor(T.disabled).lightness()) < 20


@pytest.mark.parametrize("name", sorted(icons.NAMES))
def test_every_icon_resolves(qt_app, name) -> None:
    pixmap = icons.icon(name).pixmap(20, 20)
    assert not pixmap.isNull()
    image = pixmap.toImage()
    assert any(image.pixelColor(x, y).alpha() > 0 for x in range(20) for y in range(20))  # drawn


def test_buttons_show_icons_and_keep_their_text(qt_app, tmp_path) -> None:
    window = MainWindow()
    layers = window.layers
    for button, text in (
        (layers.delete_button, "Delete"),
        (layers.up_button, "Up"),
        (layers.down_button, "Down"),
    ):
        assert not button.icon().isNull()
        assert button.defaultAction().text() == text and button.accessibleName() == text
    assert not window.play_button.icon().isNull() and window.play_button.text() == "Play"
    window.close()


def test_no_colour_is_written_outside_the_tokens() -> None:
    hex_literal = re.compile(r"""["']#[0-9a-fA-F]{3,8}["']""")
    numeric = re.compile(r"QColor\(\s*\d")
    offenders = []
    scanned = 0
    for path in UI.rglob("*.py"):
        if path.name == "theme.py":
            continue
        scanned += 1
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if hex_literal.search(line) or (numeric.search(line) and "# content" not in line):
                offenders.append(f"{path.relative_to(UI)}:{number}: {line.strip()}")
    assert scanned > 60, f"only {scanned} files scanned: is UI the whole ui package?"
    assert offenders == []


def test_document_colours_are_not_themed(qt_app, tmp_path) -> None:
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, background="#ff0000"),
        layers=[Layer(id="s", spec=Spec(type="Square", style={"fill": "#00ff00", "fill_opacity": 1.0}))],
    )
    path = tmp_path / "red.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    window = MainWindow()
    window.resize(1000, 700)
    window.show()
    window.load(path)
    qt_app.processEvents()
    canvas = window.canvas
    image = canvas.grab().toImage()
    centre = image.pixelColor(image.width() // 2, image.height() // 2)
    corner_of_frame = canvas.units_transform().map(
        __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(-6.5, 3.5)
    )
    background = image.pixelColor(int(corner_of_frame.x()), int(corner_of_frame.y()))
    assert (centre.red(), centre.green()) == (0, 255) and centre.blue() == 0  # the square's own green
    assert background == QColor(255, 0, 0)  # the project's background, not the theme's
    window.close()


def test_a_colour_swatch_labels_itself_legibly() -> None:
    readable_on = theme.readable_on
    assert readable_on("#ffff00") == "black" and readable_on("#0f172a") == "white"
    assert readable_on("#FFFFFF") == "black"


# -- Lumen (P17.1, ADR 0063): two token sets, bundled type, themed icons -------------------------------------


@pytest.mark.parametrize("name", sorted(theme.THEMES))
def test_every_set_has_legible_text_surfaces_and_an_accent_that_carries_white(name) -> None:
    c = theme.THEMES[name]
    for surface in (c.window, c.panel, c.raised, c.field, c.surface_3):
        assert theme.contrast(c.text, surface) >= 7.0, (name, surface)
        assert theme.contrast(c.muted, surface) >= 4.5, (name, surface)
    for surface in (c.panel, c.field):
        assert theme.contrast(c.accent_text, surface) >= 4.5, (name, surface)
        assert theme.contrast(c.error_text, surface) >= 4.5, (name, surface)
        assert theme.contrast(c.warning, surface) >= 4.5, (name, surface)
    assert theme.contrast(c.on_accent, c.accent) >= 4.5
    for bar in ("content", "emphasis", "motion", "morph", "sound", "cue"):
        assert theme.contrast(c.bar_text, getattr(c, bar)) >= 4.5, (name, bar)


@pytest.mark.parametrize("name", sorted(theme.THEMES))
def test_every_set_has_valid_tokens_and_a_syntax_palette_that_reads_on_the_field(name) -> None:
    c = theme.THEMES[name]
    for token in theme.token_names():
        assert re.fullmatch(r"#[0-9a-f]{6}([0-9a-f]{2})?", getattr(c, token)), (name, token)
    for token in ("syntax_keyword", "syntax_string", "syntax_number", "syntax_comment", "syntax_manim"):
        assert theme.contrast(getattr(c, token), c.field) >= 4.5, (name, token)


def test_the_bundled_fonts_load_and_are_the_families_in_use(qt_app) -> None:
    families = theme.load_fonts()
    assert families["ui"] == "Inter" and families["mono"] == "JetBrains Mono"
    assert theme.font("heading").pixelSize() == 14 and theme.font("title").family() == "Inter"
    assert theme.mono_font().family() == "JetBrains Mono"
    for name in theme.FONT_FILES:
        assert (theme.FONT_DIR / name).is_file(), name


def test_switching_the_theme_changes_the_palette_the_stylesheet_and_the_icons_then_back(qt_app) -> None:
    from PySide6.QtGui import QIcon

    def ink(mode=QIcon.Mode.Normal):
        image = icons.icon("delete").pixmap(24, 24, mode).toImage()
        return max((image.pixelColor(x, y) for x in range(24) for y in range(24)), key=lambda c: c.alpha())

    seen = []
    theme.signals.themeChanged.connect(seen.append)
    try:
        dark_icon = ink()
        theme.set_theme(qt_app, "paper")
        assert theme.THEME is theme.PAPER and seen == ["paper"]
        assert qt_app.palette().color(QPalette.ColorRole.Window) == theme.qcolor(theme.PAPER.panel)
        assert theme.PAPER.accent in qt_app.styleSheet()
        assert ink().lightness() < dark_icon.lightness()  # the same icon object now draws dark on light
        with pytest.raises(KeyError):
            theme.set_theme(qt_app, "nope")
    finally:
        theme.set_theme(qt_app, "ink")
        theme.signals.themeChanged.disconnect(seen.append)
    assert theme.THEME is theme.INK and seen == ["paper", "ink"]


def test_mix_moves_between_two_tokens() -> None:
    assert theme.mix("#000000", "#ffffff", 0.0) == "#000000"
    assert theme.mix("#000000", "#ffffff", 1.0) == "#ffffff"
    assert theme.mix("#000000", "#ffffff", 0.5) == "#808080"


def test_a_module_can_register_its_own_rules_and_they_follow_the_theme(qt_app) -> None:
    def rules(c):
        return f"QLabel#lumenProbe {{ color: {c.accent}; }}\n"

    theme.register_rules(rules)
    try:
        assert "lumenProbe" in qt_app.styleSheet() and theme.INK.accent in qt_app.styleSheet()
        theme.set_theme(qt_app, "paper")
        assert theme.PAPER.accent in qt_app.styleSheet().split("lumenProbe")[1]
    finally:
        theme.set_theme(qt_app, "ink")
        theme._RULES.remove(rules)
        qt_app.setStyleSheet(theme.stylesheet())
