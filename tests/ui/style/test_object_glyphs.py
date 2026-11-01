"""The drawings of the library's objects (ADR 0087): every type shows something, in both themes."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter

from manim_studio.core.engine import adapter
from manim_studio.ui.session import insert_catalogue as catalogue
from manim_studio.ui.style import icons, object_glyphs, theme

pytestmark = pytest.mark.ui

TYPES = sorted({t for _section, types in adapter.LIBRARY for t in types})


def drawn(type_name: str, size: int = 32) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    object_glyphs.paint(painter, QRectF(0, 0, size, size), type_name)
    painter.end()
    return image


def inked(image: QImage) -> int:
    return sum(
        image.pixelColor(x, y).alpha() > 0 for x in range(image.width()) for y in range(image.height())
    )


@pytest.mark.parametrize("type_name", TYPES)
def test_every_library_type_has_a_glyph(qt_app, type_name) -> None:
    assert inked(drawn(type_name)) > 12


def test_shapes_lines_planes_and_solids_are_drawn_as_their_own_outline(qt_app) -> None:
    for group in ("shape", "line", "graph", "solid"):
        outlined = [e for e in catalogue.variants(group) if object_glyphs.has_outline(e.type_name)]
        assert len(outlined) >= len(catalogue.variants(group)) - 1, group  # at most one falls back to an icon


def test_a_glyph_takes_the_theme_it_is_painted_in(qt_app) -> None:
    try:
        theme.apply(qt_app, theme.THEMES["paper"])
        icons.refresh()
        light = drawn("Star")
        theme.apply(qt_app, theme.THEMES["ink"])
        icons.refresh()
        dark = drawn("Star")
    finally:
        theme.apply(qt_app, theme.THEMES["ink"])
    ink_light = max((light.pixelColor(x, y) for x in range(32) for y in range(32)), key=lambda c: c.alpha())
    ink_dark = max((dark.pixelColor(x, y) for x in range(32) for y in range(32)), key=lambda c: c.alpha())
    assert ink_light.lightness() < ink_dark.lightness()


def test_the_glyph_is_also_a_qicon_for_menus(qt_app) -> None:
    pixmap = object_glyphs.icon("Cube").pixmap(24, 24)
    assert not pixmap.isNull() and inked(pixmap.toImage()) > 12
    assert (
        inked(object_glyphs.icon("NoSuchType").pixmap(24, 24).toImage()) > 12
    )  # an unknown one: a plain icon
