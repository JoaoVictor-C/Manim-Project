"""The outline of a piece of code (P13.3)."""

from __future__ import annotations

from manim_studio.core import python_templates
from manim_studio.core.outline import Symbol, symbols

SCENE = '''from manim import *

SPEED = 2
_HIDDEN = 1
lower = 3


class Intro(Scene):
    """A scene."""

    def setup(self):
        self.x = 1

    def construct(self):
        self.play(Create(Circle()))

    def helper(self):
        pass


class Plain:
    def go(self):
        pass


class Moving(MovingCameraScene):
    pass


class Qualified(manim.ThreeDScene):
    pass


def make_circle(r):
    return Circle(radius=r)
'''


def kinds(source: str) -> list[tuple[str, str, str]]:
    return [(s.kind, s.name, s.parent) for s in symbols(source)]


class TestSymbols:
    def test_a_scene_file(self):
        assert kinds(SCENE) == [
            ("constant", "SPEED", ""),
            ("constant", "_HIDDEN", ""),
            ("scene", "Intro", ""),
            ("method", "setup", "Intro"),
            ("entry", "construct", "Intro"),
            ("method", "helper", "Intro"),
            ("class", "Plain", ""),
            ("method", "go", "Plain"),
            ("scene", "Moving", ""),
            ("scene", "Qualified", ""),
            ("function", "make_circle", ""),
        ]

    def test_lines_are_one_based_and_inclusive(self):
        found = {s.name: s for s in symbols(SCENE)}
        lines = SCENE.split("\n")
        assert lines[found["Intro"].line - 1].startswith("class Intro")
        assert lines[found["Intro"].end_line - 1].strip() == "pass"
        assert found["construct"].line == found["construct"].end_line - 1
        assert found["SPEED"].line == found["SPEED"].end_line
        assert found["make_circle"].end_line == len(lines) - 1

    def test_a_python_object(self):
        source = python_templates.TEMPLATES["Right triangle"]
        found = symbols(source)
        assert [(s.kind, s.name) for s in found] == [("params", "PARAMS"), ("entry", "build")]
        assert found[0].end_line > found[0].line

    def test_a_class_with_construct_is_a_scene_whatever_its_base(self):
        source = "class Mine(Base):\n    def construct(self):\n        pass\n"
        assert kinds(source) == [("scene", "Mine", ""), ("entry", "construct", "Mine")]

    def test_a_scene_base_with_a_longer_name(self):
        assert kinds("class A(LinearTransformationScene):\n    pass\n") == [("scene", "A", "")]

    def test_top_level_construct_function_is_an_entry(self):
        assert kinds("def construct():\n    pass\n") == [("entry", "construct", "")]

    def test_build_method_is_a_plain_method(self):
        assert kinds("class A:\n    def build(self):\n        pass\n") == [
            ("class", "A", ""),
            ("method", "build", "A"),
        ]

    def test_async_functions(self):
        assert kinds("async def go():\n    pass\n") == [("function", "go", "")]

    def test_decorated_function_is_listed_at_its_def(self):
        found = symbols("@cache\ndef f():\n    pass\n")
        assert found == [Symbol("function", "f", 2, 3)]

    def test_constants_are_upper_case_only(self):
        source = "A = 1\nB2 = 2\nC_D = 3\nmixedCase = 4\nCamel = 5\n_x = 6\nX, Y = 1, 2\nZ: int = 3\n"
        assert [s.name for s in symbols(source)] == ["A", "B2", "C_D", "X", "Y", "Z"]
        assert {s.kind for s in symbols(source)} == {"constant"}

    def test_attribute_and_subscript_targets_are_ignored(self):
        assert symbols("self.A = 1\nd['B'] = 2\nitems[0], C = 1, 2\n") == [Symbol("constant", "C", 3, 3)]

    def test_params_with_annotation(self):
        assert kinds('PARAMS: dict = {"a": 1}\n') == [("params", "PARAMS", "")]

    def test_nested_definitions_are_not_listed(self):
        source = (
            "def outer():\n    def inner():\n        pass\n    LIMIT = 1\n\n"
            "class A:\n    class B:\n        pass\n    K = 1\n"
        )
        assert kinds(source) == [("function", "outer", ""), ("class", "A", "")]

    def test_definitions_under_if_are_not_listed(self):
        assert symbols("if True:\n    def f():\n        pass\n") == []

    def test_order_follows_the_lines(self):
        source = "def b():\n    pass\n\nX = 1\n\nclass C:\n    pass\n\ndef a():\n    pass\n"
        assert [s.name for s in symbols(source)] == ["b", "X", "C", "a"]
        lines = [s.line for s in symbols(source)]
        assert lines == sorted(lines)

    def test_syntax_error_gives_nothing(self):
        assert symbols("def f(:\n    pass\n") == []
        assert symbols("class A:\n  def f(self):\n") == []

    def test_empty_and_odd_input(self):
        assert symbols("") == []
        assert symbols("\n\n# only a comment\n") == []
        assert symbols("x = 1\x00") == []

    def test_bom(self):
        assert kinds("\ufeffdef f():\n    pass\n") == [("function", "f", "")]

    def test_crlf(self):
        found = symbols("class A(Scene):\r\n    def construct(self):\r\n        pass\r\n")
        assert [(s.kind, s.line, s.end_line) for s in found] == [("scene", 1, 3), ("entry", 2, 3)]

    def test_unicode_names(self):
        assert kinds("def ângulo():\n    pass\n\nclass Ação(Scene):\n    pass\n") == [
            ("function", "ângulo", ""),
            ("scene", "Ação", ""),
        ]

    def test_symbols_are_hashable_values(self):
        a, b = symbols("def f():\n    pass\n"), symbols("def f():\n    pass\n")
        assert a == b and {a[0]} == {b[0]}
