"""Bringing code into the project (P12): files through the import window's answer, presets, drops."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from manim_studio.core import code_import as ci
from manim_studio.core.code_import import ImportChoice, ImportItem
from manim_studio.core.schema import Canvas, Layer, Project, Spec
from manim_studio.ui.main_window import MainWindow

pytestmark = pytest.mark.ui

SCENE = "from manim import *\n\nclass Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"
TWO = SCENE + "\nclass Spin(Scene):\n    def construct(self):\n        self.add(Square())\n"
OBJECT = "PARAMS = {}\n\ndef build(p):\n    return Circle()\n"


@pytest.fixture
def window(qt_app, tmp_path):
    project = Project(
        canvas=Canvas(width_px=320, height_px=180, fps=10, duration=6.0),
        layers=[Layer(id="dot", spec=Spec(type="Circle"))],
    )
    path = tmp_path / "scene.json"
    path.write_text(project.model_dump_json(by_alias=True), encoding="utf-8")
    win = MainWindow()
    win.ask_trust = lambda names: "skip"
    win.resize(1500, 850)
    win.show()
    win.load(path)
    qt_app.processEvents()
    yield win
    win.close()


def drain(qt_app) -> None:
    for _ in range(20):
        qt_app.processEvents()


def answer(window, build):
    """Make the import window's answer ``build(items)``."""
    window.importer.ask = lambda items, at, position, **kw: build(items)


def test_an_object_choice_adds_a_python_layer_at_the_chosen_place_and_time(window, qt_app, tmp_path) -> None:
    file = tmp_path / "Wheel.py"
    file.write_bytes(("﻿" + OBJECT).encode("utf-8"))
    answer(
        window, lambda items: [ImportChoice(items[0], "Wheel", ci.OBJECT, appear=2.0, position=(1.5, -1.0))]
    )
    window.import_code_files([file])
    drain(qt_app)
    layer = window.project.layers[-1]
    assert (layer.spec.type, layer.name) == ("Python", "Wheel") and layer.spec.params["code"] == OBJECT
    assert layer.base.position == (1.5, -1.0) and layer.lifetime.in_ == 2.0
    assert window.selection.layer_id == layer.id
    assert "Added 1 layer" in window.statusBar().currentMessage()


def test_several_scenes_become_several_layers_in_one_undo_step(window, qt_app, tmp_path) -> None:
    file = tmp_path / "pair.py"
    file.write_text(TWO, encoding="utf-8")
    answer(window, lambda items: [ImportChoice(items[0], "Pair", ci.SCENE, scenes=("Orbit", "Spin"))])
    before = window.document.undo_stack.count()
    window.import_code_files([file])
    drain(qt_app)
    added = window.project.layers[1:]
    assert [(x.spec.type, x.name) for x in added] == [("Code", "Pair - Orbit"), ("Code", "Pair - Spin")]
    assert window.document.undo_stack.count() == before + 1
    window.document.undo_stack.undo()
    assert len(window.project.layers) == 1


def test_a_preset_choice_goes_to_the_library_and_not_the_project(window, qt_app, tmp_path) -> None:
    file = tmp_path / "Wheel.py"
    file.write_text(OBJECT, encoding="utf-8")
    answer(window, lambda items: [ImportChoice(items[0], "Wheel", ci.PRESET)])
    window.import_code_files([file])
    drain(qt_app)
    assert len(window.project.layers) == 1
    preset = next(p for p in window.code_presets.presets() if p.name == "Wheel")
    assert (preset.kind, preset.origin, preset.code) == ("object", "user", OBJECT)


def test_also_preset_adds_both(window, qt_app) -> None:
    answer(window, lambda items: [ImportChoice(items[0], "Wheel", ci.OBJECT, also_preset=True)])
    window.importer.import_items([ImportItem(OBJECT, "w.py")])
    drain(qt_app)
    assert window.project.layers[-1].name == "Wheel"
    assert any(p.name == "Wheel" for p in window.code_presets.presets())


def test_code_stays_untrusted_unless_allowed(window, qt_app) -> None:
    plain, allowed = OBJECT + "# untrusted case\n", OBJECT + "# trusted case\n"
    answer(window, lambda items: [ImportChoice(items[0], "Wheel", ci.OBJECT)])
    window.importer.import_items([ImportItem(plain, "w.py")])
    drain(qt_app)
    assert not window.trust.is_trusted(plain)
    answer(window, lambda items: [ImportChoice(items[0], "Wheel2", ci.OBJECT, trust=True)])
    window.importer.import_items([ImportItem(allowed, "w.py")])
    drain(qt_app)
    assert window.trust.is_trusted(allowed)


def test_cancelling_the_window_adds_nothing(window, qt_app, tmp_path) -> None:
    file = tmp_path / "Wheel.py"
    file.write_text(OBJECT, encoding="utf-8")
    answer(window, lambda items: None)
    window.import_code_files([file])
    drain(qt_app)
    assert len(window.project.layers) == 1


