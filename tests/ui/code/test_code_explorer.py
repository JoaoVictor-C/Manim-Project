"""The Code workspace's explorer tree (P12.5): sections and rows, filtering, signals, dragging."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtTest import QTest

from manim_studio.ui.code.code_explorer import CodeExplorer, Row, Section
from manim_studio.ui.session import code_drag

pytestmark = pytest.mark.ui


def sections() -> list[Section]:
    return [
        Section(
            "project",
            "This project",
            (
                Row("orbit", "Orbit", "scene", "layer", dirty=True),
                Row("tri", "Triangle", "object", "layer", state="error"),
            ),
            empty="Nothing yet",
        ),
        Section("builtin", "Built in", (Row("builtin:matrix", "Matrix", "object", "preset"),)),
        Section("mine", "Mine", (), empty="Import presets to see them here"),
    ]


@pytest.fixture
def tree(qt_app):
    widget = CodeExplorer()
    widget.set_sections(sections())
    return widget


def test_sections_and_rows_are_listed_in_order(tree) -> None:
    assert tree.rows() == [
        ("project", "layer", "orbit"),
        ("project", "layer", "tri"),
        ("builtin", "preset", "builtin:matrix"),
    ]
    assert tree.topLevelItemCount() == 3
    assert tree.topLevelItem(2).child(0).text(0) == "Import presets to see them here"  # the empty note


def test_dirty_and_error_rows_are_marked(tree) -> None:
    assert "\u25cf" in tree.topLevelItem(0).child(0).text(0)
    assert tree.topLevelItem(0).child(1).text(0).endswith("!")


def test_filter_keeps_matches_only_and_clearing_restores(tree) -> None:
    tree.set_filter("tria")
    assert tree.rows() == [("project", "layer", "tri")]
    tree.set_filter("zzz")
    assert tree.rows() == []
    tree.set_filter("")
    assert len(tree.rows()) == 3


def test_the_current_row_survives_a_refresh(tree) -> None:
    assert tree.select("layer", "tri")
    tree.set_sections(sections())
    assert tree.current() == ("layer", "tri")
    assert not tree.select("layer", "gone")


def test_choosing_and_opening_emit(tree) -> None:
    chosen, opened = [], []
    tree.chosen.connect(lambda s, k: chosen.append((s, k)))
    tree.opened.connect(lambda s, k: opened.append((s, k)))
    tree.select("preset", "builtin:matrix")
    assert chosen == [("preset", "builtin:matrix")]
    tree._on_activated(tree.topLevelItem(1).child(0))
    assert opened == [("preset", "builtin:matrix")]


def test_a_section_header_is_not_a_row(tree) -> None:
    tree.setCurrentItem(tree.topLevelItem(0))
    assert tree.current() is None
    header = tree.topLevelItem(0)
    expanded = header.isExpanded()
    tree._on_activated(header)
    assert header.isExpanded() is (not expanded)


def test_collapsed_sections_stay_collapsed_after_a_refresh(tree) -> None:
    tree.topLevelItem(1).setExpanded(False)
    tree.set_sections(sections())
    assert not tree.topLevelItem(1).isExpanded() and tree.topLevelItem(0).isExpanded()


def test_menu_request_names_the_row(tree) -> None:
    seen = []
    tree.menuRequested.connect(lambda s, k, p: seen.append((s, k)))
    tree.select("layer", "orbit")
    item = tree.topLevelItem(0).child(0)
    tree.setCurrentItem(item)
    pos = tree.visualItemRect(item).center()
    tree._on_menu(pos)
    assert seen == [("layer", "orbit")]


def test_a_row_drags_out_as_a_code_payload(tree, monkeypatch) -> None:
    captured = {}

    class FakeDrag:
        def __init__(self, _source) -> None: ...
        def setMimeData(self, mime: QMimeData) -> None:  # noqa: N802
            captured["mime"] = mime

        def exec(self, *_args):
            return Qt.DropAction.CopyAction

    monkeypatch.setattr("manim_studio.ui.code.code_explorer.QDrag", FakeDrag)
    tree.select("layer", "orbit")
    tree.startDrag(Qt.DropAction.CopyAction)
    assert code_drag.decode(captured["mime"]) == {
        "from": "layer",
        "id": "orbit",
        "name": "Orbit",
        "kind": "scene",
    }
    captured.clear()
    tree.setCurrentItem(tree.topLevelItem(0))  # a header: nothing to drag
    tree.startDrag(Qt.DropAction.CopyAction)
    assert captured == {}


def test_folders_fold_retain_state_and_accept_layer_drops(tree, qt_app) -> None:
    grouped = Section(
        "project",
        "This project",
        (
            Row("orbit", "Orbit", "scene", "layer", folder="Scenes"),
            Row("tri", "Triangle", "object", "layer"),
        ),
        folders=("Scenes", "Empty"),
    )
    tree.set_sections([grouped])
    project = tree.topLevelItem(0)
    scenes = project.child(1)
    assert scenes.text(0) == "Scenes" and scenes.isExpanded()
    assert scenes.child(0).text(0) == "Orbit"
    assert project.child(2).child(0).text(0) == "Empty folder"

    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(scenes).center())
    assert not scenes.isExpanded()
    tree.set_sections([grouped])
    scenes = tree.topLevelItem(0).child(1)
    assert not scenes.isExpanded()
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(scenes).center())
    assert scenes.isExpanded()

    target = tree.visualItemRect(scenes).center()
    assert tree._drop_target_at(target) == (scenes, "Scenes")
    events = []
    tree.layerDropped.connect(lambda layer_id, folder: events.append((layer_id, folder)))
    mime = code_drag.encode("layer", "tri", "Triangle", "object")

    class Drop:
        def mimeData(self):  # noqa: N802 - Qt event protocol
            return mime

        def position(self):
            return QPointF(target)

        def setDropAction(self, _action):  # noqa: N802 - Qt event protocol
            pass

        def accept(self):
            pass

        def ignore(self):
            raise AssertionError("a drop on a folder must be accepted")

    tree.dropEvent(Drop())
    qt_app.processEvents()
    assert events == [("tri", "Scenes")]
