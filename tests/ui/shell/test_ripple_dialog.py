"""Edit > Ripple Edit... (ADR 0071): a preview of what moves, and one undo step."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core.model.schema import AudioClip, Canvas, Clip, Cue, Layer, Marker, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.shell.ripple_dialog import BEAT, INSERT, RippleDialog

pytestmark = pytest.mark.ui


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=6.0),
        layers=[
            Layer(
                id="a",
                spec=Spec(type="Square"),
                clips=[
                    Clip(id="a1", kind="FadeIn", start=0.0, duration=1.0),
                    Clip(id="a2", kind="FadeIn", start=3.0, duration=1.0),
                ],
            )
        ],
        audio=[AudioClip(id="s", path="x.wav", start=3.5, duration=1.0)],
        subtitles=[Cue(id="c", start=3.2, end=4.0, text="late")],
        markers=[Marker(id="m1", t=2.0, name="act two")],
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


def dialog(window, playhead: float = 2.0) -> RippleDialog:
    return RippleDialog(lambda: window.document.project, playhead, window.document.apply, window)


def test_the_summary_says_what_would_move_before_anything_does(window) -> None:
    shown = dialog(window)
    shown.amount.setValue(1.0)
    assert shown.summary.text() == "Moves 1 clips, 1 sounds, 1 subtitles, 1 markers on 1 layer(s)."
    shown.scope_boxes["audio"].setChecked(False)
    shown.scope_boxes["markers"].setChecked(False)
    assert shown.summary.text() == "Moves 1 clips, 1 subtitles on 1 layer(s)."


def test_applying_is_one_undo_step(window) -> None:
    shown = dialog(window)
    shown.amount.setValue(1.0)
    steps = window.document.undo_stack.count()
    shown.run()
    project = window.document.project
    assert project.layer("a").clips[1].start == 4.0 and project.audio[0].start == 4.5
    assert project.layer("a").clips[0].start == 0.0
    assert window.document.undo_stack.count() == steps + 1
    window.document.undo_stack.undo()
    assert window.document.project.layer("a").clips[1].start == 3.0


def test_an_impossible_edit_disables_apply_and_says_why(window) -> None:
    shown = dialog(window, playhead=5.9)
    assert not shown.apply_button.isEnabled() and "nothing starts" in shown.summary.text()


def test_a_beat_can_be_given_a_new_length(window) -> None:
    shown = dialog(window)
    shown.mode.setCurrentIndex(shown.mode.findData(BEAT))
    assert shown.beat.count() == 2  # the lead-in and "act two"
    shown.beat.setCurrentIndex(0)  # 0-2 s
    assert shown.length.value() == pytest.approx(2.0)
    shown.length.setValue(3.0)
    shown.run()
    project = window.document.project
    assert project.markers[0].t == 3.0 and project.layer("a").clips[1].start == 4.0
    assert project.layer("a").clips[0].start == 0.0  # inside the beat: unmoved


def test_the_modes_show_their_own_fields(window) -> None:
    shown = dialog(window)
    shown.show()
    assert shown.mode.currentData() == INSERT and shown.amount.isVisible() and not shown.beat.isVisible()
    shown.mode.setCurrentIndex(shown.mode.findData(BEAT))
    assert shown.beat.isVisible() and not shown.amount.isVisible()
    shown.close()


def test_the_menu_entry_exists(window) -> None:
    edit_menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "&Edit")
    assert "&Ripple Edit..." in [a.text() for a in edit_menu.actions()]


def test_the_dialog_can_be_shown_and_painted(window, qt_app) -> None:
    dialog = RippleDialog(lambda: window.document.project, 0.0, window.document.apply)
    dialog.show()
    qt_app.processEvents()
    assert not dialog.grab().isNull()  # its header icon must exist
    dialog.close()


def test_the_mode_is_a_segmented_control_of_three(window) -> None:
    from manim_studio.ui.shell.ripple_dialog import CLOSE
    from manim_studio.ui.style.segmented import Segmented

    shown = dialog(window)
    assert isinstance(shown.mode, Segmented)
    assert [shown.mode.itemText(i) for i in range(shown.mode.count())] == [
        "Close the gap",
        "Open space",
        "Linked",
    ]
    assert shown.mode.currentData() == INSERT  # opens by default, as it always did
    shown.mode.setCurrentIndex(shown.mode.findData(CLOSE))
    shown.amount.setValue(1.0)
    shown.run()
    project = window.document.project
    assert project.layer("a").clips[1].start == 2.0 and project.audio[0].start == 2.5  # one second earlier


def test_the_chip_counts_what_moves_and_turns_bad_when_nothing_can(window) -> None:
    shown = dialog(window)
    assert shown.summary.property("chip") is True and shown.summary.property("tone") == "neutral"
    assert shown.summary.text().startswith("Moves 1 clips")
    shown.at.setValue(5.9)
    assert shown.summary.property("tone") == "bad" and "nothing starts" in shown.summary.text()
    shown.at.setValue(2.0)
    assert shown.summary.property("tone") == "neutral"


@pytest.mark.parametrize("name", ["ink", "paper"])
def test_it_fits_a_small_window_in_both_themes(window, qt_app, name) -> None:
    from manim_studio.ui.style import theme

    theme.set_theme(qt_app, name)
    shown = dialog(window)
    shown.resize(560, 460)
    shown.show()
    qt_app.processEvents()
    assert shown.width() <= 560 and shown.height() <= 640 and not shown.grab().isNull()
    for mode in (BEAT, INSERT):
        shown.mode.setCurrentIndex(shown.mode.findData(mode))
        qt_app.processEvents()
        assert not shown.grab().isNull()
    shown.close()
    theme.set_theme(qt_app, "ink")
