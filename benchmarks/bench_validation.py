"""B53 — validation and edit cost by project size: what a structural edit costs at 20 to 2000 layers.

B51 found that duplicating one object costs what any structural edit costs and grows faster than
linearly with the layer count. This times the pieces for projects of 20, 200, 1000 and 2000 layers
(shapes with clips, text, axes with graphs, a MathTex with parts, morphs, motion along a path, a
trace and a connector, so every project validator has work to do):

- ``Project.model_validate(project.model_dump())``: the document validators.
- ``edits.add_layer`` (a structural edit: validate + classify), ``edits.update_layer`` (a transform
  change on one layer), ``edits.classify(old, new)`` and ``frame_cache.changed_spans(old, new)`` alone.

Run: ``python benchmarks/bench_validation.py`` (``--profile`` prints the cProfile top for 2000 layers).
"""

from __future__ import annotations

import cProfile
import pstats
import sys
import time

from manim_studio.core import edits, frame_cache
from manim_studio.core.schema import Canvas, Clip, Keyframe, Layer, PartKey, Project, Spec

SIZES = (20, 200, 1000, 2000)


def timed(work, repeat: int = 9) -> float:
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        work()
        samples.append((time.perf_counter() - start) * 1000)
    return min(samples)  # best of N: a loaded machine only adds time


def project_of(n: int) -> Project:
    """About ``n`` layers: mostly clipped shapes and text, a tenth of them in the special groups."""
    layers: list[Layer] = []

    def shape(i: int) -> Layer:
        clips = [Clip(id="in", kind="FadeIn", start=0.1 * (i % 20), duration=0.5)]
        if i % 2:
            clips.append(Clip(id="pulse", kind="Indicate", start=3.0, duration=0.5))
        tracks = {"position": [Keyframe(t=0.0, value=(0.0, 0.0)), Keyframe(t=2.0, value=(float(i % 7), 1.0))]}
        spec = Spec(type="Circle", params={"radius": 0.2}, style={"fill": "#3b82f6"})
        return Layer(id=f"circle-{i + 1}", name=f"Dot {i}", spec=spec, clips=clips, tracks=tracks)

    groups = max(1, n // 100)
    for g in range(groups):  # axes with two graphs, a MathTex with two parts
        layers.append(Layer(id=f"axes-{g}", spec=Spec(type="Axes")))
        for k in range(2):
            spec = Spec(type="Graph", params={"expression": f"sin(x) + {k}"})
            layers.append(Layer(id=f"graph-{g}-{k}", parent_id=f"axes-{g}", spec=spec))
        text = "a + b = c"
        layers.append(Layer(id=f"tex-{g}", spec=Spec(type="MathTex", params={"text": text})))
        for k, tex in enumerate(("a", "b")):
            layers.append(Layer(id=f"part-{g}-{k}", parent_id=f"tex-{g}", part=PartKey(tex=tex)))
    i = 0
    while len(layers) < n - 6 * groups:  # the tail below adds six layers per group
        layers.append(shape(i))
        i += 1
    for g in range(groups):  # a morph pair and a mover along a path, a text
        a, b, path = f"morph-a-{g}", f"morph-b-{g}", f"path-{g}"
        morph = Clip(id="turn", kind="Transform", start=1.0, duration=1.0, to_layer=b)
        layers.append(Layer(id=a, spec=Spec(type="Square"), clips=[morph]))
        layers.append(Layer(id=b, spec=Spec(type="Circle")))
        layers.append(Layer(id=path, spec=Spec(type="Circle", params={"radius": 2.0})))
        move = Clip(id="go", kind="MoveAlongPath", start=0.0, duration=2.0, params={"path": path})
        layers.append(Layer(id=f"mover-{g}", spec=Spec(type="Dot"), clips=[move]))
    for g in range(groups):  # a trace of each mover, a connector between two shapes
        layers.append(Layer(id=f"trace-{g}", spec=Spec(type="TracedPath", params={"target": f"mover-{g}"})))
        link = {"source": f"circle-{g + 1}", "target": f"circle-{g + 2}"}
        layers.append(Layer(id=f"link-{g}", spec=Spec(type="Connector", params=link)))
    return Project(canvas=Canvas(duration=10.0), layers=layers)


def measure(project: Project) -> dict[str, float]:
    other = edits.update_layer(project, "circle-1", base={"position": (1.0, 0.5)}).project
    return {
        "validate": timed(lambda: Project.model_validate(project.model_dump())),
        "add_layer": timed(lambda: edits.add_layer(project, Spec(type="Dot"))),
        "update_layer": timed(lambda: edits.update_layer(project, "circle-1", base={"position": (2.0, 1.0)})),
        "classify": timed(lambda: edits.classify(project, other)),
        "changed_spans": timed(lambda: frame_cache.changed_spans(project, other)),
    }


def main() -> None:
    names = ("validate", "add_layer", "update_layer", "classify", "changed_spans")
    print("layers  " + "  ".join(f"{name:>13}" for name in names) + "   (ms, best of 9)")
    for n in SIZES:
        project = project_of(n)
        if "--profile" in sys.argv and n == SIZES[-1]:
            profiler = cProfile.Profile()
            profiler.runcall(edits.add_layer, project, Spec(type="Dot"))
            pstats.Stats(profiler).sort_stats("cumulative").print_stats(18)
        times = measure(project)
        print(f"{len(project.layers):6d}  " + "  ".join(f"{times[name]:13.1f}" for name in names))


if __name__ == "__main__":
    main()
