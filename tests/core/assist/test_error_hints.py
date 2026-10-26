"""core/assist/error_hints.py: plain-language help for errors, with did-you-mean (P13.1)."""

from __future__ import annotations

import pytest

from manim_studio.core.assist import error_hints
from manim_studio.core.assist.error_hints import Hint, hint, split_legacy

MANIM_SCENE = "from manim import *\n\nclass S(Scene):\n    def construct(self):\n        pass\n"


def caught(code: str) -> tuple[str, str]:
    """The (type, first line of the message) Python really reports for ``code``."""
    try:
        exec(compile(code, "<code layer>", "exec"), {})
    except BaseException as error:
        message = error.msg if isinstance(error, SyntaxError) else str(error)
        return type(error).__name__, message
    raise AssertionError("the snippet did not fail")


# Real messages, captured by running the snippet: (code, text every good hint must mention).
REAL = [
    ("x = 5\nx.fooo", "fooo"),
    ("import math\nmath.sqr(4)", "sqrt"),
    ("'a'.upperr()", "upper"),
    ("def f(a, b): pass\nf(1)", "`b`"),
    ("def f(a): pass\nf(1, 2)", "takes 1"),
    ("x = 3\nx()", "not a function"),
    ("x = 1\nx[0]", "Square brackets"),
    ("'abc' + 1", "str("),
    ("1/0", "zero"),
    ("import math\nmath.sqrt(-1)", "negative"),
    ("a, b = (1, 2, 3)", "expects 2"),
    ("[1,2][5]", "starts at 0"),
    ("{'a':1}['b']", "`b`"),
    ("def f(): return f()\nf()", "calling itself"),
    ("float('abc')", "not one"),
    ("int('abc')", "not one"),
    ("import notamodule", "notamodule"),
    ("from math import nothing", "nothing"),
    ("print('abc", "quote"),
    ("x = (1,\ny = 2", "`)`"),
    ("def f():\nx=1", "pushed to the right"),
    ("x = 1\n  y = 2", "further right"),
    ("if x\n  pass", "`:`"),
    ("print 'a'", "brackets"),
    ("x = [1, 2", "`]`"),
    ("s = '''abc", "three quotes"),
    ("x = = 1", "cannot read"),
    ("if True:\n\tx=1\n        y=2", "Tabs and spaces"),
    ("return 5", "inside a function"),
    ("x = None\nx.foo()", "None"),
    ("1 = x", "=="),
    ("print('a' 'b' c)", "comma"),
    ("print(1))", "closing bracket"),
    ("[1, 2)", "match"),
    ("def f():\n    return 1\n  y = 2", "lines up"),
    ("if True:\nprint(1)", "pushed to the right"),
    ("d = {}\nd[0]", "`0`"),
    ("unknown_function(3)", "unknown_function"),
    ("def f():\n    print(zz)\n    zz = 2\nf()", "`zz`"),
]


@pytest.mark.parametrize(("code", "expected"), REAL)
def test_real_python_errors_get_a_hint(code: str, expected: str) -> None:
    error_type, message = caught(code)
    found = hint(error_type, message, code)
    assert found is not None, (error_type, message)
    assert expected in found.text, found.text
    assert len(found.text) <= 300
    assert found.text == found.text.strip() and "\n" not in found.text


def test_every_hint_is_at_most_300_characters() -> None:
    for code, _ in REAL:
        error_type, message = caught(code)
        found = hint(error_type, message, code)
        assert found is None or len(found.text) <= error_hints.MAX_TEXT


def test_a_long_text_is_cut_to_300_characters() -> None:
    long_name = "x" * 400
    found = hint("KeyError", f"'{long_name}'", "")
    assert found is not None and len(found.text) <= 300


# -- NameError --------------------------------------------------------------------------------------


def test_name_error_suggests_manim_names() -> None:
    found = hint("NameError", "name 'Circl' is not defined", MANIM_SCENE)
    assert found is not None
    assert found.suggestions[0] == "Circle"
    assert "`Circle`" in found.text


