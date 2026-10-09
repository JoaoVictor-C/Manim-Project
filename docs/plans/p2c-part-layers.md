# P2c — Part layers (terms of an equation): implementation plan

- **Status:** ✅ Done (2026-10-09) — `tests/ui/test_acceptance_p2c.py`
- **Date:** 2026-10-09
- **Decided in:** [decision session 10](../logs/decision-sessions.md) (Terza, `balanced`, confidence 0.90)
- **Evidence:** benchmarks B28, B29 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0012 — Layer tree and part layers](../adr/0012-layer-tree-and-part-layers.md)

## Goal

Animate the terms of an equation as layers of their own, the way Manim users
write `Indicate(eq[0][4:6])`. **Done when** you can write an equation, then
indicate one term, move another with keyframes and fade a third out, and the
export shows exactly that (acceptance test).

## Model

- `Layer.parent_id` and `Layer.part = {tex, occurrence}`; `spec` is required on
  roots and absent on parts. The parent is a MathTex/Tex root or a part of one.
- A part is the `occurrence`-th match of `tex` inside its parent's text (the
  root's TeX, or the parent part's span). It resolves to **one exact span**.
- The adapter wraps each resolved span in its own
  `\special{dvisvgm:raw <g id=...>}` markers — never `substrings_to_isolate`,
  which isolates every occurrence (adding one part could move another) and
  would put a marker after every matching `^` (B28).
- A span that starts right after `^`/`_` is braced when it is one token
  (`a^2` → `a^{2}`, identical, B28) and refused otherwise; spans that cross
  another part's span are refused. An unresolvable part is **orphaned**: kept
  with its clips and keys, drawn nowhere, flagged in the UI.
- The root builds once, with markers (pixel-identical at rest and during
  Write/Create/DrawBorderThenFill, B28). The markers are a build parameter, so
  they are part of the warm key (ADR 0015) and adding parts is one async build.

## Evaluation

Per root with parts (roots without parts keep today's path unchanged):

- the clips of the whole subtree are ordered by start; by the ADR 0012 rule a
  clip never overlaps clips of its ancestors or descendants, so clips that
  overlap in time act on disjoint glyphs and commute;
- a checkpoint is the whole root after a set of finished clips (key: their ids
  in start order); a clip is begun on its layer's glyphs inside a copy of the
  checkpoint at its start;
- at `t`, each layer draws the glyphs it owns (its region minus its children's)
  from the active clip covering them, else from the checkpoint, through its
  transform composed with its ancestors' (a part pivots on its rest centre);
- a part's lifetime is its own, clamped to its parent's;
- `frame_layers` yields the root, then its parts (parts draw on top, within the
  root's z slot).

V1 refuses morph clips on part trees (on parts, on roots with parts, and
targeting them).

## Edits

| function | does |
|---|---|
| `add_part(project, parent_id, tex, occurrence=0)` | one part; `EditError` if it does not resolve |
| `add_parts(project, parent_id, keys)` | several in one undo step (Split terms) |
| `split_terms(tex)` (pure) | top-level terms around `=`, `+`, `-` at brace depth 0 |
| `remove_layer` | also removes the layer's parts |
| `move_layer` | moves a root together with its parts; parts are not reordered |

`classify` treats a changed part key, or a root whose markers changed, as a
`spec` edit; the evaluator drops a whole subtree's caches on clip/spec edits.

## UI

- Layers panel becomes a tree; timeline rows indent parts under their root.
- **Add part...** (TeX + occurrence, the matched glyphs highlighted) and
  **Split terms** on MathTex/Tex layers.
- Canvas: a click selects the **root** (group-first, so existing flows keep
  working); double-click drills into the part under the cursor; Esc selects
  the parent. Part gizmos pivot on the part's centre.
- Properties shows a part's key and whether it resolves; after a text edit, a
  status message names parts whose match changed (text, neighbours or count).

## Not in v1

Text (non-TeX) parts, named-attribute parts (axes), picking glyphs by clicking,
group layers, morphs on part trees, TransformMatchingTex, reparenting by drag,
moving a part outside its root's z slot.

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P2c.1 | schema, `core/parts.py` (resolve, brace, markers, split), adapter build with markers, edits, warm keys, classify | unit + LaTeX tests: exact glyphs, nesting, refusal, pixel identity |
| P2c.2 | evaluator: subtree checkpoints, owned glyphs, composed transforms, lifetimes | frames match hand-built Manim; export parity |
| P2c.3 | layers tree, timeline rows, Add part dialog, Split terms | edits through the UI, one undo step each |
| P2c.4 | canvas drill-in, part pivot, Properties part view, orphan/retarget messages | click/double-click/Esc; gizmo on a part |
| P2c.5 | acceptance + docs | write, indicate, move, fade a term; export checked |

## Outcome

Done on 2026-10-09. Differences from the plan:

- A sibling may not *contain* another sibling either (not only cross it): their
  shared glyphs would be drawn twice. Only a part's ancestors share its glyphs.
- The retarget warning compares the match count and the nearest character on
  the part's left; text appended after a part does not trip it.
- Clip drags and new clips on a row respect *obstacles*: the clips of the
  layer's ancestors and parts (`timeline.model.obstacles`), so the subtree
  overlap rule is never broken mid-drag.
- `Evaluator.layer_frame` gives a layer's pivot, world rotation and the map
  from a world move to its own position: dragging a part under a rotated or
  scaled object moves it under the cursor.
- An object with parts costs 3.8 ms per frame to evaluate (0.6 ms without),
  12.6 ms with rendering at 1280x720 (B29).
- Known limit: on a small part the gizmo's corner handles sit close to its
  glyphs, so a press near its edge scales instead of moving it.
