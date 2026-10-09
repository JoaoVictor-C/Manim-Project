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

## Phase 1 — editor MVP

| slice | scope | done when |
|---|---|---|
| **S1 timeline** | QGraphicsView: one row per layer, clip bars draggable and resizable, playhead scrub, overlap rejected | dragging a clip updates the canvas live (≤ 33 ms per move) |
| **S2 panels** | layer list (reorder = z-order), object library, properties panel generated from the adapter registry | a new MathTex layer with a Write clip can be built without editing JSON |
| **S3 canvas interaction** | hit-testing with `qt_paths`, selection outline, move gizmo with the stopwatch rule (no keyframes → base value; keyframes → key at playhead), `QUndoStack` | move an object, undo, redo |
| **S4 export dialog** | `QProcess` running `manim-studio render`, progress, cancel | export from the UI without freezing it |

**Smallest useful v1:** write an equation, move it, morph it into a second
equation, fade it out, export MP4 — without touching code or JSON.

## Phase 2

- Layer tree and part layers (ADR 0012): animate terms of an equation, TransformMatchingTex
- Scale / rotate / anchor gizmos, auto-key, curve editor for easing
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
