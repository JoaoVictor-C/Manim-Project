"""Write the built-in presets, themes and templates (ADR 0039) into ``src/manim_studio/data/library/``.

The JSON files are the source of truth that ships with the package; this script
is how they were made and how to regenerate them after editing the lists below.

Run: ``python examples/build_library.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from manim_studio.core.editing.library import BUILTIN_FOLDER, Preset, Template, Theme, item_to_json
from manim_studio.core.model.schema import Clip, Layer, Spec, Transform2D


def clip(kinds, duration, offset=0.0, ease=None, **params):
    out = {
        "kinds": [kinds] if isinstance(kinds, str) else list(kinds),
        "duration": duration,
        "offset": offset,
    }
    if ease:
        out["ease"] = {"name": ease}
    if params:
        out["params"] = params
    return out


def key(dt, value, ease="smooth"):
    return {"dt": dt, "value": value, "ease": {"name": ease}}


PRESETS = [
    # entrances
    ("entrance", "Fade in", "Fades in.", [clip("FadeIn", 0.5)], {}),
    (
        "entrance",
        "Pop in",
        "Fades in while growing past its size and settling.",
        [clip("FadeIn", 0.25)],
        {"scale": [key(0, 0.6), key(0.25, 1.12), key(0.4, 1.0)]},
    ),
    ("entrance", "Slide in from left", "Fades in moving right.", [clip("FadeIn", 0.6, shift="RIGHT")], {}),
    ("entrance", "Slide in from right", "Fades in moving left.", [clip("FadeIn", 0.6, shift="LEFT")], {}),
    ("entrance", "Rise in", "Fades in moving up.", [clip("FadeIn", 0.6, shift="UP")], {}),
    (
        "entrance",
        "Typewriter",
        "Letter by letter (text), or written.",
        [clip(["AddTextLetterByLetter", "Write"], 1.0)],
        {},
    ),
    ("entrance", "Write", "Written stroke by stroke.", [clip(["Write", "Create", "FadeIn"], 1.0)], {}),
    (
        "entrance",
        "Draw",
        "Outline drawn, then filled.",
        [clip(["DrawBorderThenFill", "Create", "FadeIn"], 1.0)],
        {},
    ),
    (
        "entrance",
        "Grow from below",
        "Grows up from its bottom edge.",
        [clip("GrowFromEdge", 0.6, edge="DOWN")],
        {},
    ),
    ("entrance", "Grow from centre", "Grows from its centre.", [clip("GrowFromCenter", 0.5)], {}),
    ("entrance", "Spin in", "Spins in from nothing.", [clip("SpinInFromNothing", 0.7)], {}),
    ("entrance", "Spiral in", "Spirals in.", [clip(["SpiralIn", "FadeIn"], 1.0)], {}),
    # emphasis
    ("emphasis", "Indicate", "Flashes yellow and grows a little.", [clip("Indicate", 0.8)], {}),
    (
        "emphasis",
        "Pulse",
        "Grows a little and back.",
        [],
        {"scale": [key(0, 1.0), key(0.25, 1.15), key(0.5, 1.0)]},
    ),
    ("emphasis", "Wiggle", "Wiggles (Indicate on images).", [clip(["Wiggle", "Indicate"], 0.8)], {}),
    ("emphasis", "Circle it", "A frame is drawn around it.", [clip("Circumscribe", 1.0)], {}),
    (
        "emphasis",
        "Circle it (round)",
        "A circle is drawn around it.",
        [clip("Circumscribe", 1.0, shape="circle")],
        {},
    ),
    ("emphasis", "Flash", "Lines flash out of it.", [clip("Flash", 0.6)], {}),
    ("emphasis", "Focus", "A spotlight closes on it.", [clip("FocusOn", 0.8)], {}),
    ("emphasis", "Wave", "A wave runs through it.", [clip(["ApplyWave", "Indicate"], 1.0)], {}),
    # exits
    ("exit", "Fade out", "Fades out.", [clip("FadeOut", 0.5)], {}),
    ("exit", "Shrink out", "Shrinks to its centre.", [clip("ShrinkToCenter", 0.5)], {}),
    ("exit", "Slide out to right", "Fades out moving right.", [clip("FadeOut", 0.6, shift="RIGHT")], {}),
    ("exit", "Slide out to left", "Fades out moving left.", [clip("FadeOut", 0.6, shift="LEFT")], {}),
    ("exit", "Sink out", "Fades out moving down.", [clip("FadeOut", 0.6, shift="DOWN")], {}),
    ("exit", "Unwrite", "Unwritten (faded on images).", [clip(["Unwrite", "Uncreate", "FadeOut"], 0.8)], {}),
    ("exit", "Uncreate", "Undrawn (faded on images).", [clip(["Uncreate", "FadeOut"], 0.8)], {}),
    # motion
    (
        "motion",
        "Drift up",
        "Moves half a unit up over two seconds.",
        [],
        {"position": [key(0, [0.0, 0.0], "linear"), key(2.0, [0.0, 0.5])]},
    ),
    (
        "motion",
        "Bounce",
        "Hops up twice.",
        [],
        {
            "position": [
                key(0, [0.0, 0.0], "rush_from"),
                key(0.25, [0.0, 0.6], "rush_into"),
                key(0.5, [0.0, 0.0], "rush_from"),
                key(0.65, [0.0, 0.25], "rush_into"),
                key(0.8, [0.0, 0.0]),
            ]
        },
    ),
    ("motion", "Spin", "Turns once around.", [], {"rotation": [key(0, 0.0), key(1.0, 360.0)]}),
    (
        "motion",
        "Grow",
        "Grows to one and a half times its size.",
        [],
        {"scale": [key(0, 1.0), key(0.8, 1.5)]},
    ),
    ("motion", "Shrink", "Shrinks to two thirds of its size.", [], {"scale": [key(0, 1.0), key(0.8, 2 / 3)]}),
]

THEMES = [
    ("Manim", "Black, with Manim's blue and yellow.", "#000000", "#ffffff", "#58c4dd", "#ffff00"),
    ("Chalkboard", "Green board, chalk colours.", "#1f3a2e", "#f1f5f0", "#f4d35e", "#ee964b"),
    ("Paper", "Light paper, ink colours.", "#faf7f0", "#1f2937", "#2563eb", "#dc2626"),
    ("Blueprint", "Deep blue, pale lines.", "#0b3d91", "#e0f2fe", "#93c5fd", "#fde047"),
    ("Midnight", "Slate night, cyan and pink.", "#0f172a", "#e2e8f0", "#38bdf8", "#f472b6"),
]


def layer(layer_id, name, type_name, at=(0.0, 0.0), clips=(), style=None, **params):
    return Layer(
        id=layer_id,
        name=name,
        spec=Spec(type=type_name, params=params, style=style or {}),
        base=Transform2D(position=at),
        clips=[
            Clip(id=f"{layer_id}-{i}", kind=k, start=s, duration=d, params=p)
            for i, (k, s, d, p) in enumerate(clips)
        ],
    )


TEMPLATES = [
    (
        "Title card",
        "A title, an underline and a subtitle, written in.",
        [
            layer(
                "title", "Title", "Text", (0.0, 0.7), [("Write", 0.0, 1.0, {})], text="Title", font_size=72
            ),
            layer(
                "rule",
                "Underline",
                "Line",
                (0.0, 0.05),
                [("Create", 0.6, 0.6, {})],
                {"stroke_width": 3},
                start=(-3.0, 0.0),
                end=(3.0, 0.0),
            ),
            layer(
                "subtitle",
                "Subtitle",
                "Text",
                (0.0, -0.6),
                [("FadeIn", 1.0, 0.6, {"shift": "UP"})],
                text="Subtitle",
                font_size=34,
            ),
        ],
    ),
    (
        "Section header",
        "A heading at the top with a short rule under it.",
        [
            layer(
                "heading",
                "Section",
                "Text",
                (0.0, 3.2),
                [("Write", 0.0, 0.8, {})],
                text="Section",
                font_size=48,
            ),
            layer(
                "rule",
                "Rule",
                "Line",
                (0.0, 2.7),
                [("Create", 0.4, 0.5, {})],
                {"stroke_width": 2},
                start=(-2.0, 0.0),
                end=(2.0, 0.0),
            ),
        ],
    ),
    (
        "Lower third",
        "A band with a name and a role, sliding in at the bottom left.",
        [
            layer(
                "band",
                "Band",
                "Rectangle",
                (-3.3, -2.75),
                [("FadeIn", 0.0, 0.5, {"shift": "RIGHT"})],
                {"fill": "#0f172a", "fill_opacity": 0.85, "stroke_width": 0},
                width=6.5,
                height=1.3,
            ),
            layer(
                "name",
                "Name",
                "Text",
                (-3.6, -2.5),
                [("FadeIn", 0.2, 0.5, {"shift": "RIGHT"})],
                text="Name Surname",
                font_size=34,
            ),
            layer(
                "role",
                "Role",
                "Text",
                (-3.6, -3.05),
                [("FadeIn", 0.35, 0.5, {"shift": "RIGHT"})],
                text="Role",
                font_size=24,
            ),
        ],
    ),
    (
        "Callout",
        "A labelled box with an arrow to a dot: move the dot onto what it points at.",
        [
            layer("anchor", "Points at", "Dot", (0.0, 0.0), [("FadeIn", 0.0, 0.3, {})], radius=0.06),
            layer("box", "Box", "Rectangle", (3.0, 1.8), [("Create", 0.0, 0.6, {})], width=3.2, height=1.1),
            layer(
                "label",
                "Label",
                "Text",
                (3.0, 1.8),
                [("Write", 0.3, 0.6, {})],
                text="Look here",
                font_size=30,
            ),
            layer(
                "arrow", "Arrow", "Connector", clips=(), source="box", target="anchor", tips="end", gap=0.1
            ),
        ],
    ),
    (
        "Equation reveal",
        "An equation written, then indicated.",
        [
            layer(
                "equation",
                "Equation",
                "MathTex",
                (0.0, 0.0),
                [("Write", 0.0, 1.5, {}), ("Indicate", 2.0, 0.8, {})],
                text=r"e^{i\pi} + 1 = 0",
                font_size=72,
            ),
        ],
    ),
    (
        "Counter",
        "A label and a number counting from 0 to 100.",
        [
            layer(
                "label", "Label", "Text", (-1.4, 0.0), [("FadeIn", 0.0, 0.4, {})], text="Value:", font_size=40
            ),
            layer(
                "number",
                "Number",
                "DecimalNumber",
                (0.9, 0.0),
                [("FadeIn", 0.0, 0.4, {}), ("ChangeDecimalToValue", 0.5, 2.0, {"target_number": 100.0})],
                number=0.0,
                num_decimal_places=0,
            ),
        ],
    ),
]


def write(folder: Path, stem: str, item) -> None:
    (folder / f"{stem}.json").write_text(json.dumps(item_to_json(item), indent=1) + "\n", encoding="utf-8")


def main() -> None:
    BUILTIN_FOLDER.mkdir(exist_ok=True)
    for old in BUILTIN_FOLDER.glob("preset-*.json"):
        old.unlink()
    for old in BUILTIN_FOLDER.glob("theme-*.json"):
        old.unlink()
    for old in BUILTIN_FOLDER.glob("template-*.json"):
        old.unlink()
    for name, description, layers in TEMPLATES:
        write(
            BUILTIN_FOLDER,
            f"template-{name.lower().replace(' ', '-')}",
            Template(name=name, description=description, layers=layers),
        )
    for i, (category, name, description, clips, keys) in enumerate(PRESETS):
        preset = Preset(name=name, category=category, description=description, clips=clips, keys=keys)
        write(
            BUILTIN_FOLDER,
            f"preset-{i:02d}-{name.lower().replace(' ', '-').replace('(', '').replace(')', '')}",
            preset,
        )
    for name, description, *colours in THEMES:
        theme = Theme(
            name=name,
            description=description,
            **dict(zip(("background", "text", "shape", "accent"), colours, strict=True)),
        )
        write(BUILTIN_FOLDER, f"theme-{name.lower()}", theme)
    print(f"{len(PRESETS)} presets, {len(THEMES)} themes and {len(TEMPLATES)} templates in {BUILTIN_FOLDER}")


if __name__ == "__main__":
    main()
