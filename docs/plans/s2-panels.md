# S2 — Panels: implementation plan

- **Status:** ✅ Done (2026-10-09) — acceptance test `tests/acceptance/test_acceptance_s2.py`
- **Date:** 2026-10-09
- **Decided in:** [decision session 5](../logs/decision-sessions.md) (Terza, `balanced`, confidence 0.90)
- **Evidence:** benchmarks B17–B20 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0015 build worker and warm-then-commit](../adr/0015-build-worker-warm-then-commit.md)

## Goal

Build a scene without touching JSON: a **layer list** (add from a library,
delete, rename, reorder = z-order), a **properties panel** generated from the
adapter registry, and **adding/deleting clips** on the timeline.

**Done when** a new MathTex layer with a Write clip can be built without editing
JSON (S2.7 acceptance test, driven through the real widgets).

### In scope
- Layers dock: library menu, delete (with morph cascade), rename, reorder
- Properties dock: constructor params per type, style, base transform, name,
  lifetime; for a selected clip: kind, start, duration, ease, morph target
- Timeline: context menu "Add clip", Delete key removes the selected clip
- A build worker so typing new text never freezes the UI

### Out of scope
- Clip params (hidden until the harness covers them, ADR 0007)
- Keyframe editing (S3 gizmo / Phase 2), layer tree (ADR 0012)
- Copy/paste and duplicate (the gate below already supports them)

## Responsiveness: warm-then-commit (ADR 0015)

New text is slow to build and cannot be built in a thread without stalling the
UI (B17, B18). A separate process can build it and leaves Manim's disk cache
warm, after which the editor builds the same object in 10–32 ms (B18).

```
Properties / Layers / Timeline
        │ submit(op, text, supersede_key)          op: Project -> Edit (core/editing/edits.py)
        ▼
  BuildService (ui/session/build_service.py) ──needs_warm(old, new, warmed)── core/engine/warm.py (pure)
        │ nothing to warm → Document.apply           │ keys to warm
        │                                            ▼
        │                               WorkerProcess (QProcess, JSON lines)
        │                                 python -m manim_studio.processes.worker
        │ reply ok: key → warmed; re-run pending ops on the CURRENT snapshot
        ▼
     Document.apply → Evaluator (disk-cache hit, ~10–32 ms)
```

Rules:

1. **Warm key** — canonical JSON of `type` + `params` of a text-bearing spec
   (Text, Tex, MathTex) **minus** the params measured cache-neutral
   (`font_size`, `color`, B19). Style is never part of the key. Unmeasured
   params are in the key by default.
2. **Gate** — `needs_warm(old, new, warmed)` returns the keys of text-bearing
   specs that the edit adds or changes and that are not warm. Empty → apply now.
3. **Pending operations** — otherwise the edit is held as an *operation*
   (a callable over `core/edits` functions), never as a snapshot. One request is
   sent per unwarmed key not already in flight. A newer op with the same
   supersede key `(layer_id, path)` replaces the older one (latest wins).
4. **On a reply** the key joins the warmed set, then every pending op is re-run
   on the **current** snapshot: `EditError` (e.g. its layer was deleted) → drop;
   all keys warm → commit (one undo step); otherwise keep waiting.
5. **Errors** — an error reply (bad LaTeX) drops the op and reports the message;
   nothing enters the document or the history.
6. **Drags** — commits are deferred while `document.dragging`, flushed after the
   drag is committed or cancelled.
7. **Pending values** — the service exposes `pending_value(layer_id, path)`; the
   properties panel shows it with a "building…" hint instead of the committed
   value, so an unrelated refresh never clobbers what the user typed.
8. **Not gated** — undo/redo, opening a project, image builds (~0.2 s for a
   4000×4000 PNG, B20). The warmed set is advisory: a stale entry only costs a
   slow build, never a wrong frame.

Worker lifecycle: started at launch, pre-warms the library defaults, requests
queue while it starts (3–4 s, B18); a request older than 20 s kills and restarts
it with an error; a crash restarts it. If the worker cannot start, the service
falls back to applying edits synchronously.

