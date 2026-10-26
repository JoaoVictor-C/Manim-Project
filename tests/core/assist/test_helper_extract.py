"""Extract to helper (ADR 0058): whole top-level functions and classes move into a new helper."""

from __future__ import annotations

import ast

import pytest

from manim_studio.core.assist.helper_extract import ExtractError, defined_names, extract
from manim_studio.core.code import helpers

SOURCE = '''"""A scene with a grid."""
import random

RADIUS = 2


def grid(n):
    return VGroup(*[Dot() for _ in range(n)]) if random.random() else np.zeros(n)


@staticmethod
def other():
    return 1


class Orbit(Scene):
    def construct(self):
        self.add(grid(3))
'''


def test_the_selected_definitions_move_and_are_imported_back() -> None:
    result = extract(SOURCE, "tools", first=7, last=13, origin="Orbit")
    assert result.names == ("grid", "other")
    assert "from tools import grid, other\n" in result.code
    assert "def grid" not in result.code and "@staticmethod" not in result.code
    assert result.code.index("import random") < result.code.index("from tools import")
    assert result.code.index("from tools import") < result.code.index("RADIUS = 2")
    assert "\n\n\n\n" not in result.code
    ast.parse(result.code)
    assert result.helper_code.startswith('"""Extracted from Orbit: grid, other."""')
    for line in ("from manim import *", "import numpy as np", "import random"):
        assert line in result.helper_code.splitlines()  # what the moved code uses comes along
    assert "@staticmethod\ndef other():" in result.helper_code
    ast.parse(result.helper_code)
    assert helpers.imports_of(result.code) >= {"tools"}


def test_the_cursor_takes_the_definition_it_is_in() -> None:
    result = extract("def f():\n    return 1\n\nx = f()\n", "t", cursor=2)
    assert result.names == ("f",)
    assert result.code == "from t import f\n\nx = f()\n"
    assert result.helper_code == '"""Extracted: f."""\n\n\ndef f():\n    return 1\n'  # needs no import


def test_a_decorator_line_counts_as_the_definition() -> None:
    assert extract(SOURCE, "t", cursor=11).names == ("other",)


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"cursor": 4}, "put the cursor"),
        ({"cursor": 17}, "scene of this code"),
        ({"first": 3, "last": 8}, "line 4 is not a function"),
        ({"first": 8, "last": 13}, "whole"),
        ({"first": 2, "last": 2}, "line 2 is not a function"),
    ],
)
def test_anything_but_whole_definitions_is_refused(kwargs, reason) -> None:
    with pytest.raises(ExtractError, match=reason):
        extract(SOURCE, "t", **kwargs)


def test_a_definition_using_a_name_that_stays_is_refused() -> None:
    with pytest.raises(ExtractError, match="RADIUS, which stays in the code: select it too"):
        extract("def f():\n    return RADIUS\n\n\nRADIUS = 1\n", "t", cursor=1)


def test_build_stays_in_a_python_object() -> None:
    with pytest.raises(ExtractError, match="build"):
        extract("PARAMS = {}\n\n\ndef build(p):\n    return Circle()\n", "t", cursor=4)


def test_code_that_does_not_parse_is_refused() -> None:
    with pytest.raises(ExtractError, match="syntax error"):
        extract("def f(:\n", "t", cursor=1)


def test_a_future_import_stays_first_in_the_helper() -> None:
    source = "from __future__ import annotations\n\n\ndef f(x: int) -> int:\n    return math.floor(x)\n"
    result = extract(source, "t", cursor=4)
    lines = result.helper_code.splitlines()
    assert lines[2] == "from __future__ import annotations" and "import math" in lines
    assert "from manim import *" not in lines
    assert result.code.startswith("from __future__ import annotations\nfrom t import f\n")


def test_defined_names_are_the_public_top_level_names() -> None:
    assert defined_names(SOURCE) == ["RADIUS", "grid", "other", "Orbit"]
    assert defined_names("import os\n_x = 1\nA, B = 1, 2\n") == ["A", "B"]
    assert defined_names("def (") == []
