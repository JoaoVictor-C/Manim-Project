# 0025. Moving along another layer's path

- **Status:** Accepted
- **Date:** 2026-10-10
- **Deciders:** João Victor

## Context

A dot running along a graph or around a circle is a staple of math animation
(Manim's `MoveAlongPath`). In the editor a clip animates its layer's *local*
object and the layer transform places it; a path belongs to another layer,
with its own transform.

## Decision

- A clip kind **MoveAlongPath** (category *motion*) with a param naming the
  path layer, on root objects only.
- At the clip's start the path layer's **rest shape** in world space is mapped
  into the mover's local frame and Manim's `MoveAlongPath` runs there; the end
  state is carried like any clip's. Caches include the signature of the path
  (both layers' transforms at clip start, the path's build), so editing or
  moving either layer re-runs it exactly.
- Overriding the position or adding an offset were rejected: the first fights
  position keys and makes a layer's transform depend on another; the second
  leaves a dot on a graph off the curve.
- An adapter patch measures the path once (arc-length table) instead of every
  frame.

## Consequences

- The mover jumps to the path's start when the clip begins, as in Manim.
- Keys on either layer during the run are not followed (like morphs).
- After its run, an un-keyed mover stays at the path's end whatever its base
  position; the editor says so when a drag would change nothing.

## Evidence

- Measurements: B38 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 17.
- Plan: [../plans/p3c-move-along-path.md](../plans/p3c-move-along-path.md).
