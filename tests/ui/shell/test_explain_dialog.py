"""Edit > Explain This Moment... (ADR 0082): the playhead explained, stepping, picking an item, copying."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from acceptance.test_acceptance_v1 import menu_action
from manim_studio.core.model.schema import Canvas, Clip, Layer, Lifetime, Marker, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.shell.explain_dialog import LAYER_ROLE, ExplainDialog

pytestmark = pytest.mark.ui


def scene() -> Project:
    return Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=6.0),
        layers=[
            Layer(
                id="a",
                name="Box",
                spec=Spec(type="Square"),
                clips=[Clip(id="in", kind="FadeIn", start=1.0, duration=2.0)],
            ),
            Layer(id="b", spec=Spec(type="Circle"), lifetime=Lifetime(in_=4.0, out=5.0)),
        ],
        markers=[Marker(id="m", t=2.0, name="Middle")],
    )


def rows(dialog: ExplainDialog) -> list[str]:
    return [dialog.list.item(i).text() for i in range(dialog.list.count())]


def test_it_explains_steps_picks_and_copies(qt_app) -> None:
    clock = [1.5]
    picked = []

    def seek(t: float) -> None:
        clock[0] = t

    dialog = ExplainDialog(scene, lambda: clock[0], seek, lambda lid, cid: picked.append((lid, cid)))
    dialog.show()
    qt_app.processEvents()
    assert not dialog.grab().isNull()
    assert any("Box comes in with FadeIn, 25% through" in r for r in rows(dialog))
    assert "moment 2 of" in dialog.frame.description_label.text()

    assert dialog.step(+1) == 2.0 and clock == [2.0]
    assert "Middle" in dialog.frame.description_label.text()
    assert dialog.step(+1) == 3.0 and dialog.step(+1) == 4.0
    assert any(r.startswith("b (Circle) is on screen") for r in rows(dialog))
    assert dialog.step(-1) == 3.0

    dialog.refresh(1.5)
    clip_row = next(i for i in range(dialog.list.count()) if "FadeIn" in dialog.list.item(i).text())
    dialog.pick(dialog.list.item(clip_row))
    assert picked == [("a", "in")]
    assert dialog.list.item(0).data(LAYER_ROLE) is None  # a section header selects nothing
    dialog.pick(dialog.list.item(0))
    assert picked == [("a", "in")]

    dialog.copy_text()
    assert QApplication.clipboard().text().startswith("At 0:01.5")
    dialog.follow(5.5)
    assert dialog.explanation.t == 5.5 and not any("Circle" in r for r in rows(dialog))
    assert not dialog.next_button.isEnabled()
    dialog.close()


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(scene().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.show()
    win.load(path)
    yield win
    win.close()


def test_the_menu_opens_it_and_it_follows_the_playhead_and_selects(window, qt_app) -> None:
    action = menu_action(window.menuBar(), "Edit", "Explain This Moment...")
    assert action is window.explain_action
    assert action.shortcut().toString() == "Ctrl+Alt+E"
    window.seek(1.5)
    action.trigger()
    dialog = window.explain_dialog
    assert dialog is not None and dialog.isVisible() and not dialog.isModal()
    assert dialog.explanation.t == pytest.approx(1.5)
    window.seek(4.5)
    assert dialog.explanation.t == pytest.approx(4.5)
    dialog.step(-1)
    assert window.t == pytest.approx(4.0)
    row = next(i for i in range(dialog.list.count()) if dialog.list.item(i).data(LAYER_ROLE) == "b")
    dialog.pick(dialog.list.item(row))
    assert window.selection.layer_id == "b"
    dialog.close()
