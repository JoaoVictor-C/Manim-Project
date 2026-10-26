"""Builds "Momentum, Torque and Angular Momentum": script.md and angular_momentum.json.

    uv run python examples/angular_momentum/build.py             # everything
    uv run python examples/angular_momentum/build.py --scenes    # also write scratch/<id>.py to test a scene
    uv run manim-studio render examples/angular_momentum/angular_momentum.json \
        out/angular_momentum.mp4 --trust-code

The narration is Studio's own feature (ADR 0060): ``narration.py`` has the sentences, this script makes one
subtitle of each with its voice, and ``manim-studio narrate`` speaks them, places the sounds and lays the
subtitles out one speech after another (Follow speech). The sounds are kept in ``angular_momentum_voice/``
by what they say, so a sentence that did not change is never spoken again; a new or changed one needs the
online voice: pass ``--allow-online`` to let the text go to it.

Each section is a Manim code layer that waits for its sentences (their start times are read back from the
subtitles); titles, subtitles and the sound are Studio's own.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import narration  # noqa: E402
import scenes  # noqa: E402

from manim_studio import cli  # noqa: E402
from manim_studio.core.editing import edits  # noqa: E402
from manim_studio.core.model import scene_length  # noqa: E402
from manim_studio.core.model.schema import Canvas, Cue, Project, Spec, VoiceChoice  # noqa: E402

PROJECT = HERE / "angular_momentum.json"
VOICE = VoiceChoice(provider="edge", voice="en-US-AndrewNeural", rate=0.91)
PAUSE = 0.9  # between sentences
LEAD = 1.0  # before a section's first sentence
TAIL = 1.8  # after its last sentence
OPENING = 0.6
INK, MUTED, YELLOW = "#e2e8f0", "#94a3b8", "#facc15"
BG = "#0f172a"


def skeleton() -> Project:
    """One subtitle per sentence, in order, with the voice; where they sit in time is Follow speech's job.

    The first sentence of a section is a longer silence after the one before it: the end of that section
    (``TAIL``) and the start of this one (``LEAD``), so it is that subtitle's own ``pause_before``."""
    cues, t = [], OPENING + LEAD
    for section_index, section in enumerate(narration.SECTIONS):
        for i, text in enumerate(section["sentences"]):
            first = i == 0 and section_index > 0
            cues.append(
                Cue(
                    id=f"cue-{len(cues) + 1}",
                    start=t,
                    end=t + 1.0,
                    text=text,
                    pause_before=LEAD + TAIL if first else None,
                )
            )
            t += 1.0 + PAUSE
    canvas = Canvas(width_px=1280, height_px=720, fps=30, background=BG, duration=t)
    return Project(canvas=canvas, subtitles=cues, voice=VOICE)


def narrate(allow_online: bool) -> Project:
    """Speak what is missing and lay the subtitles out (``manim-studio narrate``), then read the result."""
    PROJECT.write_text(skeleton().model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    argv = ["narrate", str(PROJECT), "--follow-speech", "--pause", str(PAUSE)]
    code = cli.main([*argv, *(["--allow-online"] if allow_online else [])])
    if code != 0:
        sys.exit(code)
    return Project.model_validate_json(PROJECT.read_text(encoding="utf-8"))


def schedule(project: Project):
    """Per section: start, end, sentence starts (relative to the section start) and their durations."""
    cues = iter(project.subtitles)
    out = []
    for s in narration.SECTIONS:
        mine = [next(cues) for _ in s["sentences"]]
        start = mine[0].start - LEAD
        length = mine[-1].end + TAIL - start
        out.append(
            {
                **s,
                "start": round(start, 3),
                "length": round(length, 3),
                "beats": [round(c.start - start, 3) for c in mine],
                "lens": [round(c.end - c.start, 3) for c in mine],
            }
        )
    return out, round(out[-1]["start"] + out[-1]["length"] + 0.8, 3)


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
        lines += [
            f"## {s['title']}  ·  {m}:{sec:02d} ({s['length']:.0f} s)",
            "",
            f"*On screen:* {s['visual']}",
            "",
        ]
        lines += [f"> {t}" for t in s["sentences"]]
        lines.append("")
    (HERE / "script.md").write_text("\n".join(lines), encoding="utf-8")


def build(project: Project, plan, total) -> Project:
    p = project

    def apply(edit):
        nonlocal p
        p = edit.project

    for s in plan:
        sid = s["id"]
        apply(
            edits.add_layer(
                p,
                Spec(type="Code", params={"code": scene_code(s)}),
                layer_id=f"scene-{sid}",
                name=f"{s['title']} (scene)",
            )
        )
        apply(
            edits.update_layer(
                p, f"scene-{sid}", lifetime={"in": s["start"], "out": round(s["start"] + s["length"], 3)}
            )
        )
        title = Spec(type="Text", params={"text": s["title"], "font_size": 40}, style={"fill": INK})
        apply(edits.add_layer(p, title, layer_id=f"title-{sid}", name=f"Title: {s['title']}"))
        apply(edits.update_layer(p, f"title-{sid}", base={"position": (0.0, 3.35)}))
        apply(edits.add_clip(p, f"title-{sid}", "FadeIn", s["start"] + 0.1, 0.6, params={"shift": "DOWN"}))
        apply(edits.add_clip(p, f"title-{sid}", "FadeOut", s["start"] + s["length"] - 0.7, 0.6))
        apply(edits.add_marker(p, s["start"], s["title"]))
    apply(
        edits.set_subtitle_style(
            p,
            font_size=24,
            y=-3.55,
            colour=INK,
            band=True,
            band_colour="#000000",
            band_opacity=0.55,
            burn_in=True,
            max_width=12.5,
        )
    )
    return p.model_copy(update={"canvas": scene_length.set_length(p, total).canvas})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", action="store_true", help="write scratch/<id>.py standalone scenes")
    ap.add_argument(
        "--allow-online", action="store_true", help="let new or changed sentences go to the online voice"
    )
    args = ap.parse_args()
    narrated = narrate(args.allow_online)
    plan, total = schedule(narrated)
    write_script_md(plan, total)
    if args.scenes:
        d = HERE / "scratch"
        d.mkdir(exist_ok=True)
        for s in plan:
            (d / f"{s['id']}.py").write_text(
                'from manim import *\nconfig.background_color = "' + BG + '"\n' + scene_code(s),
                encoding="utf-8",
            )
    project = build(narrated, plan, total)
    PROJECT.write_text(project.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    print(f"wrote {PROJECT} ({len(project.layers)} layers, {len(project.audio)} sounds, {total:.1f} s)")
    for s in plan:
        print(f"  {s['id']:13s} {s['start']:6.1f} -> {s['start'] + s['length']:6.1f}")


if __name__ == "__main__":
    main()
