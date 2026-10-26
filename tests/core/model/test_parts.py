"""Part layers: resolving keys to spans, markers, splitting, tree rules and edits (P2c.1, ADR 0012)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from manim_studio.core.editing import edits
from manim_studio.core.engine.warm import needs_warm, warm_key
from manim_studio.core.model import parts
from manim_studio.core.model.parts import Span
from manim_studio.core.model.schema import Clip, Layer, PartKey, Project, Spec

EQ = r"a^2 + b^2 = c^2"


def project(text: str = EQ, *part_layers: Layer, extra: list[Layer] | None = None) -> Project:
    root = Layer(id="eq", spec=Spec(type="MathTex", params={"text": text}))
    return Project(layers=[root, *part_layers, *(extra or [])])


def part(layer_id: str, tex: str, occurrence: int = 0, parent: str = "eq", **fields) -> Layer:
    return Layer(id=layer_id, parent_id=parent, part=PartKey(tex=tex, occurrence=occurrence), **fields)


# -- finding and checking spans -------------------------------------------------------------


def test_find_counts_non_overlapping_occurrences_within_bounds() -> None:
    assert parts.find("b + b = b", "b", 0) == 0
    assert parts.find("b + b = b", "b", 2) == 8
    assert parts.find("b + b = b", "b", 3) is None
    assert parts.find("aaaa", "aa", 1) == 2  # non-overlapping
    assert parts.find("b + b = b", "b", 0, lo=1) == 4
    assert parts.count("b + b = b", "b", 0, 5) == 2


@pytest.mark.parametrize(
    ("text", "key", "expected"),
    [
        (EQ, "b^2", Span(6, 9)),
        (EQ, "2", Span(2, 3, braced=True)),  # a^2 -> a^{2}: one token after ^
        (r"\int_0^1 x", "1", Span(7, 8, braced=True)),
        (r"x^{n+1}", "{n+1}", Span(2, 7, braced=True)),  # one braced group after ^
        (r"e^{i\pi}", r"\pi", Span(4, 7)),  # inside a group, not right after ^
    ],
)
def test_check_span_accepts_and_braces_one_token_scripts(text, key, expected) -> None:
    start = text.index(key)
    assert parts.check_span(text, start, start + len(key)) == expected


@pytest.mark.parametrize(
    ("text", "start", "end", "reason"),
    [
        (EQ, 1, 3, "starts or ends on ^"),  # "^2"
        (EQ, 0, 2, "starts or ends on ^"),  # "a^"
        (r"e^{i\pi}", 6, 8, "cuts a command"),  # "pi" of \pi
        (r"e^{i\pi}", 3, 5, "cuts a command"),  # "i\" before pi
        (r"\frac{1}{3}", 6, 9, "unbalanced"),  # "1}{"
        (r"x^n+1", 2, 5, "inside a superscript"),  # "n+1" after ^: more than one token
        ("a +  b", 3, 5, "empty"),
    ],
)
def test_check_span_refuses_spans_that_would_break_latex(text, start, end, reason) -> None:
    result = parts.check_span(text, start, end)
    assert isinstance(result, str) and reason in result, result


# -- resolving a tree -------------------------------------------------------------------------


def test_resolve_finds_each_part_and_orders_markers_outer_first() -> None:
    p = project(EQ, part("lhs", "a^2 + b^2"), part("b", "b^2", parent="lhs"), part("c", "c^2"))
    res = parts.resolve(p, "eq")
    assert res.spans == {"lhs": Span(0, 9), "b": Span(6, 9), "c": Span(12, 15)}
    assert res.orphans == {}
    assert res.order == ("lhs", "b", "c")
    assert res.marker_spans() == [[0, 9, False], [6, 9, False], [12, 15, False]]


def test_a_child_counts_occurrences_inside_its_parent_span() -> None:
    p = project("b + b = b", part("rhs", "= b"), part("inner", "b", parent="rhs"))
    assert parts.resolve(p, "eq").spans["inner"] == Span(8, 9)


def test_unresolvable_parts_are_orphaned_with_a_reason_and_never_retargeted() -> None:
    p = project(
        EQ,
        part("missing", "d^2"),
        part("third", "b^2", occurrence=1),
        part("x", "b^2"),
        part("same", "b^2"),
    )
    res = parts.resolve(p, "eq")
    assert "not in the text" in res.orphans["missing"]
    assert "occurs 1 time, not 2" in res.orphans["third"]
    assert "x" in res.spans
    assert "matches the same text as part 'x'" in res.orphans["same"]


def test_crossing_parts_orphan_the_later_one() -> None:
    p = project(EQ, part("first", "a^2 + b"), part("second", "+ b^2"))
    res = parts.resolve(p, "eq")
    assert "first" in res.spans and "overlaps part 'first'" in res.orphans["second"]


def test_a_child_of_an_orphan_is_orphaned() -> None:
    p = project(EQ, part("gone", "z"), part("kid", "z", parent="gone"))
    assert "parent part does not resolve" in parts.resolve(p, "eq").orphans["kid"]


# -- markers and the build spec -------------------------------------------------------------------


def test_mark_wraps_spans_nested_and_braced() -> None:
    open_, close = "\\special{dvisvgm:raw <g id='msp%d'>}", "\\special{dvisvgm:raw </g>}"
    marked = parts.mark("x^2 + y", [[0, 3, False], [0, 1, False], [2, 3, True]])
    assert (
        marked
        == (open_ % 0) + (open_ % 1) + "x" + close + "^{" + (open_ % 2) + "2" + close + "}" + close + " + y"
    )


def test_build_spec_adds_marker_spans_only_when_there_are_resolved_parts() -> None:
    plain = project(EQ)
    assert parts.build_spec(plain, "eq") == plain.layer("eq").spec
    orphaned = project(EQ, part("gone", "zz"))
    assert parts.build_spec(orphaned, "eq") == orphaned.layer("eq").spec
    with_part = project(EQ, part("b", "b^2"))
    spec = parts.build_spec(with_part, "eq")
    assert spec.params[parts.SPANS_PARAM] == [[6, 9, False]]
    assert spec.params["text"] == EQ


def test_warm_key_changes_when_parts_are_added() -> None:
    before = project(EQ)
    after = edits.add_part(before, "eq", "b^2").project
    key = warm_key(parts.build_spec(after, "eq"))
    assert key != warm_key(parts.build_spec(before, "eq"))
    assert needs_warm(before, after, set()) == {key}
    assert needs_warm(before, after, {key}) == set()


# -- splitting into terms ---------------------------------------------------------------------


def test_split_terms_at_top_level_operators() -> None:
    assert parts.split_terms(EQ) == [("a^2", 0), ("b^2", 0), ("c^2", 0)]
    assert parts.split_terms(r"e^{i\pi} + 1 = 0") == [(r"e^{i\pi}", 0), ("1", 0), ("0", 0)]
    # Operators inside braces or \left...\right do not split; repeated terms get occurrences.
    assert parts.split_terms(r"\frac{a+b}{2} = x") == [(r"\frac{a+b}{2}", 0), ("x", 0)]
    assert parts.split_terms(r"\left(a+b\right) - b") == [(r"\left(a+b\right)", 0), ("b", 1)]


def test_split_terms_skip_terms_that_cannot_be_marked() -> None:
    # "1" after "^" sits inside a script at top level: x^1+1 -> "x^1" and "1"
    assert parts.split_terms("x^1+1") == [("x^1", 0), ("1", 1)]


# -- schema rules -------------------------------------------------------------------------------


def test_a_part_needs_a_key_and_no_spec_and_a_root_needs_a_spec() -> None:
    with pytest.raises(ValidationError, match=r"a part key \(a part\) or its own spec"):
        Layer(id="p", parent_id="eq")
    with pytest.raises(ValidationError, match="needs a spec"):
        Layer(id="r")
    with pytest.raises(ValidationError, match="needs a spec and no part key"):
        Layer(id="r", spec=Spec(type="Circle"), part=PartKey(tex="x"))


def test_parts_only_hang_under_existing_tex_roots_without_cycles() -> None:
    with pytest.raises(ValidationError, match="parent 'nope' is missing"):
        project(EQ, part("p", "b^2", parent="nope"))
    circle = Layer(id="c", spec=Spec(type="Circle"))
    with pytest.raises(ValidationError, match="only supported on MathTex and Tex"):
        Project(layers=[circle, part("p", "x", parent="c")])
    with pytest.raises(ValidationError, match="cycle"):
        Project(layers=[part("p", "x", parent="q"), part("q", "x", parent="p")])


def test_a_clip_may_not_overlap_clips_of_its_ancestors_but_siblings_may_overlap() -> None:
    write = Clip(id="w", kind="Write", start=0.0, duration=1.0)
    root = Layer(id="eq", spec=Spec(type="MathTex", params={"text": EQ}), clips=[write])
    early = part("b", "b^2", clips=[Clip(id="i", kind="Indicate", start=0.5, duration=1.0)])
    with pytest.raises(ValidationError, match="overlaps clip 'w' on 'eq'"):
        Project(layers=[root, early])
    b = part("b", "b^2", clips=[Clip(id="i", kind="Indicate", start=1.0, duration=1.0)])
    c = part("c", "c^2", clips=[Clip(id="f", kind="FadeOut", start=1.5, duration=1.0)])
    Project(layers=[root, b, c])  # siblings overlap: allowed


def test_objects_with_parts_may_morph_but_parts_may_not() -> None:
    """ADR 0020 relaxed ADR 0012's v1 refusal."""
    other = Layer(id="other", spec=Spec(type="MathTex", params={"text": "x"}))
    morph = Clip(id="m", kind="Transform", start=1.0, duration=1.0, to_layer="other")
    root = Layer(id="eq", spec=Spec(type="MathTex", params={"text": EQ}), clips=[morph])
    Project(layers=[root, part("b", "b^2"), other])  # from an object with parts
    into = Clip(id="m", kind="Transform", start=1.0, duration=1.0, to_layer="eq")
    plain = Layer(id="eq", spec=Spec(type="MathTex", params={"text": EQ}))
    Project(layers=[plain, part("b", "b^2"), other.model_copy(update={"clips": [into]})])  # into one
    with pytest.raises(ValidationError, match="a part cannot morph"):
        Project(layers=[plain, part("b", "b^2", clips=[morph]), other])