def test_unreadable_files_are_reported_and_the_rest_still_imported(window, qt_app, tmp_path) -> None:
    good, bad = tmp_path / "good.py", tmp_path / "bad.py"
    good.write_text(OBJECT, encoding="utf-8")
    bad.write_bytes(b"\xff\xfe\x00bad")
    answer(window, lambda items: [ImportChoice(items[0], "Good", ci.OBJECT)])
    window.import_code_files([bad, good])
    drain(qt_app)
    assert window.project.layers[-1].name == "Good"
    assert "could not be read" in window.statusBar().currentMessage()
    window.importer.import_paths([bad])
    assert "bad.py" in window.statusBar().currentMessage()


def test_dropping_a_builtin_preset_adds_it_trusted_at_the_drop(window, qt_app) -> None:
    preset = next(p for p in window.code_presets.presets() if p.builtin)
    payload = {"from": "preset", "id": preset.id, "name": preset.name, "kind": "object"}
    window.place_code(payload, t=3.0, position=(2.0, 1.0))
    drain(qt_app)
    layer = window.project.layers[-1]
    assert layer.spec.type == "Python" and layer.lifetime.in_ == 3.0 and layer.base.position == (2.0, 1.0)
    assert window.trust.is_trusted(preset.code)


def test_dropping_your_own_preset_does_not_trust_it(window, qt_app) -> None:
    code = OBJECT + "# my own preset\n"
    mine = window.code_presets.add("Mine", "object", code)
    window.place_code({"from": "preset", "id": mine.id, "name": "Mine", "kind": "object"})
    drain(qt_app)
    assert window.project.layers[-1].name == "Mine" and not window.trust.is_trusted(code)


def test_dropping_a_scene_preset_makes_a_code_layer(window, qt_app) -> None:
    mine = window.code_presets.add("Orbit", "scene", SCENE)
    window.place_code({"from": "preset", "id": mine.id, "name": "Orbit", "kind": "scene"}, t=1.0)
    drain(qt_app)
    assert window.project.layers[-1].spec.type == "Code" and window.project.layers[-1].lifetime.in_ == 1.0


def test_dropping_a_layer_makes_another_instance(window, qt_app) -> None:
    answer(window, lambda items: [ImportChoice(items[0], "Wheel", ci.OBJECT)])
    window.importer.import_items([ImportItem(OBJECT, "w.py")])
    drain(qt_app)
    original = window.project.layers[-1].id
    payload = {"from": "layer", "id": original, "name": "Wheel", "kind": "object"}
    window.place_code(payload, t=2.5, position=(1.0, 1.0))
    drain(qt_app)
    copy = window.project.layers[-1]
    assert copy.id != original and copy.spec.params["code"] == OBJECT
    assert copy.lifetime.in_ == 2.5 and copy.base.position == (1.0, 1.0)


def test_dropping_something_gone_says_so(window, qt_app) -> None:
    window.place_code({"from": "preset", "id": "user:nope", "name": "Nope", "kind": "object"})
    assert "not in the library" in window.statusBar().currentMessage()
    window.place_code({"from": "layer", "id": "nope", "name": "Nope", "kind": "object"})
    assert "not in the project" in window.statusBar().currentMessage()
    assert len(window.project.layers) == 1


def test_old_saved_templates_move_into_the_library(qt_app) -> None:
    from manim_studio.ui.preferences import Preferences

    Preferences().set_python_code_templates({"Old one": OBJECT})
    win = MainWindow()
    try:
        assert any(p.name == "Old one" and p.origin == "user" for p in win.code_presets.presets())
    finally:
        win.close()


# -- preset names that are taken ---------------------------------------------------------------


def named(window, name):
    return [p for p in window.code_presets.presets() if p.name == name]


def test_a_taken_preset_name_asks_and_can_replace(window) -> None:
    other = OBJECT.replace("Circle", "Square")
    store = window.importer.store_preset
    assert store("Wheel", "object", OBJECT) == "added"
    assert store("Wheel", "object", OBJECT) == "same"  # nothing to ask
    asked = []

    def replace(name):
        asked.append(name)
        return "replace"

    assert store("wheel", "object", other, decide=replace) == "replaced"
    assert (
        asked == ["Wheel"]
        and [p.code for p in named(window, "wheel")] == [other]
        and not named(window, "Wheel")
    )


def test_a_taken_preset_name_can_be_skipped_or_kept_both(window) -> None:
    other = OBJECT.replace("Circle", "Square")
    store = window.importer.store_preset
    store("Wheel", "object", OBJECT)
    assert store("Wheel", "object", other, decide=lambda name: "skip") == "skipped"
    assert [p.code for p in named(window, "Wheel")] == [OBJECT]
    assert store("Wheel", "object", other, decide=lambda name: "copy") == "copied"
    assert len(named(window, "Wheel")) == 1 and len(named(window, "Wheel (2)")) == 1
    assert store("Wheel", "object", other.replace("Square", "Dot"), decide=lambda name: None) == "cancelled"


def test_a_builtin_preset_is_never_replaced(window) -> None:
    builtin = next(p for p in window.code_presets.presets() if p.builtin)
    outcome = window.importer.store_preset(builtin.name, "object", OBJECT, decide=lambda name: "replace")
    assert outcome == "copied" and any(
        p.builtin and p.name == builtin.name for p in window.code_presets.presets()
    )


def test_changing_the_library_is_announced(window) -> None:
    seen = []
    window.codePresetsChanged.connect(lambda: seen.append(1))
    window.importer.store_preset("Wheel", "object", OBJECT)
    assert seen == [1]
