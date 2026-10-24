"""What importing a code file can become (P12.4): the options, the preselection, the code each layer
or preset gets."""

from __future__ import annotations

import pytest

from manim_studio.core import code_import as ci
from manim_studio.core.code_import import ImportChoice, ImportItem

SCENE = "from manim import *\n\nclass Orbit(Scene):\n    def construct(self):\n        self.add(Dot())\n"
TWO = SCENE + "\nclass Spin(Scene):\n    def construct(self):\n        self.add(Square())\n"
OBJECT = "from manim import *\n\nPARAMS = {}\n\ndef build(p):\n    return Circle()\n"
BOM = "\ufeff"


def item(source: str, origin: str = "x.py") -> ImportItem:
    return ImportItem(source, origin)


def test_a_scene_is_preselected_as_a_scene_and_cannot_be_an_object() -> None:
    options = ci.possible(item(SCENE).inspection)
    assert ci.detected(item(SCENE).inspection) == ci.SCENE
    assert options[ci.SCENE] is None and options[ci.PRESET] is None
    assert "build" in options[ci.OBJECT]


def test_an_object_is_preselected_as_an_object_and_cannot_be_a_scene() -> None:
    options = ci.possible(item(OBJECT).inspection)
    assert ci.detected(item(OBJECT).inspection) == ci.OBJECT
    assert options[ci.OBJECT] is None and "Scene" in options[ci.SCENE]


def test_neither_gives_the_reason_for_every_option() -> None:
    inspection = item("print(1)\n").inspection
    assert ci.detected(inspection) is None
    assert all(reason for reason in ci.possible(inspection).values())
    syntax = item("def build(:\n").inspection
    assert "SyntaxError" in ci.possible(syntax)[ci.OBJECT]


def test_the_byte_order_mark_is_dropped_from_the_code() -> None:
    assert ci.code_for(item(BOM + OBJECT)) == OBJECT
    assert ci.detected(item(BOM + OBJECT).inspection) == ci.OBJECT


def test_a_scene_layer_holds_only_its_scene() -> None:
    code = ci.code_for(item(TWO), "Orbit")
    assert "class Orbit" in code and "Spin" not in code


def test_several_scenes_become_one_layer_each_named_after_the_scene() -> None:
    choice = ImportChoice(item(TWO), "Pair", ci.SCENE, scenes=("Orbit", "Spin"))
    layers = ci.layers_of(choice)
    assert [(n, t) for n, t, _ in layers] == [("Pair - Orbit", "Code"), ("Pair - Spin", "Code")]
    assert ci.layers_of(ImportChoice(item(TWO), "Pair", ci.SCENE, scenes=("Spin",)))[0][0] == "Pair"


def test_the_first_scene_is_used_when_none_is_chosen() -> None:
    ((_, kind, code),) = ci.layers_of(ImportChoice(item(TWO), "Pair", ci.SCENE))
    assert kind == "Code" and "class Orbit" in code and "Spin" not in code


def test_an_object_layer_is_a_python_spec_with_the_whole_text() -> None:
    assert ci.layers_of(ImportChoice(item(BOM + OBJECT), "Wheel", ci.OBJECT)) == [("Wheel", "Python", OBJECT)]


def test_presets_are_made_for_preset_choices_and_when_asked_for() -> None:
    assert ci.presets_of(ImportChoice(item(OBJECT), "Wheel", ci.PRESET)) == [("Wheel", "object", OBJECT)]
    assert ci.presets_of(ImportChoice(item(OBJECT), "Wheel", ci.OBJECT)) == []
    both = ci.presets_of(ImportChoice(item(OBJECT), "Wheel", ci.OBJECT, also_preset=True))
    assert both == [("Wheel", "object", OBJECT)]
    ((name, kind, code),) = ci.presets_of(ImportChoice(item(TWO), "Orb", ci.PRESET, scenes=("Orbit",)))
    assert (name, kind) == ("Orb", "scene") and "Spin" not in code


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        (ImportChoice(item(OBJECT), "  ", ci.OBJECT), "name"),
        (ImportChoice(item(OBJECT), "A", ci.SCENE), "Scene"),
        (ImportChoice(item(SCENE), "A", ci.OBJECT), "build"),
        (ImportChoice(item(SCENE), "A", ci.SCENE, scenes=("Nope",)), "Nope"),
        (ImportChoice(item("print(1)\n"), "A", ci.PRESET), "neither"),
    ],
)
def test_invalid_choices_say_why(choice: ImportChoice, expected: str) -> None:
    assert expected in (ci.validate(choice) or "")


def test_valid_choices_pass() -> None:
    for choice in (
        ImportChoice(item(OBJECT), "A", ci.OBJECT),
        ImportChoice(item(OBJECT), "A", ci.PRESET),
        ImportChoice(item(TWO), "A", ci.SCENE, scenes=("Spin",)),
    ):
        assert ci.validate(choice) is None


def test_a_derived_scene_cannot_be_separated() -> None:
    source = SCENE + "\nclass Child(Orbit):\n    pass\n"
    assert "another scene" in ci.validate(ImportChoice(item(source), "C", ci.SCENE, scenes=("Child",)))
