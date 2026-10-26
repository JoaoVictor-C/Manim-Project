"""The Lumen timeline, graph and curve editors (P17.4b): colours come from the theme in use when they paint,
both themes paint, and the restyle kept every hit-test geometry."""

from __future__ import annotations

import os
import wave

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QFont, QFontMetrics

from manim_studio.core.editing import edits
from manim_studio.core.model.schema import AudioClip, Canvas, Clip, Cue, Easing, Layer, Marker, Project, Spec
from manim_studio.ui.session.document import Document
from manim_studio.ui.session.selection import Selection
from manim_studio.ui.style import theme
from manim_studio.ui.timeline import curve_editor, graph_editor, paint, view
from manim_studio.ui.timeline.view import (
    CLIP_MARGIN,
    HEADER_WIDTH,
    KEY_BUTTON_X,
    RULER_HEIGHT,
    WIDE_HEADER_WIDTH,
    TimelineView,
    clock,
    kind_token,
)

pytestmark = pytest.mark.ui


def project(sound: str | None = None) -> Project:
    p = Project(
        canvas=Canvas(duration=6.0, fps=30),
        layers=[
            Layer(
                id="a",
                spec=Spec(type="Square"),
                clips=[Clip(id="c1", kind="Create", start=0.5, duration=1.0)],
            ),
            Layer(
                id="t",
                spec=Spec(type="Text"),
                clips=[Clip(id="c2", kind="Indicate", start=3.0, duration=1.0)],
            ),
        ],
        subtitles=[Cue(id="q", start=1.0, end=2.5, text="Hello there")],
        markers=[Marker(id="m", t=4.5, name="beat")],
        audio=[AudioClip(id="s", name="voice", path=sound, start=1.0, duration=1.5)] if sound else [],
    )
    p = edits.set_key(p, "a", "position", 1.0, (0.0, 0.0)).project
    return edits.set_key(p, "a", "position", 2.0, (1.0, 1.0)).project


@pytest.fixture
def sound(tmp_path) -> str:
    path = tmp_path / "tone.wav"
    rate = 8000
    t = np.arange(rate * 2) / rate
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes((np.sin(2 * np.pi * 220 * t) * 20000).astype(np.int16).tobytes())
    return str(path)


@pytest.fixture
def ink(qt_app):
    theme.apply(qt_app, theme.INK)
    yield qt_app
    theme.apply(qt_app, theme.INK)


def make_view(qt_app, p: Project) -> TimelineView:
    v = TimelineView()
    v.resize(900, 260)
    v.set_document(Document(p))
    v.show()
    qt_app.processEvents()
    return v


def near(a: QColor, b: QColor, tolerance: int) -> bool:
    return max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue())) <= tolerance


def test_no_module_keeps_a_colour() -> None:
    """A colour kept in a module constant would miss a theme switch (P17 rule)."""
    for module in (view, graph_editor, curve_editor, paint):
        kept = [name for name, value in vars(module).items() if isinstance(value, QColor)]
        assert kept == [], module.__name__


def test_the_old_background_name_follows_the_theme(ink) -> None:
    assert view.BACKGROUND.rgb() == theme.qcolor(theme.INK.track).rgb()
    theme.apply(ink, theme.PAPER)
    assert view.BACKGROUND.rgb() == theme.qcolor(theme.PAPER.track).rgb()


@pytest.mark.parametrize("name", ["ink", "paper"])
def test_everything_paints_in_both_themes(ink, sound, name) -> None:
    theme.apply(ink, theme.THEMES[name])
    v = make_view(ink, project(sound))
    v.set_selected("a", "c1")
    v.set_selected_layers(["a"])
    v.set_selected_subtitle("q")
    v.set_selected_marker("m")
    v.set_expanded("a", True)
    v.pick_prop("a", "position")
    v.set_playhead(1.5)
    v.guide, v.drop_at = 2.0, 3.0
    ink.processEvents()
    assert not v.viewport().grab().isNull() and not v.header.grab().isNull()
    selection = Selection(v.document)
    graph = graph_editor.GraphEditor(v.document, selection, lambda: 1.5)
    graph.resize(500, 240)
    graph.show()
    selection.set_key("a", 2.0)
    assert not graph.grab().isNull()
    curve = curve_editor.CurveEditor(Easing(name=None, bezier=(0.4, 0.0, 0.2, 1.2)))
    assert not curve.grab().isNull()
    for widget in (graph, curve, v):
        widget.close()