def test_a_part_lifetime_is_clamped_to_its_parent() -> None:
    root = Layer(
        id="eq",
        spec=Spec(type="MathTex", params={"text": EQ}),
        clips=[
            Clip(id="w", kind="Write", start=1.0, duration=1.0),
            Clip(id="o", kind="FadeOut", start=4.0, duration=1.0),
        ],
    )
    late = part("b", "b^2", clips=[Clip(id="f", kind="FadeIn", start=2.0, duration=0.5)])
    plain = part("c", "c^2")
    early_out = part("a", "a^2", clips=[Clip(id="o", kind="FadeOut", start=2.0, duration=0.5)])
    p = Project(layers=[root, late, plain, early_out])
    assert p.lifetime("b") == (2.0, 5.0)
    assert p.lifetime("c") == (1.0, 5.0)
    assert p.lifetime("a") == (1.0, 2.5)


def test_tree_helpers() -> None:
    p = project(EQ, part("lhs", "a^2 + b^2"), part("c", "c^2"), part("b", "b^2", parent="lhs"))
    assert [x.id for x in p.descendants("eq")] == ["lhs", "b", "c"]
    assert [x.id for x in p.children("eq")] == ["lhs", "c"]
    assert [x.id for x in p.ancestors("b")] == ["lhs", "eq"]
    assert p.root_of("b").id == "eq" and p.root_of("eq").id == "eq"
    assert [x.id for x in p.roots()] == ["eq"]


