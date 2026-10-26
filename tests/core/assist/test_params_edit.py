"""Editing PARAMS in a Python object's source (P13.3): only the entry changed is touched."""

from __future__ import annotations

import pytest

from manim_studio.core.assist.params_edit import (
    UNCHANGED,
    AddParam,
    ChangeParam,
    ParamsEditError,
    RemoveParam,
    RenameParam,
    edit_params,
    format_value,
    read_layout,
)
from manim_studio.core.code import python_object, python_templates

BUILD = '\n\ndef build(p):\n    return Circle(radius=p["r"])\n'

SINGLE = 'PARAMS = {"r": 1.0, "n": 3}' + BUILD
MULTI = (
    "# the circle\n"
    "PARAMS = {\n"
    "    # radius first\n"
    '    "r": (1.0, 0.5, 4.0),  # the radius\n'
    "\n"
    '    "n": 3,\n'
    '    "name": "é ü",  # unicode: ção\n'
    "}\n" + BUILD
)
NO_COMMA = 'PARAMS = {\n    "r": 1.0,\n    "n": 3  # last\n}\n' + BUILD
CRLF = MULTI.replace("\n", "\r\n")
TABS = MULTI.replace("    ", "\t")
EMPTY = "PARAMS = {}" + BUILD
EMPTY_MULTI = "PARAMS = {\n}" + BUILD
NESTED = (
    "PARAMS = {\n"
    '    "a": (30.0, 5.0, 85.0),\n'
    '    "b": (3, 1, 8),\n'
    '    "c": (\n        2.0,\n        0.0,\n        5.0,\n    ),\n'
    '    "d": True,\n'
    "}\n" + BUILD
)

FIXTURES = {
    "single": SINGLE,
    "multi": MULTI,
    "no-comma": NO_COMMA,
    "crlf": CRLF,
    "tabs": TABS,
    "empty": EMPTY,
    "empty-multi": EMPTY_MULTI,
    "nested": NESTED,
}


def params(source: str) -> dict:
    return {p.name: (p.kind, p.default, p.minimum, p.maximum) for p in python_object.read_params(source)}


def outside(old: str, new: str) -> tuple[str, str]:
    """What ``old`` and ``new`` share before and after the part that differs."""
    n = min(len(old), len(new))
    i = 0
    while i < n and old[i] == new[i]:
        i += 1
    j = 0
    while j < n - i and old[-1 - j] == new[-1 - j]:
        j += 1
    return old[:i], old[len(old) - j :]


def assert_only_changed(old: str, new: str, marker: str) -> None:
    """``new`` differs from ``old`` only in the part that mentions ``marker`` (and its neighbours)."""
    before, after = outside(old, new)
    assert before and after.endswith(BUILD[-20:])
    changed = new[len(before) : len(new) - len(after)] + old[len(before) : len(old) - len(after)]
    assert marker in changed or marker == ""


class TestFormat:
    @pytest.mark.parametrize(
        ("args", "text"),
        [
            ((30.0,), "30.0"),
            ((0.25,), "0.25"),
            ((6,), "6"),
            ((True,), "True"),
            ((False,), "False"),
            (("ab",), '"ab"'),
            (("#ff0000",), '"#ff0000"'),
            ((3, 1, 8), "(3, 1, 8)"),
            ((30.0, 5.0, 85.0), "(30.0, 5.0, 85.0)"),
            ((30, 5.0, 85), "(30.0, 5.0, 85.0)"),
            ((1.5, 0, 3), "(1.5, 0.0, 3.0)"),
            (('say "hi"\n',), '"say \\"hi\\"\\n"'),
            (("ção",), '"ção"'),
            (("\\frac{a}{b}",), '"\\\\frac{a}{b}"'),
        ],
    )
    def test_values(self, args, text):
        assert format_value(*args) == text

    @pytest.mark.parametrize(
        "args",
        [
            (float("nan"),),
            (float("inf"),),
            ([1],),
            (None,),
            ("text", 0, 1),
            (True, 0, 1),
            (5, 0.0, None),
            (5, None, 9),
            (10, 0, 5),
            (1, "a", 3),
        ],
    )
    def test_refused(self, args):
        with pytest.raises(ParamsEditError):
            format_value(*args)


