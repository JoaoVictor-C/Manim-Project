"""Write the built-in presets and themes (ADR 0039) into ``src/manim_studio/library/``.

The JSON files are the source of truth that ships with the package; this script
is how they were made and how to regenerate them after editing the lists below.

Run: ``python examples/build_library.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from manim_studio.core.library import BUILTIN_FOLDER, Preset, Theme, item_to_json


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


def write(folder: Path, stem: str, item) -> None:
    (folder / f"{stem}.json").write_text(json.dumps(item_to_json(item), indent=1) + "\n", encoding="utf-8")


def main() -> None:
    BUILTIN_FOLDER.mkdir(exist_ok=True)
    for old in BUILTIN_FOLDER.glob("preset-*.json"):
        old.unlink()
    for old in BUILTIN_FOLDER.glob("theme-*.json"):
        old.unlink()
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
    print(f"{len(PRESETS)} presets and {len(THEMES)} themes in {BUILTIN_FOLDER}")


if __name__ == "__main__":
    main()
