"""The project validators and edit classification keep their rules while running in linear time (B53).

The rules themselves are older (ADR 0005, 0012, 0024, 0025, 0030, 0033, 0036); these tests pin the
cases the speed-up touched: duplicate ids, morph targets, motion paths that run inside their own
object, what a trace or a connector may follow, which layers ``edits.classify`` upgrades to ``spec``
because of their parts, their parent axes or the graph they are drawn from, and the spans of an
object changed deep inside.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from manim_studio.core import edits
from manim_studio.core.frame_cache import changed_layers, changed_spans
from manim_studio.core.schema import AudioClip, Canvas, Clip, Layer, Lifetime, PartKey, Project, Spec

CIRCLE = Spec(type="Circle")
SOUND = {"path": "x.wav", "start": 0.0, "duration": 1.0}


def dots(*ids: str) -> list[Layer]:
    return [Layer(id=i, spec=CIRCLE) for i in ids]


def graph(layer_id: str, parent: str, expression: str = "x") -> Layer:
    return Layer(id=layer_id, parent_id=parent, spec=Spec(type="Graph", params={"expression": expression}))


def trace(target: str, layer_id: str = "trace") -> Layer:
    return Layer(id=layer_id, spec=Spec(type="TracedPath", params={"target": target}))


def connector(source: str, target: str, layer_id: str = "link") -> Layer:
    return Layer(id=layer_id, spec=Spec(type="Connector", params={"source": source, "target": target}))


# -- ids and morph targets ------------------------------------------------------------------------------


def test_a_repeated_id_is_named_once_whatever_it_is_shared_with() -> None:
    with pytest.raises(ValidationError, match=r"duplicate layer ids: \['a'\]"):
        Project(layers=dots("a", "a", "b"))
    with pytest.raises(ValidationError, match=r"duplicate layer ids: \['a', 'b'\]"):
        Project(layers=dots("a", "b", "b"), audio=[AudioClip(id="a", **SOUND)])
    Project(layers=dots("a", "b", "c"), audio=[AudioClip(id="d", **SOUND)])


def test_a_morph_cannot_turn_into_something_that_is_not_a_layer() -> None:
    """A sound's id is taken, but it is not a layer to morph into."""
    clip = Clip(id="m", kind="Transform", start=0, duration=1, to_layer="snd")
    with pytest.raises(ValidationError, match="to_layer 'snd' is missing"):
        Project(layers=[Layer(id="a", spec=CIRCLE, clips=[clip])], audio=[AudioClip(id="snd", **SOUND)])


# -- motion paths ----------------------------------------------------------------------------------------


def mover(layer_id: str, spec: Spec, path: str) -> Layer:
    move = Clip(id="go", kind="MoveAlongPath", start=0, duration=1, params={"path": path})
    return Layer(id=layer_id, spec=spec, clips=[move])


def test_a_mover_may_follow_a_layer_outside_itself() -> None:
    Project(layers=[*dots("x"), mover("mover", CIRCLE, "x")])
    # another object's graph, and a graph of the mover's own kind of object elsewhere
    axes = [Layer(id="axes", spec=Spec(type="Axes")), graph("g", "axes")]
    Project(layers=[*axes, mover("mover", CIRCLE, "g")])


@pytest.mark.parametrize("inside", ["mover", "g"])
def test_a_mover_cannot_follow_itself_or_what_hangs_under_it(inside: str) -> None:
    layers = [mover("mover", Spec(type="Axes"), inside), graph("g", "mover")]
    with pytest.raises(ValidationError, match=f"'{inside}' cannot be its path"):
        Project(layers=layers)


