"""The editor's icons draw their glyphs from QtAwesome's font files without loading QtAwesome.

QtAwesome loads a dozen icon fonts the editor does not use (about 40 MB); the icons are drawn here the way
it draws them, so that nothing changes on the screen, and it remains the fallback where a font is missing."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess
import sys

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QIcon

from manim_studio.ui.style import icons, theme

pytestmark = pytest.mark.ui


def test_every_icon_is_drawn_exactly_as_qtawesome_draws_it(qt_app) -> None:
    for name in sorted(icons.NAMES):
        for mode in (QIcon.Mode.Normal, QIcon.Mode.Disabled):
            ours = icons.icon(name).pixmap(20, 20, mode).toImage()
            theirs = icons._qtawesome_glyph(name).pixmap(20, 20, mode).toImage()
            assert ours == theirs, (name, mode.name)


def test_the_glyphs_follow_the_size_and_the_theme(qt_app) -> None:
    for size in (12, 16, 33):
        pixmap = icons.icon("add").pixmap(size, size)
        assert (pixmap.width(), pixmap.height()) == (size, size)
        assert any(pixmap.toImage().pixelColor(x, y).alpha() for x in range(size) for y in range(size))
    theme.set_theme(qt_app, "ink")
    dark = icons.icon("delete").pixmap(24, 24).toImage()
    theme.set_theme(qt_app, "paper")
    try:
        light = icons.icon("delete").pixmap(24, 24).toImage()
    finally:
        theme.set_theme(qt_app, "ink")
    assert dark != light  # drawn again in the new colours, by the same icon object


def test_only_the_fonts_the_editor_uses_are_loaded(qt_app) -> None:
    for name in icons.NAMES:
        icons.icon(name).pixmap(16, 16)
    assert set(icons._fonts) <= set(icons.FONTS)
    assert all(icons._fonts[prefix] for prefix in icons._fonts)  # each one was found
    assert {icons._split(glyph)[0] for glyph in icons.NAMES.values()} <= set(
        icons.FONTS
    )  # none is left to QtAwesome


def test_a_glyph_is_drawn_once_per_size_and_forgotten_with_the_theme(qt_app) -> None:
    icons.refresh()
    first = icons.icon("play").pixmap(18, 18)
    again = icons.icon("play").pixmap(18, 18)
    assert first.cacheKey() == again.cacheKey()  # the same pixmap: not painted again
    icons.refresh()
    assert icons.icon("play").pixmap(18, 18).cacheKey() != first.cacheKey()


def test_an_icon_asked_for_no_size_is_an_empty_pixmap(qt_app) -> None:
    assert icons.icon("add").pixmap(0, 0).isNull()


def test_where_a_font_is_missing_qtawesome_still_draws_the_icons(qt_app, monkeypatch) -> None:
    monkeypatch.setattr(icons, "_font", lambda prefix: None)
    icons.refresh()
    try:
        pixmap = icons.icon("add").pixmap(20, 20)
        assert any(pixmap.toImage().pixelColor(x, y).alpha() for x in range(20) for y in range(20))
    finally:
        icons.refresh()


def test_drawing_icons_does_not_load_qtawesome() -> None:
    code = (
        "import sys\n"
        "from PySide6.QtWidgets import QApplication\n"
        "app = QApplication([])\n"
        "from manim_studio.ui.style import icons, theme\n"
        "theme.apply(app)\n"
        "for name in icons.NAMES:\n"
        "    icons.icon(name).pixmap(16, 16)\n"
        "print('qtawesome' in sys.modules)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.stdout.split() == ["False"], out.stderr
