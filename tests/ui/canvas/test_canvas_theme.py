"""The canvas overlays follow the theme, and the pasteboard has dots and a shadow (Lumen, ADR 0063)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRectF

from manim_studio.ui.canvas import canvas as canvas_module
from manim_studio.ui.style import theme
from ui.canvas.test_canvas_tools import window  # noqa: F401 - the window fixture

pytestmark = pytest.mark.ui


def test_overlay_colours_are_read_again_when_the_theme_changes(qt_app) -> None:
    ink_outline = theme.qcolor(theme.INK.outline).name()
    assert canvas_module.OUTLINE_COLOR.name() == ink_outline
    try:
        theme.set_theme(qt_app, "paper")
        assert canvas_module.OUTLINE_COLOR.name() == theme.qcolor(theme.PAPER.outline).name()
        assert canvas_module.GUIDE_COLOR.name() == theme.qcolor(theme.PAPER.guide).name()
    finally:
        theme.set_theme(qt_app, "ink")
    assert canvas_module.OUTLINE_COLOR.name() == ink_outline


def test_the_pasteboard_is_dotted_and_the_frame_casts_a_shadow(window, qt_app) -> None:  # noqa: F811
    canvas = window.canvas
    canvas.setFixedSize(900, 600)
    canvas.fit()
    qt_app.processEvents()
    frame = canvas.frame_rect()
    image = canvas._decoration(frame, QRectF(canvas.rect())).toImage()
    assert frame.height() < canvas.height() - 40  # there is pasteboard above and below the frame
    marked = [
        (x, y)
        for y in range(0, canvas.height(), 3)
        for x in range(0, canvas.width(), 3)
        if image.pixelColor(x, y).alpha() > 0
    ]
    assert marked and all(not frame.contains(x, y) for x, y in marked)  # nothing is drawn inside the frame
    centre = frame.center().toPoint()
    assert image.pixelColor(centre.x(), centre.y()).alpha() == 0


def test_the_decoration_is_cached_until_the_size_or_theme_changes(window, qt_app) -> None:  # noqa: F811
    canvas = window.canvas
    canvas.setFixedSize(800, 450)
    canvas.fit()
    qt_app.processEvents()
    canvas.grab()
    first = canvas._decor
    canvas.grab()
    assert canvas._decor is first
    canvas.setFixedSize(820, 450)
    canvas.fit()
    qt_app.processEvents()
    canvas.grab()
    assert canvas._decor is not first
