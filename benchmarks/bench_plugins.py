"""B45 — what plugins cost: discovery, loading a plugin file, building, the determinism check.

Run: ``python benchmarks/bench_plugins.py``.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import tempfile
import time
from pathlib import Path

import manim as m

PLUGIN = '''
import manim as m

def build(params):
    length = params.get("length", 2.0)
    return m.VGroup(m.Line(m.ORIGIN, m.DOWN * length), m.Dot(m.DOWN * length, radius=0.2))
'''


def main() -> None:
    start = time.perf_counter()
    found = list(importlib.metadata.entry_points(group="manim_studio.plugins"))
    scan = (time.perf_counter() - start) * 1000
    folder = Path(tempfile.mkdtemp())
    path = folder / "pendulum.py"
    path.write_text(PLUGIN, encoding="utf-8")
    start = time.perf_counter()
    spec = importlib.util.spec_from_file_location("bench_plugin", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    load = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    first = module.build({"length": 3.0})
    build = (time.perf_counter() - start) * 1000
    start = time.perf_counter()
    second = module.build({"length": 3.0})
    same = all(
        (a.points == b.points).all()
        for a, b in zip(first.family_members_with_points(), second.family_members_with_points(), strict=True)
    )
    check = (time.perf_counter() - start) * 1000
    print(f"entry-point scan {scan:.1f} ms ({len(found)} found); plugin file {load:.1f} ms "
          f"(Manim already imported); build {build:.2f} ms; determinism check +{check:.2f} ms (same={same}); "
          f"{type(first).__name__}, vector={isinstance(first, m.VMobject)}")


if __name__ == "__main__":
    main()
