# 0015. Build worker: warm Manim's disk cache, then commit

- **Status:** Proposed
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

S2 lets the user type text into Text, Tex and MathTex layers. Building such an
object the first time is slow — MathTex 1287 ms, Tex 1238 ms, Text 557 ms — and
fast afterwards because Manim caches the generated SVG on disk (11–18 ms, B17).
The evaluator builds objects synchronously on the UI thread (ADR 0002 keeps it
a pure function of project and time).

A Python thread does not fix it: LaTeX runs as a subprocess (UI stall 11 ms) but
Text is rendered by manimpango, which holds the GIL (UI stall 375 ms, B18). A
separate process does fix it, and the disk cache it fills is reused by the
editor process (Text 32 ms, MathTex 16 ms afterwards), but starting Python and
importing Manim costs 3–4 s (B18).

Only some params create new cache entries: the text and the Text font do
(269–1261 ms); `font_size`, `color` and style do not (9–31 ms, B19).

## Decision

- A **persistent worker process** (`python -m manim_studio.worker`, JSON lines
  over stdin/stdout, driven by a `QProcess`) builds specs to warm the disk
  cache. It starts with the editor and pre-warms the library defaults.
- Every UI edit goes through a **gate** (`core/warm.py`, pure): the *warm keys*
  of text-bearing specs that the edit adds or changes. A warm key is the
  canonical `type` + `params` minus the measured cache-neutral params; unmeasured
  params count by default.
- If every key is warm the edit is applied at once. Otherwise it is held as a
  **re-runnable operation** (a callable over `core/edits`), never as a
  snapshot, and committed when its keys are warm by re-running it on the
  **current** snapshot. `EditError` drops it. Latest wins per `(layer, path)`.
- An error from the worker (e.g. bad LaTeX) means the edit is never committed.
- Undo/redo, opening a project and non-text builds are not gated. The warmed set
  is advisory: it affects latency, never correctness.

## Consequences

- Typing new text never freezes the UI; the change appears when it is built
  (0.5–1.3 s later), and bad LaTeX never enters the document or undo history.
- The evaluator stays synchronous and pure; export and undo need no placeholder
  states.
- One more process to manage: startup queueing, a 20 s per-request timeout with
  restart, crash restart, and a synchronous fallback if it cannot start.
- Edits made while a build is pending are preserved because pending changes are
  operations re-run on the current snapshot.
- Image builds stay synchronous (~0.2 s for a 4000×4000 PNG, B20); opening a
  project with many unseen strings is slow once.

## Alternatives considered

- **Synchronous build with a busy cursor** — up to 1.3 s freezes per new string.
- **Build in a thread** — Text still stalls the UI for 375 ms (GIL).
- **Commit first, draw a placeholder** — makes the evaluator asynchronous;
  export and undo would have to handle placeholder states (breaks ADR 0002).
- **Spawn a process per edit** — 3–4 s each.
- **Field-keyed gate** (only property-panel text fields) — misses add-from-library,
  paste and duplicate (found in decision session 5).

## Evidence

- Benchmarks B17–B20 in [../logs/benchmarks.md](../logs/benchmarks.md).
- [Decision session 5](../logs/decision-sessions.md).
- Tests (S2.2): `tests/core/test_warm.py`, `tests/ui/test_build_service.py`,
  `tests/test_worker.py`.
