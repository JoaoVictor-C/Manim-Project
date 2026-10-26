# P3b — Axes and function graphs: implementation plan

- **Status:** ✅ Done (2026-10-10) — `tests/acceptance/test_acceptance_p3b.py`
- **Date:** 2026-10-10
- **Decided in:** [decision session 16](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.82)
- **Evidence:** benchmark B37 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0024 — Child objects: axes and graphs](../adr/0024-axes-and-graphs.md)

## Goal

Plot functions and animate them. **Done when** you can add Axes from the
library, add the graph of `sin(x)` to them, draw it with Create, turn it into
`x**2/10 - 1` with Transform, and it scrubs exactly as it plays and exports
exactly as the editor shows it.

## Model

- A second kind of **child layer**: `parent_id` and its **own spec** (no part
  key), under a root whose type accepts it — `CHILD_TYPES = {"Axes": {"Graph"}}`.
  `Layer.is_part` now means *has a part key*; `is_child` means *has a parent*.
- The part rules (no clip overlapping an ancestor's clip, parts cannot morph,
  parents are MathTex/Tex) apply to parts only. Other children: the parent's
  type must accept the child's type.
- Children are drawn right after their root, carried by the root's transform,
  live within its lifetime and are removed with it (existing mechanisms).
- **Graphs are locked to their axes**: position, scale, rotation and anchor stay
  at their defaults and only opacity can be keyed. `keyable_props(layer)` drives
  the load-time check, the Properties stopwatches and the timeline's *Add key*
  menu. Moving, scaling or rotating a selected graph on the canvas acts on its
  axes. (Shifting a graph is a change of its function; a free offset would plot
  `f` against the wrong ticks.)

## Graph

- Spec params: `expression` (validated on load by a whitelist compiler on
  Python's `ast`: numbers, `x`, `pi`, `e`, `+ - * / **`, unary signs, `sin cos
  tan exp log sqrt abs` — never `eval`), `x_min`, `x_max` (default: the axes' x
  range); stroke colour and width through the style.
- Built by `adapter.build_child(axes spec, graph spec)`, cached on both. 400
  samples over the range; where values are not finite or lie beyond the y range
  plus 50 %, the curve is split, each finite run plotted on the built axes and
  added as its own subpath (B37: `log`/`sqrt` leave half the points NaN, `tan`
  and `1/x` reach 5.6e13). Very high frequencies are undersampled (v1 limit).

## Clips and edits

- Graphs take every vector clip kind; the random-access harness covers child
  specs (an Axes parent). Create and graph-to-graph Transform are exact (B37).
- A graph may morph into any layer but a part or a code layer, as a world-space
  hand-off; the morph cache key includes the root's transform.
- Clips on the axes animate the axes only (v1).
- Editing the axes' spec re-plots its graphs: they are classified as `spec` edits.
- Axes with number labels are text-bearing: the build worker warms them first
  (7.6 s cold, 31 ms warm).

## UI

- A *Graphing* section in the library with **Axes**.
- The Parts button offers **Add graph...** on axes.
- Properties for a graph: expression, x from/to, stroke colour/width, opacity.
- A click selects the axes; a double-click drills to a graph.

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P3b.1 | expressions, schema child layers, `keyable_props`, adapter build, harness | expression tests (values, rejections); schema rules; graphs vs hand-built Manim; split runs; harness over child specs |
| P3b.2 | evaluator: children in `frame_layers`, root affine, morph key, edit kinds, warm gate; locked gestures | frames vs Manim with a moved/scaled axes; scrub = play; axes edit re-plots; canvas drag on a graph moves the axes |
| P3b.3 | library, Add graph, Properties, acceptance, ADR 0024, docs | the Goal's scenario through the UI, export = editor |

## Outcome

Done on 2026-10-10, with one change found by looking at the rendered example:
the planned 50 % margin beyond the y range let `tan(x)` spill far outside the
axes. Runs now end exactly where the curve leaves the y range or its domain
(30 bisection steps between the last drawable sample and the next), so curves
stop at the axes' edge and `sqrt` starts at 0. Axes print whole-number ranges
and steps as integers (`1`, not `1.0`). `examples/graphs.json` shows axes with
numbers, a sine drawn and turned into a parabola, and `tan(x)` split at its poles.
