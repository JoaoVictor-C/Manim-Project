# S1 — Timeline: implementation plan

- **Status:** In progress — S1.1–S1.3 done
- **Date:** 2026-10-09
- **Decided in:** [decision session 4](../logs/decision-sessions.md) (Terza, `balanced`, confidence 0.90)
- **Evidence:** benchmarks B10–B14 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **Proposed ADRs:** [0013 edit kinds incl. timing](../adr/0013-timing-edits-keep-caches.md),
  [0014 document snapshots and undo](../adr/0014-document-snapshots-and-undo.md)

## Goal

A timeline under the canvas: one row per layer, clip bars you can **move** and
**trim** with the mouse, a **ruler to scrub** the playhead, and the canvas
updating **live while you drag** — at most 33 ms per applied drag step.

### In scope
- Rows per layer (name, lifetime band, clip bars coloured by category)
- Move and trim clips; snapping; overlap prevented by clamping
- Playhead + ruler scrubbing; Ctrl+wheel zoom, horizontal scroll
- Undo/redo (Edit menu, Ctrl+Z / Ctrl+Shift+Z); Escape cancels a drag

### Out of scope (later slices)
- Creating/deleting clips or layers, changing clip kind (S2)
- Reordering clips on a lane, moving clips between rows
- Keyframe lanes (Phase 2)

## Architecture

```
TimelineView (Qt) ──drag──► timeline/model.py (pure: snap + clamp)
        │                              │ proposed start/duration
        ▼                              ▼
   Document (Qt) ◄──────────── core/edits.py (pure: validated snapshot + EditKind)
        │ changed(project, layer_ids, kind)
        ├──► Evaluator.invalidate(project, ids, kind)
        ├──► Canvas.refresh()
        └──► TimelineView.sync(project)
```

| module | Qt? | responsibility |
|---|---|---|
| `core/edits.py` | no | `move_clip`, `trim_clip` → `Edit(project, kind, layer_ids)`; full validation; kind decided by diff |
| `core/evaluator.py` | no | `invalidate(..., kind="timing")`: keep caches; morph entries keyed by baked transforms |
| `ui/document.py` | yes | current snapshot, `QUndoStack`, `preview()` / `commit()` / `cancel()`, `changed` signal |
| `ui/timeline/model.py` | no | `TimeScale` (time↔x, zoom), frame quantisation, snapping, clamp bounds |
| `ui/timeline/view.py` | yes | `QGraphicsView`: ruler, rows, clip items, lifetime bands, playhead |

### Edit kinds (ADR 0013, extends ADR 0008)

| kind | when | evaluator drops |
|---|---|---|
| `timing` | only clip `start`/`duration` changed, lane order unchanged | nothing; a morph entry only if its baked start/end transforms changed |
| `transform` | `base` or keyframe tracks | morph entries touching the layer |
| `clip` | kind, params, ease, add/remove/reorder clips | layer checkpoints, active clips, proxy, morph partners |
| `spec` | the object itself | as `clip` + the built base mobject |

Why `timing` is safe: a clip's begun animation and its end checkpoint depend on
the state before it (the preceding clips), its kind, params and ease — never on
*when* it plays; the evaluator passes alpha itself. Morphs are the exception
because they bake the partners' world transforms at their start/end (ADR 0005),
hence the transform-keyed cache.

## Interaction rules

**Snapping** (`timeline/model.py`): candidates = frame grid (always), every clip
edge on every row, the playhead, 0 and the canvas end; snap to the nearest within
**8 px** at the current zoom. **Alt** disables all but the frame grid.

**Clamping** (overlap is prevented, never "rejected" mid-drag):

| gesture | allowed range |
|---|---|
| move | `start ∈ [prev.end, next.start − duration] ∩ [0, canvas.duration − duration]` |
| trim left edge | `start ∈ [prev.end, end − 1 frame]` |
| trim right edge | `end ∈ [start + 1 frame, min(next.start, canvas.duration)]` |

A morph clip is always last on its lane, so its right trim is bounded by the
canvas end. Moving a morph moves the target layer's lifetime band live.

**Drag lifecycle:** press → remember the snapshot (`before`). Each mouse move
stores only the latest proposal; one queued apply (`QTimer.singleShot(0)`)
previews it, so slow frames drop positions instead of queueing (same rule as
playback, ADR 0009). Release → push **one** undo command `(before, final)`.
Escape → restore `before`, push nothing.

## Performance budget (measured — B10–B14)

| drag on the stress scene, per step (invalidate + evaluate + Cairo 960×540) | today | with S1 |
|---|---|---|
| Write clip | ~38 ms | **21.2 ms** |
| morph (TransformMatchingShapes, MathTex), static partners | 94.3 ms | **16.3 ms** |
| morph, keyframed partners that have settled | ~94 ms | **15.4 ms** |
| morph while a partner is still moving | ~94 ms | ~105 ms — *known slow path, coalesced* |

Half-resolution drafting was measured and **does not help** (93.9 ms): the cost
is Manim's `begin()`, not drawing. The timeline itself is negligible (0.17 ms to
move one of 400 clip items and repaint).

## Work breakdown

| step | deliverable | tests / acceptance | est. |
|---|---|---|---|
| **S1.1** ✅ | `core/edits.py`, `EditKind`, `Evaluator.invalidate(kind="timing")`, transform-keyed morph cache; ADR 0013 accepted | kind detection (incl. reorder ⇒ `clip`); invalid edits raise; **spy on `adapter.make_animation` proves timing edits never re-begin**; keyframed morph vs fresh evaluator; property test: random edits via `invalidate(kind)` == fresh evaluator | 1–2 d |
| **S1.2** ✅ | `ui/document.py`, undo/redo commands, Edit menu; ADR 0014 accepted | preview/commit/cancel; one undo step per drag; undo/redo frames == fresh evaluator; undo of a timing drag is a timing edit | 1 d |
| **S1.3** ✅ | `ui/timeline/model.py` | headless: time↔x round trip at several zooms; snapping priority and threshold; every clamp bound; quantisation; Alt | 1 d |
| **S1.4** | `ui/timeline/view.py` (ruler, rows, bars, lifetime bands, playhead, zoom/scroll) | rows match layers, bars match clips, ruler click seeks, zoom keeps the time under the cursor | 2 d |
| **S1.5** | drag move/trim wiring, coalescing, Escape; benchmark B16 (drag latency in the real widget) | `QTest` drags → expected document + exactly one undo entry; Escape restores; B16 ≤ 33 ms for Write and settled-morph drags | 1–2 d |
| **S1.6** | `MainWindow`: vertical splitter (canvas over timeline), selected-clip highlight; docs (architecture, roadmap, changelog) | UI smoke test with the timeline; full suite < 20 s | 0.5 d |

Total: about **7–8 working days**. Each step is mergeable on its own and leaves
the app runnable.

## Risks

- **Mid-motion morph drags stay slow (~105 ms/step).** Bounded by coalescing; if
  it matters in practice, cache the morph's begun animation per quantised start
  frame during a drag.
- **Misclassified edit kind ⇒ stale frames.** Mitigated by deciding the kind in
  `edits.py` (callers cannot choose) and by the property test against a fresh
  evaluator.
- **Qt event-loop timing in tests.** Drag tests call the queued apply directly
  instead of relying on timer timing, as the playback tests do.
