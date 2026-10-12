"""The Audio page (P6b.4, ADR 0041): the sounds and subtitles tables, in-place edits as undo steps,
refusals in the status bar, selection both ways, the buttons and the level meter, through the real
main window."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from manim_studio.core import audio, edits, levels, tables
from manim_studio.core.schema import AudioClip, Canvas, Cue, Layer, Project, Spec
from manim_studio.ui import theme
from manim_studio.ui.audio_player import FakePlayer
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=6.0)
DOT = Layer(id="dot", spec=Spec(type="Dot"))


def tone_file(path, seconds: float = 3.0, amplitude: float = 0.5, hz: float = 440.0):
    t = np.arange(round(seconds * audio.RATE)) / audio.RATE
    wave = (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    audio.write_wav(np.stack([wave, wave]), path)
    return path


@pytest.fixture
def beat(tmp_path):
    return tone_file(tmp_path / "beat.wav")


def open_window(tmp_path, project: Project) -> MainWindow:
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    win.load(path)
    return win


def scene(beat, *, extra=(), cues=()) -> Project:
    sounds = [AudioClip(id="audio-1", name="beat", path=str(beat), start=1.0, duration=3.0), *extra]
    return Project(canvas=CANVAS, layers=[DOT], audio=sounds, subtitles=list(cues))


CUES = (
    Cue(id="cue-1", start=0.5, end=1.5, text="first"),
    Cue(id="cue-2", start=2.0, end=3.0, text="second"),
)


@pytest.fixture
def window(qt_app, tmp_path, beat):
    win = open_window(tmp_path, scene(beat, cues=CUES))
    win.show_page("audio")
    qt_app.processEvents()
    yield win
    win.close()


@pytest.fixture
def page(window):
    return window.pages.pages["audio"]


def col(model, key: str) -> int:
    return [c.key for c in model.columns].index(key)


def cell(model, row: int, key: str, role=Qt.ItemDataRole.DisplayRole):
    return model.data(model.index(row, col(model, key)), role)


def type_in(model, row: int, key: str, text: str) -> bool:
    return model.setData(model.index(row, col(model, key)), text, Qt.ItemDataRole.EditRole)


def steps(window) -> int:
    return window.document.undo_stack.count()


# -- the page ---------------------------------------------------------------------------------


def test_the_audio_page_is_registered_with_its_icon_and_shortcut_hint(window) -> None:
    assert "audio" in window.pages.pages and window.page == "audio"
    bar = window.pages.bar
    index = [bar.tabData(i) for i in range(bar.count())].index("audio")
    assert bar.tabText(index) == "Audio" and not bar.tabIcon(index).isNull()
    assert "Shift+4" in window.pages.pages["audio"].tooltip


def test_the_page_shows_the_viewer_timeline_and_properties_and_parks_the_layers(window, page) -> None:
    for view in (window.viewer, window.timeline, window.properties):
        assert page.widget.isAncestorOf(view) and view.isVisible()
    assert window.layers.parentWidget() is window.pages.parking and not window.layers.isVisible()
    assert page.widget.isAncestorOf(page.sounds) and page.sounds.isVisible() and page.cues.isVisible()
    window.show_page("compose")
    assert not page.widget.isAncestorOf(window.viewer) and window.layers.isVisible()
    window.show_page("audio")
    assert page.widget.isAncestorOf(window.viewer)


def test_the_page_opens_without_a_project(qt_app) -> None:
    win = MainWindow()
    win.show()
    try:
        win.show_page("audio")
        page = win.pages.pages["audio"]
        assert page.sounds_model.rowCount() == 0 and page.cues_model.rowCount() == 0
        for button in (
            page.import_sound_button,
            page.play_button,
            page.add_cue_button,
            page.import_srt_button,
            page.export_srt_button,
            page.delete_sound_button,
            page.delete_cue_button,
        ):
            assert not button.isEnabled()
        assert page.meter.level == levels.SILENCE
    finally:
        win.close()


# -- the tables show the document -------------------------------------------------------------


def test_the_sounds_table_shows_every_field(window, page) -> None:
    model = page.sounds_model
    assert [model.headerData(i, Qt.Orientation.Horizontal) for i in range(model.columnCount())] == [
        "Name",
        "File",
        "Start (s)",
        "Trim start (s)",
        "Duration (s)",
        "Gain (dB)",
        "Fade in (s)",
        "Fade out (s)",
    ]
    assert model.rowCount() == 1
    assert [cell(model, 0, c.key) for c in model.columns] == [
        "beat",
        "beat.wav",
        "1.000",
        "0.000",
        "3.000",
        "0.0",
        "0.000",
        "0.000",
    ]
    assert not model.flags(model.index(0, col(model, "path"))) & Qt.ItemFlag.ItemIsEditable
    assert model.flags(model.index(0, col(model, "gain"))) & Qt.ItemFlag.ItemIsEditable


def test_the_subtitles_table_shows_the_cues_in_time_order(window, page) -> None:
    model = page.cues_model
    assert [[cell(model, r, c.key) for c in model.columns] for r in range(model.rowCount())] == [
        ["0.500", "1.500", "first"],
        ["2.000", "3.000", "second"],
    ]


def test_a_missing_file_is_flagged_in_the_file_cell(qt_app, tmp_path) -> None:
    gone = AudioClip(id="audio-1", name="Music", path=str(tmp_path / "gone.wav"), duration=2.0)
    junk = tmp_path / "notes.mp3"
    junk.write_text("hello", encoding="utf-8")
    bad = AudioClip(id="audio-2", name="Notes", path=str(junk), duration=2.0)
    win = open_window(tmp_path, Project(canvas=CANVAS, audio=[gone, bad]))
    try:
        win.show_page("audio")
        model = win.pages.pages["audio"].sounds_model
        assert cell(model, 0, "path") == "gone.wav - file not found"
        assert cell(model, 1, "path") == "notes.mp3 - cannot read the file"
        assert cell(model, 0, "path", Qt.ItemDataRole.EditRole) == "gone.wav"
        assert cell(model, 0, "path", Qt.ItemDataRole.ForegroundRole) == theme.qcolor(theme.THEME.warning)
        assert "gone.wav" in cell(model, 0, "path", Qt.ItemDataRole.ToolTipRole)
        assert cell(model, 0, "name", Qt.ItemDataRole.ForegroundRole) is None
    finally:
        win.close()


def test_the_tables_follow_edits_made_elsewhere_and_while_hidden(window, page, qt_app) -> None:
    window.document.apply(edits.update_audio(window.project, "audio-1", gain=-3.0), "Change gain")
    assert cell(page.sounds_model, 0, "gain") == "-3.0"
    window.show_page("compose")
    window.document.apply(edits.update_cue(window.project, "cue-1", text="changed"), "Edit subtitle")
    window.document.apply(edits.add_cue(window.project, 4.0, 5.0, "third"), "Add subtitle")
    window.show_page("audio")
    assert [cell(page.cues_model, r, "text") for r in range(3)] == ["changed", "second", "third"]
    window.document.undo_stack.undo()
    window.document.undo_stack.undo()
    assert page.cues_model.rowCount() == 2 and cell(page.cues_model, 0, "text") == "first"


# -- editing in place ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "text", "field", "value"),
    [
        ("name", "Kick", "name", "Kick"),
        ("start", "2.5", "start", 2.5),
        ("offset", "0.5", "offset", 0.5),
        ("duration", "2", "duration", 2.0),
        ("gain", "-6 dB", "gain", -6.0),
        ("fade_in", "0.5", "fade_in", 0.5),
        ("fade_out", "0,25", "fade_out", 0.25),
    ],
)
def test_a_sound_cell_edit_is_one_undo_step_and_everything_follows(window, page, key, text, field, value):
    before, count = window.project.audio[0], steps(window)
    assert type_in(page.sounds_model, 0, key, text)
    assert steps(window) == count + 1
    assert getattr(window.project.audio[0], field) == value
    assert window.evaluator.project.audio == window.project.audio  # the evaluator follows
    assert cell(page.sounds_model, 0, key) == tables.sound_cell(window.project.audio[0], key)
    window.document.undo_stack.undo()
    assert window.project.audio[0] == before
    assert cell(page.sounds_model, 0, key) == tables.sound_cell(before, key)
    window.document.undo_stack.redo()
    assert getattr(window.project.audio[0], field) == value


def test_editing_a_sound_moves_its_bar_on_the_timeline(window, page) -> None:
    (item,) = window.timeline.audio_items()
    left, width = item.rect().left(), item.rect().width()
    type_in(page.sounds_model, 0, "start", "2")
    type_in(page.sounds_model, 0, "duration", "1.5")
    (moved,) = window.timeline.audio_items()
    assert moved.rect().left() > left and moved.rect().width() < width


@pytest.mark.parametrize(
    ("key", "text", "reason"),
    [
        ("start", "soon", "not a number"),
        ("start", "-2", "greater than or equal to 0"),
        ("duration", "0", "greater than 0"),
        ("fade_in", "9", "fades are longer than the sound"),
    ],
)
def test_a_refused_sound_edit_shows_why_and_changes_nothing(window, page, key, text, reason) -> None:
    before, count = window.project, steps(window)
    assert not type_in(page.sounds_model, 0, key, text)
    assert reason in window.statusBar().currentMessage()
    assert window.project is before and steps(window) == count
    assert cell(page.sounds_model, 0, key) == tables.sound_cell(before.audio[0], key)


def test_the_file_cell_cannot_be_edited(window, page) -> None:
    count = steps(window)
    assert not type_in(page.sounds_model, 0, "path", "other.wav")
    assert steps(window) == count and window.project.audio[0].path.endswith("beat.wav")


def test_typing_what_is_already_there_is_not_an_undo_step(window, page) -> None:
    count = steps(window)
    assert not type_in(page.sounds_model, 0, "start", "1.0")
    assert not type_in(page.cues_model, 0, "text", "first")
    assert steps(window) == count


@pytest.mark.parametrize(
    ("key", "text", "field", "value"),
    [("start", "0.25", "start", 0.25), ("end", "1.75", "end", 1.75), ("text", "a ↵ b", "text", "a\nb")],
)
def test_a_subtitle_cell_edit_is_one_undo_step(window, page, key, text, field, value) -> None:
    count = steps(window)
    assert type_in(page.cues_model, 0, key, text)
    assert steps(window) == count + 1 and getattr(window.project.subtitles[0], field) == value
    assert window.evaluator.project.subtitles == window.project.subtitles
    window.document.undo_stack.undo()
    assert window.project.subtitles[0] == CUES[0]
    assert cell(page.cues_model, 0, key) == tables.cue_cell(CUES[0], key)


@pytest.mark.parametrize(
    ("row", "key", "text", "reason"),
    [
        (0, "end", "2.5", "overlap"),  # cue-2 starts at 2.0
        (1, "start", "1.0", "overlap"),  # cue-1 ends at 1.5
        (0, "end", "0.5", "must end after it starts"),
        (1, "start", "3", "must end after it starts"),
        (0, "start", "x", "not a number"),
    ],
)
def test_a_refused_subtitle_edit_shows_why_and_changes_nothing(window, page, row, key, text, reason) -> None:
    before, count = window.project, steps(window)
    assert not type_in(page.cues_model, row, key, text)
    assert reason in window.statusBar().currentMessage()
    assert window.project is before and steps(window) == count


def test_the_edited_subtitle_is_drawn_where_it_now_is(window, page) -> None:
    window.seek(3.5)
    blank = window.canvas.grab().toImage()
    type_in(page.cues_model, 1, "end", "4")  # visible at 3.5 now
    window.seek(3.5)
    assert window.canvas.grab().toImage() != blank


# -- selection ---------------------------------------------------------------------------------


def test_a_sound_row_selects_the_sound_and_the_selection_selects_the_row(window, page) -> None:
    page.sounds.setCurrentIndex(page.sounds_model.index(0, 0))
    assert window.selection.audio_id == "audio-1" and window.selection.subtitle_id is None
    assert page.delete_sound_button.isEnabled() and not page.delete_cue_button.isEnabled()
    window.selection.set_subtitle("cue-2")
    assert page.cues.currentIndex().row() == 1 and not page.sounds.currentIndex().isValid()
    assert page.delete_cue_button.isEnabled() and not page.delete_sound_button.isEnabled()
    window.selection.clear()
    assert not page.cues.currentIndex().isValid() and not page.delete_cue_button.isEnabled()
    window.selection.set_audio("audio-1")
    assert page.sounds.currentIndex().row() == 0


def test_a_subtitle_row_selects_it_and_moves_the_playhead_to_it(window, page) -> None:
    window.seek(5.0)
    index = page.cues_model.index(1, 0)
    page.cues.setCurrentIndex(index)
    assert window.selection.subtitle_id == "cue-2" and window.t == pytest.approx(2.0)
    assert "subtitle_style.font_size" in window.properties.fields  # the style, in Properties
    window.seek(5.0)
    QTest.mouseClick(
        page.cues.viewport(), Qt.MouseButton.LeftButton, pos=page.cues.visualRect(index).center()
    )
    assert window.t == pytest.approx(2.0)  # clicking the row again brings the playhead back


def test_selecting_a_subtitle_elsewhere_does_not_move_the_playhead(window, page) -> None:
    window.seek(4.0)
    window.selection.set_subtitle("cue-1")
    assert page.cues.currentIndex().row() == 0 and window.t == pytest.approx(4.0)
    window.timeline.subtitleSelected.emit("cue-2")  # the timeline's own click
    assert page.cues.currentIndex().row() == 1 and window.t == pytest.approx(4.0)


def test_a_row_stays_selected_through_its_own_edit_and_undo(window, page) -> None:
    window.selection.set_subtitle("cue-1")
    window.seek(4.0)
    type_in(page.cues_model, 0, "text", "edited")
    assert page.cues.currentIndex().row() == 0 and window.selection.subtitle_id == "cue-1"
    window.document.undo_stack.undo()
    assert page.cues.currentIndex().row() == 0 and window.t == pytest.approx(4.0)


def test_deleting_the_selected_row_clears_the_selection(window, page) -> None:
    window.selection.set_audio("audio-1")
    count = steps(window)
    page.delete_sound_button.click()
    assert window.project.audio == [] and page.sounds_model.rowCount() == 0
    assert steps(window) == count + 1 and window.selection.audio_id is None
    assert not page.delete_sound_button.isEnabled()
    window.document.undo_stack.undo()
    assert page.sounds_model.rowCount() == 1


# -- the buttons -------------------------------------------------------------------------------


def test_import_sound_adds_a_row_at_the_playhead_and_selects_it(window, page, tmp_path) -> None:
    second = tone_file(tmp_path / "pad.wav", seconds=2.0, amplitude=0.2)
    window.ask_audio_path = lambda: str(second)
    window.seek(3.0)
    page.import_sound_button.click()
    assert page.sounds_model.rowCount() == 2
    assert [cell(page.sounds_model, 1, k) for k in ("name", "start", "duration")] == ["pad", "3.000", "2.000"]
    assert page.sounds.currentIndex().row() == 1 and window.selection.audio_id == "audio-2"


def test_add_at_playhead_makes_a_selected_row(window, page) -> None:
    window.seek(4.0)
    page.add_cue_button.click()
    assert page.cues_model.rowCount() == 3
    assert [cell(page.cues_model, 2, k) for k in ("start", "end", "text")] == [
        "4.000",
        "6.000",
        "New subtitle",
    ]
    assert page.cues.currentIndex().row() == 2 and window.selection.subtitle_id is not None
    window.seek(2.5)  # inside the second subtitle: the new one goes after it
    page.add_cue_button.click()
    assert page.cues_model.rowCount() == 4  # after the second one, up to the new one at 4 s
    assert [cell(page.cues_model, 2, k) for k in ("start", "end")] == ["3.000", "4.000"]


def test_delete_subtitle_button(window, page) -> None:
    window.selection.set_subtitle("cue-1")
    page.delete_cue_button.click()
    assert [c.id for c in window.project.subtitles] == ["cue-2"]
    assert [cell(page.cues_model, 0, "text")] == ["second"]


def test_srt_buttons_use_the_windows_actions(window, page, tmp_path) -> None:
    srt = tmp_path / "talk.srt"
    srt.write_text(
        "1\n00:00:00,500 --> 00:00:01,000\nHello\n\n2\n00:00:02,000 --> 00:00:03,000\nthere\n",
        encoding="utf-8",
    )
    window.ask_subtitles_path = lambda: str(srt)
    page.import_srt_button.click()
    assert [cell(page.cues_model, r, "text") for r in range(2)] == ["Hello", "there"]
    out = tmp_path / "out.srt"
    window.ask_subtitles_save_path = lambda: str(out)
    page.export_srt_button.click()
    assert "Hello" in out.read_text(encoding="utf-8") and "00:00:02,000 --> 00:00:03,000" in out.read_text(
        encoding="utf-8"
    )
    window.document.undo_stack.undo()
    assert [cell(page.cues_model, r, "text") for r in range(2)] == ["first", "second"]


def test_play_from_here_plays_the_mix_from_the_playhead(window, page) -> None:
    player = FakePlayer()
    window.audio_player = player
    window.seek(1.5)
    page.play_button.click()
    ((samples, t0),) = player.started
    assert t0 == pytest.approx(1.5) and np.array_equal(samples, audio.mix(window.project))
    window.pause()


# -- the level meter -----------------------------------------------------------------------------


def test_the_meter_reads_the_mix_at_the_playhead(window, page) -> None:
    window.seek(2.0)  # the 0.5 tone is playing (1.0 to 4.0)
    level = page.meter.level
    assert level.peak == pytest.approx((0.5, 0.5), abs=2e-3)
    assert level.rms_db == pytest.approx((-9.03, -9.03), abs=0.1)
    assert "-6.0" in page.meter.readout() and "-9.0" in page.meter.readout()
    assert page.meter.label.text() == page.meter.readout()
    window.seek(0.2)
    assert page.meter.level == levels.SILENCE and "-inf" in page.meter.readout()
    window.seek(4.5)
    assert page.meter.level == levels.SILENCE


def test_the_meter_follows_playback_ticks(window, page) -> None:
    window.seek(0.0)
    assert page.meter.level == levels.SILENCE
    window.play()
    window.seek(1.5)  # what each tick does
    window.pause()
    assert page.meter.level.peak[0] > 0.4


def test_the_meter_follows_gain_edits_and_undo(window, page) -> None:
    window.seek(2.0)
    type_in(page.sounds_model, 0, "gain", "-6")
    assert page.meter.level.peak == pytest.approx((0.25, 0.25), abs=2e-3)
    type_in(page.sounds_model, 0, "start", "3")  # silent at 2.0 now
    assert page.meter.level == levels.SILENCE
    window.document.undo_stack.undo()
    window.document.undo_stack.undo()
    assert page.meter.level.peak[0] == pytest.approx(0.5, abs=2e-3)


def test_the_meter_is_silent_without_sounds_and_ignores_a_missing_file(qt_app, tmp_path) -> None:
    gone = AudioClip(id="audio-1", path=str(tmp_path / "gone.wav"), duration=2.0)
    win = open_window(tmp_path, Project(canvas=CANVAS, audio=[gone]))
    try:
        win.show_page("audio")
        win.seek(1.0)
        assert win.pages.pages["audio"].meter.level == levels.SILENCE
        win.document.apply(edits.remove_audio(win.project, "audio-1"), "Delete sound")
        assert win.pages.pages["audio"].meter.level == levels.SILENCE
    finally:
        win.close()


def test_a_hidden_page_does_no_meter_work(window, page, monkeypatch) -> None:
    window.show_page("compose")
    calls = []
    monkeypatch.setattr(levels, "level_at", lambda *a, **k: calls.append(a) or levels.SILENCE)
    window.seek(2.0)
    window.document.apply(edits.update_audio(window.project, "audio-1", gain=-1.0), "Change gain")
    assert calls == []
    window.show_page("audio")
    assert len(calls) == 1  # one read when it is shown again


def test_meter_colours_come_from_the_theme(window, page) -> None:
    image = page.meter.bars.grab().toImage()
    window.seek(2.0)
    loud = page.meter.bars.grab().toImage()
    assert image != loud
    seen = {
        loud.pixelColor(x, y).name() for x in range(0, loud.width(), 3) for y in range(0, loud.height(), 2)
    }
    assert theme.qcolor(theme.THEME.warning).name() in seen  # -9 dB RMS is in the amber zone


# -- details the first tests do not pin --------------------------------------------------------


def test_picking_a_subtitle_while_playing_pauses_first(window, page) -> None:
    window.play()
    assert window.play_timer.isActive()
    page.cues.setCurrentIndex(page.cues_model.index(1, 0))
    assert not window.play_timer.isActive() and window.t == pytest.approx(2.0)


def test_delete_with_nothing_selected_does_nothing(window, page) -> None:
    window.selection.clear()
    count = steps(window)
    page.delete_sound()
    page.delete_cue()
    assert steps(window) == count and page.sounds_model.rowCount() == 1 and page.cues_model.rowCount() == 2


def test_export_needs_subtitles_and_the_file_cell_is_ignored_silently(window, page) -> None:
    assert page.export_srt_button.isEnabled()
    window.document.apply(edits.set_subtitles(window.project, []), "Delete subtitles")
    assert not page.export_srt_button.isEnabled() and page.add_cue_button.isEnabled()
    window.statusBar().showMessage("untouched")
    assert not type_in(page.sounds_model, 0, "path", "other.wav")
    assert window.statusBar().currentMessage() == "untouched"


def test_an_edit_updates_cells_without_resetting_the_table(window, page) -> None:
    resets, repaints = [], []
    page.cues_model.modelReset.connect(lambda: resets.append(1))
    page.cues_model.dataChanged.connect(lambda *_: repaints.append(1))
    window.selection.set_subtitle("cue-2")
    type_in(page.cues_model, 1, "text", "again")
    assert repaints  # the view is told the cells changed
    window.document.undo_stack.undo()
    # the rows are the same: an open editor survives
    assert resets == [] and page.cues.currentIndex().row() == 1
    window.document.apply(edits.remove_cue(window.project, "cue-1"), "Delete subtitle")
    assert resets == [1]


def test_the_selected_row_follows_its_subtitle_when_rows_are_inserted_before_it(window, page) -> None:
    window.selection.set_subtitle("cue-2")
    window.document.apply(edits.add_cue(window.project, 0.0, 0.4, "early"), "Add subtitle")
    assert window.selection.subtitle_id == "cue-2"
    assert page.cues.currentIndex().row() == 2 and cell(page.cues_model, 2, "text") == "second"
    assert window.t == 0.0  # nothing moved the playhead
