"""B73 - morph quality: what the in-between frames of a morph look like, measured.

A gallery of morph pairs (shapes, text, TeX, a group, glyphs with holes, thin lines) evaluated
through the real evaluator at several alphas, for each matching mode. Writes contact sheets
(PNG, one row per pair: alpha 0, .25, .5, .75, 1, then the target as drawn after the morph) to
``.cache/morph/`` and prints per-pair measures:

* ``travel``: the mean distance a drawn point travels over the morph relative to the object's
  centre, in units of the ends' diagonal (twisting shows as needless travel);
* ``max``: the largest such distance (pieces flying across the object to a far partner);
* ``cross``: self-crossings of the outlines at alpha .25/.5/.75 beyond those of the ends;
* ``dip``: the smallest drawn area at a mid alpha over the area interpolated between the ends
  (a shape collapsing shows as a dip toward 0; 1 means no dip);
* ``pop``: the largest pixel difference between the morph at alpha 1 and the target drawn
  after the morph (a jump at the end), and the same at alpha 0 against the source;
* ``mid L``: the OKLab lightness of the first piece's fill at alpha .5 against the mean of the
  ends (colour muddiness shows as a negative value);
* ``begin`` / ``frame``: the cost of building the morph and of one frame (ms).

Run: ``python benchmarks/bench_morph_quality.py [--modes classic smart] [--only NAME]``.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".cache" / "morph"
ALPHAS = (0.0, 0.25, 0.5, 0.75, 1.0)
SAMPLES = 20
START, LENGTH = 0.5, 1.0  # the morph runs from 0.5 s to 1.5 s; the source shows before


@dataclass
class Pair:
    name: str
    source: dict
    target: dict
    kind: str = "Transform"
    source_at: tuple[float, float] = (-2.0, 0.0)
    target_at: tuple[float, float] = (2.0, 0.0)
    params: dict = field(default_factory=dict)


def spec(type_name: str, style: dict | None = None, **params) -> dict:
    return {"type": type_name, "params": params, "style": style or {}}


BLUE = {"fill": "#3b82f6", "fill_opacity": 0.8, "stroke": "#93c5fd", "stroke_width": 4}
RED = {"fill": "#ef4444", "fill_opacity": 0.8, "stroke": "#fca5a5", "stroke_width": 4}
GREEN = {"fill": "#22c55e", "fill_opacity": 0.8, "stroke": "#86efac", "stroke_width": 4}
YELLOW = {"fill": "#eab308", "fill_opacity": 0.8, "stroke": "#fde047", "stroke_width": 4}
OUTLINE = {"fill_opacity": 0.0, "stroke": "#f97316", "stroke_width": 8}
WHITE = {"fill": "#ffffff", "fill_opacity": 1.0}

PAIRS: list[Pair] = [
    Pair("circle-square", spec("Circle", BLUE, radius=1.2), spec("Square", RED, side_length=2.2)),
    Pair("square-triangle", spec("Square", BLUE, side_length=2.2), spec("Triangle", GREEN)),
    Pair("triangle-star", spec("Triangle", GREEN), spec("Star", YELLOW, n=5, outer_radius=1.4)),
    Pair("rectangle-circle", spec("Rectangle", RED, width=3.0, height=1.5), spec("Circle", BLUE, radius=1.2)),
    Pair("star7-square", spec("Star", YELLOW, n=7, outer_radius=1.4), spec("Square", BLUE, side_length=2.0)),
    Pair(
        "square-square90",
        spec("Square", BLUE, side_length=2.0),
        spec("Square", RED, side_length=2.0),
        target_at=(2.0, 0.0),
    ),
    Pair("line-arrow", spec("Line", OUTLINE, start=(-1, -1), end=(1, 1)), spec("Arrow", OUTLINE)),
    Pair("filled-outline", spec("Circle", BLUE, radius=1.2), spec("Square", OUTLINE, side_length=2.0)),
    Pair("Hello-World", spec("Text", WHITE, text="Hello"), spec("Text", WHITE, text="World")),
    Pair("cat-elephant", spec("Text", WHITE, text="cat"), spec("Text", WHITE, text="elephant")),
    Pair("text-circle", spec("Text", WHITE, text="Hi"), spec("Circle", BLUE, radius=1.0)),
    Pair("two-lines", spec("Text", WHITE, text="one\ntwo"), spec("Text", WHITE, text="three\nfour")),
    Pair(
        "oe-glyphs",
        spec("Text", WHITE, text="oe", font_size=96),
        spec("Text", WHITE, text="eo", font_size=96),
    ),
    Pair("o-square", spec("Text", WHITE, text="o", font_size=144), spec("Square", RED, side_length=1.5)),
    Pair(
        "triangle-group-square",
        spec("RightTriangle", GREEN, angle=40.0, side_length=2.5),
        spec("Square", BLUE, side_length=2.0),
    ),
    Pair(
        "thin-lines",
        spec("Line", {"stroke": "#ffffff", "stroke_width": 1}, start=(-1, 0), end=(1, 0)),
        spec("Line", {"stroke": "#ffffff", "stroke_width": 1}, start=(0, -1), end=(0, 1)),
    ),
    Pair("tex-transform", spec("MathTex", WHITE, text="a^2 + b^2 = c^2"), spec("MathTex", WHITE, text="c^2")),
    Pair(
        "tex-matching",
        spec("MathTex", WHITE, text="a^2 + b^2 = c^2"),
        spec("MathTex", WHITE, text="c^2"),
        kind="TransformMatchingTex",
    ),
    Pair(
        "tex-matching-swap",
        spec("MathTex", WHITE, text="a^2 + b^2 = c^2"),
        spec("MathTex", WHITE, text="c^2 = a^2 + b^2"),
        kind="TransformMatchingTex",
        source_at=(0.0, 1.5),
        target_at=(0.0, -1.5),
    ),
]
# The rotated square: the same square turned by 90 degrees (its points start at another corner).
PAIRS[5].params = {"rotation": 90.0}


def project_for(pair: Pair, mode: str):
    from manim_studio.core.model.schema import (
        SMART_MORPHS,
        Canvas,
        Clip,
        Easing,
        Layer,
        Project,
        Spec,
        Transform2D,
    )

    params = {} if mode == "classic" or pair.kind not in SMART_MORPHS else {"match": mode}
    clip = Clip(
        id="m",
        kind=pair.kind,
        start=START,
        duration=LENGTH,
        to_layer="b",
        ease=Easing(name="linear"),
        params=params,
    )
    source = Layer(id="a", spec=Spec(**pair.source), base=Transform2D(position=pair.source_at), clips=[clip])
    target = Layer(
        id="b",
        spec=Spec(**pair.target),
        base=Transform2D(position=pair.target_at, rotation=pair.params.get("rotation", 0.0)),
    )
    canvas = Canvas(width_px=960, height_px=540, fps=30, duration=START + LENGTH + 0.5, background="#101418")
    return Project(canvas=canvas, layers=[source, target])


def morph_mobject(evaluator, project, alpha: float):
    """The morph's drawing at ``alpha`` (alpha 1 included, which the timeline never shows)."""
    layer = project.layers[0]
    return evaluator._morph_at(layer, 0, layer.clips[0], alpha)


