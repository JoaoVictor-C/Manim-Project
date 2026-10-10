# 0030. Points, areas, rectangles and labels on axes

- **Status:** Accepted
- **Date:** 2026-10-10
- **Deciders:** João Victor
- **Extends:** [0024](0024-axes-and-graphs.md), [0029](0029-child-objects-in-the-tree.md)

## Context

Axes could only hold graphs. Calculus and plotting videos also need points,
the area under a curve, Riemann rectangles and labels.

## Decision

- Five more child types of `Axes`, built with Manim's own Axes helpers on the
  editor's axes and graphs: **Point** (x, y), **Area** (under a graph, or
  between two), **RiemannRectangles**, **AxisLabels** and **GraphLabel**.
  Like graphs they are locked to their axes (only opacity animates) and live in
  the axes' tree.
- Area, rectangles and graph labels name a sibling graph (a `graph` parameter).
  The reference must be a graph on the same axes. Deleting the graph deletes
  what refers to it; editing it rebuilds them.
- Graphs carry the function Manim's helpers read; where a function is undefined
  or leaves the axes it counts as clamped to their range (0 where undefined).
- A graph label sits next to its graph's point in a chosen direction - not moved
  onto Manim's default screen - so its place depends only on the project.
- Labels are TeX, warmed by the build worker. They are not offered as paths to
  move along.

## Consequences

- Areas and rectangles follow their graph's formula; a morphing graph's area
  keeps the shape of the graph's formula, not its animated state.
- Over a function's gap an area runs along the axes' edge or y = 0.

## Evidence

- Measurements: B42 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 22.
- Plan: [../plans/p3h-axes-objects.md](../plans/p3h-axes-objects.md).
