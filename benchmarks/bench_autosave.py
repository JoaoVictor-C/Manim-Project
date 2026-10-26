"""B51 — autosave and the clipboard: what a recovery copy and a paste cost on the GUI thread.

1. A recovery copy (``core.recovery.write``: the project's JSON, a temporary file, ``os.replace``,
   then the sidecar the same way) for projects of 20 to 2000 layers, each with two clips and two
   keyframed properties; the JSON alone for comparison, and the file size.
2. Duplicating one object (``core.clipboard.duplicate_layers``: copy, remap, validate the new
   project) in the same projects, and copying + pasting a figure of axes with 40 graphs.

Run: ``python benchmarks/bench_autosave.py``.
"""

from __future__ import annotations

import statistics
import tempfile
import time
from pathlib import Path

from manim_studio.core.editing import clipboard, edits
from manim_studio.core.model import recovery
from manim_studio.core.model.schema import Canvas, Clip, Keyframe, Layer, Project, Spec


def timed(work, repeat: int = 7) -> float:
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        work()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def project_of(n: int) -> Project:
    layers = []
    for i in range(n):
        clips = [
            Clip(id="in", kind="FadeIn", start=0.1 * (i % 20), duration=0.5),
            Clip(id="pulse", kind="Indicate", start=3.0, duration=0.5),
        ]
        tracks = {
            "position": [Keyframe(t=0.0, value=(0.0, 0.0)), Keyframe(t=2.0, value=(float(i % 7), 1.0))],
            "opacity": [Keyframe(t=0.0, value=0.0), Keyframe(t=1.0, value=1.0)],
        }
        spec = Spec(type="Circle", params={"radius": 0.2}, style={"fill": "#3b82f6", "fill_opacity": 0.5})
        layers.append(Layer(id=f"circle-{i + 1}", name=f"Dot {i}", spec=spec, clips=clips, tracks=tracks))
    return Project(canvas=Canvas(duration=10.0), layers=layers)


def figure(graphs: int) -> Project:
    layers = [Layer(id="axes", name="Axes", spec=Spec(type="Axes"))]
    for i in range(graphs):
        spec = Spec(type="Graph", params={"expression": f"sin(x) + {i / 10}"})
        layers.append(Layer(id=f"g{i}", parent_id="axes", spec=spec))
    return Project(canvas=Canvas(), layers=layers)


def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="bench-autosave-"))
    print("layers  json ms  copy ms  size KB  duplicate ms  add_layer ms")
    for n in (20, 200, 1000, 2000):
        project = project_of(n)
        dump = timed(lambda p=project: p.model_dump_json(by_alias=True))
        write = timed(lambda p=project: recovery.write(folder, "bench-1", p, None, 1, time.time()))
        size = (folder / "bench-1.json").stat().st_size / 1024
        duplicate = timed(lambda p=project: clipboard.duplicate_layers(p, ["circle-1"]), repeat=5)
        add = timed(lambda p=project: edits.add_layer(p, Spec(type="Dot")), repeat=5)  # any edit, for scale
        print(f"{n:6d}  {dump:7.1f}  {write:7.1f}  {size:7.0f}  {duplicate:12.1f}  {add:12.1f}")
    axes = figure(40)
    data = clipboard.copy_layers(axes, ["axes"])
    text = clipboard.to_json(data)
    paste = timed(lambda: clipboard.paste_layers(axes, clipboard.from_json(text).payload), repeat=5)
    print(f"axes with 40 graphs: clipboard text {len(text) / 1024:.0f} KB, read + paste {paste:.1f} ms")
    recovery.remove(folder, "bench-1")


if __name__ == "__main__":
    main()
