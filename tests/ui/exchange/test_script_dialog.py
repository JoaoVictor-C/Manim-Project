"""File > Import Script... (ADR 0069): a live summary, and one undo step on Import."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QFileDialog

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.exchange.script_dialog import ScriptDialog
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
    shown = ScriptDialog(lambda: window.document.project, window.document.apply, window)
    yield shown
    shown.close()


def test_an_empty_script_cannot_be_imported(dialog) -> None:
    assert not dialog.import_button.isEnabled() and "nothing to read" in dialog.summary.text()


def test_the_summary_follows_the_text_and_the_choices(dialog) -> None:
    dialog.text.setPlainText("One two three. Four five six.\n\nSeven.")
    assert dialog.import_button.isEnabled() and dialog.summary.text().startswith(
        "3 subtitles in 2 paragraphs"
    )
    dialog.unit.setCurrentIndex(1)
    assert dialog.summary.text().startswith("2 subtitles in 2 paragraphs")
    dialog.placeholders.setChecked(True)
    assert "2 placeholder layers" in dialog.summary.text()


def test_import_is_one_undo_step(window, dialog) -> None:
    dialog.text.setPlainText("Hello there. This is the story.")
    steps = window.document.undo_stack.count()
    dialog.run()
    assert [c.text for c in window.document.project.subtitles] == ["Hello there.", "This is the story."]
    assert window.document.undo_stack.count() == steps + 1
    window.document.undo_stack.undo()
    assert window.document.project.subtitles == []


def test_a_file_can_be_loaded(dialog, tmp_path, monkeypatch) -> None:
    script = tmp_path / "story.md"
    script.write_text("# Title\nA line to read.\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(script), "")))
    dialog.load_file()
    assert "A line to read." in dialog.text.toPlainText()
    assert dialog.summary.text().startswith("1 subtitles")


def test_the_menu_entry_exists(window) -> None:
    labels = [a.text() for a in window.menuBar().actions()[0].menu().actions()]
    assert "Import &Script..." in labels