def leaves(mob) -> list:
    return [x for x in mob.family_members_with_points()]


def snapshot(mob) -> list[np.ndarray]:
    return [leaf.points[:, :2].copy() for leaf in leaves(mob)]


def outline_polylines(leaf, per_curve: int = 6) -> list[np.ndarray]:
    """Each closed or open subpath of ``leaf`` sampled as a polyline."""
    from manim_studio.core.engine import morph

    return [morph.sample_subpath(sub[:, :2], per_curve) for sub in morph.subpaths(leaf.points)]


def crossings(mob) -> int:
    from manim_studio.core.engine import morph

    return sum(morph.self_crossings(poly) for leaf in leaves(mob) for poly in outline_polylines(leaf))


def area(mob) -> float:
    from manim_studio.core.engine import morph

    total = 0.0
    for leaf in leaves(mob):
        if leaf.get_fill_opacity() <= 0:
            continue
        total += abs(sum(morph.signed_area(p) for p in outline_polylines(leaf)))
    return total


def first_fill(mob) -> np.ndarray | None:
    for leaf in leaves(mob):
        rgbas = getattr(leaf, "fill_rgbas", None)
        if rgbas is not None and len(rgbas) and rgbas[0, 3] > 0:
            return rgbas[0, :3].copy()
    return None