# -- traces and connectors --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("layers", "message"),
    [
        ([trace("nobody")], "the traced layer 'nobody' is missing"),
        ([trace("trace")], "the traced layer 'trace' cannot be traced"),
        ([trace("a", "t1"), trace("t1", "t2")], "the traced layer 't1' cannot be traced"),
        ([Layer(id="code", spec=Spec(type="Code")), trace("code")], "the traced layer 'code' cannot"),
        ([connector("a", "nobody")], "the connected layer 'nobody' is missing"),
        ([connector("nobody", "a")], "the connected layer 'nobody' is missing"),
        ([connector("link", "a")], "the connected layer 'link' cannot be joined"),
        ([trace("a", "t"), connector("a", "t")], "the connected layer 't' cannot be joined"),
        ([connector("a", "a")], "joins two different layers"),
    ],
)
def test_traces_and_connectors_refuse_what_they_cannot_follow(layers: list[Layer], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Project(layers=[*dots("a", "b"), *layers])


def test_traces_and_connectors_follow_ordinary_layers() -> None:
    project = Project(layers=[*dots("a", "b"), trace("a"), connector("a", "b")])
    assert project.traceable_ids("trace") == ["a", "b"]
    assert project.traceable_ids("a") == ["b"]  # not itself, not a trace or a connector


# -- classification ---------------------------------------------------------------------------------------


def equation(*parts: Layer, text: str = "b + a b") -> Project:
    root = Layer(id="eq", spec=Spec(type="MathTex", params={"text": text}))
    return Project(layers=[root, *parts])


def part(layer_id: str, tex: str, parent: str = "eq", occurrence: int = 0) -> Layer:
    return Layer(id=layer_id, parent_id=parent, part=PartKey(tex=tex, occurrence=occurrence))


def test_the_root_is_rebuilt_when_its_parts_change() -> None:
    old = equation(part("p1", "a b"), part("p2", "b"))
    for new in (
        equation(part("p1", "a b"), part("p2", "b", occurrence=1)),  # the other "b" now
        equation(part("p1", "a b"), part("p2", "b", parent="p1")),  # the same key, searched inside p1
        equation(part("p1", "a"), part("p2", "b")),  # p1 marks other glyphs
    ):
        kind, touched = edits.classify(old, new)
        assert kind == "spec" and "eq" in touched


def test_the_root_is_rebuilt_when_parts_swap_ids_but_not_places() -> None:
    """The same keys and parent names in the same order, but "c" now hangs under the part of "q"."""
    old = equation(part("a", "p"), part("b", "q"), part("c", "p", parent="a"), text="p q")
    new = equation(part("b", "p"), part("a", "q"), part("c", "p", parent="a"), text="p q")
    kind, touched = edits.classify(old, new)
    assert kind == "spec" and "eq" in touched


def test_the_root_is_rebuilt_when_parts_come_and_go() -> None:
    bare, marked = equation(), equation(part("p1", "a"))
    assert "eq" in edits.classify(bare, marked)[1]
    assert "eq" in edits.classify(marked, bare)[1]
    assert edits.classify(bare, bare) == ("timing", frozenset())


def test_the_root_is_not_touched_by_what_does_not_change_its_markers() -> None:
    old = equation(part("p1", "a b"), part("p2", "b"))
    renamed = equation(part("p1", "a b"), part("p2", "b").model_copy(update={"name": "second"}))
    assert edits.classify(old, renamed) == ("timing", frozenset({"p2"}))
    # a part that names text that is not there marks nothing, so neither key rebuilds the root
    lost = equation(part("p1", "zzz"))
    other = equation(part("p1", "qqq"))
    assert edits.classify(lost, other) == ("spec", frozenset({"p1"}))


def axes_project(expression: str, axes_params: dict | None = None) -> Project:
    return Project(
        layers=[
            Layer(id="axes", spec=Spec(type="Axes", params=axes_params or {})),
            graph("g", "axes", expression),
            Layer(id="area", parent_id="axes", spec=Spec(type="Area", params={"graph": "g"})),
            Layer(id="elsewhere", spec=CIRCLE),
        ]
    )


def test_a_child_is_rebuilt_with_its_parent_and_its_graph() -> None:
    old = axes_project("x")
    assert edits.classify(old, axes_project("x**2")) == ("spec", frozenset({"g", "area"}))
    assert edits.classify(old, axes_project("x", {"x_range": [-2, 2, 1]})) == (
        "spec",
        frozenset({"axes", "g", "area"}),
    )
    assert edits.classify(old, old) == ("timing", frozenset())


@pytest.mark.parametrize("n", [5, 300])
def test_edits_classify_alike_whatever_the_project_size(n: int) -> None:
    layers = [
        *dots(*(f"d{i}" for i in range(n))),
        *equation(part("p", "a")).layers,
        *axes_project("x").layers[:2],
    ]
    project = Project(layers=layers)
    edit = edits.update_layer(project, "d1", base={"position": (1.0, 0.5)})
    assert (edit.kind, edit.layer_ids) == ("transform", frozenset({"d1"}))
    edit = edits.update_layer(project, "g", spec=Spec(type="Graph", params={"expression": "x**2"}))
    assert (edit.kind, edit.layer_ids) == ("spec", frozenset({"g"}))
    edit = edits.add_layer(project, Spec(type="Dot"))
    assert (edit.kind, edit.layer_ids) == ("clip", frozenset({"dot-1"}))


# -- spans ----------------------------------------------------------------------------------------------


def test_a_change_deep_in_an_object_changes_the_whole_object_only() -> None:
    """A part of a part: the root, its other parts and nothing outside them are redrawn."""
    canvas = Canvas(duration=6.0)
    layers = [
        Layer(
            id="eq", spec=Spec(type="MathTex", params={"text": "a b c"}), lifetime=Lifetime(in_=1.0, out=5.0)
        ),
        part("outer", "a b"),
        part("inner", "b", parent="outer"),
        part("side", "c"),
        Layer(id="other", spec=CIRCLE, lifetime=Lifetime(in_=0.0, out=0.5)),
    ]
    old = Project(canvas=canvas, layers=layers)
    turned = [
        layer.model_copy(update={"base": layer.base.model_copy(update={"rotation": 20.0})})
        if layer.id == "inner"
        else layer
        for layer in layers
    ]
    assert changed_spans(old, Project(canvas=canvas, layers=turned)) == [(1.0, 5.0)]
    assert changed_spans(old, old) == []
    # the same through an object whose members have lifetimes of their own
    shorter = [
        layer.model_copy(update={"lifetime": Lifetime(in_=2.0, out=3.0)}) if layer.id == "side" else layer
        for layer in layers
    ]
    assert changed_spans(old, Project(canvas=canvas, layers=shorter)) == [(1.0, 5.0)]


def test_the_closure_of_a_change_is_the_whole_object() -> None:
    """Whichever member of an object changes, the layers redrawn are the root and all it holds."""
    layers = [
        Layer(id="eq", spec=Spec(type="MathTex", params={"text": "a b c"})),
        part("outer", "a b"),
        part("inner", "b", parent="outer"),
        part("side", "c"),
        *dots("other"),
    ]
    old = Project(layers=layers)
    whole = {"eq", "outer", "inner", "side"}
    for changed in whole:
        edited = [
            layer.model_copy(update={"base": layer.base.model_copy(update={"rotation": 20.0})})
            if layer.id == changed
            else layer
            for layer in layers
        ]
        assert changed_layers(old, Project(layers=edited)) == whole, changed
