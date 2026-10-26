"""The code editor's tokens and drafts (P6b.3): Python highlighting spans and the page's
bookkeeping of unapplied text, neither needing Qt."""

from __future__ import annotations

import random

import pytest

from manim_studio.ui.code.code_drafts import Drafts, clamp_line, error_line, error_text, moved_on
from manim_studio.ui.code.code_syntax import IN_DOUBLE_TRIPLE, IN_SINGLE_TRIPLE, NORMAL, scan, scan_line


def kinds(text: str, state: int = NORMAL) -> list[tuple[str, str]]:
    """(the text, its kind) for each span of one line."""
    spans, _ = scan_line(text, state)
    return [(text[start : start + length], kind) for start, length, kind in spans]


def test_a_scene_class_is_tokenised() -> None:
    assert kinds("class Orbit(Scene):") == [
        ("class", "keyword"),
        ("Orbit", "definition"),
        ("Scene", "manim"),
    ]
    assert kinds("    def construct(self):") == [
        ("def", "keyword"),
        ("construct", "definition"),
        ("self", "keyword"),
    ]


def test_keywords_manim_names_and_plain_names() -> None:
    assert kinds("for dot in dots: self.play(Create(dot), run_time=2)") == [
        ("for", "keyword"),
        ("in", "keyword"),
        ("self", "keyword"),
        ("Create", "manim"),
        ("2", "number"),
    ]
    assert kinds("x = None if True else False") == [
        ("None", "keyword"),
        ("if", "keyword"),
        ("True", "keyword"),
        ("else", "keyword"),
        ("False", "keyword"),
    ]


@pytest.mark.parametrize(
    "number", ["7", "1_000", "3.14", ".5", "2.", "1e-3", "2.5E+10", "0x1F", "0b101", "0o17", "3j"]
)
def test_numbers(number) -> None:
    assert kinds(f"x = {number}") == [(number, "number")]


def test_a_digit_inside_a_name_is_not_a_number() -> None:
    assert kinds("dot2 = a1 + b_3") == []
    assert kinds("v[0] * 2") == [("0", "number"), ("2", "number")]


def test_strings_with_prefixes_quotes_and_escapes() -> None:
    assert kinds('a = \'it\\\'s\' + "say \\"hi\\""') == [
        ("'it\\'s'", "string"),
        ('"say \\"hi\\""', "string"),
    ]
    assert kinds('t = rf"x^{n}" + b\'z\' + R"raw"') == [
        ('rf"x^{n}"', "string"),
        ("b'z'", "string"),
        ('R"raw"', "string"),
    ]
    assert kinds("name = f'{x}'") == [("f'{x}'", "string")]
    assert kinds("fx = 3") == [("3", "number")]  # an f that is not followed by a quote is a name


def test_an_unterminated_string_ends_at_the_line_end_and_does_not_leak() -> None:
    spans, state = scan_line("x = 'oops")
    assert spans == [(4, 5, "string")] and state == NORMAL
    assert scan_line("y = 1")[1] == NORMAL


def test_comments_run_to_the_end_and_hide_everything_inside() -> None:
    assert kinds("x = 1  # not 'a string', def, 2") == [
        ("1", "number"),
        ("# not 'a string', def, 2", "comment"),
    ]
    assert kinds("s = '# not a comment' # but this is") == [
        ("'# not a comment'", "string"),
        ("# but this is", "comment"),
    ]


def test_triple_quoted_strings_continue_over_lines() -> None:
    lines = ['x = """one', "# still a string", 'ends here""" + 1', "y = 2"]
    spans = scan("\n".join(lines))
    assert [(s, k) for s, _, k in spans[0]] == [(4, "string")]
    assert spans[1] == [(0, len(lines[1]), "string")]
    assert spans[2][0] == (0, len('ends here"""'), "string") and spans[2][1][2] == "number"
    assert spans[3] == [(4, 1, "number")]
    assert scan_line('a = """open')[1] == IN_DOUBLE_TRIPLE
    assert scan_line("a = '''open")[1] == IN_SINGLE_TRIPLE
    assert scan_line("still inside", IN_DOUBLE_TRIPLE) == ([(0, 12, "string")], IN_DOUBLE_TRIPLE)
    assert scan_line("end'''", IN_DOUBLE_TRIPLE)[1] == IN_DOUBLE_TRIPLE  # the other quote does not close it
    assert scan_line('"""', IN_DOUBLE_TRIPLE) == ([(0, 3, "string")], NORMAL)
    assert scan_line("", IN_DOUBLE_TRIPLE) == ([], IN_DOUBLE_TRIPLE)


