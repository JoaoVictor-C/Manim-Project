# 0014. Document snapshots and undo

- **Status:** Accepted (implemented in S1.2, 2026-10-09)
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

S1 introduces the first user edits (dragging clips). Edits need validation,
undo, and a single way to tell the evaluator, canvas and timeline what changed.
Measured costs (B10): validating a 100-layer / 400-clip project takes 0.87 ms; a
structural one-layer edit with validation takes 0.02 ms. pydantic's
`model_copy(update=...)` skips validators, so edits built that way could bypass
project-level rules such as morph targets — the class of bug that once crashed
the evaluator.

## Decision

- The project is an **immutable snapshot**. Edits never mutate it; they build a
  new one, sharing unchanged layers.
- **Edit functions live in `core/editing/edits.py`** (no Qt). They rebuild the changed
  layer from data, so lane rules run, and the project with
  `Project.model_validate`, so project rules run. They return
  `Edit(project, kind, layer_ids)` (kinds: ADR 0013).
- **`ui/session/document.py`** holds the current snapshot and a `QUndoStack`. A command
  stores `(before, after, kind, layer_ids)`; undo and redo swap snapshots and
  emit `changed(project, layer_ids, kind)`.
- **Drags** are previewed without touching the stack and pushed as **one**
  command on release. Escape restores the snapshot taken at press.
- Undo is introduced now (S1), not in S3: every later edit then goes through the
  same path for free.

## Consequences

- Undo/redo is two references per step; no inverse operations to write.
- Invalid documents cannot be produced by the UI: validation runs on every edit,
  previews included, at under 1 ms.
- Observers react to typed changes instead of polling or rebuilding.
- Memory grows with history only by the changed layers (structural sharing).

## Evidence

- Benchmark B10 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Verified during planning: a layer rebuilt from data with an overlap raises
  `ValidationError`; `Project.model_validate` over existing layers runs the
  project validator (duplicate ids rejected).
- `tests/ui/session/test_document.py`: one undo step per drag, cancel restores, undo
  emits the reverse kind; edits/undo/redo in the editor keep the evaluator equal
  to a fresh one (mutation-checked: ignoring the kind makes it fail).