def lightness(rgb: np.ndarray) -> float:
    from manim_studio.core.engine import morph

    return float(morph.srgb_to_oklab(np.asarray(rgb, dtype=float)[None, :])[0, 0])


def measure(pair: Pair, mode: str) -> tuple[dict, list[np.ndarray]]:
    from manim_studio.core.engine.evaluator import Evaluator
    from manim_studio.render.cairo_export import make_camera, render_frame

    project = project_for(pair, mode)
    evaluator = Evaluator(project)
    camera = make_camera(project.canvas)
    t0 = time.perf_counter()
    morph_mobject(evaluator, project, 0.0)
    begin = (time.perf_counter() - t0) * 1000

    tiles = []
    for alpha in ALPHAS:
        tiles.append(render_frame(camera, [morph_mobject(evaluator, project, alpha)]))
    after = render_frame(camera, evaluator.frame(START + LENGTH + 0.25))
    before = render_frame(camera, evaluator.frame(START * 0.5))
    tiles.append(after)

    # Geometry along the morph.
    samples = []
    t0 = time.perf_counter()
    for i in range(SAMPLES + 1):  # just inside the ends: smart morphs draw the exact ends at 0 and 1
        alpha = min(max(i / SAMPLES, 1e-9), 1 - 1e-9)
        samples.append(snapshot(morph_mobject(evaluator, project, alpha)))
    frame_ms = (time.perf_counter() - t0) * 1000 / (SAMPLES + 1)
    # Deformation: each point's travel relative to the object's own centre (the move itself is
    # not a defect), in units of the ends' mean diagonal.
    start, end = np.concatenate(samples[0]), np.concatenate(samples[-1])
    size = np.mean([float(np.linalg.norm(p.max(axis=0) - p.min(axis=0))) for p in (start, end)]) or 1.0
    shift = (end.min(axis=0) + end.max(axis=0)) / 2 - (start.min(axis=0) + start.max(axis=0)) / 2
    deform = np.linalg.norm(end - start - shift, axis=1)
    travel = float(np.mean(deform))
    step = float(np.max(deform))
    ends_cross = max(crossings(morph_mobject(evaluator, project, a)) for a in (0.0, 1.0))
    mid_cross = sum(
        max(0, crossings(morph_mobject(evaluator, project, a)) - ends_cross) for a in (0.25, 0.5, 0.75)
    )
    a0, a1 = area(morph_mobject(evaluator, project, 0.0)), area(morph_mobject(evaluator, project, 1.0))
    dip = 1.0
    if max(a0, a1) > 1e-3:
        for alpha in (0.25, 0.5, 0.75):
            expected = a0 + (a1 - a0) * alpha
            dip = min(dip, area(morph_mobject(evaluator, project, alpha)) / expected)
    c0, c1 = (
        first_fill(morph_mobject(evaluator, project, 0.0)),
        first_fill(morph_mobject(evaluator, project, 1.0)),
    )
    cm = first_fill(morph_mobject(evaluator, project, 0.5))
    mid_l = 0.0
    if c0 is not None and c1 is not None and cm is not None:
        mid_l = lightness(cm) - (lightness(c0) + lightness(c1)) / 2
    pop_end = int(np.abs(tiles[4].astype(int) - after.astype(int)).max())
    pop_start = int(np.abs(tiles[0].astype(int) - before.astype(int)).max())
    row = {
        "pair": pair.name,
        "mode": mode,
        "travel": travel / size,
        "step": step / size,
        "cross": mid_cross,
        "dip": dip,
        "pop": (pop_start, pop_end),
        "mid L": mid_l,
        "begin": begin,
        "frame": frame_ms,
    }
    return row, tiles


