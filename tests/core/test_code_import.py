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


def test_neither_an_object_nor_a_scene_is_a_helper() -> None:
    inspection = item("print(1)\n").inspection
    options = ci.possible(inspection)
    assert ci.detected(inspection) == ci.HELPER
    assert options[ci.HELPER] is None and options[ci.PRESET] is None
    assert "build" in options[ci.OBJECT] and "Scene" in options[ci.SCENE]
    assert ci.preset_kind(inspection) == "helper"


def test_code_that_does_not_parse_gives_the_reason_for_every_option() -> None:
    syntax = item("def build(:\n").inspection
    assert ci.detected(syntax) is None
    assert all("SyntaxError" in reason for reason in ci.possible(syntax).values())


def test_any_code_that_parses_can_be_a_helper() -> None:
    assert ci.possible(item(OBJECT).inspection)[ci.HELPER] is None
    assert ci.possible(item(SCENE).inspection)[ci.HELPER] is None


def test_a_helper_choice_makes_no_layer_and_a_helper_preset_when_asked() -> None:
    choice = ImportChoice(item(BOM + "X = 1\n"), "consts", ci.HELPER)
    assert ci.layers_of(choice) == [] and ci.presets_of(choice) == []
    both = ImportChoice(item("X = 1\n"), "consts", ci.HELPER, also_preset=True)
    assert ci.presets_of(both) == [("consts", "helper", "X = 1\n")]
    assert ci.presets_of(ImportChoice(item("X = 1\n"), "Consts", ci.PRESET)) == [
        ("Consts", "helper", "X = 1\n")
    ]


@pytest.mark.parametrize(
    ("text", "existing", "expected"),
    [
        ("grid_tools.py", (), "grid_tools"),
        ("Grid Tools.py", (), "grid_tools"),
        ("C:/files/My-Colours.py", (), "my_colours"),
        ("3d shapes", (), "helper_3d_shapes"),
        ("math.py", (), "math_helper"),
        ("json", (), "json_helper"),
        ("grid", ("grid",), "grid_helper"),
        ("grid", ("grid", "grid_helper"), "grid_2"),
        ("", (), "helper"),
    ],
)
def test_helper_names_are_python_names_that_hide_nothing(text, existing, expected) -> None:
    assert ci.helper_name(text, existing) == expected


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
        (ImportChoice(item("def build(:\n"), "A", ci.PRESET), "SyntaxError"),
        (ImportChoice(item("print(1)\n"), "2a", ci.HELPER), "Python name"),
        (ImportChoice(item("print(1)\n"), "json", ci.HELPER), "standard library"),
    ],
)
def test_invalid_choices_say_why(choice: ImportChoice, expected: str) -> None:
    assert expected in (ci.validate(choice) or "")


def test_valid_choices_pass() -> None:
    for choice in (
        ImportChoice(item(OBJECT), "A", ci.OBJECT),
        ImportChoice(item(OBJECT), "A", ci.PRESET),
        ImportChoice(item(TWO), "A", ci.SCENE, scenes=("Spin",)),
        ImportChoice(item("print(1)\n"), "A", ci.PRESET),
        ImportChoice(item("print(1)\n"), "printer_tools", ci.HELPER),
    ):
        assert ci.validate(choice) is None


def test_a_derived_scene_cannot_be_separated() -> None:
    source = SCENE + "\nclass Child(Orbit):\n    pass\n"
    assert "another scene" in ci.validate(ImportChoice(item(source), "C", ci.SCENE, scenes=("Child",)))
