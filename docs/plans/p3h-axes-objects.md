# P3h — Points, areas, rectangles and labels on axes

- **Status:** Done
- **Date:** 2026-10-10
- **Decided in:** [decision session 22](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** benchmark B42 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0030 — Points, areas, rectangles and labels on axes](../adr/0030-objects-on-axes.md)

## Goal

**Done when** you can add a point, the area under a graph, Riemann rectangles,
axis labels and a graph label to axes from the Parts menu, draw them on, and
the export matches the editor.

## Types (children of `Axes`, locked: opacity only)

| type | params | built with |
|---|---|---|
| `Point` | `x`, `y` (axes units), `radius` | `Dot(axes.c2p(x, y))` |
| `Area` | `graph`, `x_range`, `bounded_graph` (optional) | `axes.get_area` |
| `RiemannRectangles` | `graph`, `x_range`, `dx`, `sample` (left/right/center) | `axes.get_riemann_rectangles` |
| `AxisLabels` | `x_label`, `y_label` (TeX) | `axes.get_axis_labels` |
| `GraphLabel` | `graph`, `label` (TeX), `x`, `direction` | `MathTex` `next_to` the graph's point at `x` |

- Param kind **`graph`**: the id of a sibling `Graph` (validated on load;
  `bounded_graph` may be empty).
- `build_child(parent, spec, graphs)` receives the referenced graph specs;
  its cache key and the child's `_builds` entry include them.
- Graph builds carry `underlying_function` (clamped into the y range, 0 where
  undefined), `function` (x → point) and `t_min`/`t_max`.
- `remove_layer` on a graph also removes the children naming it; `classify`
  marks those children changed when the graph's spec changes.
- Warm keys: the labels' TeX. `path_layers` excludes the label types.

## UI

- **Parts > Add to axes**: Graph..., Point, Area, Riemann rectangles, Axis
  labels, Graph label (graph-referencing items use the first graph; disabled
  without one).
- Properties: the params, with a choice of sibling graphs for `graph` params.

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P3h.1 | types, graph refs, validation, cascade, function attributes, warm keys | each type equals Manim's helper on the same axes; scrub = play; refs validated; delete cascades in one undo step; editing a graph rebuilds its area |
| P3h.2 | Parts > Add to axes, Properties graph choice | add each from the menu; change an area's graph |
| P3h.3 | acceptance, docs | the Goal's scenario through the editor, export = editor |