class TestReadLayout:
    def test_none_without_params(self):
        assert read_layout("x = 1\n") is None
        assert read_layout("PARAMS = ") is None  # a syntax error
        assert read_layout("") is None

    def test_entries_and_spans(self):
        layout = read_layout(MULTI)
        assert layout is not None
        assert [e.key for e in layout.entries] == ["r", "n", "name"]
        first = layout.entries[0]
        assert MULTI[first.key_start : first.key_end] == '"r"'
        assert first.value_text == "(1.0, 0.5, 4.0)"
        assert MULTI[first.value_start : first.value_end] == first.value_text
        assert first.comment == "the radius"
        assert first.own_line and first.comma is not None
        assert MULTI[layout.dict_start] == "{" and MULTI[layout.dict_end - 1] == "}"
        assert MULTI[layout.start :].startswith("PARAMS")
        assert layout.multiline and layout.trailing_comma
        assert layout.indent == "    "
        assert layout.newline == "\n"
        assert layout.entries[2].comment == "unicode: ção"

    def test_single_line(self):
        layout = read_layout(SINGLE)
        assert layout is not None
        assert not layout.multiline and not layout.trailing_comma
        assert [e.own_line for e in layout.entries] == [False, False]
        assert [e.value_text for e in layout.entries] == ["1.0", "3"]

    def test_crlf_and_tabs(self):
        layout = read_layout(CRLF)
        assert layout is not None and layout.newline == "\r\n"
        assert CRLF[layout.entries[0].key_start : layout.entries[0].key_end] == '"r"'
        assert read_layout(TABS).indent == "\t"

    def test_offsets_count_characters_not_bytes(self):
        source = '# ação é\nPARAMS = {"é": 1, "z": 2}\n'
        layout = read_layout(source)
        assert layout is not None
        assert [source[e.key_start : e.key_end] for e in layout.entries] == ['"é"', '"z"']

    def test_bom(self):
        source = "\ufeff" + SINGLE
        layout = read_layout(source)
        assert layout is not None
        assert source[layout.entries[0].key_start : layout.entries[0].key_end] == '"r"'
        assert edit_params(source, AddParam("k", 2)).startswith("\ufeff")

    def test_empty(self):
        layout = read_layout(EMPTY)
        assert layout is not None and layout.entries == ()

    def test_parenthesised_value(self):
        source = 'PARAMS = {"a": ("x"), "b": 2}\n'
        layout = read_layout(source)
        assert layout is not None
        assert edit_params(source, RemoveParam("a")) == 'PARAMS = {"b": 2}\n'

    def test_annotated_assignment(self):
        source = 'PARAMS: dict = {"a": 1}\n'
        assert edit_params(source, AddParam("b", 2)) == 'PARAMS: dict = {"a": 1, "b": 2}\n'

    def test_last_assignment_wins(self):
        source = 'PARAMS = {"old": 1}\nPARAMS = {"a": 1}\n'
        assert edit_params(source, AddParam("b", 2)) == 'PARAMS = {"old": 1}\nPARAMS = {"a": 1, "b": 2}\n'

    def test_unsupported_shapes_raise(self):
        for source in ("PARAMS = dict(a=1)\n", 'PARAMS = {**BASE, "a": 1}\n', "PARAMS = {A: 1}\n"):
            with pytest.raises(ParamsEditError):
                read_layout(source)


