"""core/assist/diagnostics.py: syntax problems for the editor's marker, and user-only tracebacks (P13.1)."""

from __future__ import annotations

import pytest

from manim_studio.core.assist import diagnostics
from manim_studio.core.assist.diagnostics import pending_string, syntax_problem, user_traceback


def test_good_code_has_no_problem() -> None:
    assert syntax_problem("from manim import *\nx = 1\n") is None
    assert syntax_problem("") is None
    assert not pending_string("x = 1")


def test_a_simple_problem_is_placed_and_made_plain() -> None:
    problem = syntax_problem("x = 1\nif x\n    pass\n")
    assert problem is not None
    assert problem.line == 2 and problem.column >= 0
    assert "`:`" in problem.message
    assert not pending_string("x = 1\nif x\n    pass\n")


def test_line_and_column_are_inside_the_text() -> None:
    for source in ["x = (", "print('abc", "def f(:\n pass", "if True:\n", "x = 1 +", "a b c", "'''abc\n\n"]:
        problem = syntax_problem(source)
        assert problem is not None, source
        lines = source.split("\n")
        assert 1 <= problem.line <= len(lines)
        assert problem.line <= problem.end_line <= len(lines)
        assert 0 <= problem.column <= len(lines[problem.line - 1])


def test_unterminated_triple_quote_reports_at_the_end_of_the_file() -> None:
    source = 'x = 1\ntext = """hello\nmore text\n\nlast line'
    problem = syntax_problem(source)
    assert problem is not None
    assert problem.line == problem.end_line == 5
    assert problem.column == len("last line")
    assert "three quotes" in problem.message and "line 2" in problem.message
    assert pending_string(source)


def test_unterminated_triple_quote_with_a_trailing_newline() -> None:
    problem = syntax_problem('s = """abc\n')
    assert problem is not None and problem.line == 2 and problem.column == 0


def test_an_unclosed_bracket_is_pending() -> None:
    assert pending_string("x = foo(1,\n  2,\n")
    assert pending_string("data = [1, 2")
    problem = syntax_problem("x = foo(1,\n  2,\n")
    assert problem is not None and problem.line == 1  # where the bracket was opened
    assert "`)`" in problem.message


def test_other_problems_are_not_pending() -> None:
    assert not pending_string("print('abc")  # one line's quote is not "still typing"
    assert not pending_string("x = = 1")
    assert not pending_string("   ")


def test_a_bom_and_windows_line_endings_are_tolerated() -> None:
    assert syntax_problem("﻿x = 1\r\ny = 2\r\n") is None
    problem = syntax_problem("﻿x = 1\r\nif x\r\n  pass\r\n")
    assert problem is not None and problem.line == 2


def test_a_nul_byte_is_reported_where_it_is() -> None:
    problem = syntax_problem("x = 1\ny = 2\x00\nz = 3")
    assert problem is not None
    assert problem.line == 2 and problem.column == 5
    assert "null" in problem.message
    assert not pending_string("x = 1\x00")


def test_compile_time_errors_are_found_too() -> None:
    problem = syntax_problem("x = 1\nreturn x")
    assert problem is not None and problem.line == 2 and "inside a function" in problem.message


def test_invalid_escapes_are_not_a_problem() -> None:
    assert syntax_problem(r"x = '\d'") is None


def test_junk_does_not_crash() -> None:
    for source in ["\ud800", "\x00", "(" * 500, "\n\n\n", "def", ":", "é = 1\nè è"]:
        result = syntax_problem(source)
        assert result is None or result.line >= 1


# -- user_traceback -----------------------------------------------------------------------------------


def run(code: str, name: str = "<code layer>") -> BaseException:
    try:
        exec(compile(code, name, "exec"), {})
    except BaseException as error:
        return error
    raise AssertionError("did not fail")


def test_traceback_lists_only_the_users_frames() -> None:
    code = "def f(x):\n    return g(x)\ndef g(x):\n    return x / 0\nf(1)\n"
    error = run(code)
    text = user_traceback(error, {"<code layer>": code})
    assert text.startswith("Traceback (most recent call last):")
    assert "line 5" in text and "line 2, in f" in text and "return x / 0" in text
    assert text.splitlines()[-1] == "ZeroDivisionError: division by zero"
    assert "diagnostics.py" not in text and "test_" not in text and "File " not in text


def test_traceback_for_a_syntax_error() -> None:
    code = "x = 1\nif x\n  pass"
    error = None
    try:
        compile(code, "<code layer>", "exec")
    except SyntaxError as caught:
        error = caught
    text = user_traceback(error, {"<code layer>": code})
    assert "line 2" in text and "if x" in text and "SyntaxError: expected ':'" in text


def test_traceback_without_user_frames_is_empty() -> None:
    error = run("1/0", "<elsewhere>")
    assert user_traceback(error, {"<code layer>": "1/0"}) == ""
    assert user_traceback(ValueError("x"), {"<code layer>": ""}) == ""


def test_traceback_names_a_helper_frame_too() -> None:
    helper = "def area(r):\n    return r.size\n"
    helper_error = None
    namespace: dict = {}
    exec(compile(helper, "<helper:geometry>", "exec"), namespace)
    code = "area(3)"
    try:
        exec(compile(code, "<code layer>", "exec"), namespace)
    except AttributeError as caught:
        helper_error = caught
    text = user_traceback(helper_error, {"<code layer>": code, "<helper:geometry>": helper})
    assert "return r.size" in text and "area(3)" in text


def test_traceback_is_capped_at_4_kb() -> None:
    code = "def f(n):\n    return f(n + 1) if n < 3000 else 1 / 0\nf(0)\n"
    # a deep recursion with a long source line per frame
    long = "x = 1  # " + "é" * 2000 + "\nraise ValueError('é' * 5000)\n"
    error = run(long)
    text = user_traceback(error, {"<code layer>": long})
    assert 0 < len(text.encode("utf-8")) <= diagnostics.TRACEBACK_LIMIT
    deep = run("def f(n):\n    return f(n + 1)\nf(0)\n")
    text = user_traceback(deep, {"<code layer>": "def f(n):\n    return f(n + 1)\nf(0)\n"})
    assert len(text.encode("utf-8")) <= diagnostics.TRACEBACK_LIMIT
    assert code  # (kept for readability of the first snippet)


@pytest.mark.parametrize("limit", [100, 400])
def test_traceback_limit_is_respected(limit: int) -> None:
    code = "def f():\n    return g()\ndef g():\n    return h()\ndef h():\n    raise KeyError('k')\nf()\n"
    text = user_traceback(run(code), {"<code layer>": code}, limit=limit)
    assert len(text.encode("utf-8")) <= limit
