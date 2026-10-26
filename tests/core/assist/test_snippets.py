"""Code snippets (P13.3): well-formed, valid Python, only real Manim names, tab stops and search."""

from __future__ import annotations

import ast
import builtins

import pytest

from manim_studio.core.assist import snippets
from manim_studio.core.assist.snippets import SNIPPETS, Snippet, expand, indent, search, template_problem


def wrap(snippet: Snippet) -> str:
    """The snippet as a file: in a Scene's construct, or at module level for a Python object."""
    text, _ = expand(snippet.code)
    if snippet.module_level:
        return text + "\n"
    return "class S(Scene):\n    def construct(self):\n" + indent(text, "        ") + "\n"


def by_id(snippet_id: str) -> Snippet:
    return next(s for s in SNIPPETS if s.id == snippet_id)


class TestCatalogue:
    def test_has_forty_to_fifty_snippets(self):
        assert 40 <= len(SNIPPETS) <= 50

    def test_ids_are_unique_slugs(self):
        ids = [s.id for s in SNIPPETS]
        assert len(set(ids)) == len(ids)
        assert all(i and i == i.lower() and " " not in i for i in ids)

    def test_titles_are_not_empty_and_unique(self):
        titles = [s.title for s in SNIPPETS]
        assert all(t.strip() for t in titles)
        assert len(set(titles)) == len(titles)

    def test_every_snippet_has_a_description_and_a_known_category(self):
        for s in SNIPPETS:
            assert s.description.strip(), s.id
            assert s.category in snippets.CATEGORIES, s.id

    def test_every_category_has_snippets(self):
        assert {s.category for s in SNIPPETS} == set(snippets.CATEGORIES)

    def test_each_snippet_is_three_to_fifteen_lines(self):
        for s in SNIPPETS:
            n = len(s.code.split("\n"))
            assert 3 <= n <= 15, f"{s.id} has {n} lines"

    def test_code_is_dedented_and_trimmed(self):
        for s in SNIPPETS:
            lines = s.code.split("\n")
            assert not lines[0].startswith((" ", "\t")), s.id
            assert s.code == s.code.strip("\n"), s.id
            assert "\t" not in s.code, s.id

    def test_python_object_snippets_define_build(self):
        objects = [s for s in SNIPPETS if s.module_level]
        assert objects
        for s in objects:
            assert "def build(p):" in s.code and "PARAMS" in s.code, s.id

    def test_the_snippets_are_immutable(self):
        with pytest.raises(AttributeError):
            SNIPPETS[0].title = "x"  # type: ignore[misc]


class TestCompile:
    @pytest.mark.parametrize("snippet", SNIPPETS, ids=lambda s: s.id)
    def test_compiles(self, snippet):
        ast.parse(wrap(snippet))

    @pytest.mark.parametrize("snippet", SNIPPETS, ids=lambda s: s.id)
    def test_tab_stops_are_well_formed(self, snippet):
        assert template_problem(snippet.code) is None, snippet.id

    def test_no_dollar_is_left_after_expanding(self):
        for s in SNIPPETS:
            assert "$" not in expand(s.code)[0], s.id

    def test_every_dollar_sign_is_a_tab_stop(self):
        for s in SNIPPETS:
            text, stops = expand(s.code)
            assert len(stops) == s.code.count("$"), s.id
            assert all(0 <= a <= b <= len(text) for a, b in stops), s.id

    def test_stops_select_the_defaults(self):
        text, stops = expand(by_id("circle").code)
        assert [text[a:b] for a, b in stops[:4]] == ["1.5", "BLUE", "BLUE", "0.4"]


def _used_names(tree: ast.AST) -> set[str]:
    """Names a snippet reads that it does not define itself (so they must come from Manim)."""
    bound: set[str] = {"self", "p"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id not in bound
        and not hasattr(builtins, node.id)
    }


@pytest.mark.slow
def test_every_name_used_exists_in_manim():
    namespace: dict = {}
    exec("from manim import *", namespace)  # lazily: importing Manim is slow
    missing = {}
    for s in SNIPPETS:
        unknown = sorted(n for n in _used_names(ast.parse(wrap(s))) if n not in namespace)
        if unknown:
            missing[s.id] = unknown
    assert missing == {}


@pytest.mark.slow
@pytest.mark.latex
@pytest.mark.parametrize("snippet", SNIPPETS, ids=lambda s: s.id)
def test_runs_in_manim(snippet):
    """Each snippet builds and plays (nothing is rendered) in a scene with a moving camera."""
    import manim

    text, _ = expand(snippet.code)
    namespace: dict = {}
    exec("from manim import *", namespace)
    settings = {
        "dry_run": True,
        "write_to_movie": False,
        "disable_caching": True,
        "progress_bar": "none",
        "verbosity": "ERROR",
    }
    with manim.tempconfig(settings):
        if snippet.module_level:
            exec(text, namespace)
            params = {k: v[0] if isinstance(v, tuple) else v for k, v in namespace["PARAMS"].items()}
            assert isinstance(namespace["build"](params), manim.Mobject)
        else:
            source = "class S(MovingCameraScene):\n    def construct(self):\n" + indent(text, "        ")
            exec(source, namespace)
            namespace["S"]().render()