CELL = 200  # px: each tile is cropped around its drawing and scaled to this square


def _crops(tiles: list[np.ndarray]) -> list[np.ndarray]:
    """Each tile cut to one window size (the largest drawing of the row) around its drawing."""
    background = tiles[0][0, 0, :3].astype(int)
    boxes = []
    for tile in tiles:
        ink = np.any(np.abs(tile[:, :, :3].astype(int) - background) > 8, axis=2)
        ys, xs = np.nonzero(ink)
        boxes.append((xs.min(), xs.max(), ys.min(), ys.max()) if len(xs) else None)
    side = max([max(b[1] - b[0], b[3] - b[2]) for b in boxes if b] or [10]) + 12
    out = []
    for tile, box in zip(tiles, boxes, strict=True):
        cx, cy = (
            ((box[0] + box[1]) // 2, (box[2] + box[3]) // 2)
            if box
            else (tile.shape[1] // 2, tile.shape[0] // 2)
        )
        pad = np.pad(tile[:, :, :3], ((side, side), (side, side), (0, 0)), mode="edge")
        y0, x0 = cy + side - side // 2, cx + side - side // 2
        out.append(pad[y0 : y0 + side, x0 : x0 + side])
    return out


def sheet(rows: list[tuple[str, list[np.ndarray]]], path: Path) -> None:
    from PIL import Image, ImageDraw

    label, cols = 120, len(rows[0][1])
    img = Image.new("RGB", (label + CELL * cols, CELL * len(rows)), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    for r, (name, tiles) in enumerate(rows):
        draw.text((4, r * CELL + CELL // 2 - 6), name, fill=(230, 230, 230))
        for c, tile in enumerate(_crops(tiles)):
            cell = Image.fromarray(tile).resize((CELL, CELL), Image.LANCZOS)
            img.paste(cell, (label + c * CELL, r * CELL))
        draw.line([(0, r * CELL), (img.width, r * CELL)], fill=(70, 70, 70))
    img.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--modes", nargs="+", default=["classic"])
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--per-sheet", type=int, default=7)
    args = parser.parse_args()

    import logging

    from manim_studio.core.engine import adapter

    adapter.configure(ROOT / ".cache" / "manim")
    logging.getLogger("manim").setLevel(logging.WARNING)
    OUT.mkdir(parents=True, exist_ok=True)
    pairs = [p for p in PAIRS if not args.only or p.name in args.only]
    header = f"{'pair':24} {'mode':8} {'travel':>7} {'max':>6} {'cross':>5} {'dip':>5} {'pop':>9}"
    header += f" {'mid L':>6} {'begin':>7} {'frame':>6}"
    print(header)
    for mode in args.modes:
        rows = []
        for pair in pairs:
            row, tiles = measure(pair, mode)
            rows.append((f"{pair.name}\n{mode}", tiles))
            print(
                f"{row['pair']:24} {mode:8} {row['travel']:7.3f} {row['step']:6.3f} {row['cross']:5d} "
                f"{row['dip']:5.2f} {row['pop']!s:>9} {row['mid L']:6.3f} "
                f"{row['begin']:7.1f} {row['frame']:6.2f}"
            )
        for i in range(0, len(rows), args.per_sheet):
            sheet(rows[i : i + args.per_sheet], OUT / f"sheet-{mode}-{i // args.per_sheet + 1}.png")
    print(f"sheets in {OUT}")


if __name__ == "__main__":
    main()
