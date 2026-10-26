"""Builds examples/showcase.json: one scene that uses most of what the editor can do.

Run it, then open the project in the editor or render it:

    python examples/build_showcase.py
    manim-studio render examples/showcase.json out/showcase.mp4 --trust-code

What is in it (10 s, 1280x720 @ 30 fps):

* a title that fades in from the left and out;
* an equation written in, split into terms (part layers, ADR 0012): ``b^2`` is
  indicated, ``a^2`` jumps up and back with keyframes on a custom bezier curve,
  ``c^2`` wiggles; then the equation turns into ``c^2 = a^2 + b^2`` with
  TransformMatchingTex, each term flying to its new place (ADR 0020), and its
  ``c^2`` is circled with Circumscribe (ADR 0022);
* a square that is drawn, spins and grows on keyframes, then morphs into a circle;
* a star that grows from its centre, pulses its opacity and flashes;
* a pendulum (ADR 0021): a rod and a bob that both turn about the same pivot,
  set with their anchors — the rod's at its top end, the bob's far outside it;
* a code layer (ADR 0019): real Manim code with a ValueTracker, an updater and a
  TracedPath — an orbit the visual model cannot express — placed and scaled
  like any other layer.

Built with the same edit functions the editor uses, so the file is valid by
construction.
"""

from __future__ import annotations

from pathlib import Path

from manim_studio.core.editing import edits
from manim_studio.core.model import parts
from manim_studio.core.model.schema import Canvas, Easing, Project, Spec

OUT = Path(__file__).with_name("showcase.json")

ORBIT = """class Orbit(Scene):
    def construct(self):
        t = ValueTracker(0)
        sun = Dot(radius=0.18, color=ORANGE)
        planet = Dot(radius=0.1, color=TEAL).add_updater(
            lambda d: d.move_to([1.6 * np.cos(t.get_value()), 1.0 * np.sin(t.get_value()), 0])
        )
        moon = Dot(radius=0.05, color=WHITE).add_updater(
            lambda d: d.move_to(
                planet.get_center()
                + 0.4 * np.array([np.cos(5 * t.get_value()), np.sin(5 * t.get_value()), 0])
            )
        )
        planet.update()
        moon.update()  # in place before the trail starts, or it begins with a line from the origin
        trail = TracedPath(moon.get_center, stroke_color=BLUE_B, stroke_width=2, dissipating_time=1.5)
        orbit = Ellipse(width=3.2, height=2.0, stroke_color=GREY_B, stroke_width=1.5)
        self.add(orbit, trail, sun, planet, moon)
        self.play(t.animate.set_value(2 * TAU), run_time=7, rate_func=linear)
"""

SPRING = Easing(name=None, bezier=(0.34, 1.56, 0.64, 1.0))  # overshoots, then settles
SNAPPY = Easing(name=None, bezier=(0.7, 0.0, 0.2, 1.0))


