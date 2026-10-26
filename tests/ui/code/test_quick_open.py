"""Quick open (P12.5): ranking and the window."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from manim_studio.ui.code.quick_open import QuickItem, QuickOpen, rank, score

pytestmark = pytest.mark.ui

ITEMS = [
    QuickItem("layer", "orbit", "Orbit", "Scene"),
    QuickItem("layer", "wheel", "Right wheel", "Python object"),
    QuickItem("preset", "builtin:matrix", "Matrix", "Built in"),
    QuickItem("preset", "user:mine", "My matrix of ones", "Mine"),
]


def test_letters_must_appear_in_order() -> None:
    assert score("mtx", "Matrix") is not None
    assert score("xtm", "Matrix") is None
    assert score("", "anything") == 0
    assert score("MAT", "matrix") is not None  # case does not matter


def test_the_start_of_the_name_and_of_a_word_rank_higher() -> None:
    assert score("mat", "Matrix") > score("mat", "Format")
    assert score("w", "Right wheel") > score("w", "Showcase")


def test_rank_orders_by_match_then_original_order() -> None:
    assert [i.key for i in rank(ITEMS, "matrix")] == ["builtin:matrix", "user:mine"]
    assert [i.key for i in rank(ITEMS, "")] == ["orbit", "wheel", "builtin:matrix", "user:mine"]
    assert rank(ITEMS, "zzz") == []


def test_typing_filters_and_enter_chooses_the_first(qt_app) -> None:
    dialog = QuickOpen(ITEMS)
    assert dialog.list.count() == 4
    dialog.search.setText("mat")
    assert dialog.shown[0].key == "builtin:matrix"
    QTest.keyClick(dialog.search, Qt.Key.Key_Return)
    assert dialog.chosen == ITEMS[2] and dialog.result() == dialog.DialogCode.Accepted


def test_arrow_keys_move_the_choice(qt_app) -> None:
    dialog = QuickOpen(ITEMS)
    QTest.keyClick(dialog, Qt.Key.Key_Down)
    QTest.keyClick(dialog, Qt.Key.Key_Down)
    assert dialog.list.currentRow() == 2
    QTest.keyClick(dialog, Qt.Key.Key_Up)
    assert dialog.list.currentRow() == 1
    dialog.list.setCurrentRow(1)
    dialog._accept_current()
    assert dialog.chosen == ITEMS[1]


def test_nothing_matching_chooses_nothing(qt_app) -> None:
    dialog = QuickOpen(ITEMS)
    dialog.search.setText("zzz")
    dialog._accept_current()
    assert dialog.chosen is None and dialog.list.count() == 0
