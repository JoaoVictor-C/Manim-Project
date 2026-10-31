"""File > Snapshots... (ADR 0068): save, compare, restore as one undo step, rename, delete."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QInputDialog, QMessageBox

from manim_studio.core.editing import edits
from manim_studio.core.model import snapshots
from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.exchange.snapshots_dialog import SnapshotsDialog
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=2.0),
        layers=[Layer(id="a", spec=Spec(type="Square"))],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1300, 800)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


@pytest.fixture
def dialog(window):
    shown = SnapshotsDialog(window.path, lambda: window.document.project, window.restore_snapshot, window)
    yield shown
    shown.close()


def name_it(monkeypatch, text: str) -> None:
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (text, True)))


def add_circle(window) -> None:
    project = window.document.project
    new = project.model_copy(update={"layers": [*project.layers, Layer(id="b", spec=Spec(type="Circle"))]})
    window.document.apply(edits.Edit(new, "spec", frozenset({"b"})), "Add circle")


def test_a_saved_snapshot_is_listed_with_its_size(dialog, monkeypatch) -> None:
    assert dialog.list.count() == 0 and not dialog.restore_button.isEnabled()
    name_it(monkeypatch, "rough cut")
    dialog.save_new()
    assert dialog.list.count() == 1 and "rough cut" in dialog.list.item(0).text()
    assert "1 layers" in dialog.list.item(0).text()
    assert dialog.restore_button.isEnabled()


def test_the_difference_from_the_project_now_is_shown(window, dialog, monkeypatch) -> None:
    name_it(monkeypatch, "before circle")
    dialog.save_new()
    assert "No differences." in dialog.difference.toPlainText()
    add_circle(window)
    dialog._show_difference()
    assert "- b (Circle)" not in dialog.difference.toPlainText()  # it was added since, not removed
    text = dialog.difference.toPlainText()
    assert "From this snapshot to the project now" in text


def test_restoring_is_one_undo_step_and_the_snapshot_stays(window, dialog, monkeypatch) -> None:
    name_it(monkeypatch, "just a square")
    dialog.save_new()
    add_circle(window)
    assert [layer.id for layer in window.document.project.layers] == ["a", "b"]
    steps = window.document.undo_stack.count()
    dialog.restore_selected()
    assert [layer.id for layer in window.document.project.layers] == ["a"]
    assert window.document.undo_stack.count() == steps + 1
    window.document.undo_stack.undo()
    assert [layer.id for layer in window.document.project.layers] == ["a", "b"]
    assert dialog.list.count() == 1


def test_rename_and_delete(dialog, monkeypatch) -> None:
    name_it(monkeypatch, "draft")
    dialog.save_new()
    name_it(monkeypatch, "first draft")
    dialog.rename_selected()
    assert "first draft" in dialog.list.item(0).text()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    dialog.delete_selected()
    assert dialog.list.count() == 1  # declined
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    dialog.delete_selected()
    assert dialog.list.count() == 0 and snapshots.listing(dialog.path) == []


def test_an_unsaved_project_is_asked_to_be_saved_first(window) -> None:
    window.path = None
    window.show_snapshots()
    assert "Save the project first" in window.statusBar().currentMessage()
