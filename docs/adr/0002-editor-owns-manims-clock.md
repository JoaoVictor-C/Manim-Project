# 0002. The editor owns Manim's clock

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

Manim is imperative: a `Scene.construct()` calls `self.play(...)` in sequence and
time only moves forward. A visual editor needs the opposite: any frame at any
time, in any order (scrubbing), and edits that do not require code.

Manim 0.22's `Scene.play_internal` (`manim/scene/scene.py`) is only a driver
loop: `begin()` → `update_to_time(t)` which calls
`animation.interpolate(t / run_time)` per frame → `finish()`.
`Animation.begin()` stores `starting_mobject = mobject.copy()` and most
animations interpolate from that copy (`manim/animation/animation.py`).

## Decision

1. A JSON **project document** (`core/model/schema.py`) is the single source of truth.
   Manim code is never the source.
2. The **Evaluator** (`core/engine/evaluator.py`) replaces `play()` and owns the clock:
   - the state after each clip is a cached **checkpoint** (`begin()` + `finish()`
     on a copy of the previous checkpoint);
   - a clip active at `t` owns a working copy, begun once, then
     `interpolate((t - start) / duration)`;
   - layer transforms are applied afterwards to scratch copies, never in place.
3. A frame is a **pure function of (project, t)**. Objects returned by
   `frame()` are render buffers, valid until the next call.

## Consequences

- Scrubbing, random access, and chunk-parallel export are possible.
- Preview and export share one code path.
- Each animation class must be verified as random-access-safe (ADR 0007).
- History-dependent features (updaters, `TracedPath`) do not fit and need a
  separate "simulated layer" design later.

## Alternatives considered

- **Generate Python and render with `manim`** — no scrubbing, minutes per preview,
  keyframes become lossy updater code.
- **Re-implement Manim geometry in our own renderer** — enormous scope, preview
  would diverge from export.

## Evidence

- `tests/core/engine/test_random_access.py`: shuffled, reversed, repeated and
  fresh-evaluator frames equal the sequential loop for every clip kind on
  Square, Text and MathTex, plus a three-clip checkpoint chain.
