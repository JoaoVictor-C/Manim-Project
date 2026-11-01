"""Edit > Beat Sheet... (ADR 0073): beats listed with pictures, double-click goes there, copy as Markdown."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from manim_studio.core.model.schema import Canvas, Layer, Lifetime, Marker, Project, Spec
from manim_studio.ui.shell.beat_sheet_dialog import BeatSheetDialog
from manim_studio.ui.style.list_row import Dot

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
    # the rows are widgets (ADR 0084): a picture each, the name and the clock range in mono
    assert all(p.pixmap() is not None and not p.pixmap().isNull() for p in dialog.pictures)
    first = dialog.list.itemWidget(dialog.list.item(0))
    assert first.title_label.text() == "Start" and first.mono_label.text().startswith("0:00.0 - 0:02.0")
    assert (dialog.pictures[0].width(), dialog.pictures[0].height()) == (192, 108)
    assert [line.text() for line in first.lines] == ["a"]  # the label of the layer that appears at 0
    dialog.list.setCurrentRow(1)
    dialog.go()
    assert went == [2.0]
    dialog.copy_markdown()
    assert "## 2. Second" in QApplication.clipboard().text()
    dialog.close()


@pytest.mark.parametrize("name", ["ink", "paper"])
def test_it_paints_in_both_themes_at_the_smallest_size(qt_app, name) -> None:
    from manim_studio.core.model.schema import AudioClip, Cue
    from manim_studio.ui.style import theme

    theme.set_theme(qt_app, name)
    project = scene().model_copy(
        update={
            "subtitles": [Cue(id="c", start=2.5, end=3.5, text="And now the second beat.")],
            "audio": [AudioClip(id="s", path="x.wav", start=2.2, duration=1.0, name="whoosh")],
        }
    )
    dialog = BeatSheetDialog(lambda: project, lambda t: None)
    dialog.resize(560, 520)
    dialog.show()
    for _ in range(20):
        qt_app.processEvents()
    second = dialog.list.itemWidget(dialog.list.item(1))
    assert [line.text() for line in second.lines] == ['"And now the second beat."', "whoosh"]
    assert len(second.findChildren(Dot)) == 2 and {d.token for d in second.findChildren(Dot)} == {
        "cue",
        "sound",
    }
    assert dialog.width() <= 560 and not dialog.grab().isNull()
    footer = dialog.frame.footer
    buttons = [footer.itemAt(i).widget() for i in range(footer.count()) if footer.itemAt(i).widget()]
    assert [b.text() for b in buttons] == ["Copy as Markdown", "Close"] and buttons[-1].property(
        "role"
    ) == "primary"
    dialog.close()
    theme.set_theme(qt_app, "ink")
