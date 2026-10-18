"""Equation steps, the pure part (P11, ADR 0054): reading the lines, deriving the next line by an
operation on both sides, and planning the morph between two steps. Only the last check runs
LaTeX: every derived line must be something Manim builds."""

from __future__ import annotations

import manim as m
import pytest

from manim_studio.core import parts
from manim_studio.core.equation_steps import (
    MATCHING,
    MAX_LINE,
    MAX_STEPS,
    OPERATIONS,
    REPLACING,
    StepsError,
    derive,
    line_problem,
    parse,
    parse_steps,
    plan_transition,
    split_equation,
    tokenize,
)

PYTHAGORAS = [r"A = L \times L", r"L = a+b", r"A = (a+b) \times (a+b)"]


# -- the lines --------------------------------------------------------------------------------------


def test_one_step_per_non_empty_line_comments_skipped_order_kept() -> None:
    text = "  x + 2 = 5 \n\n% a comment\nx = 3\n   \n  %indented comment\n2x = 6"
    assert parse_steps(text) == ["x + 2 = 5", "x = 3", "2x = 6"]
    assert parse_steps("") == [] and parse_steps("% only\n\n") == []


def test_too_many_steps_or_a_line_too_long_is_refused_with_the_limit() -> None:
    assert len(parse_steps("\n".join(f"x = {i}" for i in range(MAX_STEPS)))) == MAX_STEPS
    with pytest.raises(StepsError, match=f"{MAX_STEPS + 1} steps: at most {MAX_STEPS}"):
        parse_steps("\n".join(f"x = {i}" for i in range(MAX_STEPS + 1)))
    long = "x = " + "1" * (MAX_LINE - 4)
    assert parse_steps(long) == [long]
    with pytest.raises(StepsError, match=f"line 2 has {MAX_LINE + 1} characters: at most {MAX_LINE}"):
        parse_steps("x = 1\n" + long + "1")


# -- tokens and the tree -----------------------------------------------------------------------------


def test_tokens_keep_commands_numbers_and_letters_whole() -> None:
    tokens = [(t.kind, t.text) for t in tokenize(r"\alpha x^{12.5}\,+\{")]
    assert tokens == [
        ("command", r"\alpha"),
        ("space", " "),
        ("letter", "x"),
        ("op", "^"),
        ("open", "{"),
        ("number", "12.5"),
        ("close", "}"),
        ("command", r"\,"),
        ("op", "+"),
        ("command", r"\{"),
    ]
    assert "".join(t.text for t in tokenize(r"\frac{a}{b} = (x)")) == r"\frac{a}{b} = (x)"


def test_the_tree_groups_braces_brackets_left_right_and_command_arguments() -> None:
    tex = r"\frac{a+b}{2} = \left( x \right) [0, 1)"
    nodes = parse(tex)
    kinds = [(n.kind, n.text(tex)) for n in nodes]
    assert kinds[0] == ("command", r"\frac{a+b}{2}")
    assert kinds[2] == ("group", r"\left( x \right)")
    assert ("leaf", "[") in kinds and ("leaf", ")") in kinds  # an interval: unpaired brackets stay tokens
    frac = nodes[0]
    assert [arg.text(tex) for arg in frac.children] == ["{a+b}", "{2}"]
    assert [c.text(tex) for c in frac.children[0].children] == ["a", "+", "b"]
    sqrt = parse(r"\sqrt[3]{x}")[0]
    assert [arg.text(r"\sqrt[3]{x}") for arg in sqrt.children] == ["[3]", "{x}"]


@pytest.mark.parametrize(
    ("tex", "message"),
    [
        (r"\frac{a}{b", "a '}' is missing"),
        (r"a} = b", "closes nothing"),
        (r"\left( x = 1", r"a \\right is missing"),
        (r"x = \frac{a}", r"\\frac at character 5 is missing an argument"),
    ],
)
def test_unbalanced_lines_say_why(tex, message) -> None:
    assert line_problem(tex) is not None
    with pytest.raises(StepsError, match=message):
        parse(tex)
    assert line_problem(r"x^2 + \frac{1}{2} = \left[ y \right]") is None


# -- splitting -------------------------------------------------------------------------------------


