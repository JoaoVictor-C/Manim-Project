"""Builds examples/camera.json: a tour of a wide scene with the camera layer (ADR 0072, 0083).

    python examples/build_camera.py
    manim-studio render examples/camera.json out/camera.mp4

What is in it (10 s, 1280x720 @ 30 fps). The scene is three times wider than the frame: three stations
side by side, 10 units apart. Nothing moves but the camera:

* 0-2 s    the camera rests on station one ("Pan");
* 2-4 s    it pans right to station two ("Zoom") on a smooth ease;
* 4-5.5 s  it zooms in on the small dot (Size 4 -> 1.4; easing runs on the size, as in Unity);
* 5.5-6.5  it zooms back out;
* 6.5-8.5  it pans on to station three ("Roll") while rolling a few degrees;
* 8.5-10   it levels out and rests.

Switch the canvas to Scene view (View > Game View off) to see the camera as a rectangle you can drag.
Built with the same edit functions the editor uses.
"""

from __future__ import annotations

from pathlib import Path

from manim_studio.core.editing import edits
from manim_studio.core.model.schema import Canvas, Easing, Project, Spec

OUT = Path(__file__).with_name("camera.json")
STATIONS = (-10.0, 0.0, 10.0)
FRAME_HEIGHT = 8.0  # the camera's Size 4 shows exactly this


def build() -> Project:
    p = Project(canvas=Canvas(duration=10.0, background="#0b1020"))

    def apply(edit: edits.Edit) -> None:
        nonlocal p
        p = edit.project

    def put(layer_id: str, spec: Spec, x: float, y: float, name: str = "") -> None:
        apply(edits.add_layer(p, spec, layer_id=layer_id, name=name))
        apply(edits.update_layer(p, layer_id, base={"position": (x, y)}))

    def text(layer_id: str, words: str, x: float, y: float, size: float = 40) -> None:
        put(layer_id, Spec(type="Text", params={"text": words, "font_size": size}), x, y)

    def shape(layer_id: str, kind: str, params: dict, colour: str, x: float, y: float) -> None:
        style = {"fill": colour, "fill_opacity": 0.85, "stroke": colour}
        put(layer_id, Spec(type=kind, params=params, style=style), x, y)

    # the world: three stations 10 units apart, a floor line so the roll is easy to see
    put(
        "floor",
        Spec(
            type="Line",
            params={"start": [-16.0, -2.4], "end": [16.0, -2.4]},
            style={"stroke": "#334155", "stroke_width": 3},
        ),
        0.0,
        0.0,
        name="Floor",
    )
    for number, x in enumerate(STATIONS, 1):
        text(f"label{number}", ("Pan", "Zoom", "Roll")[number - 1], x, 2.6, 56)
        text(f"hint{number}", f"station {number}", x, 1.5, 26)
    shape("square", "Square", {"side_length": 2.2}, "#38bdf8", STATIONS[0], -0.6)
    shape("circle", "Circle", {"radius": 1.1}, "#f472b6", STATIONS[1] - 1.8, -0.6)
    shape("dot", "Dot", {"radius": 0.14}, "#facc15", STATIONS[1] + 1.8, -0.6)
    shape("tri", "Triangle", {}, "#a3e635", STATIONS[2], -0.6)
    apply(edits.update_layer(p, "tri", base={"position": (STATIONS[2], -0.6), "scale": 1.3}))

    # the camera: a layer of its own, keyed like any other. Position is where it looks; Size is half the
    # visible height (4 shows the whole 8-unit frame); rotation rolls the view.
    apply(edits.add_camera(p))
    cam = next(layer.id for layer in p.layers if layer.is_camera)
    apply(edits.update_layer(p, cam, spec=Spec(type="Camera", params={"background": "#101a3a"})))

    def size_key(t: float, size: float) -> None:
        apply(edits.set_key(p, cam, "scale", t, (FRAME_HEIGHT / 2) / size))

    def move_key(t: float, x: float, y: float = 0.0) -> None:
        apply(edits.set_key(p, cam, "position", t, (x, y)))

    def roll_key(t: float, degrees: float) -> None:
        apply(edits.set_key(p, cam, "rotation", t, degrees))

    for t, x in ((0.0, STATIONS[0]), (2.0, STATIONS[0]), (4.0, STATIONS[1])):
        move_key(t, x)
    move_key(5.5, STATIONS[1] + 1.8, -0.6)  # in on the dot ...
    move_key(6.5, STATIONS[1])  # ... and back
    move_key(8.5, STATIONS[2])
    size_key(0.0, 4.0)
    size_key(4.0, 4.0)
    size_key(5.5, 1.4)
    size_key(6.5, 4.0)
    roll_key(0.0, 0.0)
    roll_key(6.5, 0.0)
    roll_key(7.5, -8.0)
    roll_key(8.5, 0.0)
    smooth = Easing(name="smooth")
    for t in (0.0, 2.0, 4.0, 5.5, 6.5, 7.5):
        apply(edits.set_key_ease(p, cam, t, smooth))
    return p


if __name__ == "__main__":
    project = build()
    OUT.write_text(project.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    print(f"wrote {OUT}")
