"""B71 - frozen objects (P10.2, ADR 0052): their size and build time against their sources.

For a Text, a MathTex, the Matrix template and the right-triangle template (Python objects):
the pieces and points frozen, the spec's JSON before and after, a build with Manim's disk cache
warm (the source: LaTeX/text SVGs parsed again; a Python object built twice, its first-use
determinism check) against building the shape from its data, an edit of another layer in the same
project (the frozen spec is compared, not rebuilt) and a save + load of the project. Minimum of 20.

Run: ``python benchmarks/bench_shapes.py`` (from the repository root, ``PYTHONPATH=src``).
"""

from __future__ import annotations

import time
from pathlib import Path

from manim_studio.core.code import python_object, python_templates
from manim_studio.core.editing import edits
from manim_studio.core.engine import adapter
from manim_studio.core.model.schema import Layer, Project, Spec

SOURCES = {
    "Text 'Hi ok'": Spec(type="Text", params={"text": "Hi ok"}),
    "MathTex e^{i pi}+1=0": Spec(type="MathTex", params={"text": r"e^{i\pi}+1=0"}),
    "Matrix 3x3 (Python)": Spec(type="Python", params={"code": python_templates.MATRIX}),
    "Right triangle (Python)": Spec(type="Python", params={"code": python_object.STARTER}),
}


def best(fn, n: int = 20) -> float:
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return min(times) * 1000


def measure(name: str, spec: Spec) -> str:
    adapter.build_mobject(spec)  # warm Manim's disk cache (LaTeX, text SVGs)
    data = adapter.freeze_data(spec)
    shape = Spec(type="Shape", params=data)
    points = sum(len(p["points"]) for p in data["shapes"])
    project = Project(layers=[Layer(id="a", spec=shape), Layer(id="b", spec=Spec(type="Circle"))])

    def source_build() -> None:
        adapter._build_cached.cache_clear()
        adapter.forget_python_builds()
        adapter.build_mobject(spec)

    def shape_build() -> None:
        adapter._shape_cached.cache_clear()
        adapter.build_mobject(shape)

    return (
        f"{name}: {len(data['shapes'])} pieces, {points} points; spec JSON "
        f"{len(spec.model_dump_json())} B -> {len(shape.model_dump_json())} B; build (disk cache warm) "
        f"{best(source_build):.1f} ms -> {best(shape_build):.2f} ms; edit of another layer "
        f"{best(lambda: edits.update_layer(project, 'b', name='x')):.2f} ms; save+load "
        f"{best(lambda: Project.model_validate_json(project.model_dump_json())):.1f} ms"
    )


def main() -> None:
    adapter.configure(Path(".cache/manim").resolve())
    python_object.trust_everything()
    for name, spec in SOURCES.items():
        print(measure(name, spec))


if __name__ == "__main__":
    main()