# -- edits ---------------------------------------------------------------------------------------


def test_add_part_inserts_after_the_parent_block_and_is_a_spec_edit_of_the_root() -> None:
    other = Layer(id="sq", spec=Spec(type="Square"))
    edit = edits.add_part(project(EQ, extra=[other]), "eq", "b^2")
    assert [x.id for x in edit.project.layers] == ["eq", "part-1", "sq"]
    new = edit.project.layer("part-1")
    assert new.part == PartKey(tex="b^2") and new.name == "b^2" and new.parent_id == "eq"
    assert edit.kind == "spec" and {"eq", "part-1"} <= edit.layer_ids


def test_add_part_refuses_parts_that_do_not_resolve() -> None:
    with pytest.raises(edits.EditError, match="cannot add part 'd': 'd' is not in the text"):
        edits.add_part(project(), "eq", "d")
    with_b = edits.add_part(project(), "eq", "b^2").project
    with pytest.raises(edits.EditError, match="overlaps part 'part-1'"):
        edits.add_part(with_b, "eq", "+ b^2 =")  # a sibling may not contain another sibling
    with pytest.raises(edits.EditError, match="starts inside a superscript"):
        edits.add_part(with_b, "eq", "2 + b")
    with pytest.raises(edits.EditError, match="only supported on MathTex"):
        edits.add_part(Project(layers=[Layer(id="c", spec=Spec(type="Circle"))]), "c", "x")


