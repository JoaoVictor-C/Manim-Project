"""The list rows and the segmented control shared by the dialogs (Lumen, ADR 0084)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel

from manim_studio.ui.style import theme
from manim_studio.ui.style.list_row import Dot, ListRow, RowList
from manim_studio.ui.style.segmented import Segmented, SegmentedControl

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def back_to_ink(qt_app):
    yield
    theme.set_theme(qt_app, "ink")


def test_a_row_has_a_title_chips_quiet_lines_with_dots_and_actions(qt_app) -> None:
    row = ListRow("Weather 2.0", subtitle="Live maps", mono="0:01.0")
    chip = row.add_head_chip("compatible", "ok", "tip")
    line = row.add_line("Waiting", "warning", "State")
    row.add_chips([("network", "warn"), ("ui", "neutral")])
    assert row.title_label.text() == "Weather 2.0" and row.mono_label.text() == "0:01.0"
    assert chip.property("tone") == "ok" and chip.toolTip() == "tip"
    assert [c.text() for c in row.chips] == ["compatible", "network", "ui"]
    assert line.text() == "Waiting" and [d.token for d in row.findChildren(Dot)] == ["warning"]
    assert row.subtitle_label.text() == "Live maps"


@pytest.mark.parametrize("name", ["ink", "paper"])
def test_a_list_fits_each_row_to_its_wrapped_text_and_paints(qt_app, name) -> None:
    theme.set_theme(qt_app, name)
    rows = RowList()
    rows.resize(360, 400)
    short = ListRow("Short")
    long_row = ListRow("A much longer sentence that has to wrap onto several lines " * 3, plain=True)
    rows.add_row(short, "short", "s")
    rows.add_row(long_row, "long", "l")
    rows.add_note("Nothing else.")
    rows.show()
    qt_app.processEvents()
    short_h, long_h = rows.item(0).sizeHint().height(), rows.item(1).sizeHint().height()
    assert long_h > short_h * 2  # the long one is taller, and nothing is clipped
    assert long_row.height() >= long_row.layout().totalHeightForWidth(long_row.width()) - 2
    assert rows.item(0).text() == "short" and rows.item(2).flags() == rows.item(2).flags().NoItemFlags
    rows.resize(700, 400)
    qt_app.processEvents()
    assert rows.item(1).sizeHint().height() < long_h  # wider: fewer lines
    assert not rows.grab().isNull()
    rows.close()


def test_a_row_is_chosen_by_the_view_and_a_label_does_not_swallow_the_click(qt_app) -> None:
    rows = RowList()
    rows.show()
    for k in range(3):
        rows.add_row(ListRow(f"row {k}"), f"row {k}", k)
    rows.setCurrentRow(1)
    assert rows.currentItem().data(0x100) == 1 and rows.currentRow() == 1
    assert isinstance(rows.itemWidget(rows.item(0)).title_label, QLabel)
    rows.clear()
    assert rows.count() == 0
    rows.close()


def test_the_segmented_control_reads_like_a_combo_box(qt_app) -> None:
    seg = Segmented()
    seen: list[int] = []
    seg.addItem("Close the gap", "close")
    seg.addItem("Open space", "open")
    seg.addItem("Linked", "beat")
    seg.currentIndexChanged.connect(seen.append)
    assert seg.count() == 3 and seg.currentIndex() == 0 and seg.currentData() == "close"
    assert seg.findData("beat") == 2 and seg.findData("nope") == -1
    seg.setCurrentIndex(2)
    assert seg.currentData() == "beat" and seen == [2] and seg.button(2).isChecked()
    seg.button(1).click()
    assert seg.currentData() == "open" and not seg.button(2).isChecked() and seen == [2, 1]
    seg.setCurrentIndex(1)  # no change: no signal
    assert seen == [2, 1]
    seg.setCurrentIndex(9)  # out of range: ignored
    assert seg.currentIndex() == 1


def test_the_keyed_segmented_control_is_addressed_by_key(qt_app) -> None:
    control = SegmentedControl()
    changes: list[str] = []
    control.changed.connect(changes.append)
    for key, label in (("auto", "Auto"), ("gpu", "GPU"), ("cpu", "CPU")):
        control.add(key, label, f"{label} encoder")
    assert control.current() == "auto"
    control.set_current("cpu")
    assert control.current() == "cpu" and changes[-1] == "cpu"
    assert control.button(1).toolTip() == "GPU encoder"
