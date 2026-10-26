"""Code files (P12.1): reading, inspecting and exporting .py files."""

from __future__ import annotations

import codecs

import pytest

from manim_studio.core.exchange import code_files
from manim_studio.core.exchange.code_files import (
    SourceError,
    export_files,
    free_name,
    inspect,
    read_source,
    safe_stem,
)

OBJECT = '''"""A right triangle, marked."""

PARAMS = {"angle": (30.0, 5.0, 85.0), "label": "ab", "show": True, "colour": "#ff0000"}


def build(p):
    return Polygon(ORIGIN, RIGHT, UP)
'''

SCENE = """from manim import *


class SquareToCircle(Scene):
    def construct(self):
        self.play(Create(Square()))


class Second(SquareToCircle):
    pass
"""


def keep_all(name):  # a decide that must not be asked
    raise AssertionError(f"decide called for {name}")


# -- read_source ---------------------------------------------------------------------------------------


class TestReadSource:
    def test_plain(self, tmp_path):
        path = tmp_path / "a.py"
        path.write_bytes("x = 'é'\n".encode())
        assert read_source(path) == "x = 'é'\n"

    def test_bom_is_dropped(self, tmp_path):
        path = tmp_path / "a.py"
        path.write_bytes(codecs.BOM_UTF8 + b"x = 1\n")
        assert read_source(path) == "x = 1\n"

    def test_crlf_is_kept(self, tmp_path):
        path = tmp_path / "a.py"
        path.write_bytes(b"x = 1\r\ny = 2\r\n")
        assert read_source(str(path)) == "x = 1\r\ny = 2\r\n"

    def test_empty_file(self, tmp_path):
        path = tmp_path / "a.py"
        path.write_bytes(b"")
        assert read_source(path) == ""

    def test_limit_is_one_megabyte(self, tmp_path):
        ok = tmp_path / "ok.py"
        ok.write_bytes(b"#" * code_files.MAX_BYTES)
        assert len(read_source(ok)) == code_files.MAX_BYTES
        big = tmp_path / "big.py"
        big.write_bytes(b"#" * (code_files.MAX_BYTES + 1))
        with pytest.raises(SourceError, match="too large") as caught:
            read_source(big)
        assert "big.py" in caught.value.reason

    def test_missing_file(self, tmp_path):
        with pytest.raises(SourceError, match=r"cannot read nope\.py"):
            read_source(tmp_path / "nope.py")

    def test_a_folder(self, tmp_path):
        with pytest.raises(SourceError):
            read_source(tmp_path)

    def test_not_utf8(self, tmp_path):
        path = tmp_path / "latin.py"
        path.write_bytes("x = 'é'".encode("latin-1"))
        with pytest.raises(SourceError, match="not UTF-8"):
            read_source(path)

    def test_binary_file(self, tmp_path):
        path = tmp_path / "bin.py"
        path.write_bytes(b"abc\x00def")
        with pytest.raises(SourceError, match="not a text file"):
            read_source(path)

    def test_reason_is_the_message(self):
        assert str(SourceError("why")) == "why"


# -- inspect -------------------------------------------------------------------------------------------