def build() -> Project:
    p = Project(canvas=Canvas(width_px=1280, height_px=720, fps=30, background="#0f172a", duration=10.0))

    def apply(edit: edits.Edit) -> None:
        nonlocal p
        p = edit.project

    # Title
    apply(
        edits.add_layer(
            p, Spec(type="Text", params={"text": "Manim Studio", "font_size": 44}), layer_id="title"
        )
    )
    apply(edits.update_layer(p, "title", base={"position": (0.0, 3.3)}))
    apply(edits.add_clip(p, "title", "FadeIn", 0.0, 0.8, params={"shift": "RIGHT"}))  # in from the left
    apply(edits.add_clip(p, "title", "FadeOut", 9.0, 0.8))

    # Equation with part layers
    eq_tex = r"a^2 + b^2 = c^2"
    apply(edits.add_layer(p, Spec(type="MathTex", params={"text": eq_tex, "font_size": 72}), layer_id="eq"))
    apply(edits.update_layer(p, "eq", base={"position": (0.0, 1.6)}))
    apply(edits.add_clip(p, "eq", "Write", 0.8, 1.5))
    apply(edits.add_parts(p, "eq", parts.split_terms(eq_tex), layer_ids=["a2", "b2", "c2"]))
    apply(edits.add_clip(p, "b2", "Indicate", 2.6, 1.0))
    apply(edits.set_key(p, "a2", "position", 3.0, (0.0, 0.0)))
    apply(edits.set_key(p, "a2", "position", 3.8, (0.0, 0.9)))
    apply(edits.set_key(p, "a2", "position", 4.8, (0.0, 0.0)))
    apply(edits.set_key_ease(p, "a2", 3.0, SNAPPY))
    apply(edits.set_key_ease(p, "a2", 3.8, SPRING))
    apply(edits.add_clip(p, "c2", "Wiggle", 4.0, 1.2))
    # ... then the whole equation turns into another, term by term (ADR 0020)
    eq2_tex = r"c^2 = a^2 + b^2"
    eq2 = Spec(type="MathTex", params={"text": eq2_tex, "font_size": 72})
    apply(edits.add_layer(p, eq2, layer_id="eq2"))
    apply(edits.update_layer(p, "eq2", base={"position": (0.0, 1.6)}))
    apply(edits.add_parts(p, "eq2", parts.split_terms(eq2_tex), layer_ids=["c2b", "a2b", "b2b"]))
    apply(edits.add_clip(p, "eq", "TransformMatchingTex", 6.2, 1.4, to_layer="eq2"))
    # ... and its c^2 is circled (an overlay clip on a part, ADR 0022)
    apply(edits.add_clip(p, "c2b", "Circumscribe", 8.0, 1.2, params={"shape": "circle", "color": "#22d3ee"}))

    # Square: drawn, spins and grows on keyframes, then turns into a circle
    square = Spec(type="Square", params={"side_length": 1.6}, style={"fill": "#6366f1", "fill_opacity": 0.6})
    apply(edits.add_layer(p, square, layer_id="square"))
    apply(edits.update_layer(p, "square", base={"position": (-4.2, -1.6)}))
    apply(edits.add_clip(p, "square", "Create", 1.5, 1.0))
    apply(edits.set_key(p, "square", "rotation", 2.5, 0.0))
    apply(edits.set_key(p, "square", "rotation", 5.0, 180.0))
    apply(edits.set_key(p, "square", "scale", 2.5, 1.0))
    apply(edits.set_key(p, "square", "scale", 4.0, 1.4))
    apply(edits.set_key_ease(p, "square", 2.5, SPRING, props=["scale"]))
    circle = Spec(type="Circle", params={"radius": 1.0}, style={"fill": "#f43f5e", "fill_opacity": 0.6})
    apply(edits.add_layer(p, circle, layer_id="circle"))
    apply(edits.update_layer(p, "circle", base={"position": (-4.2, -1.6)}))
    apply(edits.add_clip(p, "square", "Transform", 5.5, 1.5, to_layer="circle"))
    apply(edits.add_clip(p, "circle", "Indicate", 7.5, 1.0))

    # Star: grows in and pulses its opacity
    star = Spec(
        type="Star", params={"n": 6, "outer_radius": 0.7}, style={"fill": "#facc15", "fill_opacity": 0.9}
    )
    apply(edits.add_layer(p, star, layer_id="star"))
    apply(edits.update_layer(p, "star", base={"position": (0.0, -2.2)}))
    apply(edits.add_clip(p, "star", "GrowFromCenter", 2.0, 1.0))
    for t, value in ((3.0, 1.0), (4.0, 0.3), (5.0, 1.0), (6.0, 0.3), (7.0, 1.0)):
        apply(edits.set_key(p, "star", "opacity", t, value))
    apply(edits.set_key(p, "star", "rotation", 3.0, 0.0))
    apply(edits.set_key(p, "star", "rotation", 9.0, 360.0))
    apply(edits.add_clip(p, "star", "Flash", 7.4, 0.8, params={"color": "#fde047"}))

    # Pendulum: rod and bob swing about one pivot through their anchors (ADR 0021)
    pivot = (-5.6, 3.2)
    rod = Spec(
        type="Line",
        params={"start": (0.0, 0.0), "end": (0.0, -2.2)},
        style={"stroke": "#cbd5e1", "stroke_width": 6},
    )
    bob = Spec(
        type="Circle",
        params={"radius": 0.22},
        style={"fill": "#14b8a6", "fill_opacity": 1.0, "stroke": "#0f766e"},
    )
    for layer_id, spec, anchor in (("rod", rod, (0.0, 1.1)), ("bob", bob, (0.0, 2.2))):
        apply(edits.add_layer(p, spec, layer_id=layer_id))
        position = (pivot[0] - anchor[0], pivot[1] - anchor[1])  # the anchor lands on the pivot
        apply(edits.update_layer(p, layer_id, base={"anchor": anchor, "position": position}))
        apply(edits.add_clip(p, layer_id, "FadeIn", 0.5, 0.6))
        for i in range(9):
            apply(edits.set_key(p, layer_id, "rotation", 1.0 + 1.0 * i, -25.0 if i % 2 == 0 else 25.0))
    apply(edits.add_layer(p, Spec(type="Dot", style={"fill": "#cbd5e1"}), layer_id="hinge"))
    apply(edits.update_layer(p, "hinge", base={"position": pivot, "scale": 0.8}))

    # Code layer: an orbit with updaters and a dissipating trail, scaled and placed like any layer
    apply(
        edits.add_layer(p, Spec(type="Code", params={"code": ORBIT}), layer_id="orbit", name="Orbit (code)")
    )
    apply(edits.update_layer(p, "orbit", base={"position": (4.2, -1.5), "scale": 0.9}, lifetime={"in": 1.0}))
    return p


if __name__ == "__main__":
    project = build()
    OUT.write_text(project.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    print(f"wrote {OUT} ({len(project.layers)} layers)")