class TestAdd:
    def test_single_line(self):
        new = edit_params(SINGLE, AddParam("size", 2.0, 0.5, 5.0))
        assert new == 'PARAMS = {"r": 1.0, "n": 3, "size": (2.0, 0.5, 5.0)}' + BUILD

    def test_single_line_with_trailing_comma(self):
        new = edit_params('PARAMS = {"a": 1,}\n', AddParam("b", "x"))
        assert new == 'PARAMS = {"a": 1, "b": "x",}\n'

    def test_multi_line_keeps_the_style(self):
        new = edit_params(MULTI, AddParam("show", True))
        assert new == MULTI.replace("}\n" + BUILD, '    "show": True,\n}\n' + BUILD)
        assert params(new)["show"][0] == "bool"

    def test_multi_line_without_trailing_comma(self):
        new = edit_params(NO_COMMA, AddParam("k", 7))
        assert new == 'PARAMS = {\n    "r": 1.0,\n    "n": 3,  # last\n    "k": 7\n}\n' + BUILD

    def test_crlf_is_kept(self):
        new = edit_params(CRLF, AddParam("k", 2))
        assert '    "k": 2,\r\n}' in new
        assert "\n" not in new.replace("\r\n", "")
        assert params(new)["k"] == ("int", 2, None, None)

    def test_tabs_are_kept(self):
        new = edit_params(TABS, AddParam("k", 2))
        assert '\t"k": 2,\n}' in new

    def test_to_an_empty_dict(self):
        assert edit_params(EMPTY, AddParam("k", 2.5)) == 'PARAMS = {"k": 2.5}' + BUILD

    def test_to_an_empty_multi_line_dict(self):
        assert edit_params(EMPTY_MULTI, AddParam("k", 2.5)) == 'PARAMS = {\n    "k": 2.5,\n}' + BUILD

    def test_after_a_comment_on_the_last_entry(self):
        new = edit_params(MULTI, AddParam("k", 1))
        assert '"name": "é ü",  # unicode: ção\n    "k": 1,\n}' in new

    def test_kinds(self):
        source = "PARAMS = {}\n"
        for default, kind in (
            (1.5, "float"),
            (4, "int"),
            (False, "bool"),
            ("t", "text"),
            ("#00ff00", "colour"),
        ):
            new = edit_params(source, AddParam("k", default))
            assert params(new)["k"][:2] == (kind, default)

    def test_range_is_a_tuple(self):
        new = edit_params(SINGLE, AddParam("k", 5, 1, 9))
        assert params(new)["k"] == ("int", 5, 1, 9)

    @pytest.mark.parametrize("name", ["", "1a", "a b", "a-b", "a.b", "ç ã"])
    def test_bad_names(self, name):
        with pytest.raises(ParamsEditError, match="name"):
            edit_params(SINGLE, AddParam(name, 1))

    def test_existing_name(self):
        with pytest.raises(ParamsEditError, match="already"):
            edit_params(SINGLE, AddParam("r", 1))

    def test_a_unicode_identifier_is_fine(self):
        new = edit_params(SINGLE, AddParam("ângulo", 1.0))
        assert "ângulo" in params(new)

    def test_text_with_quotes_and_backslashes_round_trips(self):
        new = edit_params(SINGLE, AddParam("t", 'a"b\\c\n'))
        assert python_object.read_params(new)[-1].default == 'a"b\\c\n'

    def test_nothing_else_changes(self):
        new = edit_params(MULTI, AddParam("k", 1))
        before, after = outside(MULTI, new)
        assert before + after == MULTI[: len(before)] + MULTI[len(MULTI) - len(after) :]
        assert new.startswith(MULTI[: MULTI.index("}\n" + BUILD)])
        assert new.endswith("}\n" + BUILD)


class TestRemove:
    def test_single_line_middle_and_last(self):
        assert edit_params(SINGLE, RemoveParam("r")) == 'PARAMS = {"n": 3}' + BUILD
        assert edit_params(SINGLE, RemoveParam("n")) == 'PARAMS = {"r": 1.0}' + BUILD

    def test_only_entry(self):
        assert edit_params('PARAMS = {"a": 1}\n', RemoveParam("a")) == "PARAMS = {}\n"
        assert edit_params('PARAMS = {"a": 1,}\n', RemoveParam("a")) == "PARAMS = {}\n"

    def test_only_entry_multi_line(self):
        assert edit_params('PARAMS = {\n    "a": 1,\n}\n', RemoveParam("a")) == "PARAMS = {\n}\n"

    def test_first_entry_takes_its_line_and_comment(self):
        new = edit_params(MULTI, RemoveParam("r"))
        assert '"r": (' not in new and "the radius" not in new
        assert "# radius first\n" in new  # a comment on a line of its own stays
        assert [p for p in params(new)] == ["n", "name"]

    def test_last_entry(self):
        new = edit_params(MULTI, RemoveParam("name"))
        assert "unicode" not in new
        assert new.endswith('    "n": 3,\n}\n' + BUILD)

    def test_last_entry_without_trailing_comma_takes_the_comma_before_it(self):
        new = edit_params(NO_COMMA, RemoveParam("n"))
        assert new == 'PARAMS = {\n    "r": 1.0\n}\n' + BUILD

    def test_blank_lines_are_kept(self):
        new = edit_params(MULTI, RemoveParam("n"))
        assert '(1.0, 0.5, 4.0),  # the radius\n\n    "name"' in new

    def test_crlf(self):
        new = edit_params(CRLF, RemoveParam("n"))
        assert "\n" not in new.replace("\r\n", "")
        assert list(params(new)) == ["r", "name"]

    def test_multi_line_value(self):
        new = edit_params(NESTED, RemoveParam("c"))
        assert new == NESTED.replace('    "c": (\n        2.0,\n        0.0,\n        5.0,\n    ),\n', "")

    def test_unknown_name(self):
        with pytest.raises(ParamsEditError, match="no parameter"):
            edit_params(SINGLE, RemoveParam("zzz"))

    def test_entries_sharing_a_line_with_the_brace(self):
        source = 'PARAMS = {"a": 1,\n          "b": 2}\n'
        assert edit_params(source, RemoveParam("b")) == 'PARAMS = {"a": 1}\n'
        assert list(params(edit_params(source, RemoveParam("a")))) == ["b"]

    def test_comment_after_an_inline_entry_goes_with_it(self):
        source = 'PARAMS = {"a": 1, "b": 2,  # about b\n          "c": 3}\n'
        new = edit_params(source, RemoveParam("b"))
        assert "about b" not in new
        assert list(params(new)) == ["a", "c"]


