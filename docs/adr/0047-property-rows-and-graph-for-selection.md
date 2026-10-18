# 0047. Property rows on the timeline; the graph shows the chosen properties

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** João Victor
- **Amends:** [0041](0041-workspace-pages.md) (the Animate page)

## Context

The user found the Animate page confusing (decision session 43): the graph editor overlaid five
value ranges (Position x, Position y, Scale, Rotation, Opacity, switched by checkboxes) above a
timeline that already shows one key diamond per object row, so keys appeared twice and nothing said
how to add, ease or delete a key of one property. After Effects twirls a layer down into property
rows with a stopwatch each and shows the graph only for the properties picked; Unity's Animation
window lists properties beside a dope sheet, with a Record button and a curves toggle. A separate
dope sheet here would show every key twice again; one time axis is the point.

## Decision

- **Property rows.** An object's timeline row expands - the arrow by its name, or Alt+click on the
  name - into one row per property it can key (`schema.keyable_props`: position, scale, rotation,
  opacity; a locked child, ADR 0024, opacity only). A property row shows its name, its value at the
  playhead (`format_value`: x, y; scale; degrees; percent), a diamond that adds a key there holding
  the value played (or removes the key on that frame), and that property's keys on the shared time
  axis. Its keys are selected, dragged (`edits.retime_keys(..., props=[prop])`: only that track's
  neighbours bound the move, with the timeline's snapping), deleted (`edits.remove_keys(...,
  props=[prop])`) and eased (right-click: the eases and "Edit curve...", or Properties' key section,
  which a click on the key opens) one property at a time, each one undo step. The object's own row
  and its single diamond per time behave as before.
- **Editor state.** Which rows are expanded, and which properties are chosen, live in the
  `TimelineView` (per layer id), not in the project; opening a project collapses everything.
  Collapsed, the timeline is exactly what it was; the names column widens from 140 to 200 px only
  while a row is expanded, for the values.
- **The graph shows the chosen properties.** A click on a property row's name (or its empty space)
  chooses it for the graph and selects its object (Shift/Ctrl add or take out; a property of
  another object starts over). The graph editor draws the curves of the chosen properties only, or
  every property the object may key when none is chosen; the five checkboxes go, and the bar names
  the curves shown in their colours and says how to choose.
- **Record and A.** The Animate page's bar has a Record toggle with a red dot, which is Edit >
  Auto-key (each follows the other), and A frames every key shown, anywhere on the page.
- **Linear rebuilds.** Rows are laid out once per snapshot and expanded set (`TimelineView.layout`,
  bisection for hit tests); property row bands are painted for the rows in view
  (`drawBackground`), not added as items; a visible timeline rebuilds into a new `QGraphicsScene`,
  because clearing the same scene got slower with every rebuild (B68).

## Consequences

- Keying, retiming, easing and deleting one property no longer needs the graph; the graph is for
  shaping values, focused on what was chosen.
- Every place that turned a height into a row now goes through `TimelineView.locate`, so rows of
  different heights are possible (the subtitles and sounds move down under expanded rows).
- Property values are shown, not yet typed in the row (Properties' key section edits them).
- A timeline hidden while edited (another page) still clears its one scene; only visible rebuilds
  swap scenes.

## Alternatives considered

- **A dope sheet under the timeline** - every key twice, the confusion reported.
- **Keep the legend and add property rows** - two ways to pick curves that can disagree.
- **Expanded state in the project** - it is how one looks at the scene, not the scene; it would
  dirty the file on every twirl.
- **A fixed 200 px names column** - shifts the time axis of every existing scene and test for a
  feature most rows do not use.

## Evidence

- Tests: `tests/ui/test_property_rows.py` (real mouse events), `tests/ui/test_acceptance_p7_3.py`
  (add, move, ease and delete one property in the real window, one undo step each; Record; A),
  `tests/ui/test_animate_page.py::test_the_graph_shows_the_properties_chosen_on_the_timeline`,
  `tests/ui/test_long_scene_scaling.py` (scans constant with every row expanded; a new scene per
  rebuild).
- Benchmark: [B68](../logs/benchmarks.md) - sync with every row expanded 2.4 / 5.4 / 18.8 ms at
  45 / 99 / 297 layers (731 ms at 297 before the bands and the scene swap).
- Decision: [decision session 43](../logs/decision-sessions.md), [P7 plan](../plans/p7-studio-workflow.md).
