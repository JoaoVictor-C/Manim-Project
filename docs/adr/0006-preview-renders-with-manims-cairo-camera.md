# 0006. Preview renders with Manim's Cairo camera

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

The original plan assumed Manim's Cairo rendering was too slow for live preview,
so preview would draw Manim's Bezier geometry with QPainter and only export would
use Cairo. Measurements disproved the premise: the slow part was the evaluator
deep-copying mobjects, not rasterising.

## Decision

- **Content** in the editor is rendered by Manim's **Cairo camera** (the export
  renderer) at device pixels, framed to the visible viewport, and shown as a
  QImage. Preview and export are the same pixels.
- During pan/zoom gestures Qt scales the last image; Cairo re-renders at rest.
- **QPainterPaths** (`render/qt_paths.py`) are built lazily, only for the
  selected/hovered layers, for hit-testing, selection outlines and gizmos.
  They mirror Cairo: non-zero winding fill (Qt defaults to odd-even), pen width
  `stroke_width × 0.01` frame units, draw order background stroke → fill → stroke.

## Consequences

- No second renderer to keep in sync for content (images, gradients come free).
- Zooming builds a new camera for the viewport (cheap, vector-crisp).
- `qt_paths` must stay geometrically faithful — guarded by a test.

## Alternatives considered

- **QPainter for all preview drawing** — slower (13.6 vs 10.5 ms) and a second
  implementation of every Manim style feature.

## Evidence

- Benchmarks B1, B2, B4 in [../logs/benchmarks.md](../logs/benchmarks.md).
- `tests/render/test_qt_paths.py`: Qt vs Cairo on fills, glyphs with holes,
  thick scaled strokes, and a mid-Write frame.
