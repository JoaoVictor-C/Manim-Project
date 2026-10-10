# 0029. Child objects animate with their object

- **Status:** Accepted
- **Date:** 2026-10-10
- **Deciders:** João Victor
- **Amends:** [0024](0024-axes-and-graphs.md) (child objects), [0025](0025-move-along-path.md) (MoveAlongPath)

## Context

Graphs were evaluated as separate layers drawn after their axes. A clip on the
axes animated the axes alone: Create left the graphs out, FadeOut left them
standing, MoveAlongPath took the axes away from their graphs. Equations with
parts already behave as one object (ADR 0012), and a MoveAlongPath clip on such
an equation crashed.

## Decision

- An object with child objects evaluates as **one tree**, like an equation with
  parts: the axes' build followed by their graphs' builds. A clip on the axes
  animates the whole object; a clip on a graph animates that graph.
- Child objects keep their own transform rules (ADR 0024).
- A graph can still turn into another graph, or into any layer: while it does,
  its own drawing is replaced by the hand-off. A morph of the whole object takes
  its graphs along.
- As for parts, a clip on a child object may not overlap a clip of its object.
- MoveAlongPath works on objects with parts or child objects.
- MoveAlongPath can turn the object along the path (`rotate`: `no` or `along`),
  by the path's change of direction since the clip started.

## Consequences

- Graphs that exist from the start now fade in, move and disappear with their
  axes.
- A file with a graph clip overlapping an axes clip no longer opens.

## Evidence

- A probe on master: a MoveAlongPath clip on an equation with a part raised
  "needs a target".
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 21.
- Plan: [../plans/p3g-child-trees.md](../plans/p3g-child-trees.md).
