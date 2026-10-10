# 0026. Curved position paths

- **Status:** Accepted
- **Date:** 2026-10-10
- **Deciders:** João Victor
- **Amends:** [0018](0018-keyable-properties-and-auto-key.md) (position keys)

## Context

Between two position keys an object moved in a straight line. Arcs and swoops
needed many keys or a separate path layer (ADR 0025).

## Decision

- Position keys may carry an in and an out **tangent**; a segment with one is a
  cubic Bezier. Keys without tangents behave exactly as before.
- Curved segments are walked by **arc length**, so the key's ease controls the
  speed along the path, as it does on straight segments.
- The canvas draws the selected layer's motion path with its keys and tangent
  handles; a smooth key keeps its handles aligned but of their own lengths.
- Adding a key inside a curved segment splits the curve so its shape stays.

## Consequences

- Straight motion is untouched; curved motion costs a cached table per segment.
- Inserting a key keeps the path's shape, not its timing (as before for
  straight segments).

## Evidence

- Measurements: B39 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 18.
- Plan: [../plans/p3d-curved-paths.md](../plans/p3d-curved-paths.md).
