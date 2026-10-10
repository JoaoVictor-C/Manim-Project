# 0031. Python export: readable when it can be, exact otherwise

- **Status:** Accepted
- **Date:** 2026-10-10
- **Deciders:** João Victor
- **Implements:** [0010](0010-python-round-trip-is-export-only.md)

## Context

ADR 0010 promised a one-way export to Manim code: readable `self.play` code
where the timeline allows, else a scene that loads the project through this
package. The editor's model differs from plain Manim code in places (clips act
on an object before its transform, keyframes, morph hand-offs, parts, child
objects, code layers, a few random-access patches).

## Decision

- **Whole project, one form.** A project is exported as readable code only when
  every layer fits the readable subset; otherwise as the exact scene, whose
  header says why.
- **Readable subset:** objects without parts or child objects, no code layers,
  no keyframes; layers with clips are not rotated or scaled (moving and fading
  are fine); MoveAlongPath does not turn along its path; no object appears or
  disappears in the middle of overlapping clips; morph targets have no set
  lifetime; no missing media.
- **Readable code** builds each layer as a variable, keeps the layer order with
  `z_index`, plays overlapping clips together (`AnimationGroup` of
  `Succession(Wait, …)`), waits in gaps, and adds three small helpers where the
  editor differs from plain Manim (eases kept within their end states, Wiggle's
  fixed pivot, Bézier eases). The text is deterministic and compiled before it
  is written.
- **Exact scene:** the project embedded in the file, Manim configured from the
  canvas, and a `StudioScene` from this package that draws the evaluator's frame
  at each frame time, code layers included.
- File → Export Python… and `manim-studio python PROJECT OUT.py`.

## Consequences

- Readable files need only Manim; exact files need Manim Studio installed (and
  the code cache for code layers).
- One keyframed layer makes the whole file exact; the header explains it.

## Evidence

- Probes: B43 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 23.
- Plan: [../plans/p4a-python-export.md](../plans/p4a-python-export.md).
