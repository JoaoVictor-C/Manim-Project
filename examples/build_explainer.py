"""Builds examples/explainer.json: "What is a derivative?", a 1.5-minute explainer video.

    python examples/build_explainer.py
    manim-studio render examples/explainer.json out/explainer.mp4

A complete little lesson made only with the editor's features:

* subtitles along the bottom on a dark band (Text layers that fade in and out);
* explanatory text: section headers, formulas written in (MathTex), one formula
  turning into another (TransformMatchingTex) and circled (Circumscribe);
* axes with a curve; points on the curve; a secant line that slides, step by
  step (morphs), into the tangent; Delta x / Delta y guides;
* a dot running along the curve (MoveAlongPath) with a tangent that turns with
  it (rotate along, ADR 0029) and a comet tail (a traced path, ADR 0033);
* sound effects synthesized here (pops, whooshes, ticks, pencil strokes, chimes)
  and a quiet pad under everything, placed on the audio track (ADR 0034).

Built with the same edit functions the editor uses, so the file is valid by
construction. The sounds are written next to this script (``explainer_audio/``)
and referenced by absolute path, as the editor does.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from manim_studio.core import adapter, audio, edits
from manim_studio.core.schema import Canvas, Easing, Project, Spec

HERE = Path(__file__).resolve().parent
OUT = HERE / "explainer.json"
SOUNDS = HERE / "explainer_audio"
DURATION = 95.0
MASTER_GAIN = 4.0  # dB on every cue: the mix peaks near -3 dBFS

INK = "#e2e8f0"
MUTED = "#94a3b8"
BLUE = "#38bdf8"
ORANGE = "#fb923c"
GREEN = "#4ade80"
PINK = "#f472b6"
YELLOW = "#facc15"
LINEAR = Easing(name="linear")

# The curve: f(x) = x^2 / 4 on axes at the left of the frame; formulas go on the right.
AXES = Spec(
    type="Axes",
    params={
        "x_range": [-0.5, 5.0],
        "x_step": 1.0,
        "y_range": [-0.5, 5.5],
        "y_step": 1.0,
        "x_length": 6.8,
        "y_length": 5.0,
        "numbers": "yes",
    },
)
AXES_AT = (-2.9, -0.15)
P_X = 1.5  # the point where the slope is asked for


def f(x: float) -> float:
    return x * x / 4


# -- sound effects ----------------------------------------------------------------------------

RATE = audio.RATE


def _t(seconds: float) -> np.ndarray:
    return np.arange(round(seconds * RATE)) / RATE


def _stereo(mono: np.ndarray, pan: np.ndarray | float = 0.0) -> np.ndarray:
    """-1 = left, 1 = right (equal power)."""
    angle = (np.asarray(pan) + 1) * math.pi / 4
    return np.stack([mono * np.cos(angle), mono * np.sin(angle)]).astype(np.float32)


def _lowpass(signal: np.ndarray, width: int) -> np.ndarray:
    kernel = np.hanning(width)
    return np.convolve(signal, kernel / kernel.sum(), mode="same")


def pop() -> np.ndarray:
    t = _t(0.16)
    freq = 900 * np.exp(-t * 18) + 380  # a quick downward chirp
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    return _stereo(0.7 * np.sin(phase) * np.exp(-t * 28))


def tick() -> np.ndarray:
    t = _t(0.06)
    return _stereo(0.6 * np.sin(2 * np.pi * 2200 * t) * np.exp(-t * 90))


def whoosh() -> np.ndarray:
    t = _t(0.9)
    noise = np.random.default_rng(7).standard_normal(len(t))
    airy = noise - _lowpass(noise, 9)  # the hiss, without the rumble
    body = _lowpass(noise, 40) * 3
    envelope = np.sin(np.pi * t / t[-1]) ** 2
    return _stereo(0.25 * (airy + body) * envelope, pan=np.linspace(-0.8, 0.8, len(t)))


def pencil() -> np.ndarray:
    t = _t(1.4)
    noise = np.random.default_rng(11).standard_normal(len(t))
    scratch = noise - _lowpass(noise, 5)
    strokes = 0.55 + 0.45 * np.sin(2 * np.pi * 5.5 * t) ** 2  # back-and-forth strokes
    envelope = np.minimum(1, t / 0.1) * np.minimum(1, (t[-1] - t) / 0.3)
    return _stereo(0.12 * scratch * strokes * envelope)


def chime(notes: tuple[float, ...] = (880.0,), gap: float = 0.0, seconds: float = 2.2) -> np.ndarray:
    t = _t(seconds + gap * len(notes))
    out = np.zeros(len(t))
    for i, base in enumerate(notes):
        start = round(i * gap * RATE)
        local = t[: len(t) - start]
        bell = sum(
            amp * np.sin(2 * np.pi * base * ratio * local) * np.exp(-local * decay)
            for ratio, amp, decay in ((1, 1.0, 2.2), (2.01, 0.45, 3.5), (3.02, 0.25, 5), (4.2, 0.12, 7))
        )
        out[start:] += bell
    out *= np.minimum(1, t / 0.004)  # no click at the start
    return _stereo(0.22 * out)


def pad(seconds: float) -> np.ndarray:
    """A soft, slowly breathing A-major chord to sit under the whole video."""
    t = _t(seconds)
    chord = (110.0, 164.8, 220.0, 277.2, 329.6)
    mono = np.zeros(len(t))
    for i, freq in enumerate(chord):
        for detune in (-0.6, 0.6):
            mono += np.sin(2 * np.pi * (freq + detune) * t + i)
    breathing = 0.7 + 0.3 * np.sin(2 * np.pi * t / 9.0)
    return _stereo(0.035 * mono * breathing)


def write_sounds() -> dict[str, Path]:
    SOUNDS.mkdir(exist_ok=True)
    made = {
        "pop": pop(),
        "tick": tick(),
        "whoosh": whoosh(),
        "pencil": pencil(),
        "chime": chime((880.0,)),
        "reveal": chime((659.3, 880.0, 1318.5), gap=0.12),
        "outro": chime((440.0, 659.3, 880.0, 1108.7), gap=0.18, seconds=3.0),
        "pad": pad(DURATION),
    }
    paths = {}
    for name, samples in made.items():
        paths[name] = SOUNDS / f"{name}.wav"
        audio.write_wav(np.clip(samples, -1, 1), paths[name])
    return paths


# -- the project ------------------------------------------------------------------------------


def build() -> Project:
    p = Project(canvas=Canvas(width_px=1280, height_px=720, fps=30, background="#0f172a", duration=DURATION))

    def apply(edit: edits.Edit) -> None:
        nonlocal p
        p = edit.project

    axes_mob = adapter.build_mobject(AXES)

    def world(x: float, y: float) -> tuple[float, float]:
        point = axes_mob.c2p(x, y)
        return (point[0] + AXES_AT[0], point[1] + AXES_AT[1])

    unit_ratio = (world(0, 1)[1] - world(0, 0)[1]) / (world(1, 0)[0] - world(0, 0)[0])

    def layer(layer_id: str, spec: Spec, at=(0.0, 0.0), **fields) -> None:
        apply(edits.add_layer(p, spec, layer_id=layer_id))
        apply(edits.update_layer(p, layer_id, base={"position": at}, **fields))

    def clip(layer_id: str, kind: str, start: float, duration: float, **kwargs) -> None:
        apply(edits.add_clip(p, layer_id, kind, start, duration, **kwargs))

    def text(layer_id: str, words: str, at, size: float, colour: str = INK, **fields) -> None:
        layer(
            layer_id,
            Spec(type="Text", params={"text": words, "font_size": size}, style={"fill": colour}),
            at,
            **fields,
        )

    def tex(layer_id: str, latex: str, at, size: float = 40, colour: str = INK) -> None:
        layer(
            layer_id,
            Spec(type="MathTex", params={"text": latex, "font_size": size}, style={"fill": colour}),
            at,
        )

    def segment(layer_id: str, a, b, colour: str, width: float = 4, extend: float = 0.0) -> None:
        """A line from a to b (world units), extended by ``extend`` at both ends."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        ux, uy = dx / length, dy / length
        total = length + 2 * extend
        spec = Spec(
            type="Line",
            params={"start": (0.0, 0.0), "end": (ux * total, uy * total)},
            style={"stroke": colour, "stroke_width": width},
        )
        layer(layer_id, spec, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))

    def tangent_at(x: float, half: float = 1.7) -> tuple[tuple[float, float], tuple[float, float]]:
        slope = x / 2 * unit_ratio  # f'(x) = x / 2, in world units
        c = world(x, f(x))
        ux, uy = 1 / math.hypot(1, slope), slope / math.hypot(1, slope)
        return (c[0] - ux * half, c[1] - uy * half), (c[0] + ux * half, c[1] + uy * half)

    # ---- subtitles: a dark band and timed lines ----
    band = Spec(
        type="Rectangle",
        params={"width": 13.6, "height": 0.72},
        style={"fill": "#020617", "fill_opacity": 0.72, "stroke_width": 0},
    )
    layer("band", band, (0.0, -3.52))
    clip("band", "FadeIn", 0.3, 0.5)
    clip("band", "FadeOut", 88.4, 0.6)
    subtitles = [
        (0.8, 4.6, "Every day we ask: how fast is something changing?"),
        (4.8, 8.4, "Speed, growth, cooling... they are all rates of change."),
        (9.0, 13.0, "Here is a curve: f(x) = x² / 4."),
        (13.2, 17.6, "Its steepness keeps changing. How steep is it at the point P?"),
        (18.0, 22.4, "Take a second point Q, a bit further along the curve."),
        (22.6, 27.4, "The line through P and Q is a secant. Its slope is rise over run."),
        (27.6, 31.9, "Now slide Q towards P, and watch the slope..."),
        (32.1, 36.6, "As Q gets closer, the secant settles on a single line:"),
        (36.8, 41.8, "the tangent. It just touches the curve at P."),
        (42.2, 47.0, "Its slope is the derivative of f at that point, written f′(x)."),
        (47.2, 52.4, "h is the gap between P and Q. Shrinking it to zero gives the exact slope."),
        (52.6, 57.6, "For our curve, the algebra works out to f′(x) = x / 2."),
        (58.0, 63.0, "So at every point, the slope is half of x. Watch the tangent move:"),
        (63.2, 69.2, "flat at the bottom, then steeper and steeper as x grows."),
        (69.6, 75.4, "Plot all those slopes and you get a new curve: the derivative."),
        (76.6, 82.6, "In short: the derivative measures change at a single instant."),
        (82.8, 88.4, "Next time you look at a speedometer, you are reading a derivative!"),
    ]
    for i, (start, end, words) in enumerate(subtitles, start=1):
        text(f"sub{i}", words, (0.0, -3.52), 26)
        clip(f"sub{i}", "FadeIn", start, 0.3)
        clip(f"sub{i}", "FadeOut", end - 0.3, 0.3)

    # ---- 0-8 s: title ----
    text("title", "What is a derivative?", (0.0, 0.7), 60)
    clip("title", "Write", 0.6, 2.0)
    clip("title", "FadeOut", 7.6, 0.8, params={"shift": "UP"})
    text("tagline", "A visual explanation of change", (0.0, -0.35), 30, "#cbd5e1")
    clip("tagline", "FadeIn", 2.6, 0.8, params={"shift": "UP"})
    clip("tagline", "FadeOut", 7.6, 0.8, params={"shift": "UP"})

    def header(layer_id: str, words: str, start: float, end: float) -> None:
        text(layer_id, words, (0.0, 3.45), 30, MUTED)
        clip(layer_id, "FadeIn", start, 0.5, params={"shift": "DOWN"})
        clip(layer_id, "FadeOut", end, 0.5)

    header("h1", "1  ·  How steep is a curve?", 8.6, 41.5)
    header("h2", "2  ·  The derivative", 42.2, 75.6)
    header("h3", "In short", 76.4, 88.6)

    # ---- 9-18 s: the curve and the point P ----
    layer("axes", AXES, AXES_AT)
    clip("axes", "Create", 9.0, 1.4)
    clip("axes", "FadeOut", 76.0, 0.8)
    curve = Spec(
        type="Graph",
        params={"expression": "x**2/4", "x_range": [0.0, 4.5]},
        style={"stroke": BLUE, "stroke_width": 5},
    )
    apply(edits.add_child(p, "axes", curve, layer_id="f"))
    clip("f", "Create", 10.4, 1.8)
    tex("f_label", r"f(x) = \frac{x^2}{4}", (3.9, 2.4), 44, BLUE)
    clip("f_label", "Write", 11.6, 1.4)

    def point(layer_id: str, x: float, colour: str, radius: float = 0.11) -> None:
        spec = Spec(type="Point", params={"x": x, "y": f(x), "radius": radius}, style={"fill": colour})
        apply(edits.add_child(p, "axes", spec, layer_id=layer_id))

    point("P", P_X, PINK, 0.13)
    clip("P", "GrowFromCenter", 15.0, 0.5)
    clip("P", "FadeOut", 57.2, 0.5)
    tex("P_name", "P", (world(P_X, f(P_X))[0] - 0.05, world(P_X, f(P_X))[1] + 0.45), 36, PINK)
    clip("P_name", "FadeIn", 15.3, 0.4)
    clip("P_name", "FadeOut", 57.2, 0.5)

    # ---- 18-27 s: Q, the secant, rise over run ----
    q_steps = (4.0, 3.0, 2.3, 1.85)
    for i, q in enumerate(q_steps):
        point(f"Q{i}", q, GREEN)
    clip("Q0", "GrowFromCenter", 18.6, 0.5)
    pw = world(P_X, f(P_X))
    for i, q in enumerate(q_steps):
        segment(f"sec{i}", pw, world(q, f(q)), YELLOW, extend=0.9)
    clip("sec0", "Create", 20.2, 1.0)
    run_end = world(q_steps[0], f(P_X))
    segment("dx", pw, run_end, MUTED, 3)
    segment("dy", run_end, world(q_steps[0], f(q_steps[0])), MUTED, 3)
    clip("dx", "Create", 24.3, 0.6)
    clip("dy", "Create", 24.9, 0.6)
    clip("dx", "FadeOut", 27.4, 0.4)
    clip("dy", "FadeOut", 27.4, 0.4)
    tex("dx_label", r"\Delta x", (pw[0] + (run_end[0] - pw[0]) / 2, pw[1] - 0.26), 26, MUTED)
    tex("dy_label", r"\Delta y", (run_end[0] + 0.4, (run_end[1] + world(4.0, 4.0)[1]) / 2), 26, MUTED)
    clip("dx_label", "FadeIn", 24.5, 0.4)
    clip("dy_label", "FadeIn", 25.1, 0.4)
    clip("dx_label", "FadeOut", 27.4, 0.4)
    clip("dy_label", "FadeOut", 27.4, 0.4)
    tex("slope_def", r"\text{slope} = \frac{\Delta y}{\Delta x}", (3.9, 0.9), 40)
    clip("slope_def", "Write", 23.0, 1.4)
    clip("slope_def", "FadeOut", 41.2, 0.6)

    # ---- 27-42 s: Q slides towards P; the secant becomes the tangent ----
    values = [(q + P_X) / 4 for q in q_steps] + [P_X / 2]  # the secant's slope (q + p) / 4, then f'(p)
    for i, value in enumerate(values):
        tex(f"val{i}", rf"\text{{slope}} \approx {value:.2f}", (3.9, -0.5), 40, YELLOW if i < 4 else ORANGE)
    clip("val0", "FadeIn", 25.6, 0.5)
    step_starts = (28.2, 30.0, 31.8)
    for i, start in enumerate(step_starts):
        clip(f"Q{i}", "Transform", start, 1.2, to_layer=f"Q{i + 1}")
        clip(f"sec{i}", "Transform", start, 1.2, to_layer=f"sec{i + 1}")
        clip(f"val{i}", "Transform", start, 1.2, to_layer=f"val{i + 1}")
    a, b = tangent_at(P_X)
    segment("tangent", a, b, ORANGE, 6)
    clip("sec3", "Transform", 34.6, 1.6, to_layer="tangent")
    clip("val3", "Transform", 34.6, 1.6, to_layer="val4")
    clip("Q3", "FadeOut", 34.6, 0.8)
    clip("tangent", "Indicate", 38.0, 1.2, params={"color": ORANGE})
    clip("val4", "FadeOut", 41.2, 0.6)
    text("tangent_name", "tangent", (b[0] + 0.25, b[1] - 0.5), 28, ORANGE)
    clip("tangent_name", "FadeIn", 37.0, 0.5)
    clip("tangent_name", "FadeOut", 57.2, 0.5)
    clip("tangent", "FadeOut", 57.2, 0.5)

    # ---- 42-58 s: the definition, then f'(x) = x / 2 ----
    tex("limit", r"f'(x) = \lim_{h \to 0} \frac{f(x+h) - f(x)}{h}", (3.95, 0.4), 36)
    clip("limit", "Write", 43.0, 2.4)
    clip("limit", "Circumscribe", 48.6, 1.6, params={"color": YELLOW})
    clip("limit", "FadeOut", 52.6, 0.6)
    tex("derivative", r"f'(x) = \frac{x}{2}", (3.9, 2.4), 44, ORANGE)
    clip("f_label", "TransformMatchingTex", 53.4, 1.6, to_layer="derivative")
    clip("derivative", "Indicate", 56.0, 1.0, params={"color": ORANGE})
    clip("derivative", "FadeOut", 76.0, 0.8)

    # ---- 58-76 s: the tangent rides along the curve with a comet tail ----
    run = (59.0, 10.0)
    dot = Spec(type="Dot", params={"radius": 0.12}, style={"fill": PINK})
    layer("rider", dot, world(0.0, 0.0), lifetime={"in": 58.6})
    clip("rider", "MoveAlongPath", *run, params={"path": "f"}, ease=LINEAR)
    clip("rider", "FadeOut", 69.4, 0.6)
    rider_tangent = Spec(
        type="Line",
        params={"start": (0.0, 0.0), "end": (1.8, 0.0)},
        style={"stroke": ORANGE, "stroke_width": 6},
    )
    layer("rider_tangent", rider_tangent, world(0.0, 0.0), lifetime={"in": 58.6})
    clip("rider_tangent", "MoveAlongPath", *run, params={"path": "f", "rotate": "along"}, ease=LINEAR)
    clip("rider_tangent", "FadeOut", 69.4, 0.6)
    tail = Spec(
        type="TracedPath",
        params={"target": "rider", "dissipate": 1.2},
        style={"stroke": YELLOW, "stroke_width": 6},
    )
    layer("tail", tail, lifetime={"in": 58.6, "out": 70.0})
    slope_graph = Spec(
        type="Graph",
        params={"expression": "x/2", "x_range": [0.0, 4.5]},
        style={"stroke": ORANGE, "stroke_width": 5},
    )
    apply(edits.add_child(p, "axes", slope_graph, layer_id="g"))
    clip("g", "Create", 70.2, 2.4)
    text("g_name", "slopes: f′(x) = x / 2", world(3.6, 0.5), 26, ORANGE)
    clip("g_name", "FadeIn", 72.4, 0.6)
    clip("g_name", "FadeOut", 76.0, 0.8)

    # ---- 76-95 s: summary and outro ----
    lines = [
        ("sum1", "The derivative is the slope of the tangent.", 1.4, 77.2),
        ("sum2", "It tells you how fast f changes at each point.", 0.5, 79.4),
    ]
    for layer_id, words, y, start in lines:
        text(layer_id, words, (0.0, y), 36)
        clip(layer_id, "FadeIn", start, 0.8, params={"shift": "UP"})
        clip(layer_id, "FadeOut", 88.6, 0.8)
    tex("sum_limit", r"f'(x) = \lim_{h \to 0} \frac{f(x+h) - f(x)}{h}", (0.0, -1.1), 48, YELLOW)
    clip("sum_limit", "Write", 81.6, 2.0)
    clip("sum_limit", "FadeOut", 88.6, 0.8)
    text("credit", "Made with Manim Studio", (0.0, 0.0), 34, MUTED)
    clip("credit", "FadeIn", 89.8, 1.0)
    clip("credit", "FadeOut", DURATION - 1.6, 1.0)
    return p


