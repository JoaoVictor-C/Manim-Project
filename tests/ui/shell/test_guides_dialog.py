"""View > Layout Guides... (ADR 0074): list, add, move, delete, and the margin, thirds and centre sets."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.editing import edits
from manim_studio.core.model.schema import Canvas, Project
from manim_studio.ui.shell.guides_dialog import GuidesDialog

pytestmark = pytest.mark.ui


class Holder:
    """The project and its undo steps, as the document keeps them."""

    def __init__(self) -> None:
        self.project = Project(canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0))
        self.steps: list[str] = []

    def apply(self, edit: edits.Edit, text: str) -> None:
        self.project = edit.project
        self.steps.append(text)


@pytest.fixture
def shown(qt_app):
    holder = Holder()
    dialog = GuidesDialog(lambda: holder.project, holder.apply)
    dialog.show()
    qt_app.processEvents()
    yield dialog, holder
    dialog.close()


def test_it_shows_and_paints(shown) -> None:
    dialog, _ = shown
    assert not dialog.grab().isNull()  # every icon it names exists
    assert dialog.list.count() == 0
    assert not dialog.delete_button.isEnabled()


def test_add_move_and_delete_a_guide(shown) -> None:
    dialog, holder = shown
    dialog.axis.setCurrentIndex(dialog.axis.findData("y"))
    dialog.position.setValue(1.5)
    dialog.name.setText("horizon")
    dialog.add()
    assert [(g.axis, g.position, g.name) for g in holder.project.guides] == [("y", 1.5, "horizon")]
    assert dialog.list.count() == 1 and "horizon" in dialog.list.item(0).text()
    dialog.add()  # the same place again: refused, said
    assert len(holder.project.guides) == 1 and dialog.status.text()
    dialog.list.setCurrentRow(0)
    dialog.position.setValue(-2.0)
    dialog.move_selected()
    assert holder.project.guides[0].position == -2.0
    dialog.list.setCurrentRow(0)
    dialog.delete_selected()
    assert holder.project.guides == [] and dialog.list.count() == 0
    assert holder.steps == ["Add guide", "Move guide", "Delete guide"]


def test_margins_thirds_and_centre(shown, monkeypatch) -> None:
    dialog, holder = shown
    monkeypatch.setattr(dialog, "ask_margin", lambda: 0.5)
    dialog.add_margins()
    assert len(holder.project.guides) == 6
    dialog.add_centre()  # already there
    assert len(holder.project.guides) == 6 and dialog.status.text()
    dialog.add_thirds()
    assert dialog.list.count() == 10
    monkeypatch.setattr(dialog, "ask_margin", lambda: None)  # cancelled
    dialog.add_margins()
    assert holder.steps == ["Margin guides", "Thirds guides"]