class TestInspect:
    def test_object(self):
        found = inspect(OBJECT, "tri.py")
        assert found.kind == "object"
        assert found.scenes == ()
        assert found.problem is None
        assert [(p.name, p.kind, p.default) for p in found.params] == [
            ("angle", "float", 30.0),
            ("label", "text", "ab"),
            ("show", "bool", True),
            ("colour", "colour", "#ff0000"),
        ]
        assert found.suggested_name == "Tri"
        assert found.summary == "A right triangle, marked."

    def test_build_without_params_is_an_object(self):
        found = inspect("def build(p):\n    return Circle()\n")
        assert found.kind == "object"
        assert found.params == ()

    def test_params_without_build_is_still_an_object(self):
        assert inspect("PARAMS = {'a': 1}\n").kind == "object"
        assert inspect("PARAMS: dict = {'a': 1}\n").kind == "object"

    def test_nested_build_is_not_an_object(self):
        assert inspect("class A:\n    def build(self): ...\n").kind == "unknown"

    def test_scene(self):
        found = inspect(SCENE, "demo.py")
        assert found.kind == "scene"
        assert found.scenes == ("SquareToCircle", "Second")
        assert found.params == ()
        assert found.suggested_name == "SquareToCircle"

    def test_scene_wins_over_object(self):
        found = inspect(SCENE + "\nPARAMS = {'a': 1}\n\ndef build(p):\n    pass\n")
        assert found.kind == "scene"
        assert found.params == ()

    def test_unknown(self):
        found = inspect("x = 1\nprint(x)\n", "notes.py")
        assert found.kind == "unknown"
        assert found.problem is None
        assert found.suggested_name == "Notes"

    def test_empty(self):
        found = inspect("")
        assert (found.kind, found.problem, found.suggested_name, found.summary) == (
            "unknown",
            None,
            "Code",
            "",
        )

    def test_syntax_error_has_a_line(self):
        found = inspect("x = 1\ndef build(p:\n    pass\n", "broken.py")
        assert found.kind == "unknown"
        assert found.problem is not None
        assert found.problem.startswith("line 2: SyntaxError")
        assert found.suggested_name == "Broken"

    def test_nul_character_is_a_problem_not_a_crash(self):
        found = inspect("x = 1\x00\n")
        assert found.kind == "unknown"
        assert found.problem is not None and "SyntaxError" in found.problem

    def test_unreadable_params_are_a_problem_of_an_object(self):
        found = inspect("PARAMS = {'a': foo()}\n\ndef build(p):\n    pass\n")
        assert found.kind == "object"
        assert found.params == ()
        assert found.problem is not None and "line 1" in found.problem

    def test_bom_in_the_text_is_ignored(self):
        assert inspect("\ufeff" + OBJECT).kind == "object"

    def test_crlf_text(self):
        found = inspect(OBJECT.replace("\n", "\r\n"))
        assert found.kind == "object"
        assert found.summary == "A right triangle, marked."

    def test_code_is_never_run(self, tmp_path):
        marker = tmp_path / "ran"
        source = f"open({str(marker)!r}, 'w').write('x')\nPARAMS = {{'a': 1}}\n\ndef build(p):\n    pass\n"
        assert inspect(source).kind == "object"
        assert not marker.exists()

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("right_triangle.py", "Right Triangle"),
            ("my-scene.PY", "My Scene"),
            ("MyScene.py", "MyScene"),
            (r"C:\work\two_words.py", "Two Words"),
            ("/home/me/x.py", "X"),
            ("__init__.py", "Init"),
            ("", "Code"),
            (".py", "Code"),
            (".hidden.py", "Hidden"),
        ],
    )
    def test_name_from_the_file(self, filename, expected):
        assert inspect("x = 1\n", filename).suggested_name == expected

    def test_name_from_the_scene_beats_the_file(self):
        assert inspect(SCENE, "other.py").suggested_name == "SquareToCircle"

    def test_summary_from_a_leading_comment(self):
        found = inspect(
            "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\n\n#\n# A matrix of any size.\n# More.\nx = 1\n"
        )
        assert found.summary == "A matrix of any size."

    def test_summary_docstring_first_line(self):
        found = inspect('# a comment\n"""\n  The docstring line.\n\nMore.\n"""\n')
        assert found.summary == "The docstring line."

    def test_comment_after_code_is_not_a_summary(self):
        assert inspect("x = 1\n# later\n").summary == ""

    def test_summary_is_at_most_120_characters(self):
        found = inspect("# " + "word " * 80 + "\n")
        assert len(found.summary) == 120
        assert found.summary.endswith("\u2026")

    def test_summary_of_broken_code_comes_from_its_comment(self):
        assert inspect("# Broken one\ndef (:\n").summary == "Broken one"

    def test_inspection_is_frozen(self):
        with pytest.raises(AttributeError):
            inspect("x = 1").kind = "scene"  # type: ignore[misc]


