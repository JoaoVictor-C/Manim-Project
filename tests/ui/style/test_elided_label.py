"""The eliding label (P6d.2): shortened with "...", never cut, whole text kept."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.ui.style.elided_label import ElidedLabel

pytestmark = pytest.mark.ui

TEXT = " 1.25 s  frame   37  (12.0 ms)   Fit (80 %)   ahead 30/120"


def test_it_shortens_when_narrow_and_keeps_the_whole_text(qt_app) -> None:
    label = ElidedLabel(TEXT, minimum=60)
    label.resize(label.sizeHint().width() + 10, 24)
    assert label.shown_text() == TEXT
    label.resize(90, 24)
    shown = label.shown_text()
    assert shown != TEXT and shown.endswith("…") and TEXT.startswith(shown[:-1])
    assert label.text() == TEXT and label.toolTip() == TEXT
    label.setText("2.00 s")
    assert label.toolTip() == "2.00 s"


def test_it_asks_only_for_its_minimum_width(qt_app) -> None:
    label = ElidedLabel(TEXT, minimum=70)
    assert label.minimumSizeHint().width() == 70
    assert label.sizeHint().width() > 70  # it still prefers the whole text
    label.resize(90, 24)
    label.grab()  # paints without error
