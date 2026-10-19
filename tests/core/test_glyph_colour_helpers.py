"""The pure helpers of Colour characters (ADR 0055): gradients, rainbows, ranges - no Qt, no Manim."""

from __future__ import annotations

import pytest

from manim_studio.core import glyph_colours as gc

RED, GREEN, BLUE = "#ff0000", "#00ff00", "#0000ff"  # content: colours a user picks


def rgb(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[i : i + 2], 16) for i in (1, 3, 5))


def test_a_gradient_starts_and_ends_on_its_colours_and_moves_monotonically() -> None:
    out = gc.gradient([RED, BLUE], 5)
    assert len(out) == 5 and out[0] == RED and out[-1] == BLUE
    reds = [rgb(c)[0] for c in out]
    blues = [rgb(c)[2] for c in out]
    assert reds == sorted(reds, reverse=True) and blues == sorted(blues)
    assert out[2] == "#800080"  # the middle: 127.5 rounded half to even would be 128 = 0x80
    assert gc.gradient(["#F00", "#00f"], 2) == [RED, BLUE]  # short and upper-case colours read too


def test_a_gradient_through_three_colours_passes_the_middle_one() -> None:
    out = gc.gradient([RED, GREEN, BLUE], 5)
    assert out[0] == RED and out[2] == GREEN and out[4] == BLUE


def test_gradient_edge_cases_and_ranges() -> None:
    assert gc.gradient([RED, BLUE], 1) == [RED]
    assert gc.gradient([RED, BLUE], 0) == []
    assert gc.gradient([GREEN], 3) == [GREEN] * 3
    ranged = gc.gradient([RED, BLUE], 6, start=2, end=5)
    assert ranged[:2] == [None, None] and ranged[5] is None
    assert ranged[2] == RED and ranged[4] == BLUE and len(ranged) == 6
    with pytest.raises(ValueError, match="at least one colour"):
        gc.gradient([], 3)
    with pytest.raises(ValueError, match="not a colour"):
        gc.gradient(["red", BLUE], 3)


def test_a_rainbow_has_a_different_colour_per_glyph_from_red() -> None:
    out = gc.rainbow(6)
    assert len(out) == 6 and out[0] == RED and len(set(out)) == 6
    assert all(len(c) == 7 and c.startswith("#") for c in out)
    assert gc.rainbow(1) == [RED] and gc.rainbow(0) == []
    assert gc.rainbow(3) == [RED, GREEN, BLUE]  # evenly around the wheel
    assert out[2] == GREEN or rgb(out[2])[1] == 255  # a third of the way: green's side of the wheel


def test_alternate_repeats_its_colours() -> None:
    assert gc.alternate(5, [RED, BLUE]) == [RED, BLUE, RED, BLUE, RED]
    assert gc.alternate(2, [RED, GREEN, BLUE]) == [RED, GREEN]
    with pytest.raises(ValueError):
        gc.alternate(3, [])


def test_ranges_set_and_clear_without_touching_the_rest() -> None:
    assert gc.apply_range([], 1, 3, RED) == [None, RED, RED]
    assert gc.apply_range([BLUE, BLUE, BLUE, BLUE], 1, 3, RED) == [BLUE, RED, RED, BLUE]
    assert gc.clear_range([BLUE, RED, RED, BLUE], 1, 3) == [BLUE, None, None, BLUE]
    assert gc.clear_range([BLUE], 2, 5) == [BLUE]  # past the end: nothing to clear
    original = [BLUE, BLUE]
    gc.apply_range(original, 0, 1, RED)
    assert original == [BLUE, BLUE]  # pure


def test_assign_puts_values_at_chosen_glyphs() -> None:
    assert gc.assign([RED], [3, 1], [GREEN, BLUE]) == [RED, BLUE, None, GREEN]
    assert gc.assign([RED, RED], [0], [None]) == [None, RED]
    assert gc.assign([RED], [1], [GREEN]) == [RED, GREEN]  # right after the end


def test_normalised_trims_and_resolved_fits_the_glyph_count() -> None:
    assert gc.normalised([RED, None, None]) == [RED]
    assert gc.normalised([None, None]) is None and gc.normalised([]) is None and gc.normalised(None) is None
    assert gc.normalised(["#F00"]) == ["#F00"]  # stored as the user typed it
    assert gc.resolved([RED], 3) == [RED, None, None]  # missing: the object's colour
    assert gc.resolved([RED, GREEN, BLUE], 2) == [RED, GREEN]  # extra: ignored


def test_problem_checks_a_list_of_colours_or_nulls() -> None:
    assert gc.problem([RED, None, "#abc"]) is None
    assert "must be a list" in gc.problem("#ff0000")
    assert "glyph 2" in gc.problem([RED, "blue"])
    assert "at most" in gc.problem([None] * (gc.MAX_GLYPHS + 1))
    assert gc.problem([None] * gc.MAX_GLYPHS) is None