def test_the_equation_splits_at_its_one_top_level_equals() -> None:
    assert split_equation(r"f(x = 1) + \frac{a=b}{2} = y") == (r"f(x = 1) + \frac{a=b}{2}", "y")
    with pytest.raises(StepsError, match="no '=' at the top level"):
        split_equation(r"x + \frac{a=b}{2}")
    with pytest.raises(StepsError, match="2 '=' signs at the top level: operations need exactly one"):
        split_equation("x = y = z")
    with pytest.raises(StepsError, match="left side of '=' is empty"):
        split_equation("= y")


# -- operations ------------------------------------------------------------------------------------

DERIVED = [  # (line, operation, term, the derived line)
    ("x + 2 = 5", "add", "3", "x + 2 + 3 = 5 + 3"),
    ("x + 2 = 5", "add", "-3", "x + 2 + (-3) = 5 + (-3)"),
    ("x + 2 = 5", "subtract", "2", "x + 2 - 2 = 5 - 2"),
    ("x + 2 = 5", "subtract", "a+b", "x + 2 - (a+b) = 5 - (a+b)"),
    ("x + 2 = 5", "multiply", "2", r"(x + 2) \cdot 2 = 5 \cdot 2"),
    ("-x = 5", "multiply", "2", r"-x \cdot 2 = 5 \cdot 2"),  # a leading sign is not a sum
    ("2x = 5", "multiply", "-3", r"2x \cdot (-3) = 5 \cdot (-3)"),
    ("x + 2 = 5", "divide", "a", r"\frac{x + 2}{a} = \frac{5}{a}"),
    ("x + 2 = y", "square", "", "(x + 2)^2 = y^2"),
    (r"x^2 = \frac{a}{b}", "square", "", r"(x^2)^2 = \left( \frac{a}{b} \right)^2"),
    ("a_1 = (b+c)", "square", "", "a_1^2 = (b+c)^2"),
    ("{a+b} = -3", "square", "", "({a+b})^2 = (-3)^2"),
    ("x^2 = 9", "sqrt", "", r"\sqrt{x^2} = \sqrt{9}"),
    ("x = y + 1", "reciprocal", "", r"\frac{1}{x} = \frac{1}{y + 1}"),
    ("e^x = (a+b)", "ln", "", r"\ln(e^x) = \ln(a+b)"),
    (r"x = \frac{a}{b}", "ln", "", r"\ln x = \ln\left( \frac{a}{b} \right)"),
    (r"\ln x = 2", "exp", "", r"e^{\ln x} = e^{2}"),
    (r"A = L \times L", "substitute", "L = a+b", r"A = (a+b) \times (a+b)"),
    (r"A = 2L + \alpha", "substitute", "L := 3", r"A = 2(3) + \alpha"),  # not 23
    (r"\alpha x^2 + \frac{x}{2} = e^x", "substitute", "x = a+b", r"\alpha (a+b)^2 + \frac{a+b}{2} = e^{a+b}"),
    ("y = x_1 + x", "substitute", "x_1 = t", "y = t + x"),
    ("y = x_{1} + x", "substitute", "x = 2", "y = x_{1} + 2"),  # x_1 is another symbol
    (r"\frac{x}{2} = \text{max} + \exp x", "substitute", "x = 4", r"\frac{4}{2} = \text{max} + \exp 4"),
    (r"y = x\pi + xy", "substitute", r"x = \beta", r"y = \beta\pi + \beta y"),  # a space after \beta
    (r"\theta = 2\pi", "substitute", r"\theta = \frac{\pi}{2}", r"\frac{\pi}{2} = 2\pi"),
    ("y = 3^x", "substitute", "x = 12", "y = 3^{12}"),  # a script takes one character without braces
]


@pytest.mark.parametrize(("line", "operation", "term", "expected"), DERIVED)
def test_each_operation_derives_the_next_line(line, operation, term, expected) -> None:
    assert derive(line, operation, term) == expected


@pytest.mark.latex
@pytest.mark.parametrize("derived", sorted({expected for *_, expected in DERIVED}))
def test_every_derived_line_builds_in_manim(derived) -> None:
    built = m.MathTex(derived)  # raises when LaTeX refuses it (one compile each, then cached)
    assert built.family_members_with_points()


