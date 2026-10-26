"""The scrubbing label (Lumen, P17.4a): drag sideways to change a number, Shift fine, Ctrl coarse."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from manim_studio.ui.style.fields import FloatField, IntField
from manim_studio.ui.style.scrub_label import COARSE, FINE, PIXELS_PER_STEP, ScrubLabel, steps_for

pytestmark = pytest.mark.ui

LEFT = Qt.MouseButton.LeftButton
NONE = Qt.MouseButton.NoButton


def send(widget, kind, x: float, buttons, modifiers=Qt.KeyboardModifier.NoModifier, button=LEFT) -> None:
    local = QPointF(x, 5)
    event = QMouseEvent(kind, local, QPointF(widget.mapToGlobal(local)), button, buttons, modifiers)
    QApplication.sendEvent(widget, event)


def drag(label, dx: float, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    send(label, QEvent.Type.MouseButtonPress, 2, LEFT)
    send(label, QEvent.Type.MouseMove, 2 + dx / 2, LEFT, modifiers, NONE)
    send(label, QEvent.Type.MouseMove, 2 + dx, LEFT, modifiers, NONE)
    send(label, QEvent.Type.MouseButtonRelease, 2 + dx, NONE)


def test_steps_follow_the_modifier_keys() -> None:
    assert steps_for(10, Qt.KeyboardModifier.NoModifier) == pytest.approx(10 / PIXELS_PER_STEP)
    assert steps_for(10, Qt.KeyboardModifier.ShiftModifier) == pytest.approx(10 / PIXELS_PER_STEP * FINE)
    assert steps_for(-10, Qt.KeyboardModifier.ControlModifier) == pytest.approx(
        -10 / PIXELS_PER_STEP * COARSE
    )


def test_a_label_reports_a_drag_and_a_double_click(qt_app) -> None:
    label = ScrubLabel("X")
    label.resize(40, 20)
    label.show()
    seen = []
    label.scrubStarted.connect(lambda: seen.append("start"))
    label.scrubbed.connect(lambda steps: seen.append(round(steps, 3)))
    label.scrubFinished.connect(lambda: seen.append("end"))
    label.doubleClicked.connect(lambda: seen.append("double"))
    drag(label, 20)
    assert seen[0] == "start" and seen[-1] == "end"
    assert seen[-2] == pytest.approx(20 / PIXELS_PER_STEP)
    seen.clear()
    send(label, QEvent.Type.MouseButtonPress, 2, LEFT)  # a click that does not move is not a drag
    send(label, QEvent.Type.MouseButtonRelease, 2, NONE)
    assert seen == []
    send(label, QEvent.Type.MouseButtonDblClick, 2, LEFT)
    assert seen == ["double"]
    label.close()


def test_scrubbing_a_number_field_changes_it_and_commits_once(qt_app) -> None:
    commits = []
    field = FloatField(commits.append, 0, 100, 0.5, 2)
    field.set_label("Size")
    field.set_value(10.0)
    field.widget.resize(200, 30)
    field.widget.show()
    label = field.widget.inside.label
    assert label.text() == "Size" and label.isVisible()
    drag(label, 20)  # 10 steps of 0.5
    assert field.widget.value() == pytest.approx(15.0)
    assert commits == [pytest.approx(15.0)]  # one commit: one undo step
    drag(label, 20, Qt.KeyboardModifier.ShiftModifier)  # fine: a step a tenth as large
    assert field.widget.value() == pytest.approx(15.5)
    drag(label, -20, Qt.KeyboardModifier.ControlModifier)  # coarse, and clamped at the minimum
    assert field.widget.value() == pytest.approx(0.0)
    assert len(commits) == 3
    field.widget.close()


def test_scrubbing_a_whole_number_rounds(qt_app) -> None:
    commits = []
    field = IntField(commits.append, 0, 50)
    field.set_label("N")
    field.set_value(3)
    field.widget.resize(160, 30)
    field.widget.show()
    drag(field.widget.inside.label, 8, Qt.KeyboardModifier.NoModifier)
    assert field.widget.value() == 3 + 8 // PIXELS_PER_STEP
    assert commits == [field.widget.value()]
    field.widget.close()


def test_a_unit_shows_beside_the_number_but_not_its_special_value(qt_app) -> None:
    field = FloatField(lambda v: None, 0, 10, 0.1, 2, none_text="Auto", suffix=" s")
    field.set_label("Start")
    field.widget.resize(200, 30)
    field.widget.show()
    field.set_value(2.0)
    assert field.widget.inside.unit.text() == "s" and field.widget.inside.unit.isVisible()
    assert field.widget.value() == pytest.approx(2.0) and "s" not in field.widget.text()
    field.set_value(None)
    assert field.widget.text() == "Auto" and not field.widget.inside.unit.isVisible()
    field.widget.close()
