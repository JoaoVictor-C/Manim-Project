"""The Audio and Deliver pages in Lumen (ADR 0063, P17.4d): the card structure exists, the mix lanes read the
document, the destinations start the form, the queue shows its jobs with a ring, both themes build, and the
pages fit a 1024 x 640 window."""

from __future__ import annotations

import os
from typing import ClassVar

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from manim_studio.core.model.schema import AudioClip, Canvas, Cue, Layer, Project, Spec, VoiceChoice
from manim_studio.core.sound import audio
from manim_studio.core.voice import narration
from manim_studio.ui.deliver.queue_view import ProgressRing
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.pages import deliver, mix_lanes
from manim_studio.ui.style import theme
from manim_studio.ui.style.card import Card

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=6.0)
SMALL = (1024, 640)


def tone_file(path, seconds: float = 3.0):
    t = np.arange(round(seconds * audio.RATE)) / audio.RATE
    wave = (0.5 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    audio.write_wav(np.stack([wave, wave]), path)
    return path


def project_with(tmp_path) -> Project:
    beat = tone_file(tmp_path / "beat.wav")
    voice = tone_file(tmp_path / "voice.wav", seconds=2.0)
    cue = Cue(
        id="cue-1",
        start=1.0,
        end=3.0,
        text="Euler found a bridge",
        voice=VoiceChoice(provider="piper", voice="amy"),
        audio_id="audio-2",
        audio_key="old-key",  # not what the text and voice hash to: stale
    )
    return Project(
        canvas=CANVAS,
        layers=[Layer(id="dot", spec=Spec(type="Dot"))],
        audio=[
            AudioClip(id="audio-1", name="beat", path=str(beat), start=0.5, duration=3.0),
            AudioClip(id="audio-2", name="voice", path=str(voice), start=1.0, duration=2.0),
        ],
        subtitles=[cue, Cue(id="cue-2", start=3.5, end=5.0, text="and nothing was the same")],
    )


@pytest.fixture
def make_window(qt_app, tmp_path):
    windows: list[MainWindow] = []

    def make(size=(1400, 900)) -> MainWindow:
        path = tmp_path / "scene.json"
        path.write_text(project_with(tmp_path).model_dump_json(by_alias=True), encoding="utf-8")
        win = MainWindow()
        win.resize(*size)
        win.show()
        win.load(path)
        windows.append(win)
        return win

    yield make
    for win in windows:
        win.document.undo_stack.setClean()
        win.close()
    theme.set_theme(qt_app, "ink")


# -- Audio ------------------------------------------------------------------------------------------


def test_the_audio_page_is_made_of_cards(make_window, qt_app) -> None:
    win = make_window()
    win.show_page("audio")
    qt_app.processEvents()
    page = win.pages.pages["audio"]
    cards = [card.title() for card in page.widget.findChildren(Card)]
    assert sorted(cards) == ["Mix", "Narration"]  # no Stage, Properties, Sounds or Subtitles card
    assert page.mix_card.isAncestorOf(page.lanes) and page.mix_card.isAncestorOf(page.meter)
    assert page.narration_card.isAncestorOf(page.narration) and page.top.widget(1) is page.narration_card
    assert page.mix_card.isAncestorOf(page.sounds) and page.mix_card.isAncestorOf(page.cues)  # the Table view
    assert abs(page.narration_card.width() - 400) < 40  # the 400 px card of the design
    for shared in (win.viewer, win.timeline, win.properties):
        assert not page.widget.isAncestorOf(shared) and not shared.isVisible()


def test_the_lanes_group_what_the_document_holds(make_window, qt_app) -> None:
    win = make_window()
    win.show_page("audio")
    qt_app.processEvents()
    lanes = win.pages.pages["audio"].lanes
    groups = lanes.groups(win.project)
    assert [(clip.id, cue.id) for clip, cue in groups["narration"]] == [("audio-2", "cue-1")]
    assert [clip.id for clip in groups["music"]] == ["audio-1"]  # 3 s of a 6 s scene: half of it
    assert groups["effects"] == []
    assert [cue.id for cue in groups["subtitles"]] == ["cue-1", "cue-2"]
    assert narration.state(win.project, win.project.subtitles[0]) == narration.STALE
    page = win.pages.pages["audio"]
    assert page.stale_chip.text() == "1 stale" and not page.stale_chip.isHidden()


def test_a_click_on_a_bar_selects_it_and_a_click_on_the_ruler_seeks(make_window, qt_app) -> None:
    win = make_window()
    win.show_page("audio")
    qt_app.processEvents()
    page = win.pages.pages["audio"]
    lanes = page.lanes
    lanes.repaint()  # the bars' rectangles are known once painted
    kinds = {(kind, item_id): rect for rect, kind, item_id in lanes._hits}
    assert ("sound", "audio-1") in kinds and ("cue", "cue-2") in kinds
    QTest.mouseClick(lanes, Qt.MouseButton.LeftButton, pos=kinds[("sound", "audio-1")].center().toPoint())
    assert win.selection.audio_id == "audio-1"
    QTest.mouseClick(lanes, Qt.MouseButton.LeftButton, pos=kinds[("cue", "cue-2")].center().toPoint())
    assert win.selection.subtitle_id == "cue-2" and win.t == pytest.approx(3.5)
    QTest.mouseClick(lanes, Qt.MouseButton.LeftButton, pos=QPointF(lanes.width() - 20, 8).toPoint())
    assert win.t > 5.0  # the ruler: near the end of the six seconds


def test_the_lanes_help_functions() -> None:
    assert mix_lanes.tick_step(100.0) == 1 and mix_lanes.tick_step(10.0) == 10
    assert mix_lanes.stamp(3.1) == "0:03.10" and mix_lanes.stamp(75.5) == "1:15.50"
    assert mix_lanes.ruler_label(2.0, 1) == "2s" and mix_lanes.ruler_label(90.0, 30) == "1:30"


def test_the_lanes_draw_something_in_the_lane_colours_in_both_themes(make_window, qt_app) -> None:
    win = make_window()
    win.show_page("audio")
    qt_app.processEvents()
    lanes = win.pages.pages["audio"].lanes
    for name in ("ink", "paper"):
        theme.set_theme(qt_app, name)
        qt_app.processEvents()
        image = lanes.grab().toImage()
        seen = {
            image.pixelColor(x, y).name()
            for x in range(0, image.width(), 5)
            for y in range(0, image.height(), 3)
        }
        assert len(seen) > 12, name


def test_the_master_strip_and_the_chip_follow_the_playhead(make_window, qt_app) -> None:
    win = make_window()
    win.show_page("audio")
    page = win.pages.pages["audio"]
    win.seek(2.0)
    assert page.time_chip.text() == "0:02.00" and page.meter.objectName() == "masterStrip"


def test_short_sounds_are_effects_and_long_ones_music() -> None:
    short = AudioClip(id="a", path="x.wav", duration=0.5)
    long_ = AudioClip(id="b", path="x.wav", duration=9.0)
    half = AudioClip(id="c", path="x.wav", duration=3.0)
    assert not mix_lanes.is_music(short, 6.0) and mix_lanes.is_music(long_, 60.0)
    assert mix_lanes.is_music(half, 6.0) and not mix_lanes.is_music(half, 60.0)


def test_the_lanes_zoom_and_scroll_and_a_header_is_not_the_ruler(make_window, qt_app) -> None:
    win = make_window()
    win.show_page("audio")
    qt_app.processEvents()
    page = win.pages.pages["audio"]
    lanes = page.lanes
    assert lanes.zoom == 1.0 and page.scroll_bar.isHidden()
    page.zoom_slider.setValue(50)  # 16 ** 0.5 = 4 times
    assert lanes.zoom == pytest.approx(4.0) and not page.scroll_bar.isHidden()
    assert lanes.span() == pytest.approx(lanes.duration() / 4)
    page.scroll_bar.setValue(page.scroll_bar.maximum())
    assert lanes.scroll == pytest.approx(lanes.duration() - lanes.span())
    lanes.repaint()
    width = lanes.width()
    QTest.mouseClick(lanes, Qt.MouseButton.LeftButton, pos=QPointF(width - 8, 8).toPoint())
    assert win.t > lanes.duration() - lanes.span()  # a click on the ruler seeks in the zoomed view
    seen = win.t
    QTest.mouseClick(lanes, Qt.MouseButton.LeftButton, pos=QPointF(40, 40).toPoint())  # a lane header
    assert win.t == seen
    page.zoom_slider.setValue(0)
    assert lanes.zoom == 1.0 and lanes.scroll == 0.0 and page.scroll_bar.isHidden()


def test_a_zoomed_mix_follows_the_playhead(make_window, qt_app) -> None:
    win = make_window()
    win.show_page("audio")
    page = win.pages.pages["audio"]
    page.zoom_slider.setValue(50)
    win.seek(5.5)
    assert page.lanes.scroll <= 5.5 <= page.lanes.scroll + page.lanes.span()
    assert page.scroll_bar.value() == round(page.lanes.scroll * 1000)


def test_the_wheel_zooms_with_control_and_pans_when_zoomed(make_window, qt_app) -> None:
    win = make_window()
    win.show_page("audio")
    qt_app.processEvents()
    lanes = win.pages.pages["audio"].lanes
    lanes.set_zoom(4.0)
    before = lanes.scroll
    event = QWheelEvent(
        QPointF(300, 50), QPointF(300, 50), QPoint(0, 0), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
    )  # fmt: skip
    QApplication.sendEvent(lanes, event)
    assert lanes.scroll > before  # the wheel moved the view along
    zoom = lanes.zoom
    event = QWheelEvent(
        QPointF(300, 50), QPointF(300, 50), QPoint(0, 0), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False,
    )  # fmt: skip
    QApplication.sendEvent(lanes, event)
    assert lanes.zoom > zoom


def test_the_transport_play_button_plays_and_pauses_and_shows_which(make_window, qt_app) -> None:
    win = make_window()
    win.show_page("audio")
    page = win.pages.pages["audio"]
    assert not page.play_button.playing and page.meter.isAncestorOf(page.play_button)
    page.play_button.click()
    assert win.play_timer.isActive() and page.play_button.playing
    page.play_button.click()
    assert not win.play_timer.isActive() and not page.play_button.playing
    assert not page.play_button.grab().isNull()


def test_the_markers_menu_and_the_more_menu_reach_the_old_functions(make_window, qt_app) -> None:
    win = make_window()
    win.show_page("audio")
    qt_app.processEvents()
    page = win.pages.pages["audio"]
    assert not win.project.markers and not page.next_marker_action.isEnabled()
    win.seek(2.0)
    page.add_marker_action.trigger()
    assert [m.t for m in win.project.markers] == [pytest.approx(2.0)]
    win.seek(0.0)
    assert page.next_marker_action.isEnabled()
    page.next_marker_action.trigger()
    assert win.t == pytest.approx(2.0)
    page.lanes.repaint()  # a marker is drawn on the ruler
    assert not page.lanes.grab().isNull()
    win.selection.set_audio("audio-1")
    page.more_actions["delete"].trigger()
    assert [c.id for c in win.project.audio] == ["audio-2"]
    win.selection.set_subtitle("cue-2")
    page.delete_selected()
    assert [c.id for c in win.project.subtitles] == ["cue-1"]
    assert not page.more_actions["delete"].isEnabled()


def test_a_cue_row_of_the_narration_card_selects_the_subtitle_and_moves_the_playhead(
    make_window, qt_app
) -> None:
    win = make_window()
    win.show_page("audio")
    qt_app.processEvents()
    page = win.pages.pages["audio"]
    win.seek(0.0)
    page.narration.cue_list.rows["cue-2"].pressed.emit()
    assert win.selection.subtitle_id == "cue-2" and win.t == pytest.approx(3.5)
    assert page.lanes.subtitle_id == "cue-2" and page.cues.currentIndex().row() == 1
    win.seek(0.0)
    page.narration.cue_list.rows["cue-2"].pressed.emit()  # pressing it again brings the playhead back
    assert win.t == pytest.approx(3.5)


# -- Deliver ----------------------------------------------------------------------------------------


class FakeExport(QObject):
    progress = Signal(int, int)
    stage = Signal(str)
    finished = Signal(str, str)
    failed = Signal(str)
    how = ""  # what encoded and how many processes drew (the real job's summary)
    instances: ClassVar[list] = []

    def __init__(self, project, output, cache_dir, *, trust_code=False, options=None, parent=None):
        super().__init__(parent)
        FakeExport.instances.append(self)

    def start(self) -> None:
        pass

    def cancel(self) -> None:
        pass


@pytest.fixture
def deliver_page(make_window, qt_app, monkeypatch):
    FakeExport.instances = []
    monkeypatch.setattr(deliver, "ExportJob", FakeExport)
    win = make_window()
    win.show_page("deliver")
    qt_app.processEvents()
    return win, win.pages.pages["deliver"]


def test_the_deliver_page_is_three_cards_with_the_viewer_in_the_middle(deliver_page) -> None:
    win, page = deliver_page
    assert [card.title() for card in (page.destination_card, page.settings_card, page.queue_card)] == [
        "Where is it going?",
        "Video for the web",
        "Queue",
    ]
    assert page.centre.widget(0) is win.viewer_card and page.centre.widget(1) is page.settings_card
    assert page.outer.widget(0) is page.destination_card and page.outer.widget(2) is page.queue_card
    assert list(page.destinations) == ["web", "draft", "hd", "master", "deck", "python"]
    assert page.destinations["web"].isChecked() and not page.destinations["draft"].isChecked()


def test_a_destination_starts_the_form_and_the_chip_says_when_it_was_edited(deliver_page) -> None:
    _win, page = deliver_page
    page.destinations["draft"].click()
    assert page.size.currentData() == "480p" and page.quality.currentData() == 28
    assert page.settings_card.title() == "Quick draft" and page.preset_chip.text() == "Preset"
    page.quality.setCurrentIndex(page.quality.findData(18))
    assert page.preset_chip.text() == "Edited"
    page.destinations["web"].click()
    assert page.size.currentData() == "project" and page.quality.currentData() == 18
    assert page.preset_chip.text() == "Preset" and not page.destinations["draft"].isChecked()


def test_the_python_destination_shows_the_scene(deliver_page) -> None:
    _win, page = deliver_page
    page.destinations["python"].click()
    assert page.settings_stack.currentIndex() == 1 and page.preset_chip.isHidden()
    assert page.python_code.toPlainText() and page.python_save.isEnabled()
    page.destinations["web"].click()
    assert page.settings_stack.currentIndex() == 0


def test_the_estimate_tiles_describe_the_export(deliver_page) -> None:
    _win, page = deliver_page
    assert page.tile_length.value.text() == "0:06 - 60 frames"
    assert page.tile_sound.value.text() == "2 sounds" and page.tile_time.value.text() == "-"
    assert page.tile_size.value.text().startswith("about ")
    page.quality.setCurrentIndex(page.quality.findData(12))  # a higher quality is a bigger file
    assert deliver.megabytes(2e6) == "2.0 MB" and deliver.clock(3725) == "1:02:05"


def test_the_queue_shows_a_ring_for_the_running_job_and_a_check_for_a_finished_one(
    deliver_page, qt_app
) -> None:
    win, page = deliver_page
    out = win.path.parent / "out"
    page.path.setText(str(out / "a.mp4"))
    first = page.add_to_queue()
    page.path.setText(str(out / "b.mp4"))
    second = page.add_to_queue()
    assert page.now_ring.state == "idle" and page.queue_chip.isHidden() is False  # two queued
    assert page.queue_chip.text() == "2 queued"
    page.render_button.click()  # queues a third and starts
    run = FakeExport.instances[0]
    run.progress.emit(30, 60)
    qt_app.processEvents()
    assert page.now_ring.state == "running" and page.now_ring.percent_text() == "50%"
    assert page.now_title.text() == "a.mp4" and page.queue_chip.text() == "1 running"
    assert page._row_widgets[first.id].ring.state == "running"
    assert page._row_widgets[second.id].ring.state == "queued"
    run.finished.emit(str(first.output), "")
    assert page._row_widgets[first.id].ring.state == "done"
    assert page._row_widgets[first.id].name.text() == "a.mp4"
    assert page.tile_time.value.text() != "-" or page._pixel_rate is None  # measured, when it ran long enough
    page.clear_button.click()
    assert first.id not in page._row_widgets and page.tree.topLevelItemCount() == 2


def test_the_progress_ring_states() -> None:
    ring = ProgressRing(44)
    for state in ("idle", "starting", "running", "queued", "done", "failed", "cancelled"):
        ring.set_state(state, 0.25)
        assert ring.grab().toImage().width() == 44
    ring.set_state("running", 0.64)
    assert ring.percent_text() == "64%"
    with pytest.raises(ValueError):
        ring.set_state("sleeping")


# -- both pages, both themes, a small window --------------------------------------------------------


@pytest.mark.parametrize("page_name", ["audio", "deliver"])
@pytest.mark.parametrize("name", ["ink", "paper"])
def test_the_pages_build_in_both_themes_and_fit_a_small_window(make_window, qt_app, page_name, name) -> None:
    theme.set_theme(qt_app, name)
    win = make_window(SMALL)
    win.show_page(page_name)
    qt_app.processEvents()
    page = win.pages.pages[page_name]
    assert not page.widget.grab().isNull()
    assert win.size().width() <= SMALL[0] + 2 and win.size().height() <= SMALL[1] + 2
    for card in page.widget.findChildren(Card):
        if card.isVisible():
            assert card.width() >= card.minimumSizeHint().width() - 1, card.title()
            assert card.height() >= card.minimumSizeHint().height() - 1, card.title()
