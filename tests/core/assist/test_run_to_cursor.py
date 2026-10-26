"""Run to cursor (P13.3): the scene cut after the statement under the cursor, line numbers kept."""

from __future__ import annotations

import ast

import pytest

from manim_studio.core.assist.run_to_cursor import RunToCursor, truncate

SCENE = '''from manim import *


class Demo(Scene):
    """Docs."""

    def construct(self):
        """Inside docs."""
        circle = Circle()  # first
        self.play(Create(circle))

        # now the square
        square = Square()
        for i in range(3):
            self.play(square.animate.shift(RIGHT))
            self.wait(0.1)
        self.play(FadeOut(square))
        self.wait()

    def other(self):
        return 1


TAIL = 1
'''


def line_of(source: str, needle: str) -> int:
    for number, text in enumerate(source.split("\n"), 1):
        if needle in text:
            return number
    raise AssertionError(needle)


def same_lines(old: str, new: str) -> None:
    assert len(old.split("\n")) == len(new.split("\n"))


class TestTruncate:
    def test_cuts_after_the_statement_under_the_cursor(self):
        result = truncate(SCENE, line_of(SCENE, "Create(circle)"))
        assert result is not None
        assert result.statements_kept == 2 and result.statements_total == 6
        assert result.last_line == line_of(SCENE, "Create(circle)")
        assert "circle = Circle()  # first" in result.source
        assert "square" not in result.source
        assert "FadeOut" not in result.source and "wait()" not in result.source
        assert result.scene == "Demo"

    def test_line_numbers_are_kept(self):
        result = truncate(SCENE, line_of(SCENE, "Create(circle)"))
        assert result is not None
        same_lines(SCENE, result.source)
        old, new = SCENE.split("\n"), result.source.split("\n")
        assert new[: result.last_line] == old[: result.last_line]
        assert new[line_of(SCENE, "TAIL") - 1] == "TAIL = 1"
        assert new[line_of(SCENE, "def other") - 1] == "    def other(self):"
        ast.parse(result.source)

    def test_removed_lines_are_empty(self):
        result = truncate(SCENE, line_of(SCENE, "Create(circle)"))
        assert result is not None
        start = line_of(SCENE, "Create(circle)")
        end = line_of(SCENE, "self.wait()")
        assert all(result.source.split("\n")[n] == "" for n in range(start + 1, end - 1) if n > start)

    def test_first_statement(self):
        result = truncate(SCENE, line_of(SCENE, "circle = Circle()"))
        assert result is not None and result.statements_kept == 1
        assert "# first" in result.source  # the statement's own comment stays
        ast.parse(result.source)

    def test_a_line_inside_a_block_keeps_the_whole_top_level_statement(self):
        result = truncate(SCENE, line_of(SCENE, "shift(RIGHT)"))
        assert result is not None
        assert result.statements_kept == 4  # circle, play, square, the for loop
        assert result.last_line == line_of(SCENE, "self.wait(0.1)")
        assert "self.wait(0.1)" in result.source and "FadeOut" not in result.source
        ast.parse(result.source)

    def test_the_header_of_a_block_counts_as_the_block(self):
        result = truncate(SCENE, line_of(SCENE, "for i in range"))
        assert result is not None and result.last_line == line_of(SCENE, "self.wait(0.1)")

    def test_the_last_statement_keeps_everything(self):
        result = truncate(SCENE, line_of(SCENE, "self.wait()"))
        assert result is not None
        assert result.source == SCENE
        assert result.statements_kept == result.statements_total == 6

    def test_a_comment_or_blank_line_keeps_the_statements_before_it(self):
        result = truncate(SCENE, line_of(SCENE, "# now the square"))
        assert result is not None and result.statements_kept == 2
        blank = truncate(SCENE, line_of(SCENE, "Create(circle)") + 1)
        assert blank is not None and blank.statements_kept == 2

    def test_a_comment_after_the_cut_goes_with_the_removed_part(self):
        result = truncate(SCENE, line_of(SCENE, "Create(circle)"))
        assert result is not None and "now the square" not in result.source

    def test_not_applicable_outside_construct(self):
        for needle in ("from manim", "class Demo", "TAIL", "return 1", "def other", '"""Docs."""'):
            assert truncate(SCENE, line_of(SCENE, needle)) is None, needle

    def test_not_applicable_on_the_signature_or_docstring(self):
        assert truncate(SCENE, line_of(SCENE, "def construct")) is None
        assert truncate(SCENE, line_of(SCENE, "Inside docs")) is None

    def test_line_out_of_range(self):
        assert truncate(SCENE, 0) is None
        assert truncate(SCENE, -3) is None
        assert truncate(SCENE, 10_000) is None

    def test_syntax_error(self):
        assert truncate("class A(Scene):\n    def construct(self):\n        x = (\n", 3) is None

    def test_empty_source(self):
        assert truncate("", 1) is None

    def test_a_construct_without_a_docstring(self):
        source = "class A(Scene):\n    def construct(self):\n        a = 1\n        b = 2\n        c = 3\n"
        result = truncate(source, 4)
        assert result == RunToCursor(
            "class A(Scene):\n    def construct(self):\n        a = 1\n        b = 2\n\n", 4, 2, 3, "A"
        )

    def test_an_empty_line_before_a_construct_body_is_not_applicable(self):
        source = "class A(Scene):\n    def construct(self):\n\n        a = 1\n"
        assert truncate(source, 3) is None

    def test_a_pass_only_construct(self):
        source = "class A(Scene):\n    def construct(self):\n        pass\n"
        result = truncate(source, 3)
        assert result is not None and result.source == source