def test_name_error_ranks_case_mistakes_first() -> None:
    found = hint("NameError", "name 'circle' is not defined", MANIM_SCENE)
    assert found is not None and found.suggestions[0] == "Circle"


def test_name_error_suggests_names_the_code_defines() -> None:
    source = "from manim import *\nradius_value = 3\nprint(raduis_value)"
    found = hint("NameError", "name 'raduis_value' is not defined", source)
    assert found is not None and found.suggestions[0] == "radius_value"


def test_name_error_suggests_python_builtins() -> None:
    found = hint("NameError", "name 'prnt' is not defined", "prnt(1)")
    assert found is not None and "print" in found.suggestions


def test_name_error_british_spelling_of_a_manim_name() -> None:
    found = hint("NameError", "name 'LIGHT_GREY' is not defined", MANIM_SCENE)
    assert found is not None
    assert found.suggestions[0] == "LIGHT_GRAY"


def test_name_error_without_a_manim_import_suggests_the_import() -> None:
    source = "class S(Scene):\n    def construct(self):\n        self.add(Circle())\n"
    found = hint("NameError", "name 'Circle' is not defined", source)
    assert found is not None
    assert found.fix == "from manim import *"
    assert "from manim import *" in found.text and found.suggestions == ("Circle",)


def test_name_error_with_the_import_present_does_not_blame_the_import() -> None:
    found = hint("NameError", "name 'Circle' is not defined", "from manim import *\nCircle")
    assert found is None or found.fix == ""


def test_name_error_without_a_source_says_nothing_about_the_import() -> None:
    found = hint("NameError", "name 'Circle' is not defined")
    assert found is not None and found.fix == ""


def test_name_error_with_nothing_close() -> None:
    found = hint("NameError", "name 'qzxwv' is not defined", MANIM_SCENE)
    assert found is not None and found.suggestions == ()
    assert "created before it is used" in found.text


def test_name_error_self_is_explained() -> None:
    found = hint("NameError", "name 'self' is not defined", "self.play(Create(Circle()))")
    assert found is not None and "construct(self)" in found.text


def test_name_error_in_a_source_that_does_not_parse_still_works() -> None:
    found = hint("NameError", "name 'valu' is not defined", "value = 1\nprint(valu\n")
    assert found is not None and found.suggestions[0] == "value"


# -- AttributeError ---------------------------------------------------------------------------------


def test_attribute_error_on_a_manim_class_uses_its_methods() -> None:
    found = hint("AttributeError", "Circle object has no attribute 'set_colur'")
    assert found is not None and found.suggestions[0] == "set_color"


def test_attribute_error_british_spelling_comes_first() -> None:
    found = hint("AttributeError", "Circle object has no attribute 'set_colour'")
    assert found is not None and found.suggestions[0] == "set_color"
    found = hint("AttributeError", "'Square' object has no attribute 'set_colour'")
    assert found is not None and found.suggestions[0] == "set_color"


def test_attribute_error_on_a_builtin_type() -> None:
    found = hint("AttributeError", "'list' object has no attribute 'apend'")
    assert found is not None and found.suggestions[0] == "append"


def test_attribute_error_on_a_module() -> None:
    found = hint("AttributeError", "module 'numpy' has no attribute 'arrray'")
    assert found is not None and found.suggestions[0] == "array"


def test_attribute_error_on_none_explains_none() -> None:
    found = hint("AttributeError", "'NoneType' object has no attribute 'shift'")
    assert found is not None and "None" in found.text and found.suggestions == ()


# -- TypeError --------------------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["colour", "fill_colour", "stroke_colour"])
def test_british_keyword_spellings(word: str) -> None:
    found = hint("TypeError", f"Mobject.__init__() got an unexpected keyword argument '{word}'")
    assert found is not None
    assert found.suggestions[0] == word.replace("colour", "color")
    assert "American spelling" in found.text


