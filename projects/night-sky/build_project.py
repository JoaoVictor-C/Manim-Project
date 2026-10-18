"""Build the five-minute Manim Studio project: A Pocket Guide to the Night Sky.

Run from the repository root with ``uv run python projects/night-sky/build_project.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "night_sky.json"

BG = "#07111f"
INK = "#eff6ff"
MUTED = "#9fb3c8"
GOLD = "#ffd166"
BLUE = "#67d5ff"
PINK = "#ff8fab"
GREEN = "#8ce99a"
PURPLE = "#b197fc"

CHAPTERS = [
    ("01", "Look up", "The night sky is a map of light and time. Every point you see is a real sun, planet, or galaxy—separated from us by distances too large to picture.", GOLD, "START WITH ONE PATCH OF SKY"),
    ("02", "Light takes time", "Sunlight reaches Earth in about eight minutes. The Moon is just over one second away. When you look farther out, you also look farther back in time.", BLUE, "DISTANCE BECOMES HISTORY"),
    ("03", "Find a pattern", "Constellations are familiar shapes we draw between stars. Their stars may be at very different distances; the pattern belongs to our point of view.", PURPLE, "A SKY FULL OF STORIES"),
    ("04", "Follow the Moon", "The Moon does not make its own light. As it orbits Earth, sunlight illuminates changing portions of its surface: the phases we see night after night.", PINK, "A MONTHLY CYCLE"),
    ("05", "Spot the planets", "Planets shine by reflected sunlight. They often look steadier than stars and travel against the background constellations over days and weeks.", GREEN, "WANDERERS IN THE SKY"),
    ("06", "Gravity keeps the rhythm", "An orbit is a continuous fall. A planet moves forward while the Sun's gravity bends its path, keeping it circling instead of flying away.", GOLD, "MOTION MEETS ATTRACTION"),
    ("07", "Stars have a life", "Stars form inside clouds of gas, shine for millions or billions of years, and change as their fuel runs low. Our Sun is one ordinary star among many.", BLUE, "BIRTH · LIGHT · CHANGE"),
    ("08", "Our home galaxy", "The Milky Way is a vast disk of stars. From inside it, we see its crowded plane as a pale band stretching across a truly dark sky.", PURPLE, "ONE GALAXY, MANY SUNS"),
    ("09", "Make the sky visible", "Your eyes adapt to darkness. Binoculars gather more light, while a telescope reveals finer detail. Give your eyes time—and let bright screens rest.", GREEN, "PATIENCE IS AN INSTRUMENT"),
    ("10", "Keep wondering", "Step outside on a clear night. Find the Moon, trace a constellation, and remember: the sky is not a ceiling. It is a place, and we are part of it.", PINK, "THE UNIVERSE IS OUR NEIGHBOURHOOD"),
]

NARRATION = [
    ("Take a breath. Let your eyes adjust, and begin with one small patch of sky.", "You are seeing real objects, separated by distances our everyday world cannot hold."),
    ("Light has a speed, so the sky arrives with a delay.", "The farther away an object is, the older the light reaching your eyes today."),
    ("People connect bright stars into shapes that are easy to remember.", "The stars in one constellation can be far apart in space, though they look nearby from Earth."),
    ("Half of the Moon is always lit by the Sun.", "Our changing view of that sunlit half creates the familiar phases across the month."),
    ("Watch a bright point over several nights and it may change its place.", "That slow drift across the stars is a clue that you may be looking at a planet."),
    ("A planet is always moving forward through space.", "The Sun's pull continually turns that motion into a curved path: an orbit."),
    ("Stars begin in clouds of gas and dust, where gravity gathers material together.", "They shine by making energy in their cores, then change as their fuel is used up."),
    ("On a dark night, the Milky Way appears as a soft river of light.", "It is the edge-on view of our galaxy, home to the Sun and billions of other stars."),
    ("Give your eyes twenty minutes away from bright lights.", "Binoculars are a friendly first tool: steady them, look slowly, and let detail emerge."),
    ("You do not need to know every star to begin exploring.", "One clear night and one good question are enough to make the sky feel closer."),
]


def layer(layer_id: str, name: str, spec: dict, pos: tuple[float, float], start: float, end: float, *, size: float = 1.0) -> dict:
    return {
        "id": layer_id,
        "name": name,
        "spec": spec,
        "base": {"position": list(pos), "scale": size, "rotation": 0.0, "opacity": 1.0},
        "lifetime": {"in": None, "out": None},
        "tracks": {},
        "clips": [
            {"id": f"{layer_id}-in", "kind": "FadeIn", "start": start, "duration": 1.0, "ease": None, "params": {}, "to_layer": None},
            {"id": f"{layer_id}-out", "kind": "FadeOut", "start": end - 1.0, "duration": 1.0, "ease": None, "params": {}, "to_layer": None},
        ],
    }


def text_spec(text: str, font_size: int, colour: str) -> dict:
    return {"type": "Text", "params": {"text": text, "font_size": font_size}, "style": {"fill": colour}}


def build() -> dict:
    duration = 300.0
    layers = []

    # A quiet, fixed star field gives the whole film a consistent visual frame.
    stars = [(-6.0, 3.1), (-4.1, 2.6), (-2.3, 3.25), (0.2, 3.35), (2.2, 2.9), (5.8, 3.2),
             (-6.2, 0.9), (6.0, 1.4), (-5.6, -1.5), (5.7, -1.8), (-3.8, -3.15), (-1.0, -3.35),
             (2.0, -3.25), (4.4, -2.9), (0.1, 2.1), (3.8, 1.9), (-2.7, -2.0), (1.2, -1.7)]
    for i, (x, y) in enumerate(stars):
        layers.append({
            "id": f"star-{i}", "name": "Star", "spec": {"type": "Dot", "params": {"radius": 0.025 if i % 3 else 0.04}, "style": {"fill": "#d8e9ff", "fill_opacity": 0.72}},
            "base": {"position": [x, y], "scale": 1.0, "rotation": 0.0, "opacity": 1.0}, "lifetime": {"in": None, "out": None}, "tracks": {}, "clips": [],
        })

    for index, (number, title, copy, colour, kicker) in enumerate(CHAPTERS):
        start = index * 30.0
        end = start + 30.0
        prefix = f"chapter-{number}"
        layers.append(layer(f"{prefix}-number", "Chapter number", text_spec(number, 30, colour), (-5.15, 2.35), start, end))
        layers.append(layer(f"{prefix}-title", "Chapter title", text_spec(title, 56, INK), (-2.6, 1.32), start + 0.25, end))
        layers.append(layer(f"{prefix}-copy", "Explanation", text_spec(copy, 30, MUTED), (0.0, -0.2), start + 1.0, end))
        layers.append(layer(f"{prefix}-kicker", "Chapter note", text_spec(kicker, 20, colour), (0.0, -2.25), start + 1.7, end))
        # A simple colored marker shifts position by chapter, making progress visible.
        marker_x = -4.8 + index * (9.6 / 9)
        layers.append(layer(f"{prefix}-marker", "Progress marker", {
            "type": "Circle", "params": {"radius": 0.09}, "style": {"fill": colour, "stroke": colour, "stroke_width": 1.5}
        }, (marker_x, -2.9), start + 0.4, end))

    subtitles = []
    for index, pair in enumerate(NARRATION):
        start = index * 30.0
        for cue_index, words in enumerate(pair):
            cue_start = start + 1.5 + cue_index * 14.0
            subtitles.append({"id": f"narration-{index+1}-{cue_index+1}", "start": cue_start, "end": cue_start + 12.5, "text": words})

    return {
        "schema_version": 1,
        "canvas": {"width_px": 1280, "height_px": 720, "fps": 30, "background": BG, "frame_height": 8.0, "duration": duration},
        "layers": layers,
        "markers": [
            {"id": f"mark-{i+1}", "t": i * 30.0, "name": chapter[1], "colour": chapter[3]}
            for i, chapter in enumerate(CHAPTERS)
        ],
        "subtitles": subtitles,
        "subtitle_style": {"font_size": 24, "y": -3.45, "colour": INK, "band": True, "band_colour": "#020617", "band_opacity": 0.82, "fade": 0.25, "burn_in": True, "max_width": 12.0},
    }


if __name__ == "__main__":
    project = build()
    OUTPUT.write_text(json.dumps(project, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT} ({len(project['layers'])} layers, {project['canvas']['duration']:.0f}s)")
