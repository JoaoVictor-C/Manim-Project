# 0036. Value readouts and connectors

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** João Victor

## Context

Manim videos often show a number that changes (a `ValueTracker` driving a
`DecimalNumber`) and lines that stay attached to moving objects
(`always_redraw`). The explainer faked a changing slope readout with five
morphing formulas.

## Decision

- **Number.** A Number object is Manim's `DecimalNumber`: value, decimal places,
  a suffix (a LaTeX unit such as `\,\text{m/s}`), font size, and whether to show a
  `+` sign. Its value changes with a new clip kind, **ChangeDecimalToValue**
  (Manim's own animation; param: the new value; Number only), so counting gets
  easing, checkpoints and random access from the clip machinery (ADR 0002, 0007):
  one animation interpolated in any order equals fresh ones (B49). A label in front
  of a number is a separate MathTex layer; the number keeps its left edge in place
  as it changes width. The build worker compiles a Number's digits ahead (ADR
  0015): the first build costs 1.35 s, later values 3.5 ms.
- **Connector.** A Connector layer draws a line or an arrow between two layers'
  points (the traced point of ADR 0033, with offsets), redrawn every frame. Its ends
  stop where the line between the two points leaves each target's bounding box, plus
  a gap (`ends: edges`, the default), or run between the points themselves
  (`ends: centres`). Tips: none, at the end, at both ends. Like a trace it has no
  clips (fade it with opacity keys); it cannot join itself, a trace, another
  connector or a code layer; it is deleted with either target; render-ahead redraws
  it when a target changes.
- **Python export.** Numbers and their clips are plain Manim in readable exports. A
  connector with `centres` ends, no offsets and two plain objects is written as
  `always_redraw(lambda: Line(a.get_center(), b.get_center(), buff=gap))` (or
  `Arrow`); any other connector makes the export exact.

## Consequences

- A connector cannot be drawn in with a clip.
- A number and its label move independently (key both, or multi-select them later).

## Evidence

- Probe: B49 in [../logs/benchmarks.md](../logs/benchmarks.md) and a check during
  the design session (random access of ChangeDecimalToValue, fixed left edge).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 29.
- Plan: [../plans/p5b-readouts.md](../plans/p5b-readouts.md).
