"""Showing that code is running (ADR 0059): the spinner, the activity line, the explorer rows."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal

from manim_studio.core import limits
from manim_studio.ui.code_explorer import CodeExplorer, Row, Section
from manim_studio.ui.render_activity import FRAMES, RenderActivity, activity_text, spinner

pytestmark = pytest.mark.ui

NAMES = {"a": "Orbit", "b": "Torque"}.get


def test_the_spinner_turns() -> None:
    seen = {spinner(t / 10) for t in range(len(FRAMES))}
    assert seen == set(FRAMES)
    assert spinner(0.0) == FRAMES[0] and spinner(0.1) == FRAMES[1]


def test_the_line_says_what_renders_and_what_waits() -> None:
    assert activity_text([], NAMES, lambda i: 0) == ""
    assert (
        activity_text([("a", "queued", 0.0), ("b", "queued", 0.0)], NAMES, lambda i: 0)
        == "Waiting to render 2 scenes"
    )
    line = activity_text([("a", "rendering", 12.4), ("b", "queued", 0.0)], NAMES, lambda i: 340)
    assert line == "Rendering Orbit · 340 frames · 12 s · 1 waiting"


def test_the_line_says_when_there_is_no_time_limit() -> None:
    limits.set_unlimited(True)
    line = activity_text([("a", "rendering", 3.0)], NAMES, lambda i: 0)
    assert line == "Rendering Orbit · 3 s · no time limit"


class FakeService(QObject):
    statusChanged = Signal(str)  # noqa: N815

    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, str, float]] = []

    def active(self):
        return self.items

    def status(self, layer_id):
        return None


def test_the_indicator_shows_while_rendering_and_hides_when_done(qt_app) -> None:
    service = FakeService()
    indicator = RenderActivity(service, NAMES)
    lines, asked = [], []
    indicator.textChanged.connect(lines.append)
    indicator.layerRequested.connect(asked.append)
    assert indicator.isHidden()
    service.items = [("a", "rendering", 1.0)]
    service.statusChanged.emit("a")
    assert not indicator.isHidden() and "Rendering Orbit" in indicator.text()
    indicator.click()
    assert asked == ["a"]
    service.items = []
    service.statusChanged.emit("a")
    assert indicator.isHidden() and lines[-1] == ""


def test_a_rendering_row_shows_a_spinner_that_turns(qt_app) -> None:
    tree = CodeExplorer()
    tree.set_sections([Section("p", "This project", (Row("a", "Orbit", "scene", "layer", state="running"),))])
    item = tree.topLevelItem(0).child(0)
    assert item.text(0).startswith("Orbit") and item.text(0)[-1] in FRAMES
    item.setText(0, "Orbit")
    tree._spin()
    assert item.text(0)[-1] in FRAMES
    tree.set_sections([Section("p", "This project", (Row("a", "Orbit", "scene", "layer"),))])
    assert tree.topLevelItem(0).child(0).text(0) == "Orbit" and not tree._spin_timer.isActive()
