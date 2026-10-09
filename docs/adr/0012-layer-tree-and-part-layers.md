# 0012. Layer tree and part layers

- **Status:** Proposed
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

ADR 0004 makes the layer the unit of animation. Everyday Manim usage animates
*parts* of objects: one term of an equation (`Indicate(eq[0][1:3])`), the axes
of a graph separately from its curve. And a graph built with `axes.plot()` must
move with its axes. Flat, independent layers cannot express either.

## Decision (proposed)

- Layers form a **tree** mirroring Manim's submobject tree. Kinds:
  - *object layer*: built from a spec;
  - *part layer*: a stable id plus a key into the parent's built mobject —
    tex substring (via `substrings_to_isolate`), named attribute
    (`axes.x_axis`), SVG element id captured at import, or index as a fallback.
    Unresolvable keys are flagged "orphaned", never silently retargeted;
  - *group layer*.
- Children inherit the parent's layer transform (After Effects parenting).
- The overlap rule (ADR 0004) is scoped to the subtree: a clip may not overlap
  clips on its ancestors or descendants; siblings may animate concurrently.
- A child's lifetime is clamped to its parent's; an ancestor's clip targets
  only descendants alive at its start.

## Consequences

- Schema gains `parent_id`, `kind`, `part_key` — add them before the UI depends
  on the flat model to avoid a migration.
- Needs tests: tex-part isolation does not change the rendered equation; part
  keys survive spec edits.

## Evidence

- Design reasoning: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 1.
- Not yet implemented or measured.