class TestRename:
    def test_renames_only_the_key(self):
        new = edit_params(MULTI, RenameParam("r", "radius"))
        assert new == MULTI.replace('"r": (', '"radius": (')

    def test_single_quotes_stay_single(self):
        assert edit_params("PARAMS = {'a': 1}\n", RenameParam("a", "b")) == "PARAMS = {'b': 1}\n"

    def test_keeps_order_value_and_comment(self):
        new = edit_params(MULTI, RenameParam("n", "count"))
        assert list(params(new)) == ["r", "count", "name"]
        assert params(new)["count"] == params(MULTI)["n"]

    def test_same_name_is_a_no_op(self):
        assert edit_params(SINGLE, RenameParam("r", "r")) == SINGLE

    def test_new_name_exists(self):
        with pytest.raises(ParamsEditError, match="already"):
            edit_params(SINGLE, RenameParam("r", "n"))

    @pytest.mark.parametrize("new", ["", "a b", "1x", "x-y"])
    def test_new_name_not_an_identifier(self, new):
        with pytest.raises(ParamsEditError, match="name"):
            edit_params(SINGLE, RenameParam("r", new))

    def test_unknown_old_name(self):
        with pytest.raises(ParamsEditError, match="no parameter"):
            edit_params(SINGLE, RenameParam("zzz", "q"))

    def test_the_build_code_is_not_touched(self):
        assert edit_params(SINGLE, RenameParam("r", "q")).endswith(BUILD)

    def test_swap_through_a_temporary_name(self):
        step = edit_params(SINGLE, RenameParam("r", "tmp"))
        step = edit_params(step, RenameParam("n", "r"))
        step = edit_params(step, RenameParam("tmp", "n"))
        assert params(step) == {"r": ("int", 3, None, None), "n": ("float", 1.0, None, None)}


