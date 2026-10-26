# 0050. Groups: a root that draws nothing and carries its children

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** João Victor

## Context

The Pythagoras project (P9, row 6) had about twenty separate text and triangle layers moved by hand
to rearrange the scene: "grouping objects is a need too". Decision session 44 scoped Group v1 as
transform-only: a group's position, scale, rotation, anchor and opacity (base and keys) carry its
objects; clips on a whole group, nested groups and parts inside a group are later steps; a morph
does not cross a group's boundary; the readable Python export falls back to the exact form.

The layer tree already had two kinds of children (`parent_id`): part layers (ADR 0012) and child
objects on axes (ADR 0029). Both make their root a **tree**: one build holding every member's
glyphs, checkpoints of the whole object, clips acting on glyph regions. A group's children are
arbitrary objects (text, images, code, simulations) with their own clips and morphs; evaluating them
as one tree would rebuild every child on any child's edit and could not hold a code layer.

## Decision

- **Representation:** a group is a root layer with `spec: {"type": "Group"}` (no params, no style);
  its objects have `parent_id` = the group's id and keep their own id, spec, clips, keys and
  lifetime. No new field: files without groups are byte-for-byte as before, and the Layers tree and
  the timeline (which nest and indent by `parent_id`) show the group with its objects for free.
  `Group` is not in `adapter.MOBJECT_TYPES` (it is not in the library); `build_mobject` returns an
  empty `VGroup`, `build_problem` is None and `allowed_clip_kinds` is empty.
- **Validation (v1):** a group has no clips and no parent; its children are whole plain objects -
  not parts, not axes objects, not objects that have parts or objects on axes, not traced paths or
  connectors (drawn in world units from their layers: the group would move them twice). A morph's
  two ends are in the same group (or neither in one), and nothing morphs into a group or travels
  along one. A group's object may travel along a path (`MoveAlongPath`).
- **Evaluation:** a group is not a tree (`Evaluator._trees_of` leaves it out). Each child is
  evaluated exactly as a root object - its own build, checkpoints, active clips and morphs - and is
  then carried by the group's transform the way a child object is by its parent (`_to_world`,
  `_world_affine`): the child's own transform first, then the group's about the group's anchor,
  opacities multiplied. `frame_layers` yields the children in their list order where the group is
  stacked; the group itself yields nothing. Morph ends and path runs include the group's transform
  in their signatures, so a group transform edit (kind `transform`, no cache dropped) re-begins them
  lazily. Code frames are placed by the composed affine; a trace or a connector aimed at a group
  follows the box of its children.
- **Lifetime:** a group's lifetime is its explicit Appears / Disappears, else the span of its
  children's own lifetimes (min start .. max end; never visible when empty); the children are
  clamped to it as parts are to their object. Computed once per snapshot (`LayerIndex`, the
  evaluator's `_group_spans`), not per child per frame.
- **Edits:** `edits.group_layers(project, ids, name)` puts whole objects in a new group (`group-n`)
  at the front-most one's place in the stacking order, the group's transform the identity so nothing
  moves. Moving a layer into, out of or between groups is a `transform` edit of it (`classify`): its
  build and clips are unchanged, and the evaluator's build keys treat an object in a group as a root,
  so grouping rebuilds nothing. `edits.ungroup` bakes a constant group transform into each child -
  exact at every time, keys included, because keeping the child's anchor makes the composed position
  affine in the child's position alone (`A_G pos + A_G anchor - anchor + b_G`); scale keys are
  multiplied, rotation keys shifted, opacity keys multiplied, path tangents turned - and bakes the
  group's explicit Appears / Disappears into the children it clamped. A keyed group is refused
  ("bake the keys first"). Deleting a group deletes its objects; deleting a group's last objects
  deletes the group. Copy/duplicate remaps ids; an object copied out of a group pastes into it when it
  is in the destination, else on its own.
- **Frame cache:** a group edit redraws its children's spans; an edit of one child only that child's
  (an object in a group is an object of its own for `changed_spans`).
- **UI:** Edit > Group (Ctrl+G) and Ungroup (Ctrl+Shift+G). A click on a group's object selects the
  group (outline and gizmo on the children's box, moved, scaled and turned as one); a double-click
  enters it, a click inside then picks another of its objects and Escape backs out. Properties shows
  a group's name, transform and lifetime only.
- **Export:** `readable_problems` gives "groups are evaluated as one object" for the group and each
  of its objects; the exact export plays them through the evaluator.

## Consequences

- Moving, scaling, turning or fading many objects is one edit on their group, keyed or not; nothing
  rebuilds and each object's clips keep playing as before.
- A clip edit on one object of a group drops only that object's caches (no tree expansion).
- The per-frame cost of a group is one transform per child, as for child objects.
- Not yet: clips on a group (an entrance for all), nested groups, groups holding equations with
  parts or axes with graphs, reordering objects inside a group (move_layer refuses children), and
  collapsing a group's timeline rows.

## Alternatives considered

- **A group as a tree (CHILD_TYPES["Group"] = everything)** - reuses `_child_tree`, but a child's
  edit would rebuild the whole group, code layers and simulations cannot be glyphs of one build, and
  clips would act on glyph regions with other semantics than a root's.
- **A `group` flag or a `group_id` field on layers** - a second parent concept beside `parent_id`;
  the Layers tree, the timeline indentation, cascades and the clipboard would all need teaching.
- **Baking the group into its children on every edit (no group in the file)** - no undoable
  grouping, and a keyed group could not exist.

## Evidence

- Tests: `tests/core/features/test_groups.py` (drawing against a hand-built Manim reference, keyed groups,
  clips inside, no-LaTeX placeholders, lifetime, caches kept on group edits and sibling edits, morph
  and path signatures, frame-cache spans, group/ungroup baking with curved keys, cascades, clipboard,
  export fallback, validation), `tests/ui/panels/test_groups_ui.py`. Every guard was mutation-checked.
- Plan: [../plans/p9-pythagoras-feedback.md](../plans/p9-pythagoras-feedback.md) (U6).