def test_british_keyword_names_the_call_from_the_source() -> None:
    source = "from manim import *\nCircle(colour=RED)"
    found = hint("TypeError", "Mobject.__init__() got an unexpected keyword argument 'colour'", source)
    assert found is not None and "`Circle`" in found.text


def test_keyword_suggestions_come_from_the_callable() -> None:
    source = "from manim import *\nCircle(radiu=2)"
    found = hint("TypeError", "Mobject.__init__() got an unexpected keyword argument 'radiu'", source)
    assert found is not None and found.suggestions[0] == "radius"


def test_keyword_with_nothing_close() -> None:
    found = hint("TypeError", "f() got an unexpected keyword argument 'qzxwv'")
    assert found is not None and found.suggestions == ()


@pytest.mark.parametrize(
    ("word", "american"),
    [
        ("colour", "color"),
        ("centre", "center"),
        ("grey", "gray"),
        ("GREY_A", "GRAY_A"),
        ("behaviour", "behavior"),
    ],
)
def test_americanise(word: str, american: str) -> None:
    assert error_hints.americanise(word) == american


def test_missing_argument_names_it() -> None:
    found = hint("TypeError", "Rectangle() missing 1 required positional argument: 'width'")
    assert found is not None and "`width`" in found.text


def test_not_callable_hint() -> None:
    found = hint("TypeError", "'float' object is not callable")
    assert found is not None and "`float`" in found.text


# -- syntax ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error_type", "message", "expected"),
    [
        ("SyntaxError", "unterminated string literal (detected at line 3)", "closing quote"),
        ("SyntaxError", "unterminated triple-quoted string literal (detected at line 9)", "three quotes"),
        ("SyntaxError", "'(' was never closed", "`)`"),
        ("SyntaxError", "'{' was never closed", "`}`"),
        ("IndentationError", "expected an indented block after 'for' statement on line 2", "pass"),
        ("IndentationError", "unexpected indent", "further right"),
        ("IndentationError", "unindent does not match any outer indentation level", "lines up with no"),
        ("TabError", "inconsistent use of tabs and spaces in indentation", "spaces only"),
        ("SyntaxError", "invalid syntax", "cannot read this line"),
        ("SyntaxError", "expected ':'", "`:`"),
        ("SyntaxError", "invalid syntax. Perhaps you forgot a comma?", "comma"),
        ("SyntaxError", "f-string: expecting '}'", "`}`"),
    ],
)
def test_syntax_messages(error_type: str, message: str, expected: str) -> None:
    found = hint(error_type, message)
    assert found is not None and expected in found.text


# -- the rest -----------------------------------------------------------------------------------------


def test_import_errors() -> None:
    found = hint("ModuleNotFoundError", "No module named 'scipy'")
    assert found is not None and "not installed here" in found.text
    found = hint("ImportError", "helper 'physics' is not trusted yet")
    assert found is not None and "not been approved" in found.text
    found = hint("ImportError", "cannot import name 'Circl' from 'manim' (unknown location)")
    assert found is not None and found.suggestions[0] == "Circle"


def test_value_errors() -> None:
    found = hint("ValueError", "not enough values to unpack (expected 3, got 2)")
    assert found is not None and "expects 3" in found.text
    found = hint("ValueError", "could not convert string to float: 'abc'")
    assert found is not None and "'abc'" in found.text


def test_index_error_for_an_empty_list() -> None:
    found = hint("IndexError", "pop from empty list")
    assert found is not None and "empty" in found.text


def test_key_error_for_a_parameter_names_the_ones_that_exist() -> None:
    source = "PARAMS = {'radius': 1.0, 'speed': 2.0}\ndef build(p):\n    return Circle(radius=p['radiu'])\n"
    found = hint("KeyError", "'radiu'", source)
    assert found is not None
    assert "no parameter called `radiu`" in found.text and "PARAMS has radius, speed" in found.text
    assert found.suggestions == ("radius",)


