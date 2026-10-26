"""P6d.3 acceptance (ADR 0044): browse the presets with moving previews, search, apply one to
two selected layers in one undo step, save a preset of your own and find it marked, and check
the result against the frames the editor draws."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from acceptance.test_acceptance_v1 import menu_action
from manim_studio.core.model.schema import Canvas, Clip, Layer, Project, Spec
from manim_studio.render import preset_thumbs
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.panels import presets_browser as pb

pytestmark = pytest.mark.ui


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    monkeypatch.setenv("MANIM_STUDIO_LIBRARY", str(tmp_path / "library"))
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=6.0),
        layers=[
            Layer(id="sq", name="Square", spec=Spec(type="Square")),
            Layer(id="tx", name="Title", spec=Spec(type="Text", params={"text": "Hi"})),
        ],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1100, 800)
    win.show()
    win.load(path)
    yield win
    win.close()


def over(qt_app, browser, name) -> None:
    item = browser.item(name)
    browser.grid.scrollToItem(item)
    qt_app.processEvents()
    pos = QPointF(browser.grid.visualItemRect(item).center())
    glob = QPointF(browser.grid.viewport().mapToGlobal(pos.toPoint()))
    none, nokeys = Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier
    QApplication.sendEvent(
        browser.grid.viewport(), QMouseEvent(QEvent.Type.MouseMove, pos, glob, none, none, nokeys)
    )


def pixels(browser, name) -> np.ndarray:
    image = browser.item(name).icon().pixmap(160, 90).toImage()
    return np.array([[image.pixelColor(x, y).getRgb() for x in range(0, 160, 8)] for y in range(0, 90, 6)])


def test_browse_preview_and_apply_a_preset_to_two_layers_then_save_your_own(window, qt_app) -> None:
    window.selection.set_layers(["sq", "tx"])
    window.seek(1.0)

    # Open it from the Animate menu: every built-in preset is a card with a still.
    menu_action(window.menuBar(), "Animate", "Browse Presets...").trigger()
    browser = window.presets_browser
    assert browser.isVisible() and len(browser.names()) == len(window.library.presets)
    assert browser.status.text() == "Applies to 2 selected layers at the playhead"

    # Narrow it down: the Entrance tab, then a search on the description.
    browser.tabs.setCurrentIndex(1)
    assert set(browser.names()) <= {p.name for p in window.library.presets_in("entrance")}
    browser.search.setText("growing")
    assert browser.names() and all(n in {p.name for p in window.library.presets} for n in browser.names())
    assert "Pop in" in browser.names()  # "Fades in while growing"
    browser.search.setText("pop")
    assert browser.names() == ["Pop in"]

    # Hovering the card plays the preset's run: the frames differ and loop.
    still = pixels(browser, "Pop in")
    over(qt_app, browser, "Pop in")
    seen = [pixels(browser, "Pop in")]
    for _ in range(preset_thumbs.FRAMES - 1):
        browser.timer.timeout.emit()
        seen.append(pixels(browser, "Pop in"))
    assert len({frame.tobytes() for frame in seen}) > 3  # it moves
    assert not np.array_equal(seen[0], still)  # and starts from the beginning, not the still
    QApplication.sendEvent(browser.grid.viewport(), QEvent(QEvent.Type.Leave))
    assert np.array_equal(pixels(browser, "Pop in"), still) and not browser.timer.isActive()

    # Double-click: both layers get the clip at the playhead, as one undo step.
    steps = window.document.undo_stack.count()
    rect = browser.grid.visualItemRect(browser.item("Pop in")).center()
    QTest.mouseClick(browser.grid.viewport(), Qt.MouseButton.LeftButton, pos=rect)
    QTest.mouseDClick(browser.grid.viewport(), Qt.MouseButton.LeftButton, pos=rect)
    for layer_id in ("sq", "tx"):
        (clip,) = window.project.layer(layer_id).clips
        assert clip.start == 1.0 and clip.duration > 0
    assert window.document.undo_stack.count() == steps + 1
    assert browser.isVisible()  # open for the next
    window.document.undo_stack.undo()
    assert window.project.layer("sq").clips == [] and window.project.layer("tx").clips == []
    window.document.undo_stack.redo()
    assert len(window.project.layer("sq").clips) == len(window.project.layer("tx").clips) == 1

    # The canvas at the playhead shows what the preview promised: the object is drawn growing in.
    window.seek(1.0)
    first = window.canvas.grab().toImage()
    window.seek(1.4)
    assert window.canvas.grab().toImage() != first

    # A preset of your own: save the square's animation, and the open browser lists it, marked.
    window.selection.set("sq")
    window.ask_preset_name = lambda: ("Mine", "emphasis")
    menu_action(window.menuBar(), "Animate", "Save Animation as Preset...").trigger()
    browser.search.setText("")
    browser.tabs.setCurrentIndex(2)
    assert "Mine" in browser.names()
    assert browser.item("Mine").data(pb.USER_ROLE) is True
    assert browser.item("Indicate").data(pb.USER_ROLE) is False
    plain = pb.to_pixmap(
        preset_thumbs.thumbnails(browser.item("Mine").data(pb.PRESET_ROLE), pb.thumb_background())[4]
    )
    assert browser.item("Mine").icon().pixmap(160, 90).toImage() != plain.toImage()  # the badge

    # Close; the saved preset is also a menu item, and the dialog opens again where it was.
    browser.close_button.click()
    assert not browser.isVisible()
    menu_action(window.menuBar(), "Animate", "Browse Presets...").trigger()
    assert window.presets_browser is browser and browser.isVisible() and "Mine" in browser.names()


def test_a_timeline_row_opens_it_for_that_row_and_time(window, qt_app) -> None:
    from acceptance.test_acceptance_v1 import timeline_menu

    window.document.replace(
        window.project.model_copy(
            update={
                "layers": [
                    window.project.layer("sq").model_copy(
                        update={"clips": [Clip(id="g", kind="GrowFromCenter", start=0.0, duration=0.5)]}
                    ),
                    window.project.layer("tx"),
                ]
            }
        )
    )
    window.selection.set("sq")
    menu_action(timeline_menu(window, "tx", 3.0), "Browse presets...").trigger()
    browser = window.presets_browser
    assert browser.status.text() == "Applies to Title at 3.00 s"
    item = browser.item("Fade out")
    browser.grid.setCurrentItem(item)
    browser.apply_button.click()
    (clip,) = window.project.layer("tx").clips
    assert (clip.kind, clip.start) == ("FadeOut", 3.0)
    assert [c.kind for c in window.project.layer("sq").clips] == ["GrowFromCenter"]  # not the selection
