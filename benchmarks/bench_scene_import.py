"""B72 - importing a Manim scene (P10.3, ADR 0053): how long a 27-second scene takes.

The scene: a Write, a LaggedStart of five Creates, ten moves and Indicates, an arrange and scale of
the group, five Transforms, a FadeIn, five Rotates, FadeOuts and an Unwrite (21 steps, 12 layers).
Measured: the whole ``manim-studio import`` command (a new Python process: Manim's import, the
recording process, the import, the project written); in one process, the recording (Manim plays
the scene once, nothing drawn) and the import (pure); the recording's JSON size. Minimum of 3.

Run: ``python benchmarks/bench_scene_import.py`` (from the repository root, ``PYTHONPATH=src``).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

SCENE = textwrap.dedent(
    """
    from manim import *

    class Long(Scene):
        def construct(self):
            title = Text("Thirty seconds").to_edge(UP)
            self.play(Write(title), run_time=2)
            shapes = VGroup(*[Circle(radius=0.4, color=c) for c in (RED, GREEN, BLUE, YELLOW, PURPLE)])
            shapes.arrange(RIGHT)
            self.play(LaggedStart(*[Create(s) for s in shapes], lag_ratio=0.3), run_time=2)
            for i, s in enumerate(shapes):
                self.play(s.animate.shift(DOWN * (i % 2 + 0.5)), run_time=1)
                self.play(Indicate(s), run_time=0.5)
            self.play(shapes.animate.arrange(DOWN).scale(0.7), run_time=2)
            squares = VGroup(*[Square(side_length=0.6).move_to(s) for s in shapes])
            self.play(*[Transform(s, q) for s, q in zip(shapes, squares)], run_time=2)
            label = Text("done", font_size=36).next_to(shapes, RIGHT)
            self.play(FadeIn(label, shift=LEFT), run_time=1)
            self.wait(3)
            self.play(*[Rotate(s, PI / 2) for s in shapes], run_time=2)
            self.play(FadeOut(shapes), FadeOut(label), run_time=1.5)
            self.play(Unwrite(title), run_time=1.5)
            self.wait(2.5)
    """
)


def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="bench-scene-import-"))
    path = folder / "long.py"
    path.write_text(SCENE, encoding="utf-8")
    cache = Path(".cache/manim").resolve()
    commands = []
    for _ in range(3):
        t0 = time.perf_counter()
        command = [sys.executable, "-m", "manim_studio", "import", str(path), "-o", str(folder / "long.json")]
        subprocess.run([*command, "--cache-dir", str(cache)], check=True, capture_output=True)
        commands.append(time.perf_counter() - t0)

    from manim_studio.core.engine import adapter

    adapter.configure(cache)
    from manim_studio.core.exchange.scene_import import import_scene
    from manim_studio.processes import scene_recorder

    records, imports = [], []
    for _ in range(3):
        t0 = time.perf_counter()
        recording = scene_recorder.record_file(path)
        records.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        result = import_scene(recording)
        imports.append(time.perf_counter() - t0)
    size = len(json.dumps(recording)) / 1000
    layers = len(result.project.layers)
    print(f"scene {recording['duration']:g} s, {len(recording['steps'])} steps, {layers} layers")
    print(f"import command {min(commands):.2f} s; recording {min(records) * 1000:.0f} ms; ", end="")
    print(f"import {min(imports) * 1000:.0f} ms; recording JSON {size:.0f} KB")


if __name__ == "__main__":
    main()
