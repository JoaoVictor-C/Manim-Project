"""The Timeline card's header (ADR 0084): Snap and Auto-key chips, + Clip, the zoom."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui


def scene() -> Project:
    a = Layer(id="a", spec=Spec(type="Square", params={"side_length": 1.0}))
    return Project(canvas=Canvas(width_px=640, height_px=360, fps=30, duration=4.0), layers=[a])


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(scene().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1440, 900)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


def test_the_header_has_the_chips_the_button_and_the_zoom_visible(window) -> None:
    header = window.timeline_header
    assert window.timeline_card.header.isAncestorOf(header)
    for widget in (header.snap_chip, header.autokey_chip, header.add_clip_button, header.zoom_slider):
        assert not widget.isHidden()
    assert header.snap_chip.text() == "Snap" and header.autokey_chip.text() == "Auto-key"


def test_snap_chip_is_the_timeline_snapping_and_a_view_menu_item(window) -> None:
    chip = window.timeline_header.snap_chip
    assert chip.isChecked() and window.timeline.snap_enabled and window.timeline_snap_action.isChecked()
    chip.click()
    assert not window.timeline.snap_enabled and not window.timeline_snap_action.isChecked()
    window.timeline_snap_action.setChecked(True)
    assert chip.isChecked() and window.timeline.snap_enabled
    assert ("timeline_snap", window.timeline_snap_action, True) in window._toggles()


def test_auto_key_chip_follows_the_edit_menu_item(window) -> None:
    chip = window.timeline_header.autokey_chip
    assert not chip.isChecked()
    chip.click()
    assert window.auto_key_action.isChecked()
    window.auto_key_action.setChecked(False)
    assert not chip.isChecked()


def test_the_zoom_slider_and_the_timeline_zoom_follow_each_other(window, qt_app) -> None:
    header, timeline = window.timeline_header, window.timeline
    steps = header.zoom_slider.maximum()
    before = timeline.scale.px_per_second
    header.zoom_slider.setValue(min(header.zoom_slider.value() + 100, steps))
    assert timeline.scale.px_per_second > before
    timeline.zoom(1 / 1.5, 100)  # the wheel moves the slider
    assert header.zoom_slider.value() == round(timeline.zoom_fraction() * steps)
    header.zoom_in.click()
    assert header.zoom_slider.value() == round(timeline.zoom_fraction() * steps)
    assert 0.0 <= timeline.zoom_fraction() <= 1.0


def test_plus_clip_offers_the_add_clip_menu_for_the_selected_object(window) -> None:
    header = window.timeline_header
    window.selection.clear()
    assert header.clip_menu() is None  # nothing selected
    window.selection.set("a")
    menu = header.clip_menu()
    assert menu is not None
    add = next(a for a in menu.actions() if a.text().startswith("Add clip"))
    assert add.menu() is not None and add.isEnabled()
    kinds = {a.text() for sub in add.menu().actions() if sub.menu() for a in sub.menu().actions()}
    assert kinds  # the kinds this object takes, grouped as in the row's context menu
