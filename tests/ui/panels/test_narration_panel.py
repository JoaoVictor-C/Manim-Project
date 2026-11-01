"""The Narration section of the Audio page (ADR 0060): voices, generate, stale, follow, cancel, consent."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QFileDialog

from manim_studio import plugins
from manim_studio.core.editing import edits
from manim_studio.core.model.schema import Canvas, Cue, Layer, Project, Spec, VoiceChoice
from manim_studio.core.voice import narration
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.panels.narration_panel import PronunciationDialog
from manim_studio.ui.style.card import Chip
from voice_support import SECONDS_PER_CHAR

pytestmark = [pytest.mark.ui, pytest.mark.usefixtures("fake_voice")]

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=20.0)
FAKE = VoiceChoice(provider="fake", voice="anna")


def project(*texts: str, voice: VoiceChoice | None = FAKE) -> Project:
    cues = [Cue(id=f"cue-{i}", start=i * 4.0, end=i * 4.0 + 2.0, text=t) for i, t in enumerate(texts)]
    return Project(
        canvas=CANVAS, layers=[Layer(id="dot", spec=Spec(type="Dot"))], subtitles=cues, voice=voice
    )


def open_window(tmp_path, p: Project) -> MainWindow:
    path = tmp_path / "scene.json"
    path.write_text(p.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    win.load(path)
    win.show_page("audio")
    return win


@pytest.fixture
def make(qt_app, tmp_path):
    windows = []

    def build(*texts: str, voice: VoiceChoice | None = FAKE):
        win = open_window(tmp_path, project(*texts, voice=voice))
        windows.append(win)
        return win, win.pages.pages["audio"].narration

    yield build
    for win in windows:
        win.close()


def settle(panel, qt_app) -> None:
    assert panel.client.wait(60000)
    qt_app.processEvents()
    assert not panel.running


def generate(panel, qt_app, scope: str = "stale") -> None:
    panel.generate(scope)
    settle(panel, qt_app)


def test_the_providers_are_listed_and_a_choice_becomes_the_projects_voice(make, qt_app) -> None:
    win, panel = make("hello", voice=None)
    names = [panel.provider_combo.itemData(i) for i in range(panel.provider_combo.count())]
    assert {"edge", "sapi", "fake"} <= set(names)
    panel.provider_combo.setCurrentIndex(panel.provider_combo.findData("fake"))
    panel.provider_combo.activated.emit(panel.provider_combo.currentIndex())
    settle(panel, qt_app)
    voices = lambda: [panel.voice_combo.itemData(i) for i in range(panel.voice_combo.count())]  # noqa: E731
    assert [panel.language_combo.itemText(i) for i in range(panel.language_combo.count())] == [
        "All languages",
        "en-GB",
        "en-US",
    ]
    assert voices() == ["anna"]  # the voices of one language (en-US is the default)
    assert win.project.voice == VoiceChoice(provider="fake", voice="anna")  # the first voice, applied
    panel.language_combo.setCurrentIndex(0)
    panel.language_combo.activated.emit(0)
    assert voices() == ["anna", "ben"]
    panel.voice_combo.setCurrentIndex(1)
    panel.voice_combo.activated.emit(1)
    assert win.project.voice.voice == "ben"
    panel.rate_spin.setValue(1.2)
    panel.rate_spin.editingFinished.emit()
    assert win.project.voice.rate == 1.2
    win.document.undo_stack.undo()
    assert win.project.voice.rate == 1.0


def test_an_unavailable_provider_says_why_and_offers_no_voices(make, qt_app, monkeypatch) -> None:
    _, panel = make("hello", voice=None)
    panel.provider_combo.setCurrentIndex(panel.provider_combo.findData("needs"))
    panel.provider_combo.activated.emit(panel.provider_combo.currentIndex())
    assert "pip install thing" in panel.info.text()
    assert panel.voice_combo.count() == 0


def test_generate_places_a_sound_at_each_subtitle_in_one_undo_step(make, qt_app, tmp_path) -> None:
    win, panel = make("first", "the second one")
    before = win.project
    generate(panel, qt_app)
    placed = win.project
    assert [(c.start, round(c.duration, 3)) for c in placed.audio] == [
        (0.0, round(5 * SECONDS_PER_CHAR, 3)),
        (4.0, round(14 * SECONDS_PER_CHAR, 3)),
    ]
    assert all(narration.state(placed, c) == narration.READY for c in placed.subtitles)
    assert (tmp_path / "scene_voice").is_dir()  # next to the project
    assert all((tmp_path / "scene_voice") in __import__("pathlib").Path(c.path).parents for c in placed.audio)
    assert panel.status.text().startswith("Placed 2 sounds")
    win.document.undo_stack.undo()
    assert win.project == before  # a single step
    win.document.undo_stack.redo()
    assert win.project == placed


def test_what_is_current_is_not_generated_again(make, qt_app, monkeypatch) -> None:
    win, panel = make("first", "second")
    generate(panel, qt_app)
    calls = []
    real = panel.client.speak
    monkeypatch.setattr(
        panel.client, "speak", lambda provider, items: calls.append(items) or real(provider, items)
    )
    generate(panel, qt_app)
    assert calls == []
    assert panel.status.text() == "Every subtitle's sound is current."
    win.document.apply(edits.update_cue(win.project, "cue-1", text="second, changed"), "Edit subtitle")
    assert narration.counts(win.project) == {narration.READY: 1, narration.STALE: 1}
    assert "(1)" in panel.generate_stale.text()
    generate(panel, qt_app)
    assert [[i["id"] for i in items] for items in calls] == [["cue-1"]]  # only the changed one
    assert narration.counts(win.project) == {narration.READY: 2}
    assert len(win.project.audio) == 2  # its sound was replaced, not added


def test_a_text_spoken_before_is_reused_not_spoken_again(make, qt_app, monkeypatch) -> None:
    win, panel = make("same words", "same words")
    calls = []
    real = panel.client.speak
    monkeypatch.setattr(
        panel.client, "speak", lambda provider, items: calls.append(items) or real(provider, items)
    )
    generate(panel, qt_app)
    assert [len(items) for items in calls] == [1]  # two subtitles, one file
    assert len(win.project.audio) == 2
    assert win.project.audio[0].path == win.project.audio[1].path


def test_follow_speech_after_generating_lays_the_subtitles_end_to_end(make, qt_app) -> None:
    win, panel = make("first", "the second one")
    panel.follow_check.setChecked(True)
    panel.pause_spin.setValue(0.5)
    generate(panel, qt_app)
    cues = win.project.subtitles
    assert (cues[0].start, round(cues[0].end, 3)) == (0.0, round(5 * SECONDS_PER_CHAR, 3))
    assert round(cues[1].start, 3) == round(5 * SECONDS_PER_CHAR + 0.5, 3)
    assert [c.start for c in win.project.audio] == [cues[0].start, cues[1].start]


def test_follow_speech_now_and_fit_speech(make, qt_app) -> None:
    win, panel = make("first", "the second one")
    generate(panel, qt_app)
    assert win.project.subtitles[0].end == 2.0  # generating alone moves nothing
    panel.follow_speech()
    assert round(win.project.subtitles[0].end, 3) == round(5 * SECONDS_PER_CHAR, 3)
    panel.follow_speech()
    assert "already follow" in panel.status.text()

    # now squeeze the second subtitle: its speech (0.7 s) should fill a 0.5 s window -> faster
    short = win.project.subtitles[1]
    win.document.apply(edits.update_cue(win.project, short.id, end=short.start + 0.4), "Move subtitle")
    panel.fit_speech()
    assert win.project.subtitles[1].voice.rate == pytest.approx(1.25, abs=0.01)  # the limit
    assert "cannot fit" in panel.status.text()
    assert narration.state(win.project, win.project.subtitles[1]) == narration.STALE


def test_a_refused_text_fails_alone_and_the_rest_is_placed(make, qt_app) -> None:
    win, panel = make("fine", "FAIL please", "also fine")
    generate(panel, qt_app)
    assert [c.id for c in win.project.audio] == ["voice-cue-0", "voice-cue-2"]
    assert "1 failed: this text is refused" in panel.status.text()
    states = [narration.state(win.project, c) for c in win.project.subtitles]
    assert states == [narration.READY, narration.NEW, narration.READY]


def test_cancel_keeps_the_project_valid_and_places_what_finished(make, qt_app) -> None:
    win, panel = make("quick", "SLOW one", "never")
    before = win.project
    panel.generate("stale")
    assert panel.running
    assert panel.cancel_button.isVisibleTo(panel)
    panel.cancel()
    qt_app.processEvents()
    assert not panel.running
    assert not panel.cancel_button.isVisibleTo(panel)
    assert panel.status.text().startswith("Cancelled")
    Project.model_validate_json(win.project.model_dump_json())
    assert len(win.project.audio) <= 1
    assert win.project.subtitles[2].audio_id is None
    assert before.subtitles[2] == win.project.subtitles[2]


def test_generate_without_a_voice_uses_the_one_shown_and_says_so_when_there_is_none(make, qt_app) -> None:
    win, panel = make("hello", voice=None)
    panel.generate("stale")
    assert panel.status.text() == "Choose a voice first."
    panel.provider_combo.setCurrentIndex(panel.provider_combo.findData("fake"))
    panel.provider_combo.activated.emit(panel.provider_combo.currentIndex())
    settle(panel, qt_app)
    win.document.apply(edits.set_voice(win.project, None), "Choose voice")  # the project has none again
    generate(panel, qt_app)
    assert win.project.voice == FAKE  # taken from the panel
    assert len(win.project.audio) == 1


def test_an_online_provider_asks_once_before_any_text_leaves(make, qt_app, monkeypatch) -> None:
    _, panel = make("hello", voice=VoiceChoice(provider="edge", voice="en-US-AndrewNeural"))
    asked = []
    monkeypatch.setattr(panel.client, "speak", lambda provider, items: pytest.fail("text was sent"))
    panel.confirm_online = lambda label, count: asked.append((label, count)) or False
    panel.generate("stale")
    assert asked == [("Microsoft Edge neural (online)", 1)]
    assert panel.status.text() == "Cancelled: nothing was sent."
    assert not panel.consented("edge")
    panel.confirm_online = lambda label, count: True
    assert panel._allowed_online("edge", 1)
    assert panel.consented("edge")
    panel.confirm_online = lambda label, count: pytest.fail("asked twice")
    assert panel._allowed_online("edge", 3)


def test_an_online_service_is_not_contacted_just_by_showing_the_page(make, qt_app) -> None:
    _, panel = make("hello", voice=VoiceChoice(provider="edge", voice="en-US-AndrewNeural"))
    assert not panel.client.busy
    assert panel.voice_combo.currentData() == "en-US-AndrewNeural"  # the project's voice is shown anyway


def test_an_online_providers_voices_load_on_request_and_change_nothing(make, qt_app, monkeypatch) -> None:
    # The provider can run here, whether or not the optional edge-tts package is installed (without it the
    # panel says "not available" and offers no button).
    edge = plugins.voice_providers()["edge"]
    monkeypatch.setitem(plugins.VOICES, "edge", replace(edge, check=lambda: None))
    win, panel = make("hello", voice=VoiceChoice(provider="edge", voice="en-US-AndrewNeural"))
    asked = []
    monkeypatch.setattr(panel.client, "list_voices", lambda name: asked.append(name))
    panel.refresh()
    assert asked == []
    assert panel.load_button.isVisibleTo(panel)
    before = win.project
    panel.load_button.click()
    assert asked == ["edge"]
    panel._on_voices(
        "edge",
        {
            "ok": True,
            "voices": [
                {
                    "id": "en-US-AndrewNeural",
                    "name": "en-US-AndrewNeural",
                    "language": "en-US",
                    "gender": "male",
                },
                {"id": "en-US-AvaNeural", "name": "en-US-AvaNeural", "language": "en-US", "gender": "female"},
            ],
        },
    )
    assert panel.voice_combo.count() == 2
    assert panel.voice_combo.currentData() == "en-US-AndrewNeural"  # the project's voice stays chosen
    assert win.project == before
    assert not panel.load_button.isVisibleTo(panel)


def test_a_project_without_a_voice_starts_on_a_provider_that_needs_no_asking(make, qt_app) -> None:
    _, panel = make("hello", voice=None)
    assert panel.provider_combo.currentData() != "edge"  # an online service is never the first thing shown
    assert not panel.consented("edge")


def test_a_subtitle_can_have_its_own_voice(make, qt_app) -> None:
    win, panel = make("one", "two")
    settle(panel, qt_app)  # the voices are listed
    win.selection.set_subtitle("cue-1")
    qt_app.processEvents()
    assert panel.scope_check.isEnabled()
    panel.scope_check.setChecked(True)
    assert win.project.subtitles[1].voice == FAKE
    assert win.project.subtitles[0].voice is None
    panel.language_combo.setCurrentIndex(0)  # all languages: ben speaks en-GB
    panel.language_combo.activated.emit(0)
    panel.voice_combo.setCurrentIndex(panel.voice_combo.findData("ben"))
    panel.voice_combo.activated.emit(panel.voice_combo.currentIndex())
    assert win.project.subtitles[1].voice.voice == "ben"
    assert win.project.voice.voice == "anna"  # the project's did not change
    panel.scope_check.setChecked(False)
    assert win.project.subtitles[1].voice is None


def test_the_subtitles_table_shows_voice_and_speech(make, qt_app) -> None:
    win, panel = make("first", "second")
    page = win.pages.pages["audio"]
    model = page.cues_model
    cells = lambda: [[model.data(model.index(r, c)) for c in (3, 4)] for r in range(model.rowCount())]  # noqa: E731
    assert cells() == [["anna", "not generated"], ["anna", "not generated"]]
    generate(panel, qt_app)
    assert cells()[0][1].startswith("ready, ")
    win.document.apply(edits.update_cue(win.project, "cue-0", text="changed"), "Edit subtitle")
    assert cells()[0][1] == "stale"


def test_deleting_a_subtitle_takes_its_sound_with_it(make, qt_app) -> None:
    win, panel = make("first", "second")
    generate(panel, qt_app)
    win.selection.set_subtitle("cue-0")
    win.pages.pages["audio"].delete_cue()
    assert [c.id for c in win.project.subtitles] == ["cue-1"]
    assert [c.id for c in win.project.audio] == ["voice-cue-1"]
    win.document.undo_stack.undo()
    assert len(win.project.audio) == 2


def test_the_script_is_exported_as_text(make, qt_app, tmp_path, monkeypatch) -> None:
    _, panel = make("first words", "second words")
    target = tmp_path / "script.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    panel.export_script()
    assert target.read_text(encoding="utf-8") == "[0:00.0] first words\n\n[0:04.0] second words\n"


def test_the_pronunciation_dialog_edits_pairs(qt_app) -> None:
    dialog = PronunciationDialog({"F": "force"})
    dialog._add("dp/dt", "d p by d t")
    dialog._add("", "ignored")
    assert dialog.entries() == {"F": "force", "dp/dt": "d p by d t", "": "ignored"}  # blanks go in the edit
    dialog.table.setCurrentCell(0, 0)
    dialog._remove()
    assert dialog.entries() == {"dp/dt": "d p by d t", "": "ignored"}


# -- the Lumen layout (P17.6): engine cards, speed slider, cue rows, pronunciation chips --------------------


def test_engines_are_cards_and_pressing_one_chooses_it(make, qt_app) -> None:
    win, panel = make("hello", voice=None)
    assert set(panel.engines.cards) == {
        panel.provider_combo.itemData(i) for i in range(panel.provider_combo.count())
    }
    chosen = panel.provider_combo.currentData()
    assert [n for n, card in panel.engines.cards.items() if card.property("selected")] == [chosen]
    other = next(n for n in panel.engines.cards if n != chosen)
    panel.engines.cards[other].pressed.emit()  # a card was pressed
    settle(panel, qt_app)
    assert panel.provider_combo.currentData() == other
    assert [n for n, card in panel.engines.cards.items() if card.property("selected")] == [other]
    assert win.project.voice is None or win.project.voice.provider == other
    assert "Offline" in panel.engines.describe(plugins.voice_providers()["fake"])
    assert "sends the text" in panel.engines.describe(plugins.voice_providers()["edge"])


def test_the_speed_slider_and_the_box_show_one_value(make, qt_app) -> None:
    win, panel = make("hello")
    assert panel.rate_slider.value() == 100
    panel.rate_spin.setValue(1.25)
    assert panel.rate_slider.value() == 125
    count = win.document.undo_stack.count()
    panel.rate_slider.setValue(150)  # a key or a click on the groove: chosen at once
    assert panel.rate_spin.value() == 1.5 and win.project.voice.rate == 1.5
    assert win.document.undo_stack.count() == count + 1
    panel.rate_slider.setSliderDown(True)  # a drag: nothing is chosen until it ends
    panel.rate_slider.setValue(80)
    assert panel.rate_spin.value() == 0.8 and win.project.voice.rate == 1.5
    panel.rate_slider.setSliderDown(False)
    panel.rate_slider.sliderReleased.emit()
    assert win.project.voice.rate == 0.8


def test_cues_are_rows_with_their_state_and_a_press_selects_the_cue(make, qt_app) -> None:
    win, panel = make("first", "second", "third")
    cue_list = panel.cue_list
    assert list(cue_list.rows) == ["cue-0", "cue-1", "cue-2"] and cue_list.empty.isHidden()
    words = lambda: [row.findChild(Chip).text() for row in cue_list.rows.values()]  # noqa: E731
    assert words() == ["no sound"] * 3
    generate(panel, qt_app)
    assert words() == ["ready"] * 3
    win.document.apply(edits.update_cue(win.project, "cue-1", text="second, changed"), "Edit subtitle")
    panel.refresh()
    assert words() == ["ready", "stale", "ready"]  # stale says so in words, not only in its outline
    assert (
        cue_list.rows["cue-1"].property("stale") is True and cue_list.rows["cue-0"].property("stale") is False
    )
    got = []
    panel.cueChosen.connect(got.append)
    cue_list.rows["cue-2"].pressed.emit()
    assert win.selection.subtitle_id == "cue-2" and got == ["cue-2"]
    panel.refresh()
    assert (
        cue_list.rows["cue-2"].property("current") is True
        and cue_list.rows["cue-0"].property("current") is False
    )


def test_the_cue_list_says_when_there_are_no_subtitles(make, qt_app) -> None:
    _, panel = make()
    assert panel.cue_list.rows == {} and not panel.cue_list.empty.isHidden()


def test_pronunciations_are_chips_and_plus_word_opens_the_editor(make, qt_app, monkeypatch) -> None:
    win, panel = make("hello")
    assert panel._words_host.isHidden() and not panel._words_empty.isHidden()
    win.document.apply(edits.set_pronunciations(win.project, {"π": "pie", "θ": "theta"}), "Pronunciation")
    panel.refresh()
    assert [c.text() for c in panel._words_host.findChildren(Chip)] == ["π → pie", "θ → theta"]
    assert panel._words_empty.isHidden() and panel.pronunciation_button.text() == "+ Word"
    opened = []
    monkeypatch.setattr(PronunciationDialog, "exec", lambda self: opened.append(self.entries()) or 0)
    panel.pronunciation_button.click()
    assert opened == [{"π": "pie", "θ": "theta"}]
