"""P18 acceptance (ADR 0087): mark slide stops with Edit > Add Slide Stop, give one a loop, save, present it
full screen with Page Down / Page Up, and export the same slides as an HTML deck that lists one video per slide.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from acceptance.test_acceptance_v1 import menu_action
from manim_studio.core.editing import edits, slides
from manim_studio.core.model.schema import Project
from manim_studio.render.options import RenderOptions
from manim_studio.render.slide_deck import export_deck
from manim_studio.ui.main_window import MainWindow

pytestmark = [pytest.mark.ui, pytest.mark.slow]  # the deck renders real videos


@pytest.fixture
def window(qt_app):
    win = MainWindow()
    win.resize(1280, 820)
    win.show()
    yield win
    win.presenter.finish()
    win.pause()
    win.document.undo_stack.setClean()
    win.close()


def tick(window, seconds: float) -> None:
    wall, start = window._play_origin
    window._play_origin = (time.perf_counter() - seconds, start)
    window._on_play_tick()


def test_mark_present_and_export_slides(window, qt_app, tmp_path) -> None:
    menu_action(window.menuBar(), "File", "New").trigger()
    small = {"width_px": 320, "height_px": 180, "fps": 10, "duration": 6.0}
    window.document.replace(
        window.project.model_copy(update={"canvas": window.project.canvas.model_copy(update=small)})
    )
    menu_action(window.layers.library_menu, "Circle").trigger()

    # Mark two stops at the playhead, the first looping its last half second.
    window.seek(2.0)
    menu_action(window.menuBar(), "Edit", "Add Slide Stop").trigger()
    window.seek(4.0)
    menu_action(window.menuBar(), "Edit", "Add Slide Stop").trigger()
    first = slides.stops(window.project)[0]
    window.document.apply(edits.update_marker(window.project, first.id, loop=0.5), "Slide loop")
    assert [(s.first, s.last) for s in slides.windows(window.project)] == [(0, 21), (21, 41), (41, 60)]

    path = tmp_path / "Talk.json"
    window.path = path
    window.save()
    saved = Project.model_validate_json(path.read_text(encoding="utf-8"))
    assert [(m.slide, m.loop) for m in saved.markers] == [("stop", 0.5), ("stop", None)]

    # Present: Page Down plays to the stop and loops there; Page Down again plays slide 2; Page Up goes back.
    window.present()
    qt_app.processEvents()
    presenter = window.presenter
    assert presenter.slides_mode and presenter.bar.slide.text() == "Slide 1 of 3"
    QTest.keyClick(presenter, Qt.Key.Key_PageDown)
    tick(window, 3.0)
    assert presenter.waiting and window.play_loop == pytest.approx((1.6, 2.0))
    QTest.keyClick(presenter, Qt.Key.Key_PageDown)
    tick(window, 3.0)
    assert window.t == pytest.approx(4.0) and presenter.bar.slide.text() == "Slide 2 of 3"
    QTest.keyClick(presenter, Qt.Key.Key_PageUp)
    assert window.t == pytest.approx(2.0) and not window.play_timer.isActive()
    QTest.keyClick(presenter, Qt.Key.Key_Escape)
    assert not presenter.active and window.play_loop is None

    # Export the deck: a page and one video per slide, plus the loop.
    deck = export_deck(window.project, tmp_path / "talk.html", options=RenderOptions(jobs=1))
    assert deck.slides == 3 and deck.path.is_file()
    files = sorted(p.name for p in (tmp_path / "talk_files").iterdir())
    assert [f for f in files if f.endswith(".mp4")] == [
        "slide-01-loop.mp4",
        "slide-01.mp4",
        "slide-02.mp4",
        "slide-03.mp4",
    ]
    page = deck.path.read_text(encoding="utf-8")
    assert "slide-03.mp4" in page and "http" not in page.split("<body", 1)[1]