# -- safe_stem / free_name -------------------------------------------------------------------------------


class TestSafeStem:
    def test_plain_names_are_unchanged(self):
        assert safe_stem("Right triangle", "x") == "Right triangle"
        assert safe_stem("a.b", "x") == "a.b"

    def test_forbidden_characters_are_removed(self):
        assert safe_stem('a<b>c:d"e/f\\g|h?i*j', "x") == "abcdefghij"

    def test_control_characters_are_removed(self):
        assert safe_stem("a\x00b\x1fc\nd\x7fe", "x") == "abcde"

    def test_trailing_dots_and_spaces(self):
        assert safe_stem("name. . ", "x") == "name"
        assert safe_stem("  name  ", "x") == "name"

    @pytest.mark.parametrize("name", ["CON", "con", "Prn", "AUX", "nul", "COM1", "com9", "LPT1", "lpt9"])
    def test_reserved_names(self, name):
        stem = safe_stem(name, "x")
        assert stem == f"{name}_"
        assert stem.upper() not in code_files.RESERVED

    def test_reserved_name_before_a_dot(self):
        stem = safe_stem("con.test", "x")
        assert stem == "con_.test"

    def test_names_that_only_start_like_reserved_ones_are_fine(self):
        assert safe_stem("CONSOLE", "x") == "CONSOLE"
        assert safe_stem("COM10", "x") == "COM10"
        assert safe_stem("Auxiliary", "x") == "Auxiliary"

    def test_empty_uses_the_fallback(self):
        assert safe_stem("", "Fallback") == "Fallback"
        assert safe_stem('<>:"', "Fallback") == "Fallback"
        assert safe_stem("...", "Fallback") == "Fallback"

    def test_fallback_is_cleaned_too(self):
        assert safe_stem("", "NUL") == "NUL_"
        assert safe_stem("", "") == "Code"
        assert safe_stem("", "?") == "Code"

    def test_default_fallback(self):
        assert safe_stem("") == "Code"

    def test_long_names_are_cut(self):
        assert len(safe_stem("x" * 500, "y")) == code_files.MAX_STEM

    def test_unicode_is_kept(self):
        assert safe_stem("Função área", "x") == "Função área"


class TestFreeName:
    def test_free(self):
        assert free_name("A.py", []) == "A.py"
        assert free_name("A.py", ["B.py"]) == "A.py"

    def test_taken(self):
        assert free_name("A.py", ["A.py"]) == "A (2).py"

    def test_case_insensitive(self):
        assert free_name("Name.py", ["name.PY"]) == "Name (2).py"

    def test_counts_up(self):
        assert free_name("A.py", ["A.py", "A (2).py", "a (3).py"]) == "A (4).py"

    def test_a_gap_is_used(self):
        assert free_name("A.py", ["A.py", "A (3).py"]) == "A (2).py"

    def test_without_extension(self):
        assert free_name("A", ["a"]) == "A (2)"

    def test_taken_may_be_an_iterator(self):
        assert free_name("A.py", iter(["A.py"])) == "A (2).py"


# -- export_files ----------------------------------------------------------------------------------------


def listing(folder):
    return sorted(p.name for p in folder.iterdir())