class TestChange:
    def test_default_only_keeps_the_limits(self):
        new = edit_params(MULTI, ChangeParam("r", default=2.0))
        assert new == MULTI.replace("(1.0, 0.5, 4.0)", "(2.0, 0.5, 4.0)")

    def test_limits_only(self):
        new = edit_params(MULTI, ChangeParam("r", minimum=0.1, maximum=9.0))
        assert new == MULTI.replace("(1.0, 0.5, 4.0)", "(1.0, 0.1, 9.0)")

    def test_one_limit(self):
        new = edit_params(MULTI, ChangeParam("r", maximum=6.0))
        assert new == MULTI.replace("(1.0, 0.5, 4.0)", "(1.0, 0.5, 6.0)")

    def test_unchanged_text_of_numbers_is_kept(self):
        source = 'PARAMS = {"a": (1e1, 0.0, 1e2)}\n'
        assert edit_params(source, ChangeParam("a", minimum=2.0)) == 'PARAMS = {"a": (1e1, 2.0, 1e2)}\n'

    def test_remove_the_limits(self):
        new = edit_params(MULTI, ChangeParam("r", minimum=None, maximum=None))
        assert new == MULTI.replace("(1.0, 0.5, 4.0)", "1.0")
        assert params(new)["r"] == ("float", 1.0, None, None)

    def test_add_limits(self):
        new = edit_params(SINGLE, ChangeParam("n", minimum=1, maximum=9))
        assert params(new)["n"] == ("int", 3, 1, 9)
        assert new.startswith('PARAMS = {"r": 1.0, "n": (3, 1, 9)}')

    def test_one_limit_alone_cannot_be_written(self):
        with pytest.raises(ParamsEditError, match="both"):
            edit_params(SINGLE, ChangeParam("n", minimum=1))

    def test_whole_to_float_limits(self):
        new = edit_params(NESTED, ChangeParam("b", minimum=0.5))
        assert params(new)["b"] == ("float", 3.0, 0.5, 8.0)

    def test_new_default_outside_the_limits(self):
        with pytest.raises(ParamsEditError, match="not from"):
            edit_params(MULTI, ChangeParam("r", default=9.0))

    def test_change_the_type(self):
        new = edit_params(MULTI, ChangeParam("r", default="#ff0000"))
        assert params(new)["r"] == ("colour", "#ff0000", None, None)
        assert new == MULTI.replace("(1.0, 0.5, 4.0)", '"#ff0000"')

    def test_change_the_type_to_a_number_with_limits(self):
        new = edit_params(MULTI, ChangeParam("name", default=5, minimum=1, maximum=9))
        assert params(new)["name"] == ("int", 5, 1, 9)

    def test_limits_with_a_default_that_is_not_a_number(self):
        with pytest.raises(ParamsEditError, match="limits"):
            edit_params(MULTI, ChangeParam("r", default="x", minimum=1.0, maximum=2.0))

    def test_bool_to_int(self):
        new = edit_params(NESTED, ChangeParam("d", default=4))
        assert params(new)["d"] == ("int", 4, None, None)

    def test_same_value_is_a_no_op(self):
        assert edit_params(MULTI, ChangeParam("r", default=1.0)) == MULTI
        assert edit_params(MULTI, ChangeParam("r")) == MULTI
        assert edit_params(SINGLE, ChangeParam("n", default=3)) == SINGLE

    def test_int_to_float_default_rewrites_the_text(self):
        assert edit_params(SINGLE, ChangeParam("n", default=3.0)).startswith('PARAMS = {"r": 1.0, "n": 3.0}')

    def test_comment_and_neighbours_stay(self):
        new = edit_params(MULTI, ChangeParam("name", default="ä"))
        assert new == MULTI.replace('"é ü"', '"ä"')

    def test_multi_line_tuple(self):
        new = edit_params(NESTED, ChangeParam("c", default=3.0))
        assert params(new)["c"] == ("float", 3.0, 0.0, 5.0)
        assert new.count("\n") == NESTED.count("\n") - 4  # the tuple is written on one line

    def test_unknown_name(self):
        with pytest.raises(ParamsEditError, match="no parameter"):
            edit_params(SINGLE, ChangeParam("zzz", default=1))

    def test_unchanged_marker_is_not_none(self):
        assert UNCHANGED is not None
        assert repr(UNCHANGED) == "UNCHANGED"

    def test_nan_default(self):
        with pytest.raises(ParamsEditError):
            edit_params(SINGLE, ChangeParam("r", default=float("nan")))


class TestRefusals:
    @pytest.mark.parametrize(
        ("source", "word"),
        [
            ("def build(p):\n    pass\n", "no PARAMS"),
            ("PARAMS = {\n", "syntax"),
            ("PARAMS = dict(a=1)\n", "plain"),
            ("PARAMS = make()\n", "plain"),
            ("PARAMS = [1, 2]\n", "plain"),
            ("PARAMS = {k: 1 for k in 'ab'}\n", "plain"),
            ('PARAMS = {**BASE, "a": 1}\n', "\\*\\*"),
            ("PARAMS = {NAME: 1}\n", "key"),
            ('PARAMS = {"a": SIZE}\n', "plain value"),
            ('PARAMS = {"a": 1 + x}\n', "plain value"),
            ("PARAMS = {1: 2}\n", "key"),
            ("def f():\n    PARAMS = {'a': 1}\n", "no PARAMS"),
        ],
    )
    def test_every_operation_refuses(self, source, word):
        for op in (AddParam("z", 1), RemoveParam("a"), RenameParam("a", "b"), ChangeParam("a", default=1)):
            with pytest.raises(ParamsEditError, match=word):
                edit_params(source, op)

    def test_reason_is_readable(self):
        with pytest.raises(ParamsEditError) as info:
            edit_params("x = 1\n", AddParam("a", 1))
        assert info.value.reason == str(info.value)
        assert "PARAMS" in info.value.reason

    def test_duplicate_keys_are_refused_for_that_name(self):
        source = 'PARAMS = {"a": 1, "a": 2, "b": 3}\n'
        with pytest.raises(ParamsEditError, match="more than once"):
            edit_params(source, RemoveParam("a"))
        assert list(params(edit_params(source, RemoveParam("b")))) == ["a"]

    def test_a_value_that_is_not_a_parameter_cannot_be_changed(self):
        source = 'PARAMS = {"a": [1, 2], "b": 1}\n'
        with pytest.raises(ParamsEditError, match="not a parameter value"):
            edit_params(source, ChangeParam("a", default=1))
        assert edit_params(source, RemoveParam("a")) == 'PARAMS = {"b": 1}\n'

    def test_source_is_never_modified_on_failure(self):
        source = "PARAMS = dict(a=1)\n"
        with pytest.raises(ParamsEditError):
            edit_params(source, AddParam("b", 1))
        assert source == "PARAMS = dict(a=1)\n"


