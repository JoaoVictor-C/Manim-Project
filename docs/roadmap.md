# Roadmap

Each slice ends with something runnable and its tests. Order decided in
[decision session 2](logs/decision-sessions.md).

## Phase 0 — core ✅ (2026-10-09)

- Project schema, Manim adapter, random-access evaluator with checkpoints
- Cairo export to MP4 and `manim-studio render`
- Incremental invalidation with edit classes
- Test suite (random access, transforms, invalidation, Qt-vs-Cairo, UI smoke)
- Benchmarks B1–B9
- **S0 previewer**: `manim-studio edit` — open/save, scrub, play, step, idle checkpoints

## Phase 1 — editor MVP ✅ (2026-10-09)

| slice | scope | done when |
|---|---|---|
| ✅ **S1 timeline** — [plan](plans/s1-timeline.md) | QGraphicsView: one row per layer, clip bars draggable and resizable, playhead scrub, overlap prevented (drags clamp at neighbours), undo/redo | dragging a clip updates the canvas live (≤ 33 ms per applied step; B16: 19–24 ms in the editor) |
| ✅ **S2 panels** — [plan](plans/s2-panels.md) | layer list (reorder = z-order), object library, properties panel generated from the adapter registry | a new MathTex layer with a Write clip can be built without editing JSON (`tests/ui/test_acceptance_s2.py`) |
| ✅ **S3 canvas interaction** — [plan](plans/s3-canvas.md) | hit-testing with `qt_paths`, selection outline, move gizmo with the stopwatch rule (no keyframes → base value; keyframes → key at playhead), `QUndoStack` | move an object, undo, redo (`tests/ui/test_acceptance_s3.py`; B24: 18.5 ms per drag step) |
| ✅ **S4 export dialog** — [plan](plans/s4-export.md) | `QProcess` running `manim-studio render`, progress, cancel | export from the UI without freezing it (`tests/ui/test_export_dialog.py`; B26) |

**Smallest useful v1:** write an equation, move it, morph it into a second
equation, fade it out, export MP4 — without touching code or JSON. ✅ Reached:
`tests/ui/test_acceptance_v1.py` does exactly this through the menus, panels,
timeline and canvas, with the real build worker and renderer.

## Phase 2

- ✅ **P2c** — [plan](plans/p2c-part-layers.md): part layers (ADR 0012) — animate
  the terms of an equation as their own layers
- ✅ **P2e** — [plan](plans/p2e-matching-tex.md): TransformMatchingTex between equations (ADR 0020)
- ✅ **P2d** — [plan](plans/p2d-code-layers.md): code layers (ADR 0019) — a layer
  holding user-written Manim code, rendered into a frame cache and composited
  (for what the visual model cannot express: updaters, ValueTracker, simulations)
- ✅ **P2a** — [plan](plans/p2a-gizmos.md): scale / rotate gizmos, keyable transform properties, auto-key
- Anchor (pivot) gizmo — needs a schema field, an evaluator change and morph
  baking; wanted for pendulums, clock hands, hinges
- ✅ **P2b** — [plan](plans/p2b-keyframes.md): keyframes on the timeline, key view, easing curve editor
- More clip kinds through the allow-list harness

## Phase 3

- Axes and function graphs as child layers; SVG and image import
- Spatial (curved) motion paths, MoveAlongPath clips
- Viewport zoom/pan with re-framed camera; render-ahead cache

## Phase 4

- One-way Python export (ADR 0010)
- Plugin API for custom mobjects
- Simulated layers (updaters, TracedPath) with replay from checkpoints
- Audio track