def add_sounds(p: Project, sounds: dict[str, Path]) -> Project:
    cues = [
        ("pad", 0.0, DURATION, -4.0, 2.5, 3.0),
        ("chime", 0.6, None, -3.0, 0, 0),  # title
        ("whoosh", 2.5, None, -9.0, 0, 0),  # tagline
        ("whoosh", 7.5, None, -6.0, 0, 0),  # title out
        ("pencil", 9.0, None, -4.0, 0, 0),  # axes
        ("pencil", 10.4, None, -2.0, 0, 0),  # the curve
        ("pencil", 11.6, None, -6.0, 0, 0),  # f(x) = ...
        ("pop", 15.0, None, -2.0, 0, 0),  # P
        ("pop", 18.6, None, -2.0, 0, 0),  # Q
        ("pencil", 20.2, None, -3.0, 0, 0),  # the secant
        ("pencil", 23.0, None, -6.0, 0, 0),  # slope = dy / dx
        ("tick", 24.3, None, -4.0, 0, 0),  # dx
        ("tick", 24.9, None, -4.0, 0, 0),  # dy
        ("tick", 28.2, None, 0.0, 0, 0),  # Q slides...
        ("tick", 30.0, None, 0.0, 0, 0),
        ("tick", 31.8, None, 0.0, 0, 0),
        ("whoosh", 34.6, None, -6.0, 0, 0),  # into the tangent
        ("reveal", 36.4, None, -2.0, 0, 0),  # "the tangent"
        ("whoosh", 41.8, None, -8.0, 0, 0),  # section 2
        ("pencil", 43.0, None, -3.0, 0, 0),  # the limit
        ("chime", 48.6, None, -8.0, 0, 0),  # circled
        ("whoosh", 53.4, None, -5.0, 0, 0),  # f(x) -> f'(x)
        ("reveal", 55.0, None, -4.0, 0, 0),
        ("whoosh", 59.0, None, -9.0, 0, 0),  # the ride
        ("pencil", 70.2, None, -4.0, 0, 0),  # the slope graph
        ("pop", 72.4, None, -6.0, 0, 0),
        ("whoosh", 76.0, None, -6.0, 0, 0),  # summary
        ("pop", 77.2, None, -6.0, 0, 0),
        ("pop", 79.4, None, -6.0, 0, 0),
        ("pencil", 81.6, None, -4.0, 0, 0),
        ("outro", 89.8, None, -2.0, 0, 0),
    ]
    for name, start, duration, gain, fade_in, fade_out in cues:
        length = audio.probe(str(sounds[name]))
        edit = edits.add_audio(p, str(sounds[name]), start, duration or length, name=name)
        p = edits.update_audio(
            edit.project,
            edit.project.audio[-1].id,
            gain=gain + MASTER_GAIN,
            fade_in=fade_in,
            fade_out=fade_out,
        ).project
    return p


if __name__ == "__main__":
    adapter.configure(HERE.parent / ".cache" / "manim")  # the axes' numbers are LaTeX
    project = add_sounds(build(), write_sounds())
    OUT.write_text(project.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    print(f"wrote {OUT} ({len(project.layers)} layers, {len(project.audio)} sounds, {DURATION:g} s)")
