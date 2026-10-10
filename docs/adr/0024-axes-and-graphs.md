# 0024. Child objects: axes and graphs

- **Status:** Accepted
- **Date:** 2026-10-10
- **Deciders:** João Victor
- **Amends:** [0012](0012-layer-tree-and-part-layers.md) (a second kind of child layer)

## Context

Function graphs are central to math animation. A graph belongs to a coordinate
system: it is plotted in the axes' coordinates and moves with them. ADR 0012
introduced child layers only as *parts* — spans of a TeX object's glyphs.

## Decision

- A child layer may instead carry **its own spec**, under a root whose type
  accepts that child type (`Axes` accepts `Graph`). It is drawn right after its
  root, carried by the root's transform, lives within its lifetime and is
  deleted with it. The part-only rules of ADR 0012 do not apply to it.
- A graph is **locked to its axes**: no position, scale, rotation or anchor of
  its own; only opacity can be keyed. Gestures on a selected graph move its axes.
- A graph's function is an **expression** compiled by a whitelist over Python's
  syntax tree (numbers, `x`, `pi`, `e`, arithmetic, a few functions). Nothing
  else is accepted, on load or in the editor; nothing is ever passed to `eval`.
- Where the function is undefined or leaves the axes' y range, the curve is
  split into separate subpaths that end exactly at the edge.

## Consequences

- Graphs animate and morph like other layers; editing the axes re-plots them.
- A clip on the axes does not animate their graphs (v1).
- More child types (points on a graph, areas, labels) can follow the same rule.

## Evidence

- Measurements: B37 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 16.
- Plan: [../plans/p3b-graphs.md](../plans/p3b-graphs.md).
