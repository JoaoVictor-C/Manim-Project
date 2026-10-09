# 0008. Incremental invalidation with edit classes

- **Status:** Accepted; extended by [0013](0013-timing-edits-keep-caches.md) (the API now takes `kind=`)
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

Rebuilding the Evaluator after every edit costs 109–225 ms, far too slow for
dragging a clip or an object (one rebuild per mouse move).

## Decision

`Evaluator.invalidate(project, layer_ids, transform_only=False)` adopts the
edited document and drops only what the edit affects:

| edit class | examples | drops | cost |
|---|---|---|---|
| transform-only | gizmo drag, keyframe value/ease | active morph clips touching the layer | 3.1 ms |
| clip / layer | move, resize, add, remove a clip | the layer's checkpoints, active clips, proxy; morph partners | 27 ms |
| spec | change the object (text, radius) | as above plus the built base mobject | rebuild one layer |

Morph partners are always included: a morph reads both ends.

## Consequences

- Every UI command must declare its edit class and the layer ids it touches.
- A wrong classification shows stale frames — each class is covered by a test
  comparing against a freshly built evaluator.

## Evidence

- Benchmarks B3, B5, B6 in [../logs/benchmarks.md](../logs/benchmarks.md).
- `tests/core/test_invalidation.py`.