def test_every_operation_is_listed_with_a_label() -> None:
    assert set(OPERATIONS) == {op for _, op, _, _ in DERIVED}
    assert all(op.label for op in OPERATIONS.values())


@pytest.mark.parametrize(
    ("line", "operation", "term", "message"),
    [
        ("x + 2", "add", "1", "no '='"),
        ("x = 1 = 2", "multiply", "2", "2 '=' signs"),
        ("x = 1", "add", "", "type the term to add"),
        ("x = 1", "add", "y = 2", "cannot contain '='"),
        ("x = 1", "divide", r"\frac{1}{", "a '}' is missing"),
        ("x = 1", "substitute", "y = 2", "'y' does not appear in the line"),
        (r"\alpha = 1", "substitute", "a = 2", "'a' does not appear in the line"),  # not inside \alpha
        ("x = 1", "substitute", "2 = 3", "the symbol must be a letter or a command"),
        ("x = 1", "substitute", "x^2 = 3", "the symbol must be a letter or a command"),
        ("x = 1", "substitute", "x", "type the substitution as symbol = value"),
        ("x = 1", "power", "2", "unknown operation 'power'"),
    ],
)
def test_operations_refuse_with_a_message(line, operation, term, message) -> None:
    with pytest.raises(StepsError, match=message):
        derive(line, operation, term)


# -- planning the morph ----------------------------------------------------------------------------


def test_pythagoras_steps_keep_what_they_share_and_name_the_new_terms() -> None:
    first = plan_transition(PYTHAGORAS[0], PYTHAGORAS[1])
    assert first.kind == MATCHING and first.shared == ("L",)
    assert [(n.tex, n.occurrence) for n in first.new] == [("= a+b", 0)]
    assert first.gone == ("A =", r"\times L")
    second = plan_transition(PYTHAGORAS[1], PYTHAGORAS[2])
    assert second.kind == MATCHING and second.shared == ("=", "a", "+", "b")
    assert [(n.tex, n.occurrence) for n in second.new] == [("A", 0), (r"\times (a+b)", 0)]
    assert second.gone == ("L",)


def test_new_pieces_are_runs_of_whole_terms_with_their_occurrence() -> None:
    plan = plan_transition("x + 2 = 5", "x + 2 - 2 = 5 - 2")
    assert [(n.tex, n.occurrence) for n in plan.new] == [("- 2", 0), ("- 2", 1)]
    for piece in plan.new:  # each is a part key that resolves to exactly that run
        start = parts.find("x + 2 - 2 = 5 - 2", piece.tex, piece.occurrence)
        assert (start, start + len(piece.tex)) == (piece.start, piece.end)
    divided = plan_transition("x + 2 = 5", r"\frac{x + 2}{a} = \frac{5}{a}")
    # Not the braces; and part keys count plain matches, so the "a" of each \frac counts too.
    assert [(n.tex, n.occurrence) for n in divided.new] == [("a", 1), ("a", 3)]
    powered = plan_transition("x = 5", "x^2 = 5")
    assert [n.tex for n in powered.new] == ["2"]  # not "^2": a part cannot start on ^
    early = plan_transition("x = 1", "x + 1 = 1 + 1")  # each piece matches as early as it can
    assert [(n.tex, n.occurrence) for n in early.new] == [("+ 1", 0), ("+ 1", 1)]


def test_steps_sharing_nothing_are_a_replacement_and_unreadable_lines_too() -> None:
    plan = plan_transition("x = 5", "y^2 + 7")
    assert plan.kind == REPLACING and plan.shared == ()
    assert plan_transition("x = 5", "x = 5").new == ()  # the same line: nothing new
    bad = plan_transition("x = 5", r"\frac{x}{")
    assert bad.kind == REPLACING and "cannot be read" in bad.skipped[0][1]
    brackets_only = plan_transition("(a) = b", "(c)")  # brackets alone are not a shared term
    assert brackets_only.kind == REPLACING


def test_a_new_run_that_would_not_resolve_as_a_part_is_skipped_with_the_reason() -> None:
    # The first "a" stays; the new run "a a" starts at the second, inside the first match of "a a".
    plan = plan_transition("a = y", "a a a = y")
    assert plan.new == ()
    assert plan.skipped == (("a a", "it overlaps another match of the same text"),)
