# 0021. The anchor point

- **Status:** Accepted
- **Date:** 2026-10-10
- **Deciders:** João Victor
- **Amends:** [0018](0018-keyable-properties-and-auto-key.md) (a non-keyable transform field)

## Context

A layer rotated and scaled about its position: its build centre for objects,
its rest centre for parts (ADR 0012). Pendulums, clock hands, hinges and doors
need to turn about an end. After Effects has an anchor point, and moves the
position when the anchor moves so the layer does not jump.

## Decision

- `Transform2D.anchor` (local units, default (0, 0)) shifts the pivot:
  `world(p) = A (p - P) + P + position` with `P` = anchor for objects and code
  layers, rest centre + anchor for parts. The default is the old behaviour.
- The anchor is **base only**: no track, never keyed or auto-keyed. A moving
  pivot is out of scope (a code layer can draw one).
- Moving the anchor compensates the position by `(I - A_t)(old - new)`, added
  to the base and to every position key, so the drawing stays put. It is exact
  at all times unless rotation or scale is keyed; then only at the edit time,
  and the editor says so.
- `position` keeps its meaning (where the build centre goes). We did not adopt
  After Effects' "position is where the anchor sits": it would change the
  meaning of every saved project and of part positions.
- The format change is additive; the default is not written.

## Consequences

- Existing projects are untouched; the pivot cross can now be dragged.
- Setting the anchor after keying rotation can move the object at other times
  — set it first.
- Position values no longer tell where the pivot is; the canvas cross does.

## Evidence

- Measurements: B34 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 13.
- Plan: [../plans/p2f-anchor-gizmo.md](../plans/p2f-anchor-gizmo.md).
