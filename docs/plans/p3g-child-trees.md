# P3g — Child objects animate with their object; turning along a path

- **Status:** In progress
- **Date:** 2026-10-10
- **Decided in:** [decision session 21](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **ADR:** [0029 — Child objects animate with their object](../adr/0029-child-objects-in-the-tree.md)

## Goal

**Done when** a Create on axes draws their graphs too, Indicate on the axes
scales the whole figure, the axes can ride a curve carrying their graphs, a
graph still turns into another, and a shape can ride a curve turning with it -
scrub = play, export = editor.

## Evaluator

- Trees cover roots with parts **or child objects** (`_has_parts` becomes
  `_trees_of`). For child objects:
  - the base is `VGroup(root build, child builds)` in project order;
  - regions: the root's = every leaf, each child's = its slice; the root owns
    its own slice, each child its slice;
  - children have no rest centre, so `_member_affine` composes their transform
    exactly as before (`parent ∘ child`).
- The separate child drawing path (`_objects`) goes.
- **Member morphs**: `_tree_clips` keeps excluding morph clips; in
  `_tree_members_at` a member whose morph is active draws the hand-off instead
  of its glyphs. A morph end that is a tree member is taken from
  `_tree_members_at(root, t, morphs=False)`; its signature = the tree's finished
  clips, member transforms and the root's path signatures.
- **Path clips in trees**: `_tree_animation` passes `_path_target` for root
  motion clips; tree-state and tree-active keys add the root's path signatures.
- `_builds` keys a root with child objects by its spec and its children's specs.
- Schema: the member-vs-ancestor overlap rule also covers child objects (morph
  clips included).

## MoveAlongPath rotate

- Clip param `rotate`: `no` (default) | `along`.
- `TabledMoveAlongPath` keeps a copy of the mover at `begin()`; each frame it
  restores that copy, rotates it about its centre by the tangent angle at the
  eased point minus the angle at the start, then moves it to the point.

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P3g.1 | trees for child objects, member morphs, path clips in trees, build keys, overlap rule | the graph suite passes; root clips carry graphs; graph morphs as before; MoveAlongPath on equations and axes; a graph edit rebuilds |
| P3g.2 | `rotate=along` | turning follows the tangent; scrub = play; overshoot clamps |
| P3g.3 | acceptance, docs | the Goal's scenario through the editor, export = editor |