def test_key_error_without_params_is_general() -> None:
    found = hint("KeyError", "'b'", "d = {}\nd['b']")
    assert found is not None and "PARAMS" not in found.text


def test_recursion_and_zero_division() -> None:
    assert hint("RecursionError", "maximum recursion depth exceeded") is not None
    assert hint("ZeroDivisionError", "division by zero") is not None


def test_latex_problems_point_at_troubleshooting() -> None:
    missing = hint("RuntimeError", "LaTeX is not installed (latex was not found): install MiKTeX or TeX Live")
    assert missing is not None and "Troubleshooting > missing LaTeX" in missing.text
    broken = hint("ValueError", "latex error converting to dvi. See log output above or the log file: x.log")
    assert broken is not None and "Troubleshooting > missing LaTeX" in broken.text
    miktex = hint("OSError", "dvisvgm could not be started")
    assert miktex is not None and "missing LaTeX" in miktex.text


def test_timeouts_mention_an_endless_loop() -> None:
    for message in ("rendering took longer than 120 s", "building took longer than 5 s (an endless loop?)"):
        found = hint("", message)
        assert found is not None and "endless loop" in found.text


def test_scene_class_message() -> None:
    found = hint("", "define exactly one Scene subclass (found: none)")
    assert found is not None and "construct" in found.text


def test_the_type_can_come_inside_the_message() -> None:
    found = hint("", "NameError: name 'Circl' is not defined", MANIM_SCENE)
    assert found is not None and found.suggestions[0] == "Circle"
    found = hint("NameError", "NameError: name 'Circl' is not defined", MANIM_SCENE)
    assert found is not None and found.suggestions[0] == "Circle"


def test_unknown_things_give_no_hint() -> None:
    assert hint("Boom", "something unusual") is None
    assert hint("AssertionError", "msg") is None
    assert hint("", "") is None


@pytest.mark.parametrize(
    ("error_type", "message", "source"),
    [
        ("NameError", "", ""),
        ("NameError", "name '' is not defined", ""),
        ("AttributeError", "object has no attribute", ""),
        ("TypeError", "got an unexpected keyword argument ''", ""),
        ("KeyError", "", ""),
        ("KeyError", "'", "PARAMS = {"),
        ("SyntaxError", "\x00\x01 junk \ud800", "\x00"),
        ("ImportError", "cannot import name 'x' from ''", ""),
        ("ValueError", "invalid literal for int() with base 10:", ""),
        (None, None, None),
        ("NameError", "name 'x' is not defined", "\x00 broken ((("),
    ],
)
def test_junk_does_not_crash(error_type, message, source) -> None:
    result = hint(error_type, message, source)
    assert result is None or isinstance(result, Hint)


# -- split_legacy -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("NameError: name 'x' is not defined", ("NameError", "name 'x' is not defined")),
        ("SyntaxError: invalid syntax", ("SyntaxError", "invalid syntax")),
        ("ModuleNotFoundError: No module named 'a.b'", ("ModuleNotFoundError", "No module named 'a.b'")),
        ("builtins.ValueError: boom", ("ValueError", "boom")),
        ("KeyboardInterrupt:", ("KeyboardInterrupt", "")),
        (
            "define exactly one Scene subclass (found: none)",
            ("", "define exactly one Scene subclass (found: none)"),
        ),
        ("LaTeX error: Missing { inserted", ("", "LaTeX error: Missing { inserted")),
        ("rendering took longer than 120 s", ("", "rendering took longer than 120 s")),
        ("", ("", "")),
        ("line 3: NameError: x", ("", "line 3: NameError: x")),
    ],
)
def test_split_legacy(message: str, expected: tuple[str, str]) -> None:
    assert split_legacy(message) == expected


def test_split_legacy_keeps_the_extra_lines() -> None:
    assert split_legacy("ValueError: first\nsecond") == ("ValueError", "first\nsecond")