def test_a_theme_switch_repaints_the_ruler_and_the_rows(ink) -> None:
    v = make_view(ink, project())
    ruler = QPointF(v._viewport_x(5.8) - 3, 4).toPoint()  # empty ruler, left of the end line
    row = QPointF(v._viewport_x(5.8) - 3, v.viewport().height() - 4).toPoint()  # under every row

    def pixel(where):
        return v.viewport().grab().toImage().pixelColor(where)

    assert pixel(ruler).rgb() == theme.qcolor(theme.INK.ruler).rgb()
    theme.apply(ink, theme.PAPER)
    ink.processEvents()
    assert pixel(ruler).rgb() == theme.qcolor(theme.PAPER.ruler).rgb()
    assert near(pixel(row), theme.qcolor(theme.PAPER.track), 12)
    v.close()


@pytest.mark.parametrize("name", ["ink", "paper"])
def test_the_playhead_is_drawn_in_the_accent_gradient_with_its_time_on_a_pill(ink, name) -> None:
    theme.apply(ink, theme.THEMES[name])
    v = make_view(ink, project())
    v.set_playhead(5.0)  # nothing else there
    ink.processEvents()
    image = v.viewport().grab().toImage()
    x = round(v._viewport_x(5.0))
    height = v.viewport().height()
    c = theme.THEMES[name]
    top, bottom = theme.qcolor(c.accent_2), theme.qcolor(c.accent)
    y = height - 4
    t = y / height
    expected = QColor(
        round(top.red() + (bottom.red() - top.red()) * t),
        round(top.green() + (bottom.green() - top.green()) * t),
        round(top.blue() + (bottom.blue() - top.blue()) * t),
    )
    column = [image.pixelColor(x + dx, y) for dx in (-1, 0)]
    assert any(near(p, expected, 40) for p in column)
    mono = paint.font("caption", kind="mono", weight=QFont.Weight.DemiBold)
    padding = x + QFontMetrics(mono).horizontalAdvance(clock(5.0)) / 2 + 3  # right of the time, on the pill
    assert near(image.pixelColor(round(padding), RULER_HEIGHT // 2), theme.qcolor(c.accent), 30)
    v.close()


def test_a_clip_bar_is_its_category_colour(ink) -> None:
    v = make_view(ink, project())
    bar = v.clip_item("a", "c1")
    middle = v.mapFromScene(QPointF(bar.rect().right() - 4, bar.rect().center().y()))
    pixel = v.viewport().grab().toImage().pixelColor(middle)
    assert near(pixel, theme.qcolor(theme.INK.content), 28)
    v.close()


def test_the_selected_row_is_tinted_in_the_header_and_the_lanes(ink) -> None:
    v = make_view(ink, project())
    rows = [layer.id for layer in v.rows()]
    v.set_selected(rows[0], None)
    ink.processEvents()
    header = v.header.grab().toImage()
    lit = header.pixelColor(HEADER_WIDTH - 6, round(v.row_top(rows[0])) + 3)
    plain = header.pixelColor(HEADER_WIDTH - 6, round(v.row_top(rows[1])) + 3)
    assert lit != plain
    lanes = v.viewport().grab().toImage()
    x = round(v._viewport_x(5.8)) - 3
    assert lanes.pixelColor(x, round(v.row_top(rows[0])) + 1) != lanes.pixelColor(
        x, round(v.row_top(rows[1])) + 1
    )
    v.close()


def test_bars_paint_beyond_their_rectangle_but_hit_inside_it(ink) -> None:
    """The glow and the ring are drawn outside a bar; clicks still find it only on its rectangle."""
    v = make_view(ink, project())
    bar = v.clip_item("a", "c1")
    rect = bar.rect()
    assert bar.boundingRect().contains(rect.adjusted(-4, -4, 4, 4))
    assert bar.shape().boundingRect().adjusted(1, 1, -1, -1) == rect.adjusted(0.5, 0.5, -0.5, -0.5)
    outside = v.mapFromScene(QPointF(rect.center().x(), rect.top() - 3))
    assert all(item is not bar for item in v.items(outside))
    assert rect.height() == view.ROW_HEIGHT - 2 * CLIP_MARGIN
    v.close()


def test_the_geometry_the_hit_tests_use() -> None:
    assert (view.ROW_HEIGHT, view.RULER_HEIGHT, view.SUB_ROW_HEIGHT) == (28, 26, 22)
    assert HEADER_WIDTH < WIDE_HEADER_WIDTH and KEY_BUTTON_X == WIDE_HEADER_WIDTH - 14


def test_clock_kind_and_shade() -> None:
    assert clock(2.4) == "0:02.40" and clock(59.999) == "1:00.00" and clock(-1) == "0:00.00"
    assert kind_token(Layer(id="x", spec=Spec(type="MathTex"))) == "content"
    assert kind_token(Layer(id="x", spec=Spec(type="Code"))) == "morph"
    assert kind_token(Layer(id="x", spec=Spec(type="Circle"))) == "motion"
    grey = QColor(100, 100, 100)
    assert paint.shade(grey, 0.5).red() == 178 and paint.shade(grey, -0.5).red() == 50
