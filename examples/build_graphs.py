"""Builds examples/graphs.json: axes and function graphs (ADR 0024).

    python examples/build_graphs.py
    manim-studio render examples/graphs.json out/graphs.mp4

What is in it (7 s, 1280x720 @ 30 fps):

* axes with numbers, drawn with Create;
* ``sin(x)`` drawn along the axes, then turned into ``x**2/10 - 1``;
* ``tan(x)`` faded in: its poles split the curve instead of spiking;
* a title written in, then the whole chart glides up while the graphs ride along;
* a dot runs along the parabola with MoveAlongPath (ADR 0025).

Built with the same edit functions the editor uses.
"""

from __future__ import annotations

from pathlib import Path

from manim_studio.core.editing import edits
from manim_studio.core.model.schema import Canvas, Project, Spec

OUT = Path(__file__).with_name("graphs.json")


def build() -> Project:
    p = Project(canvas=Canvas(duration=7.0, background="#0f172a"))

    def apply(edit: edits.Edit) -> None:
        nonlocal p
        p = edit.project

    apply(
        edits.add_layer(p, Spec(type="Text", params={"text": "y = f(x)", "font_size": 40}), layer_id="title")
    )
    apply(edits.update_layer(p, "title", base={"position": (0.0, 3.4)}))
    apply(edits.add_clip(p, "title", "Write", 0.0, 1.0))

    axes = Spec(
        type="Axes",
        params={
            "x_range": [-5.0, 5.0],
            "y_range": [-3.0, 3.0],
            "x_length": 11.0,
            "y_length": 5.6,
            "numbers": "yes",
        },
    )
    apply(edits.add_layer(p, axes, layer_id="axes"))
    apply(edits.update_layer(p, "axes", base={"position": (0.0, -0.5)}))
    apply(edits.add_clip(p, "axes", "Create", 0.0, 1.2))
    for t, y in ((4.4, -0.5), (5.4, 0.0)):
        apply(edits.set_key(p, "axes", "position", t, (0.0, y)))

    def graph(layer_id: str, expression: str, colour: str) -> None:
        spec = Spec(
            type="Graph",
            params={"expression": expression, "x_range": [-5.0, 5.0]},
            style={"stroke": colour, "stroke_width": 5},
        )
        apply(edits.add_child(p, "axes", spec, layer_id=layer_id, name=f"y = {expression}"))

    graph("sine", "sin(x)", "#38bdf8")
    graph("parabola", "x**2/10 - 1", "#f472b6")
    graph("tangent", "tan(x)", "#facc15")
    apply(edits.add_clip(p, "sine", "Create", 1.2, 1.5))
    apply(edits.add_clip(p, "sine", "Transform", 3.0, 1.3, to_layer="parabola"))
    apply(edits.add_clip(p, "tangent", "FadeIn", 4.4, 0.8))
    # a dot runs along the parabola once the axes have settled (ADR 0025)
    dot = Spec(type="Dot", params={"radius": 0.12}, style={"fill": "#ffffff", "fill_opacity": 1.0})
    apply(edits.add_layer(p, dot, layer_id="runner"))
    apply(edits.add_clip(p, "runner", "FadeIn", 5.4, 0.2))
    apply(edits.add_clip(p, "runner", "MoveAlongPath", 5.6, 1.3, params={"path": "parabola"}))
    return p


if __name__ == "__main__":
    project = build()
    OUT.write_text(project.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    print(f"wrote {OUT} ({len(project.layers)} layers)")
