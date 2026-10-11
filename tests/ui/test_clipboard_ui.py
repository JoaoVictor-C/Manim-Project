"""Cut, copy, paste and duplicate in the editor (P5d.2, ADR 0038): the Edit menu and its
shortcuts, the system clipboard, what is selected afterwards, one undo step each, and the
messages when something cannot be pasted."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtTest import QTest

from manim_studio.core import adapter, clipboard
from manim_studio.core.schema import AudioClip, Canvas, Clip, Cue, Layer, Project, Spec, Transform2D
from manim_studio.ui.main_window import MainWindow
from ui.test_acceptance_v1 import menu_action

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=320, height_px=180, fps=10, duration=4.0)
CIRCLE = Spec(type="Circle", params={"radius": 0.5})
SQUARE = Spec(type="Square", params={"side_length": 1.0})


def scene() -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(id="sq", name="Square", spec=SQUARE, base=Transform2D(position=(2.0, 0.0))),
            Layer(
                id="c",
                name="Circle",
                spec=CIRCLE,
                clips=[Clip(id="in", kind="FadeIn", start=0.0, duration=0.5)],
            ),
            Layer(
                id="link", name="Link", spec=Spec(type="Connector", params={"source": "c", "target": "sq"})
            ),
        ],
        audio=[AudioClip(id="audio-1", name="pop", path="C:/nowhere/pop.wav", start=0.5, duration=1.0)],
        subtitles=[Cue(id="cue-1", start=0.0, end=1.0, text="Hello")],
    )


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "scene.json"
    path.write_text(scene().model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    win.load(path)
    yield win
    win.close()


def trigger(window, name: str) -> None:
    menu_action(window.menuBar(), "Edit", name).trigger()


def status(window) -> str:
    return window.statusBar().currentMessage()


def steps(window) -> int:
    return window.document.undo_stack.count()


def test_the_edit_menu_has_cut_copy_paste_and_duplicate(window) -> None:
    keys = {
        "Cut": QKeySequence(QKeySequence.StandardKey.Cut),
        "Copy": QKeySequence(QKeySequence.StandardKey.Copy),
        "Paste": QKeySequence(QKeySequence.StandardKey.Paste),
        "Duplicate": QKeySequence("Ctrl+D"),
    }
    for name, key in keys.items():
        assert menu_action(window.menuBar(), "Edit", name).shortcut() == key


def test_duplicate_a_layer_selects_the_copy_in_one_undo_step(window) -> None:
    window.selection.set("c")
    before = steps(window)
    trigger(window, "Duplicate")
    copy = window.project.layers[2]
    assert (copy.id, copy.name, copy.clips[0].kind) == ("circle-1", "Circle copy", "FadeIn")
    assert window.selection.layer_id == "circle-1" and window.layers.selected_id() == "circle-1"
    assert steps(window) == before + 1 and status(window) == "Duplicated Circle copy"
    window.document.undo_stack.undo()
    assert [x.id for x in window.project.layers] == ["sq", "c", "link"]


def test_copy_and_paste_a_layer_through_the_system_clipboard(window) -> None:
    window.selection.set("link")
    trigger(window, "Copy")
    assert status(window) == "Copied Link"
    mime = QGuiApplication.clipboard().mimeData()
    assert mime.hasFormat(clipboard.MIME_TYPE)
    data = json.loads(bytes(mime.data(clipboard.MIME_TYPE).data()))
    assert (data["kind"], data["payload"]["layers"][0]["id"]) == ("layers", "link")
    assert json.loads(mime.text()) == data  # plain text too: another instance can paste it
    window.selection.set("sq")
    before = steps(window)
    trigger(window, "Paste")
    ids = [x.id for x in window.project.layers]
    assert ids == ["sq", "connector-1", "c", "link"]  # right above the selected layer
    assert window.selection.layer_id == "connector-1" and steps(window) == before + 1
    pasted = window.project.layer("connector-1").spec.params
    assert (pasted["source"], pasted["target"]) == ("c", "sq")


def test_paste_reads_plain_text_from_another_instance(window) -> None:
    text = clipboard.to_json(clipboard.copy_layers(scene(), ["c"]))
    QGuiApplication.clipboard().setText(text)
    window.selection.clear()
    trigger(window, "Paste")
    assert window.project.layers[-1].id == "circle-1" and window.selection.layer_id == "circle-1"


def test_cut_removes_the_layer_and_paste_brings_it_back(window) -> None:
    window.selection.set("c")
    before = steps(window)
    trigger(window, "Cut")
    assert [x.id for x in window.project.layers] == ["sq"]  # its connector goes with it
    assert steps(window) == before + 1 and status(window) == "Cut Circle"
    trigger(window, "Paste")
    (copy,) = [x for x in window.project.layers if x.id != "sq"]
    assert (copy.name, copy.spec) == ("Circle", CIRCLE)  # the name is free again
    window.document.undo_stack.undo()
    window.document.undo_stack.undo()
    assert [x.id for x in window.project.layers] == ["sq", "c", "link"]


def test_a_clip_pastes_on_the_selected_layer_at_the_playhead(window) -> None:
    window.selection.set("c", "in")
    trigger(window, "Copy")
    assert status(window) == "Copied FadeIn clip"
    window.selection.set("sq")
    window.seek(1.0)
    trigger(window, "Paste")
    (clip,) = window.project.layer("sq").clips
    assert (clip.kind, clip.start, clip.duration) == ("FadeIn", 1.0, 0.5)
    assert (window.selection.layer_id, window.selection.clip_id) == ("sq", clip.id)
    assert window.timeline.selected == ("sq", clip.id)
    window.seek(1.2)
    trigger(window, "Paste")  # on the clip just pasted
    assert "No room" in status(window) and len(window.project.layer("sq").clips) == 1
    window.selection.set("link")
    trigger(window, "Paste")
    assert status(window) == "A FadeIn clip cannot go on Link"
    window.selection.set_audio("audio-1")
    trigger(window, "Paste")
    assert status(window) == "Select the layer to paste the clip on"


def test_duplicate_a_clip_sound_and_subtitle(window) -> None:
    window.selection.set("c", "in")
    trigger(window, "Duplicate")
    starts = [c.start for c in window.project.layer("c").clips]
    assert starts == [0.0, 0.5] and window.selection.clip_id == "fadein-1"
    window.selection.set_audio("audio-1")
    trigger(window, "Duplicate")
    assert [a.start for a in window.project.audio] == [0.5, 1.5]
    assert window.selection.audio_id == "audio-2" and status(window) == "Duplicated sound"
    window.selection.set_subtitle("cue-1")
    trigger(window, "Duplicate")
    assert [(c.start, c.text) for c in window.project.subtitles] == [(0.0, "Hello"), (1.0, "Hello")]
    assert window.selection.subtitle_id == window.project.subtitles[1].id
    window.selection.set_subtitle("cue-1")
    trigger(window, "Duplicate")
    assert "No room" in status(window) and len(window.project.subtitles) == 2


def test_a_sound_and_a_subtitle_paste_at_the_playhead(window) -> None:
    window.selection.set_audio("audio-1")
    trigger(window, "Copy")
    window.seek(2.0)
    trigger(window, "Paste")
    sound = window.project.audio[-1]
    assert (sound.id, sound.start, sound.path) == ("audio-2", 2.0, "C:/nowhere/pop.wav")
    assert window.selection.audio_id == "audio-2" and status(window) == "Pasted sound"
    window.selection.set_subtitle("cue-1")
    trigger(window, "Copy")
    trigger(window, "Paste")
    cue = next(c for c in window.project.subtitles if c.id == window.selection.subtitle_id)
    assert (cue.start, cue.end, cue.text) == (2.0, 3.0, "Hello")
    window.seek(0.5)
    trigger(window, "Paste")
    assert "No room for the subtitle" in status(window)


def test_cutting_a_clip_a_sound_or_a_subtitle(window) -> None:
    for select, gone in (
        (lambda: window.selection.set("c", "in"), lambda: window.project.layer("c").clips == []),
        (lambda: window.selection.set_audio("audio-1"), lambda: window.project.audio == []),
        (lambda: window.selection.set_subtitle("cue-1"), lambda: window.project.subtitles == []),
    ):
        select()
        trigger(window, "Cut")
        assert gone()


def test_messages_without_a_selection_or_a_clipboard(window) -> None:
    window.selection.clear()
    trigger(window, "Copy")
    assert status(window) == "Select a layer, clip, sound or subtitle first"
    trigger(window, "Duplicate")
    assert status(window) == "Select a layer, clip, sound or subtitle to duplicate"
    trigger(window, "Cut")
    assert status(window) == "Select a layer, clip, sound or subtitle first"
    QGuiApplication.clipboard().setText("just some words")
    before = window.project
    trigger(window, "Paste")
    assert status(window) == clipboard.NOTHING and window.project is before
    QGuiApplication.clipboard().clear()
    trigger(window, "Paste")
    assert status(window) == clipboard.NOTHING


def test_left_out_references_are_reported(window) -> None:
    other = Project(canvas=CANVAS, layers=[Layer(id="a", spec=SQUARE), Layer(id="b", spec=CIRCLE)])
    link = Layer(id="j", name="Joint", spec=Spec(type="Connector", params={"source": "a", "target": "b"}))
    text = clipboard.to_json(
        clipboard.copy_layers(other.model_copy(update={"layers": [*other.layers, link]}), ["j"])
    )
    QGuiApplication.clipboard().setText(text)
    trigger(window, "Paste")
    assert status(window).startswith("Joint was not pasted") and len(window.project.layers) == 3


def test_without_a_project_nothing_happens(qt_app) -> None:
    win = MainWindow()
    try:
        for name in ("Cut", "Copy", "Paste", "Duplicate"):
            trigger(win, name)
            assert status(win) == "Create or open a project first."
    finally:
        win.close()


def test_pasted_code_is_not_trusted(window) -> None:
    code = adapter.default_spec("Code").params["code"] + "\n# pasted from somewhere else\n"
    project = Project(canvas=CANVAS, layers=[Layer(id="k", spec=Spec(type="Code", params={"code": code}))])
    QGuiApplication.clipboard().setText(clipboard.to_json(clipboard.copy_layers(project, ["k"])))
    trigger(window, "Paste")
    assert window.trust.untrusted(window.project) == ["code-1"]


def test_shortcuts_work_from_the_timeline_and_text_fields_keep_theirs(window, qt_app) -> None:
    window.activateWindow()
    window.selection.set("c")
    window.timeline.setFocus()
    qt_app.processEvents()
    QTest.keyClick(window.timeline, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert window.project.layers[2].id == "circle-1"
    window.selection.set("sq")
    field = window.properties.fields["name"].widget
    field.setFocus()
    field.selectAll()
    qt_app.processEvents()
    QTest.keyClick(field, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QGuiApplication.clipboard().text() == "Square"  # the field's text, not the layer


@pytest.mark.latex
def test_a_part_cannot_be_copied_or_duplicated(qt_app, tmp_path) -> None:
    project = Project(
        canvas=CANVAS,
        layers=[
            Layer(id="eq", spec=Spec(type="MathTex", params={"text": "a+b"})),
            Layer(id="p", name="b", parent_id="eq", part={"tex": "b"}),
        ],
    )
    path = tmp_path / "eq.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.load(path)
    try:
        win.selection.set("p")
        for name in ("Copy", "Duplicate", "Cut"):
            trigger(win, name)
            assert "part of its equation" in status(win)
        assert len(win.project.layers) == 2
        win.selection.set("eq")
        trigger(win, "Duplicate")
        assert [x.parent_id for x in win.project.layers] == [None, "eq", None, "mathtex-1"]
    finally:
        win.close()