def test_a_one_line_triple_quoted_string_closes_on_its_line() -> None:
    assert scan_line('"""doc""" + x') == ([(0, 9, "string")], NORMAL)


def test_spans_are_ordered_disjoint_and_inside_the_line_for_any_text() -> None:
    rng = random.Random(7)
    alphabet = "abcXYZ_ 0123456789.'\"#\\():=+-*\n\tdefclass ²érRfb"
    for _ in range(400):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
        state = NORMAL
        for line in text.split("\n"):
            spans, state = scan_line(line, state)
            end = 0
            for start, length, kind in spans:
                assert start >= end and length > 0 and start + length <= len(line), (line, spans)
                assert kind in {"keyword", "string", "number", "comment", "manim", "definition"}
                end = start + length


def test_a_long_file_is_scanned_without_trouble() -> None:
    source = "\n".join(
        f"        self.play(Create(Circle(radius={i}.5)), run_time=1)  # step {i}" for i in range(2000)
    )
    assert len(scan(source)) == 2000


# -- drafts --------------------------------------------------------------------------------------


def test_a_draft_is_kept_only_while_it_differs_from_the_project() -> None:
    drafts = Drafts()
    drafts.park("a", "typed", 3, "old", "old")
    assert drafts.dirty("a", "old") and "a" in drafts and len(drafts) == 1
    got = drafts.get("a", "old")
    assert (got.text, got.cursor, got.base) == ("typed", 3, "old")
    drafts.park("a", "old", 0, "old", "old")  # typed back to the project's text
    assert "a" not in drafts and not drafts.dirty("a", "old") and drafts.get("a", "old") is None


def test_a_draft_that_became_the_projects_text_is_dropped_when_asked_for() -> None:
    drafts = Drafts()
    drafts.park("a", "typed", 0, "old", "old")
    assert (
        drafts.get("a", "typed") is None and "a" not in drafts
    )  # the project caught up (e.g. Run elsewhere)


def test_dirty_compares_exactly_and_knows_a_layer_that_is_gone() -> None:
    drafts = Drafts()
    drafts.park("a", "code ", 0, "code", "code")  # one trailing space
    assert drafts.dirty("a", "code")
    assert drafts.dirty("a", None) and not drafts.dirty("b", "code")


def test_clear_counts_what_it_drops_and_discard_forgets_one() -> None:
    drafts = Drafts()
    drafts.park("a", "1", 0, "", "")
    drafts.park("b", "2", 0, "", "")
    drafts.discard("a")
    assert drafts.clear() == 1 and len(drafts) == 0 and drafts.clear() == 0


def test_moved_on_means_the_project_changed_under_unapplied_text() -> None:
    assert moved_on("mine", "was", "now")
    assert not moved_on("mine", "was", "was")  # an ordinary draft
    assert not moved_on("same", "was", "same")  # nothing unapplied
    assert not moved_on("x", "was", "was")


@pytest.mark.parametrize(
    ("line", "count", "expected"),
    [(3, 10, 3), (0, 10, 1), (-4, 10, 1), (99, 10, 10), (5, 0, 1), (1, 1, 1)],
)
def test_error_lines_are_kept_inside_the_text(line, count, expected) -> None:
    assert clamp_line(line, count) == expected


def test_only_an_error_with_a_positive_line_has_a_line() -> None:
    assert error_line("error", 7) == 7
    assert error_line("error", None) is None and error_line("error", 0) is None
    assert error_line("error", -2) is None and error_line("error", True) is None
    assert error_line("ready", 7) is None and error_line("rendering", 3) is None


def test_the_error_reads_as_one_line() -> None:
    assert error_text("NameError: name 'x' is not defined", 3) == "line 3: NameError: name 'x' is not defined"
    assert error_text("define exactly one Scene subclass (found: none)", None).startswith("define exactly")


def test_a_name_before_a_quote_is_not_a_string_prefix_unless_it_is_one() -> None:
    assert kinds("abc'x'") == [("'x'", "string")]
    assert kinds("Rb'x' + xr'y'") == [("Rb'x'", "string"), ("'y'", "string")]


def test_a_draft_the_project_has_caught_up_with_is_not_dirty() -> None:
    drafts = Drafts()
    drafts.park("a", "typed", 0, "old", "old")
    assert drafts.dirty("a", "old") and not drafts.dirty("a", "typed")
