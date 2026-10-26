"""The Code page's chapter commands (ADR 0061): Analyse, Split with its proof and undo, Move selection.

The render service is replaced by what it would leave behind: finished renders in the cache and a status.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shutil
import time

import numpy as np
import pytest

pytest.importorskip("PySide6")

from tests.core.code.test_scene_analysis import PHASE_ROWS, probes
from tests.core.code.test_scene_split import SCENE

from manim_studio.core.model.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.services.code_render import CodeStatus
from ui.code.code_page_helpers import choose

pytestmark = pytest.mark.ui

CANVAS = Canvas(width_px=32, height_px=18, fps=10, duration=8.0)


def picture(seed: int) -> np.ndarray:
    frame = np.zeros((18, 32, 4), dtype=np.uint8)
    frame[3:9, 4:20] = np.random.default_rng(seed).integers(1, 255, (6, 16, 4), dtype=np.uint8)
    return frame


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=CANVAS,
        layers=[Layer(id="scene", name="Orbit", spec=Spec(type="Code", params={"code": SCENE}))],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.ask_trust = lambda names: "skip"
    win.resize(1500, 850)
    win.show()
    win.load(path)
    win.show_page("code")
    qt_app.processEvents()
    yield win
    win.document.undo_stack.setClean()
    win.close()


def page(window):
    return window.pages.pages["code"]


def fresh_writer(window, layer):
    """A writer for the layer's key; what an earlier test left under it (the cache is shared) goes first."""
    cache = window.code.cache
    key = window.evaluator.code_key(layer)
    shutil.rmtree(cache.root / key, ignore_errors=True)
    cache._open.pop(key, None)
    return cache.writer(key, 32, 18, 10, workers=0)


def render_whole(window) -> list[np.ndarray]:
    """What the service would have left for the layer: 60 frames, with the probes of a phased scene."""
    frames = [picture(i // 5) for i in range(60)]  # 12 distinct pictures, five frames each
    layer = window.project.layer("scene")
    writer = fresh_writer(window, layer)
    writer.probes.extend(probes(PHASE_ROWS))
    for frame in frames:
        writer.add(frame)
    writer.finish()
    return frames


def render_chapters(window, frames: list[np.ndarray], damage: int | None = None) -> None:
    project = window.project
    chapters = [x for x in project.layers if x.id != "scene"]
    for layer in chapters:
        start = int(layer.spec.params.get("start_frame", 0) or 0)
        end = start + 20 if start < 40 else 60
        mine = list(frames[start:end])
        if damage is not None and start <= damage < end:
            mine[damage - start] = picture(999)
        writer = fresh_writer(window, layer)
        for frame in mine:
            writer.add(frame)
        writer.finish()
    window.code.status = lambda layer_id: CodeStatus("ready", frames=20)
    for layer in chapters:
        window.code.statusChanged.emit(layer.id)


def wait_for(qt_app, condition, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        qt_app.processEvents()
        time.sleep(0.01)


def test_analyse_asks_for_a_render_first_then_reports(window, qt_app) -> None:
    code = page(window)
    choose(code, 0)
    cache = window.code.cache
    key = window.evaluator.code_key(window.project.layer("scene"))
    shutil.rmtree(cache.root / key, ignore_errors=True)  # an earlier test may have left a render
    cache._open.pop(key, None)
    assert code.chapter_actions.analyse() is None
    assert "Render the scene first" in window.statusBar().currentMessage()
    render_whole(window)
    dialog = code.chapter_actions.analyse()
    assert dialog is not None and dialog.split_button.isEnabled()
    text = dialog.report.toPlainText()
    assert "3 chapters" in text and "Editing one chapter re-renders at most 33%" in text
    dialog.close()


def test_a_split_that_matches_is_kept_and_says_so(window, qt_app) -> None:
    code = page(window)
    choose(code, 0)
    frames = render_whole(window)
    assert code.chapter_actions.split()
    layers = window.project.layers
    assert [x.name for x in layers] == ["Orbit - chapter 1", "Orbit - chapter 2", "Orbit - chapter 3"]
    assert [x.spec.params.get("start_frame", 0) for x in layers] == [0, 20, 40]
    render_chapters(window, frames)
    verifier = code.chapter_actions.verifier
    wait_for(qt_app, lambda: verifier.verdict is not None)
    assert verifier.verdict.ok
    assert "verified" in window.statusBar().currentMessage()
    assert len(window.project.layers) == 3  # kept
    window.document.undo_stack.undo()  # and it is one undo step
    assert [x.id for x in window.project.layers] == ["scene"]


def test_a_split_that_draws_differently_is_undone_and_says_where(window, qt_app) -> None:
    code = page(window)
    choose(code, 0)
    frames = render_whole(window)
    assert code.chapter_actions.split()
    render_chapters(window, frames, damage=27)
    verifier = code.chapter_actions.verifier
    wait_for(qt_app, lambda: verifier.verdict is not None)
    assert not verifier.verdict.ok and verifier.verdict.first_bad == 27
    assert [x.id for x in window.project.layers] == ["scene"]  # put back
    assert (
        "undone" in window.statusBar().currentMessage() and "frame 27" in window.statusBar().currentMessage()
    )


def test_a_chapter_that_fails_to_render_undoes_the_split(window, qt_app) -> None:
    code = page(window)
    choose(code, 0)
    render_whole(window)
    assert code.chapter_actions.split()
    window.code.status = lambda layer_id: CodeStatus("error", error="NameError: x")
    window.code.statusChanged.emit(window.project.layers[1].id)
    verifier = code.chapter_actions.verifier
    wait_for(qt_app, lambda: verifier.verdict is not None)
    assert not verifier.verdict.ok and "did not render" in verifier.verdict.message
    assert [x.id for x in window.project.layers] == ["scene"]


def test_move_selection_gives_the_statements_a_layer_of_their_own(window, qt_app) -> None:
    code = page(window)
    choose(code, 0)
    editor = code.editor
    lines = SCENE.splitlines()
    first = next(i for i, line in enumerate(lines) if "b = Square()" in line)
    cursor = editor.textCursor()
    block = editor.document().findBlockByNumber(first)
    cursor.setPosition(block.position())
    last = editor.document().findBlockByNumber(first + 2)
    cursor.setPosition(last.position() + last.length() - 1, cursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    assert code.chapter_actions.move_selection()
    layers = window.project.layers
    assert [x.name for x in layers] == ["Orbit", "Orbit (moved)"]
    assert "Square()" in layers[1].spec.params["code"] and "Square()" not in layers[0].spec.params["code"]
    window.document.undo_stack.undo()
    assert [x.id for x in window.project.layers] == ["scene"]


def test_move_selection_wants_a_selection(window, qt_app) -> None:
    code = page(window)
    choose(code, 0)
    assert not code.chapter_actions.move_selection()
    assert "Select the statements" in window.statusBar().currentMessage()


def test_the_editor_menu_has_the_three_commands(window) -> None:
    code = page(window)
    assert [a.text() for a in (code.analyse_action, code.split_action, code.move_action)] == [
        "Analyse scene…",
        "Split into chapters…",
        "Move selection to a new layer",
    ]
