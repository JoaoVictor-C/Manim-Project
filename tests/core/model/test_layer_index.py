"""LayerIndex answers tree questions like Project's own methods, from maps built once (B66)."""

from __future__ import annotations

import pytest

from manim_studio.core.model.layer_index import LayerIndex
from manim_studio.core.model.schema import Canvas, Clip, Layer, PartKey, Project, Spec

SQUARE = Spec(type="Square")
AXES = Spec(type="Axes", params={})
SIN = Spec(type="Graph", params={"expression": "sin(x)"})
MATH = Spec(type="MathTex", params={"text": "a+b=c"})


def tree() -> Project:
    """Roots, a morph pair, parts of a formula, graphs on axes (two levels in one place)."""
    return Project(
        canvas=Canvas(duration=10.0, fps=30),
        layers=[
            Layer(id="a", spec=SQUARE, clips=[Clip(id="in", kind="FadeIn", start=1.0, duration=1.0)]),
            Layer(id="eq", spec=MATH, clips=[Clip(id="w", kind="Write", start=0.5, duration=1.0)]),
            Layer(id="p1", parent_id="eq", part=PartKey(tex="a", occurrence=0)),
            Layer(id="p2", parent_id="eq", part=PartKey(tex="b", occurrence=0)),
            Layer(
                id="b",
                spec=SQUARE,
                clips=[
                    Clip(id="s", kind="FadeIn", start=0.0, duration=0.5),
                    Clip(id="m", kind="Transform", start=3.0, duration=1.0, to_layer="c"),
                ],
            ),
            Layer(id="c", spec=SQUARE),
            Layer(id="axes", spec=AXES),
            Layer(id="g1", spec=SIN, parent_id="axes"),
            Layer(id="g2", spec=SIN, parent_id="axes"),
            Layer(id="d", spec=SQUARE),
        ],
    )


@pytest.fixture
def project() -> Project:
    return tree()


def test_it_answers_every_tree_question_like_the_project(project: Project) -> None:
    index = LayerIndex(project)
    assert [x.id for x in index.roots()] == [x.id for x in project.roots()]
    assert index.morph_sources == project.morph_sources()
    for layer in project.layers:
        i = layer.id
        assert layer.id in index
        assert index.layer(i) is project.layer(i)
        assert [x.id for x in index.children(i)] == [x.id for x in project.children(i)]
        assert [x.id for x in index.descendants(i)] == [x.id for x in project.descendants(i)]
        assert [x.id for x in index.ancestors(i)] == [x.id for x in project.ancestors(i)]
        assert index.root_of(i) is project.root_of(i)
        assert index.depth(i) == len(project.ancestors(i))
        assert index.lifetime(i) == project.lifetime(i)


def test_rows_put_each_object_before_its_parts_front_most_first(project: Project) -> None:
    ids = [x.id for x in LayerIndex(project).rows()]
    assert ids == ["d", "axes", "g1", "g2", "c", "b", "eq", "p1", "p2", "a"]


def test_a_part_lives_within_its_parent(project: Project) -> None:
    index = LayerIndex(project)
    assert index.lifetime("c")[0] == 4.0  # the morph into it ends there
    assert index.lifetime("p1") == index.lifetime("eq")


def test_an_unknown_id_is_a_key_error(project: Project) -> None:
    index = LayerIndex(project)
    assert "nope" not in index
    for ask in (index.layer, index.ancestors, index.root_of, index.lifetime, index.depth):
        with pytest.raises(KeyError):
            ask("nope")
    assert index.children("nope") == []
    assert index.descendants("nope") == []


def test_the_answers_are_copies_a_caller_can_change(project: Project) -> None:
    index = LayerIndex(project)
    index.children("axes").clear()
    index.roots().clear()
    assert len(index.children("axes")) == 2
    assert len(index.roots()) == 6
