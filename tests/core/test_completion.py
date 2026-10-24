"""Names to complete and hover text (P13.6)."""

from __future__ import annotations

from manim_studio.core import completion as c

SOURCE = (
    "class Orbit(Scene):\n"
    "    def construct(self):\n"
    "        circle = Circle(radius=1)\n"
    "        planet_count = 3\n"
)


def test_context_finds_the_word_and_the_name_before_a_dot() -> None:
    text = "circle.mov"
    assert c.context(text, len(text)) == c.Context("mov", 7, "circle")
    assert c.context("  Cir", 5) == c.Context("Cir", 2, "")
    assert c.context("x = ", 4) == c.Context("", 4, "")


def test_a_name_starts_with_what_was_typed_and_the_codes_own_names_come_first() -> None:
    text = SOURCE + "        pl"
    found = c.suggestions(text, len(text))
    assert found[0] == "planet_count"
    text = SOURCE + "        Circ"
    assert "Circle" in c.suggestions(text, len(text))


def test_one_letter_offers_nothing_unless_forced() -> None:
    text = SOURCE + "        C"
    assert c.suggestions(text, len(text)) == []
    assert c.suggestions(text, len(text), force=True)


def test_after_a_dot_the_methods_of_the_class_it_was_made_from() -> None:
    text = SOURCE + "        circle.mov"
    found = c.suggestions(text, len(text))
    assert "move_to" in found
    assert all(name.startswith("mov") for name in found)


def test_after_a_dot_on_an_unknown_name_nothing_is_guessed() -> None:
    text = SOURCE + "        mystery.mov"
    assert c.suggestions(text, len(text)) == []


def test_self_offers_the_methods_of_a_scene() -> None:
    text = SOURCE + "        self.pla"
    assert "play" in c.suggestions(text, len(text))


def test_inside_a_call_its_keyword_arguments_are_offered() -> None:
    text = SOURCE + "        sq = Square(sid"
    assert "side_length=" in c.suggestions(text, len(text))


def test_enclosing_call_ignores_closed_brackets() -> None:
    assert c.enclosing_call("Circle(radius=f(2), col", 23) == "Circle"
    assert c.enclosing_call("x = [Circle(), 4", 16) == ""


def test_hover_describes_a_manim_name_and_a_method() -> None:
    assert c.hover(SOURCE, "Circle").startswith("Circle(")
    assert c.hover(SOURCE, "move_to", "circle") == "Circle.move_to"
    assert c.hover(SOURCE, "nothing_here") == ""
    assert c.hover(SOURCE, "move_to", "mystery") == ""


def test_nothing_is_suggested_in_a_comment_or_a_string() -> None:
    for text in ("# Circ", 'x = "Circ', "x = 'Circ"):
        assert c.suggestions(text, len(text), force=True) == [], text
    assert c.suggestions("x = 'a' + Circ", 14)