def test_add_parts_is_one_edit_for_split_terms() -> None:
    p = project()
    edit = edits.add_parts(p, "eq", parts.split_terms(EQ))
    assert [x.name for x in edit.project.children("eq")] == ["a^2", "b^2", "c^2"]
    assert parts.resolve(edit.project, "eq").orphans == {}


def test_remove_layer_removes_its_parts() -> None:
    p = project(EQ, part("lhs", "a^2 + b^2"), part("b", "b^2", parent="lhs"), part("c", "c^2"))
    assert [x.id for x in edits.remove_layer(p, "lhs").project.layers] == ["eq", "c"]
    assert edits.remove_layer(p, "eq").project.layers == []


def test_move_layer_moves_objects_with_their_parts_and_refuses_parts() -> None:
    sq = Layer(id="sq", spec=Spec(type="Square"))
    p = project(EQ, part("b", "b^2"), extra=[sq])
    moved = edits.move_layer(p, "eq", 1).project
    assert [x.id for x in moved.layers] == ["sq", "eq", "b"]
    assert [x.id for x in edits.move_layer(moved, "sq", 1).project.layers] == ["eq", "b", "sq"]
    with pytest.raises(edits.EditError, match="is a part"):
        edits.move_layer(p, "b", 0)


def test_changing_a_part_key_or_the_root_text_is_a_spec_edit() -> None:
    p = project(EQ, part("b", "b^2"))
    key_edit = edits.update_layer(p, "b", part=PartKey(tex="c^2"))
    assert key_edit.kind == "spec" and {"eq", "b"} <= key_edit.layer_ids
    moved = edits.update_layer(p, "b", base={"position": (1.0, 0.0)})
    assert moved.kind == "transform" and moved.layer_ids == {"b"}


def test_retargeted_flags_parts_whose_match_may_have_moved() -> None:
    def retyped(p: Project, text: str) -> Project:
        return edits.update_layer(p, "eq", spec=Spec(type="MathTex", params={"text": text})).project

    p = project("b + b = c", part("second", "b", occurrence=1), part("c", "c"))
    assert parts.retargeted(p, retyped(p, "b + b = c + 1")) == {}  # same matches, same neighbours
    swapped = parts.retargeted(p, retyped(p, "c + b = b"))
    assert swapped == {"second": "may now match another place", "c": "may now match another place"}
    assert parts.retargeted(p, retyped(p, "b + b + b = c")) == {"second": "may now match another place"}
    gone = parts.retargeted(p, retyped(p, "x = y"))
    assert gone["c"].startswith("no longer found") and gone["second"].startswith("no longer found")
    assert parts.retargeted(p, edits.update_layer(p, "c", name="C").project) == {}
