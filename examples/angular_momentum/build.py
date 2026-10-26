"""Builds "Momentum, Torque and Angular Momentum": script.md, the narration audio and angular_momentum.json.

    uv run python examples/angular_momentum/build.py                 # everything
    uv run python examples/angular_momentum/build.py --scenes        # also write scratch/<id>.py to test one scene
    uv run manim-studio render examples/angular_momentum/angular_momentum.json out/angular_momentum.mp4 --trust-code

Narration is Windows' Microsoft Zira voice (one WAV per sentence). Each section is a Manim code layer that
waits for its sentences; titles, subtitles and the sound are Studio's own.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import narration  # noqa: E402
import scenes  # noqa: E402
import tts  # noqa: E402

from manim_studio.core.editing import edits  # noqa: E402
from manim_studio.core.model.schema import Canvas, Project, Spec  # noqa: E402

PAUSE = 0.9  # between sentences
LEAD = 1.0  # before a section's first sentence
TAIL = 1.8  # after its last sentence
OPENING = 0.6
INK, MUTED, YELLOW = "#e2e8f0", "#94a3b8", "#facc15"
BG = "#0f172a"


def schedule():
    """Per section: start, end, sentence starts (relative to the section start) and their durations."""
    texts = {f"{s['id']}_{i}": t for s in narration.SECTIONS for i, t in enumerate(s["sentences"])}
    clips = tts.synthesize(texts, HERE / "voice")
    t = OPENING
    out = []
    for s in narration.SECTIONS:
        start = t
        rel = LEAD
        beats, lens = [], []
        for i in range(len(s["sentences"])):
            path, secs = clips[f"{s['id']}_{i}"]
            beats.append(round(rel, 3))
            lens.append(secs)
            rel += secs + PAUSE
        length = rel - PAUSE + TAIL
        out.append({**s, "start": round(start, 3), "length": round(length, 3), "beats": beats, "lens": lens,
                    "paths": [clips[f"{s['id']}_{i}"][0] for i in range(len(s["sentences"]))]})
        t += length
    return out, round(t + 0.8, 3)


def scene_code(section) -> str:
    return f"B = {section['beats'] + [section['length']]}\n" + scenes.CODE[section["id"]]


def write_script_md(plan, total) -> None:
    lines = [
        "# Momentum, Torque and Angular Momentum - video script",
        "",
        f"Running time: about {int(total // 60)}:{int(total % 60):02d}. Narration: one voice. "
        "The animation (Manim scenes) and subtitles are built by `build.py`; the exact wording below is "
        "the narration and the subtitles.",
        "",
    ]
    for s in plan:
        m, sec = divmod(int(s["start"]), 60)
        lines += [f"## {s['title']}  ·  {m}:{sec:02d} ({s['length']:.0f} s)", "", f"*On screen:* {s['visual']}", ""]
        lines += [f"> {t}" for t in s["sentences"]]
        lines.append("")
    (HERE / "script.md").write_text("\n".join(lines), encoding="utf-8")


def chunks(text, start, length, limit=62):
    """Split a sentence into short one-line subtitle pieces, timed by their share of the characters."""
    import re
    parts = [x.strip() for x in re.split(r"(?<=[,:;.])\s+", text) if x.strip()]
    out = []
    for part in parts:
        if out and len(out[-1]) + 1 + len(part) <= limit:
            out[-1] += " " + part
        else:
            out.append(part)
    final = []
    for part in out:
        while len(part) > limit + 14:  # still long: cut at the space nearest the middle
            cut = part.rfind(" ", 0, len(part) // 2 + 6)
            final.append(part[:cut])
            part = part[cut + 1:]
        final.append(part)
    total = sum(len(x) for x in final)
    t = start
    res = []
    for k, piece in enumerate(final):
        dur = length * len(piece) / total
        res.append((round(t, 3), round(t + dur - (0.02 if k < len(final) - 1 else 0), 3), piece))
        t += dur
    return res


def build(plan, total) -> Project:
    p = Project(canvas=Canvas(width_px=1280, height_px=720, fps=30, background=BG, duration=total))

    def apply(edit):
        nonlocal p
        p = edit.project

    for s in plan:
        sid = s["id"]
        apply(edits.add_layer(p, Spec(type="Code", params={"code": scene_code(s)}), layer_id=f"scene-{sid}", name=f"{s['title']} (scene)"))
        apply(edits.update_layer(p, f"scene-{sid}", lifetime={"in": s["start"], "out": round(s["start"] + s["length"], 3)}))
        if True:
            title = Spec(type="Text", params={"text": s["title"], "font_size": 40}, style={"fill": INK})
            apply(edits.add_layer(p, title, layer_id=f"title-{sid}", name=f"Title: {s['title']}"))
            apply(edits.update_layer(p, f"title-{sid}", base={"position": (0.0, 3.35)}))
            apply(edits.add_clip(p, f"title-{sid}", "FadeIn", s["start"] + 0.1, 0.6, params={"shift": "DOWN"}))
            apply(edits.add_clip(p, f"title-{sid}", "FadeOut", s["start"] + s["length"] - 0.7, 0.6))
        apply(edits.add_marker(p, s["start"], s["title"]))
        for i, text in enumerate(s["sentences"]):
            a = s["start"] + s["beats"][i]
            apply(edits.add_audio(p, str(s["paths"][i]), a, s["lens"][i], name=f"{sid} {i + 1}"))
            for c0, c1, piece in chunks(text, a, s["lens"][i]):
                apply(edits.add_cue(p, c0, c1, piece))
    apply(edits.set_subtitle_style(p, font_size=24, y=-3.55, colour=INK, band=True, band_colour="#000000",
                                   band_opacity=0.55, burn_in=True, max_width=12.5))
    return p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", action="store_true", help="write scratch/<id>.py standalone scenes")
    args = ap.parse_args()
    plan, total = schedule()
    write_script_md(plan, total)
    if args.scenes:
        d = HERE / "scratch"
        d.mkdir(exist_ok=True)
        for s in plan:
            (d / f"{s['id']}.py").write_text(
                'from manim import *\nconfig.background_color = "' + BG + '"\n' + scene_code(s), encoding="utf-8")
    project = build(plan, total)
    out = HERE / "angular_momentum.json"
    out.write_text(project.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    print(f"wrote {out} ({len(project.layers)} layers, {total:.1f} s)")
    for s in plan:
        print(f"  {s['id']:13s} {s['start']:6.1f} -> {s['start'] + s['length']:6.1f}")


if __name__ == "__main__":
    main()