class TestSeveralScenes:
    SOURCE = (
        "class One(Scene):\n"
        "    def construct(self):\n"
        "        a = 1\n"
        "        b = 2\n"
        "\n"
        "\n"
        "class Two(MovingCameraScene):\n"
        "    def construct(self):\n"
        "        c = 3\n"
        "        d = 4\n"
        "        e = 5\n"
    )

    def test_the_scene_holding_the_line_is_cut(self):
        result = truncate(self.SOURCE, 10)
        assert result is not None and result.scene == "Two"
        lines = result.source.split("\n")
        assert lines[2:4] == ["        a = 1", "        b = 2"]  # the other scene is untouched
        assert lines[8:10] == ["        c = 3", "        d = 4"]
        assert lines[10] == ""
        assert result.statements_kept == 2 and result.statements_total == 3

    def test_the_first_scene(self):
        result = truncate(self.SOURCE, 3)
        assert result is not None and result.scene == "One"
        assert result.source.split("\n")[3] == ""
        assert "d = 4" in result.source  # the second scene is untouched

    def test_between_the_scenes(self):
        assert truncate(self.SOURCE, 5) is None


class TestAwkwardSources:
    def test_crlf_line_endings(self):
        source = SCENE.replace("\n", "\r\n")
        result = truncate(source, line_of(SCENE, "Create(circle)"))
        assert result is not None
        assert result.source.count("\r\n") == source.count("\r\n")
        assert "\n" not in result.source.replace("\r\n", "")
        ast.parse(result.source)
        assert "square" not in result.source

    def test_tabs(self):
        source = "class A(Scene):\n\tdef construct(self):\n\t\ta = 1\n\t\tif a:\n\t\t\tb = 2\n\t\tc = 3\n"
        result = truncate(source, 5)
        assert result is not None and result.statements_kept == 2
        assert (
            result.source == "class A(Scene):\n\tdef construct(self):\n\t\ta = 1\n\t\tif a:\n\t\t\tb = 2\n\n"
        )

    def test_unicode_before_the_cut(self):
        source = 'class A(Scene):\n    def construct(self):\n        t = Text("ação é ü")\n        u = 1\n'
        result = truncate(source, 3)
        assert result is not None
        assert result.source == 'class A(Scene):\n    def construct(self):\n        t = Text("ação é ü")\n\n'

    def test_unicode_before_a_semicolon_cut(self):
        source = "class A(Scene):\n    def construct(self):\n        t = 'é'; u = 'ü'\n        v = 1\n"
        result = truncate(source, 3)
        assert result is not None
        assert result.statements_kept == 1 or result.statements_kept == 2
        ast.parse(result.source)

    def test_statements_sharing_a_line(self):
        source = "class A(Scene):\n    def construct(self):\n        a = 1; b = 2\n        c = 3\n"
        result = truncate(source, 3)
        assert result is not None
        # both statements start on line 3: the cursor is on that line, so both are kept
        assert result.statements_kept == 2
        assert result.source == "class A(Scene):\n    def construct(self):\n        a = 1; b = 2\n\n"

    def test_multi_line_statement(self):
        source = (
            "class A(Scene):\n    def construct(self):\n"
            "        self.play(\n            Create(Circle()),\n            run_time=2,\n        )\n"
            "        self.wait()\n"
        )
        result = truncate(source, 4)
        assert result is not None and result.last_line == 6 and result.statements_kept == 1
        assert "self.wait()" not in result.source
        same_lines(source, result.source)

    def test_a_triple_quoted_string_statement(self):
        source = 'class A(Scene):\n    def construct(self):\n        a = """x\ny"""\n        b = 2\n'
        result = truncate(source, 5)
        assert result is not None and result.statements_kept == 2

    def test_a_bom_is_kept(self):
        bom = chr(0xFEFF)
        result = truncate(bom + SCENE, line_of(SCENE, "Create(circle)"))
        assert result is not None
        assert result.source.startswith(bom + "from manim")
        assert "square" not in result.source

    def test_a_missing_final_newline(self):
        source = "class A(Scene):\n    def construct(self):\n        a = 1\n        b = 2"
        result = truncate(source, 3)
        assert (
            result is not None
            and result.source == "class A(Scene):\n    def construct(self):\n        a = 1\n"
        )

    def test_a_nested_class_scene_is_not_used(self):
        source = "class Outer:\n    class A(Scene):\n        def construct(self):\n            x = 1\n"
        assert truncate(source, 4) is None

    @pytest.mark.parametrize("line", range(1, 27))
    def test_every_line_gives_a_valid_program_or_none(self, line):
        result = truncate(SCENE, line)
        if result is not None:
            ast.parse(result.source)
            same_lines(SCENE, result.source)
            assert result.statements_kept <= result.statements_total
            assert 1 <= result.last_line <= len(SCENE.split("\n"))
