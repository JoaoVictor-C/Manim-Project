# P3c — MoveAlongPath clips: implementation plan

- **Status:** ✅ Done (2026-10-10) — `tests/acceptance/test_acceptance_p3c.py`
- **Date:** 2026-10-10
- **Decided in:** [decision session 17](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.80)
- **Evidence:** benchmark B38 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0025 — Moving along another layer's path](../adr/0025-move-along-path.md)

## Goal

Make an object travel along another layer's shape — a dot along a graph,
around a circle, down a line. **Done when** a dot runs along `sin(x)` on axes
through *Add clip > Move > Along path*, its centre is on the curve at every
sampled time, it scrubs exactly as it plays and exports as the editor shows.

## Model

- Clip kind **MoveAlongPath**, category **motion** (alpha clamped to [0, 1]).
  Offered on **root objects only**: parts run as tree clips with their own
  caches, graphs are locked to their axes, code layers have no clips.
- Registered param **`path`**: a layer id (new param kind `layer`), validated
  on load: the layer exists, is not the mover or one of its descendants, and is
  not a part, a code layer or an image. Roots and graphs qualify.

## Semantics

- At the clip's start, the path layer's **rest shape** (its built object, never
  its clip state) under its world transform at that time (and its axes' for a
  graph) is mapped into the mover's local frame by the inverse of the mover's
  transform at that time; Manim's `MoveAlongPath` runs on the mover's local
  object. The end is carried by the checkpoint like any clip.
- Reading the rest shape, not the animated state, also means layers that follow
  each other cannot recurse.
- The mover jumps to the path's start when the clip begins (Manim does the same).
- Keys on either layer *during* the run are not followed (like morphs).

## Caching

Begun clips, checkpoints, the idle precompute and morph bake keys include the
**path signatures** of every path clip up to them (the mover's and the path
layer's transforms at clip start, the path's build). Moving or editing the path
layer re-runs the path exactly; transform edits keep caches (ADR 0013).

## Edges

- Deleting the path layer drops the clips that follow it (as morphs targeting a
  deleted layer are dropped).
- A canvas drag that the path fully compensates (an un-keyed mover after its
  run) is applied and explained by a status hint.
- Adapter patch: an arc-length table built when the clip begins (B38: 23.6 ms →
  0.005 ms per frame on a graph, identical points).
- No orientation along the tangent yet.

## UI

*Add clip > Move > Along path > (layer)* on the timeline; a **Path** choice in
the clip's Properties.

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P3c.1 | registry, `layer` param kind, schema rules, adapter patch, harness | validation tests; patch = Manim's points; two-layer harness |
| P3c.2 | evaluator: local path, signature keys, removal, hint | frames vs hand-built MoveAlongPath; the dot stays on the path after moving either layer; a later clip starts at the path end |
| P3c.3 | menus, Properties, acceptance, ADR 0025, docs | the Goal's scenario through the UI, export = editor |

## Outcome

Done on 2026-10-10, as planned. The timeline's submenu is named after the kind
(*Move > MoveAlongPath > layer*) like the other clip menus. Graphs are kept out
by the allow-list too (`allowed_clip_kinds("Graph")` has no motion kinds).