class TestExport:
    def test_writes_new_files(self, tmp_path):
        result = export_files([("One", "a = 1\n"), ("Two", "b = 2\n")], tmp_path, keep_all)
        assert result.written == ("One.py", "Two.py")
        assert result.replaced == result.copied == result.skipped == result.failed == ()
        assert not result.cancelled
        assert result.saved == 2
        assert (tmp_path / "One.py").read_text(encoding="utf-8") == "a = 1\n"
        assert listing(tmp_path) == ["One.py", "Two.py"]

    def test_creates_the_folder(self, tmp_path):
        folder = tmp_path / "new" / "deeper"
        result = export_files([("A", "x")], folder, keep_all)
        assert result.written == ("A.py",)
        assert (folder / "A.py").is_file()

    def test_utf8_without_bom_and_line_endings_kept(self, tmp_path):
        export_files([("A", "x = 'é'\r\ny = 1\n")], tmp_path, keep_all)
        data = (tmp_path / "A.py").read_bytes()
        assert data == "x = 'é'\r\ny = 1\n".encode()
        assert not data.startswith(codecs.BOM_UTF8)

    def test_empty_items(self, tmp_path):
        result = export_files([], tmp_path, keep_all)
        assert result == code_files.ExportResult()

    def test_stems_are_made_safe(self, tmp_path):
        result = export_files([("a/b?", "x"), ("CON", "y"), ("", "z")], tmp_path, keep_all)
        assert result.written == ("ab.py", "CON_.py", "Code.py")

    def test_decide_is_not_asked_without_a_conflict(self, tmp_path):
        asked = []
        export_files([("A", "x")], tmp_path, lambda name: asked.append(name) or "skip")
        assert asked == []

    def test_replace(self, tmp_path):
        (tmp_path / "A.py").write_text("old", encoding="utf-8")
        asked = []
        result = export_files([("A", "new")], tmp_path, lambda name: asked.append(name) or "replace")
        assert asked == ["A.py"]
        assert result.replaced == ("A.py",)
        assert result.written == ()
        assert (tmp_path / "A.py").read_text(encoding="utf-8") == "new"

    def test_skip(self, tmp_path):
        (tmp_path / "A.py").write_text("old", encoding="utf-8")
        result = export_files([("A", "new"), ("B", "b")], tmp_path, lambda name: "skip")
        assert result.skipped == ("A.py",)
        assert result.written == ("B.py",)
        assert not result.cancelled
        assert (tmp_path / "A.py").read_text(encoding="utf-8") == "old"

    def test_copy_keeps_both(self, tmp_path):
        (tmp_path / "A.py").write_text("old", encoding="utf-8")
        result = export_files([("A", "new")], tmp_path, lambda name: "copy")
        assert result.copied == ("A (2).py",)
        assert (tmp_path / "A.py").read_text(encoding="utf-8") == "old"
        assert (tmp_path / "A (2).py").read_text(encoding="utf-8") == "new"

    def test_copy_skips_a_copy_name_already_there(self, tmp_path):
        (tmp_path / "A.py").write_text("old", encoding="utf-8")
        (tmp_path / "A (2).py").write_text("older", encoding="utf-8")
        result = export_files([("A", "new")], tmp_path, lambda name: "copy")
        assert result.copied == ("A (3).py",)
        assert (tmp_path / "A (2).py").read_text(encoding="utf-8") == "older"

    def test_conflict_is_found_whatever_the_letter_case(self, tmp_path):
        (tmp_path / "a.py").write_text("old", encoding="utf-8")
        asked = []
        export_files([("A", "new")], tmp_path, lambda name: asked.append(name) or "skip")
        assert asked == ["A.py"]

    def test_same_stem_twice_never_overwrites(self, tmp_path):
        result = export_files([("Same", "first"), ("Same", "second"), ("same", "third")], tmp_path, keep_all)
        assert result.written == ("Same.py",)
        assert result.copied == ("Same (2).py", "same (3).py")
        assert (tmp_path / "Same.py").read_text(encoding="utf-8") == "first"
        assert (tmp_path / "Same (2).py").read_text(encoding="utf-8") == "second"
        assert (tmp_path / "same (3).py").read_text(encoding="utf-8") == "third"

    def test_same_stem_twice_over_an_existing_file(self, tmp_path):
        (tmp_path / "Same.py").write_text("old", encoding="utf-8")
        asked = []
        result = export_files(
            [("Same", "first"), ("Same", "second")], tmp_path, lambda name: asked.append(name) or "replace"
        )
        assert asked == ["Same.py"]  # only the one that meets the file on disk is asked
        assert result.replaced == ("Same.py",)
        assert result.copied == ("Same (2).py",)
        assert (tmp_path / "Same.py").read_text(encoding="utf-8") == "first"

    def test_copy_choice_then_same_stem_does_not_collide(self, tmp_path):
        (tmp_path / "A.py").write_text("old", encoding="utf-8")
        result = export_files([("A", "one"), ("A", "two")], tmp_path, lambda name: "copy")
        assert (
            result.copied == ("A (2).py", "A (3).py") or len(set(result.copied) | set(result.replaced)) == 2
        )
        contents = {p.name: p.read_text(encoding="utf-8") for p in tmp_path.iterdir()}
        assert sorted(contents.values()) == ["old", "one", "two"]

    def test_cancel_stops_the_rest(self, tmp_path):
        (tmp_path / "B.py").write_text("old", encoding="utf-8")
        items = [("A", "a"), ("B", "b"), ("C", "c"), ("C", "c2")]
        result = export_files(items, tmp_path, lambda name: None)
        assert result.cancelled
        assert result.written == ("A.py",)
        assert result.skipped == ("B.py", "C.py", "C (2).py")
        assert listing(tmp_path) == ["A.py", "B.py"]
        assert (tmp_path / "B.py").read_text(encoding="utf-8") == "old"

    def test_cancel_after_a_decision_for_all(self, tmp_path):
        for name in ("A", "B", "C"):
            (tmp_path / f"{name}.py").write_text("old", encoding="utf-8")
        answers = iter(["replace", None])
        result = export_files([("A", "n"), ("B", "n"), ("C", "n")], tmp_path, lambda name: next(answers))
        assert result.replaced == ("A.py",)
        assert result.skipped == ("B.py", "C.py")
        assert result.cancelled
        assert (tmp_path / "C.py").read_text(encoding="utf-8") == "old"

    def test_no_temporary_files_are_left(self, tmp_path):
        (tmp_path / "A.py").write_text("old", encoding="utf-8")
        export_files([("A", "new"), ("B", "b"), ("B", "b2")], tmp_path, lambda name: "replace")
        assert listing(tmp_path) == ["A.py", "B (2).py", "B.py"]

    def test_failure_does_not_touch_the_old_file_or_leave_temporaries(self, tmp_path, monkeypatch):
        (tmp_path / "A.py").write_text("old", encoding="utf-8")
        real = code_files.os.replace

        def broken(src, dst):
            if str(dst).endswith("A.py"):
                raise PermissionError(13, "Permission denied")
            real(src, dst)

        monkeypatch.setattr(code_files.os, "replace", broken)
        result = export_files([("A", "new"), ("B", "b")], tmp_path, lambda name: "replace")
        assert result.failed == (("A.py", "Permission denied"),)
        assert result.written == ("B.py",)
        assert result.replaced == ()
        assert not result.cancelled
        assert (tmp_path / "A.py").read_text(encoding="utf-8") == "old"
        assert listing(tmp_path) == ["A.py", "B.py"]

    def test_replacing_a_folder_fails_cleanly(self, tmp_path):
        (tmp_path / "A.py").mkdir()
        result = export_files([("A", "x"), ("B", "y")], tmp_path, lambda name: "replace")
        assert [name for name, _ in result.failed] == ["A.py"]
        assert result.failed[0][1]
        assert result.written == ("B.py",)
        assert listing(tmp_path) == ["A.py", "B.py"]

    def test_text_that_cannot_be_encoded_is_a_failure(self, tmp_path):
        result = export_files([("A", "x = '\ud800'"), ("B", "ok")], tmp_path, keep_all)
        assert [name for name, _ in result.failed] == ["A.py"]
        assert result.written == ("B.py",)
        assert listing(tmp_path) == ["B.py"]

    def test_a_folder_that_cannot_be_made_fails_every_file(self, tmp_path):
        blocker = tmp_path / "file"
        blocker.write_text("x", encoding="utf-8")
        result = export_files([("A", "x"), ("B", "y")], blocker / "inside", keep_all)
        assert [name for name, _ in result.failed] == ["A.py", "B.py"]
        assert result.saved == 0

    def test_result_is_frozen(self):
        result = code_files.ExportResult()
        with pytest.raises(AttributeError):
            result.cancelled = True  # type: ignore[misc]