class TestExpand:
    def test_replaces_placeholders_by_their_defaults(self):
        text, stops = expand("a = ${1:foo}\nb = ${2:bar}")
        assert text == "a = foo\nb = bar"
        assert [text[s:e] for s, e in stops] == ["foo", "bar"]

    def test_stops_are_in_number_order_with_zero_last(self):
        text, stops = expand("$0 ${2:two} ${1:one}")
        assert text == " two one"
        assert [text[s:e] for s, e in stops[:2]] == ["one", "two"]
        assert stops[-1] == (0, 0)

    def test_final_stop_is_an_empty_range_where_zero_was(self):
        text, stops = expand("x = ${1:1}\n$0\ny")
        assert text == "x = 1\n\ny"
        assert stops == [(4, 5), (6, 6)]

    def test_without_zero_there_is_no_final_stop(self):
        assert expand("x = ${1:1}")[1] == [(4, 5)]

    def test_a_placeholder_without_default_is_an_empty_range(self):
        text, stops = expand("f(${1})")
        assert (text, stops) == ("f()", [(2, 2)])

    def test_no_placeholders(self):
        assert expand("self.wait()") == ("self.wait()", [])

    def test_a_default_can_hold_balanced_braces(self):
        text, stops = expand(r'MathTex(r"${1:\frac{a}{b}}")')
        assert text == r'MathTex(r"\frac{a}{b}")'
        assert text[stops[0][0] : stops[0][1]] == r"\frac{a}{b}"

    def test_a_default_can_hold_colons_and_braces(self):
        text, _ = expand("x = ${1:{'a': 1}}")
        assert text == "x = {'a': 1}"

    def test_a_plain_dollar_sign_stays(self):
        assert expand("price $x and $") == ("price $x and $", [])

    def test_offsets_count_characters_not_bytes(self):
        text, stops = expand("é = ${1:ã}")
        assert text[stops[0][0] : stops[0][1]] == "ã"

    def test_a_malformed_placeholder_is_left_alone(self):
        for bad in ("${1:open", "${x}", "${}", "${1 foo}", "$1"):
            assert expand(bad) == (bad, [])

    def test_expand_is_empty_safe(self):
        assert expand("") == ("", [])


class TestTemplateProblem:
    def test_well_formed(self):
        assert template_problem("${1:a} ${2:b} ${3} $0") is None
        assert template_problem("no stops") is None

    @pytest.mark.parametrize(
        "code",
        [
            "${2:a} ${1:b}",  # not ascending
            "${1:a} ${1:b}",  # not unique
            "${1:a} ${3:b}",  # gap
            "${2:a}",  # does not start at 1
            "$0 and $0",
            "${1:open",
            "${:x}",
            "${a:x}",
            "$1",
        ],
    )
    def test_malformed(self, code):
        assert template_problem(code)

    def test_zero_may_come_anywhere(self):
        assert template_problem("$0 ${1:a}") is None


class TestIndent:
    def test_prefixes_every_non_blank_line(self):
        assert indent("a\n\nb", "    ") == "    a\n\n    b"

    def test_blank_lines_with_spaces_stay_empty_of_the_prefix(self):
        assert indent("a\n   \nb", "  ") == "  a\n   \n  b"

    def test_skip_first(self):
        assert indent("a\nb", "  ", skip_first=True) == "a\n  b"

    def test_keeps_relative_indentation(self):
        assert indent("for x in y:\n    f(x)", "\t") == "\tfor x in y:\n\t    f(x)"

    def test_empty_prefix_changes_nothing(self):
        assert indent("a\n b", "") == "a\n b"

    def test_a_snippet_indented_still_compiles_in_a_construct(self):
        for s in SNIPPETS:
            if not s.module_level:
                body = indent(expand(s.code)[0], " " * 12)
                ast.parse("class S(Scene):\n    def construct(self):\n        if True:\n" + body)


class TestSearch:
    def test_empty_query_returns_everything_in_order(self):
        assert search("") == list(SNIPPETS)
        assert search("   ") == list(SNIPPETS)

    def test_matches_title_case_insensitively(self):
        assert by_id("circle") in search("CIRCLE")

    def test_all_words_must_match(self):
        found = search("matrix vector")
        assert found
        for s in found:
            blob = f"{s.title} {s.description} {s.category} {s.id}".lower()
            assert "matrix" in blob and "vector" in blob
        assert search("circle xyzzy") == []

    def test_title_beats_description(self):
        hits = search("circle")
        assert hits[0].id == "circle"

    def test_matches_category_and_id(self):
        assert by_id("point-on-graph") in search("numbers and trackers")
        assert by_id("point-on-graph") in search("point-on")

    def test_matches_description_words(self):
        assert by_id("write-fadeout") in search("hold moment")

    def test_a_given_pool(self):
        pool = (Snippet("a", "Alpha", "Shapes", "first", "x"), Snippet("b", "Beta", "Shapes", "alpha", "y"))
        assert [s.id for s in search("alpha", pool)] == ["a", "b"]  # title match first
        assert search("nothing", pool) == []

    def test_equal_ranks_keep_their_order(self):
        pool = tuple(Snippet(f"s{i}", f"Thing {i}", "Shapes", "", "x") for i in range(4))
        assert [s.id for s in search("thing", pool)] == ["s0", "s1", "s2", "s3"]
