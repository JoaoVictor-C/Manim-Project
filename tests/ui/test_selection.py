"""The shared selection (S3.3, ADR 0016): every view follows a choice made in any other."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from manim_studio.core import edits
from manim_studio.core.schema import Clip, Layer, Project, Spec
from manim_studio.ui.document import Document
from manim_studio.ui.main_window import MainWindow
from manim_studio.ui.selection import Selection
from support import CANVAS

pytestmark = pytest.mark.ui

DEMO = Path(__file__).resolve().parents[2] / "examples" / "euler.json"


def project() -> Project:
    return Project(
        canvas=CANVAS,
        layers=[
            Layer(
                id="a", spec=Spec(type="Square"), clips=[Clip(id="c", kind="FadeIn", start=0, duration=0.5)]
            ),
            Layer(id="b", spec=Spec(type="Circle")),
        ],
    )


# -- the object --------------------------------------------------------------------


@pytest.fixture
def selection(qt_app):
    sel = Selection(Document(project()))
    sel.events = []
    sel.changed.connect(lambda: sel.events.append((sel.layer_id, sel.clip_id)))
    return sel


def test_set_emits_only_on_change(selection) -> None:
    selection.set("a", "c")
    selection.set("a", "c")
    selection.set("b")
    assert selection.events == [("a", "c"), ("b", None)]


def test_selecting_the_same_layer_keeps_its_clip(selection) -> None:
    selection.set("a", "c")
    selection.select_layer("a")
    assert (selection.layer_id, selection.clip_id) == ("a", "c")
    selection.select_layer("b")
    assert (selection.layer_id, selection.clip_id) == ("b", None)
    selection.select_layer("")
    assert selection.layer_id is None


def test_deleted_things_drop_out(selection) -> None:
    doc = selection.document
    selection.set("a", "c")
    doc.apply(edits.remove_clip(doc.project, "a", "c"), "Delete clip")
    assert (selection.layer_id, selection.clip_id) == ("a", None)
    doc.apply(edits.remove_layer(doc.project, "a"), "Delete layer")
    assert selection.layer_id is None
    selection.set("b")
    doc.replace(project())
    assert selection.layer_id is None


# -- every view follows ------------------------------------------------------------


@pytest.fixture
def window(qt_app, tmp_path):
    path = tmp_path / "euler.json"
    path.write_text(DEMO.read_text(encoding="utf-8"), encoding="utf-8")
    win = MainWindow()
    win.show()
    win.load(path)
    yield win
    win.close()


def views(window) -> tuple:
    return (
        window.layers.selected_id(),
        window.timeline.selected,
        (window.properties.layer_id, window.properties.clip_id),
    )


def test_a_layer_chosen_in_the_list_reaches_every_view(window) -> None:
    first = window.project.layers[0].id
    window.layers.select(first)
    assert (window.selection.layer_id, window.selection.clip_id) == (first, None)
    assert views(window) == (first, None, (first, None))


def test_a_clip_chosen_in_the_timeline_reaches_every_view(window) -> None:
    layer = window.project.layers[1]
    clip = layer.clips[0]
    window.timeline.clipSelected.emit(layer.id, clip.id)
    assert views(window) == (layer.id, (layer.id, clip.id), (layer.id, clip.id))


def test_the_selection_drives_every_view(window) -> None:
    layer = window.project.layers[1]
    window.selection.set(layer.id, layer.clips[0].id)
    assert views(window) == (layer.id, (layer.id, layer.clips[0].id), (layer.id, layer.clips[0].id))
    window.selection.clear()
    assert views(window) == (None, None, (None, None))


def test_deleting_the_selected_clip_falls_back_to_its_layer(window) -> None:
    layer = window.project.layers[1]
    window.selection.set(layer.id, layer.clips[0].id)
    window.timeline.delete_clip(layer.id, layer.clips[0].id)
    assert views(window) == (layer.id, None, (layer.id, None))


def test_adding_a_layer_selects_it_everywhere(window) -> None:
    window.layers.add_object("Dot")
    new_id = window.project.layers[-1].id
    assert views(window) == (new_id, None, (new_id, None))


def test_a_key_selection_falls_back_to_its_layer_when_the_keys_go(selection) -> None:
    doc = selection.document
    doc.apply(edits.set_key(doc.project, "b", "rotation", 0.2, 30.0), "Key")
    selection.set_key("b", 0.2)
    assert (selection.layer_id, selection.clip_id, selection.key_time) == ("b", None, 0.2)
    selection.set("b", None, 0.2)
    assert len(selection.events) == 1  # unchanged
    doc.apply(edits.remove_keys(doc.project, "b", 0.2), "Delete keys")
    assert (selection.layer_id, selection.key_time) == ("b", None)
