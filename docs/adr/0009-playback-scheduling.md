# 0009. Playback scheduling: frame dropping, idle checkpoints, gc.freeze

- **Status:** Accepted (amended by [0028](0028-render-ahead-cache.md): playback shows grid frames)
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

Median frame cost is under the 33 ms budget (30 fps), but single frames spiked
to 64–115 ms. Tracing showed two causes: the lazy checkpoint computed on the
first frame after a clip ends, and Python's full (gen-2) garbage collection.
The evaluator is pure Python on the UI thread; a worker thread would not run in
parallel (GIL) and would race on the evaluator's caches.

## Decision

- **Playback samples wall-clock time** (`t = t0 + elapsed`) and draws that frame;
  slow frames are dropped, never queued.
- After load or a clip/spec edit, **missing checkpoints are computed one per idle
  tick** on the UI thread (`Evaluator.missing_checkpoints()` /
  `compute_checkpoint()`, ≤ 25 ms each).
- **`gc.collect(); gc.freeze()`** after a project loads.
- **Half-resolution playback** is a View option for heavy projects.

## Consequences

- Worst frame over 3 × 120 frames at 1080p: 81–115 ms → 31–35 ms.
- The UI stays responsive while preparing (status bar shows progress).

## Alternatives considered

- **QThread precompute** — GIL-bound and not thread-safe with shared caches.
- **Worker process** — cannot share in-memory checkpoints.

## Evidence

- Benchmarks B7, B8 in [../logs/benchmarks.md](../logs/benchmarks.md).
- `tests/core/engine/test_invalidation.py::test_missing_checkpoints_drain`