## Properties panel

Generated from `adapter.MOBJECT_PARAMS`: per type, a hand-curated list of
`Param(name, kind, default, min, max, choices)` — kinds `float`, `int`, `text`,
`color`, `choice`, `bool`, `path`. A test builds every type with its defaults
and with a non-default value of each param.

| selection | fields |
|---|---|
| layer | name; type params; style (VMobjects: fill, fill_opacity, stroke, stroke_width); base position x/y, scale, rotation, opacity; lifetime (auto / explicit in–out) |
| clip | kind (from `allowed_clip_kinds(type)`, same category family: a morph stays a morph), start, duration, ease (named list + presets), morph target |

Fields commit on `editingFinished` (spin boxes without keyboard tracking): one
undo step per field. A value the schema rejects reverts and shows the message
in the status bar.

## Layers

| operation | edit function | kind (by diff) |
|---|---|---|
| add from library | `add_layer(project, spec, index=None)` — id `<type>-<n>` (smallest free n), on top | `clip` for the new id |
| delete | `remove_layer(project, layer_id)` — also removes the morph clip that targets it | `clip` |
| rename | `update_layer(project, id, name=...)` | `timing` |
| reorder (z-order) | `move_layer(project, layer_id, index)` | `timing`, no ids |

The list is top-to-bottom = front-to-back (last layer in the project draws on
top). Selecting a layer selects it in the properties panel.

## Clips

- Timeline context menu on a row → **Add clip ▸** kinds allowed for the layer
  type, grouped by category. The clip starts at the clicked time, 1 s long,
  clamped to the gap (`add_clip` refuses if less than one frame fits). Morph
  kinds open a submenu of targets: other layers that are not already morph
  targets. The menu is disabled after a morph (nothing may follow one).
- **Delete** key / menu removes the selected clip (`remove_clip`).

## Work breakdown

| step | content | acceptance |
|---|---|---|
| S2.1 | `core/editing/edits.py`: `add_layer`, `remove_layer`, `move_layer`, `add_clip`, `remove_clip`, `new_layer_id`, `new_clip_id` | unit tests; property test: random structural edits + `Evaluator.apply` == fresh evaluator |
| S2.2 | `core/engine/warm.py`, `manim_studio/processes/worker.py`, `ui/session/build_service.py`, ADR 0015 | fake-worker tests for rules 1–7; real subprocess: warm then main build < 100 ms, LaTeX error reported, killed worker restarts and a queued request completes |
| S2.3 | `adapter.MOBJECT_PARAMS` for the 12 types | every type builds with defaults and with each param changed |
| S2.4 | Layers dock | add/delete/rename/reorder through the widget, one undo step each |
| S2.5 | Properties dock | edits through widgets; pending text survives an unrelated edit |
| S2.6 | Timeline add/delete clip | context menu + Delete key; morph target menu |
| S2.7 | Acceptance + docs | "MathTex + Write without JSON" through the widgets; export renders it |

## Outcome

All steps done on 2026-10-09; 407 tests (about 30–38 s). Differences from the
plan, found while building it:

- **File > New** was missing — without it "no JSON" was impossible (S2.7).
- **Timeline rows** now list the front-most layer first, like the Layers panel
  (found from a screenshot of the finished docks, S2.6).
- The schema now rejects duplicate clip ids on a lane and vector-only kinds on
  image layers (S2.1): both would have reached the evaluator from the new panels.
- `\frac{x}{` is valid LaTeX inside Manim's `align*` wrapper, so error tests use
  an undefined command (S2.2).
- The worker's cache dir must match the editor's: a test that re-pointed Manim's
  cache made the editor miss the warmed entry (S2.2).

Added right after S2: a Save / Discard / Cancel prompt for unsaved changes on
New, Open and quit. Left for later: keyframe editing
(S3 gizmo); clip params (ADR 0007).