class TestRoundTrip:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_add_then_remove_gives_the_same_text(self, name):
        source = FIXTURES[name]
        added = edit_params(source, AddParam("zz_new", 1.5, 0.0, 3.0))
        assert "zz_new" in params(added)
        assert edit_params(added, RemoveParam("zz_new")) == source

    @pytest.mark.parametrize("name", FIXTURES)
    def test_rename_there_and_back(self, name):
        source = FIXTURES[name]
        layout = read_layout(source)
        assert layout is not None
        if not layout.entries:
            return
        key = layout.entries[0].key
        there = edit_params(source, RenameParam(key, "zz_new"))
        assert edit_params(there, RenameParam("zz_new", key)) == source

    @pytest.mark.parametrize("name", FIXTURES)
    def test_every_op_keeps_params_readable_and_the_rest_identical(self, name):
        source = FIXTURES[name]
        layout = read_layout(source)
        assert layout is not None
        for op in (AddParam("zz_new", "text"), AddParam("zz_flag", False), AddParam("zz_int", 3, 1, 5)):
            new = edit_params(source, op)
            before, after = outside(source, new)
            assert source.startswith(before) and source.endswith(after)
            assert new.startswith(before) and new.endswith(after)
            assert list(params(new))[:-1] == list(params(source))
        if layout.entries:
            first = layout.entries[0].key
            new = edit_params(source, RemoveParam(first))
            assert first not in params(new)
            assert new.endswith(source[layout.dict_end :])
            assert new.startswith(source[: layout.dict_start])

    @pytest.mark.parametrize("name", list(python_templates.TEMPLATES))
    def test_built_in_presets(self, name):
        source = python_templates.TEMPLATES[name]
        before = params(source)
        for default in (1.5, 4, True, "text", "#abcdef"):
            added = edit_params(source, AddParam("zz_new", default))
            assert params(added)["zz_new"][1] == default
            assert list(params(added)) == [*before, "zz_new"]
            assert edit_params(added, RemoveParam("zz_new")) == source
        added = edit_params(source, AddParam("zz_new", 2.0, 0.0, 9.0))
        assert edit_params(added, RemoveParam("zz_new")) == source

    @pytest.mark.parametrize("name", list(python_templates.TEMPLATES))
    def test_built_in_presets_remove_and_re_add_every_parameter(self, name):
        source = python_templates.TEMPLATES[name]
        for p in python_object.read_params(source):
            new = edit_params(source, RemoveParam(p.name))
            assert p.name not in params(new)
            assert new.count("\n") < source.count("\n")

    def test_a_series_of_edits_ends_where_expected(self):
        source = MULTI
        for op in (
            AddParam("a", 1.5),
            RenameParam("a", "b"),
            ChangeParam("b", default=2.5, minimum=0.0, maximum=5.0),
            RemoveParam("n"),
            AddParam("c", "x"),
            RemoveParam("r"),
        ):
            source = edit_params(source, op)
        assert params(source) == {
            "name": ("text", "é ü", None, None),
            "b": ("float", 2.5, 0.0, 5.0),
            "c": ("text", "x", None, None),
        }
        assert source.endswith(BUILD)
        assert "# the circle\nPARAMS" in source
