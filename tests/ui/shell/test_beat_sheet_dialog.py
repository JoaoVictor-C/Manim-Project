"""Edit > Beat Sheet... (ADR 0073): beats listed with pictures, double-click goes there, copy as Markdown."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from manim_studio.core.model.schema import Canvas, Layer, Lifetime, Marker, Project, Spec
from manim_studio.ui.shell.beat_sheet_dialog import BeatSheetDialog

pytestmark = pytest.mark.ui


def scene() -> Project:
    return Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=6.0),
        layers=[Layer(id="a", spec=Spec(type="Square"), lifetime=Lifetime(in_=0.0, out=5.0))],
        markers=[Marker(id="m", t=2.0, name="Second")],
    )


def test_it_lists_the_beats_draws_them_and_goes_to_one(qt_app) -> None:
    went = []
    dialog = BeatSheetDialog(scene, went.append)
    dialog.show()
    for _ in range(20):
        qt_app.processEvents()
    assert dialog.list.count() == 2
    assert "Second" in dialog.list.item(1).text()
    assert not dialog.list.item(0).icon().isNull() and not dialog.list.item(1).icon().isNull()
    dialog.list.setCurrentRow(1)
    dialog.go()
    assert went == [2.0]
    dialog.copy_markdown()
    assert "## 2. Second" in QApplication.clipboard().text()
    dialog.close()
