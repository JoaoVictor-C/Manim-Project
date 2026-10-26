"""The replace / skip / keep-both question (P12.4)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.ui.exchange.conflict_dialog import COPY, REPLACE, SKIP, ConflictAsker, ConflictDialog

pytestmark = pytest.mark.ui


def test_each_button_answers_and_cancel_answers_nothing(qt_app) -> None:
    for key in (REPLACE, SKIP, COPY):
        dialog = ConflictDialog("Orbit.py", "C:/out")
        dialog.buttons[key].click()
        assert dialog.answer == key and not dialog.for_all()
    dialog = ConflictDialog("Orbit.py")
    dialog.reject()
    assert dialog.answer is None


def test_keep_both_is_the_default_button(qt_app) -> None:
    assert ConflictDialog("a.py").buttons[COPY].isDefault()


def test_for_all_answers_the_later_conflicts_without_asking(qt_app) -> None:
    asked = []

    def ask(name):
        asked.append(name)
        return REPLACE, True

    asker = ConflictAsker()
    asker.ask = ask
    assert [asker("a.py"), asker("b.py"), asker("c.py")] == [REPLACE, REPLACE, REPLACE]
    assert asked == ["a.py"]


def test_without_for_all_every_conflict_is_asked(qt_app) -> None:
    answers = iter([(SKIP, False), (COPY, False)])
    asked = []
    asker = ConflictAsker()
    asker.ask = lambda name: (asked.append(name), next(answers))[1]
    assert (asker("a.py"), asker("b.py")) == (SKIP, COPY) and asked == ["a.py", "b.py"]


def test_cancel_is_not_remembered(qt_app) -> None:
    asker = ConflictAsker()
    asker.ask = lambda name: (None, True)
    assert asker("a.py") is None and asker.sticky is None


def test_the_dialog_for_all_checkbox_reaches_the_asker(qt_app, monkeypatch) -> None:
    def fake_exec(self):
        self.all_box.setChecked(True)
        self.buttons[SKIP].click()

    monkeypatch.setattr(ConflictDialog, "exec", fake_exec)
    asker = ConflictAsker()
    assert asker("a.py") == SKIP and asker("b.py") == SKIP and asker.sticky == SKIP
