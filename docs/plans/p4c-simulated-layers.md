# P4c — Simulated layers: traced paths and plugin simulations

- **Status:** In progress
- **Date:** 2026-10-11
- **Decided in:** [decision session 25](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** B46 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0033 — Simulated layers](../adr/0033-simulated-layers.md)

## Goal

**Done when** a dot moving along a graph on axes leaves a trace, a plugin
pendulum simulation swings and its bob is traced, and both scrub in any order
equal to playing them, render ahead equal to live frames, and export to a video
and to an exact Python scene that match the editor.

## Schema (`core/schema.py`)

- `TRACE_TYPES = {"TracedPath"}`; a TracedPath is a root with params `target`
  (a layer id, required), `offset` (x, y; default 0, 0) and `dissipate` (seconds,
  0 = keep everything).
- Validation: the target exists and is not a TracedPath or a code layer; a
  TracedPath has no clips.
- Param kind `layer` for object params (a layer chooser in Properties).

## Plugins (`plugins.py`)

- `Simulation(name, start, step, draw, point=None, params=(), section="Plugins",
  label=None)` registered with `register`; `SIMULATIONS` by name.

## Adapter

- `TracedPath` params and library entry (section *Simulation*, "Traced path");
  `allowed_clip_kinds` is empty for traces and simulations.
- `build_mobject` of a simulation: the drawing of its start state, styled, not
  re-centred. `build_problem` of a simulation: first-use determinism check (start
  and three steps run twice, drawings compared) and its exceptions.
- `trace_mobject(runs)`: a VMobject through runs of world points (a new
  sub-path per run; a one-point run is a zero-length line, as in Manim).

## Evaluator

- Simulated layers (traces, simulations) are drawn by `_simulated_at` instead
  of clips: the local drawing, then the layer's keyed transform and opacity.
- Simulations: `first = ceil(start × fps)`, frame `k = frame_index(t)`, state
  `k - first`; states kept every 30 steps and the latest (deep copies); keyed
  by `(spec, fps, first)`. A step that raises → placeholder, reason in
  `build_errors`.
- Traces: points per grid frame from `first` to `k`, `None` where the target
  is not drawn; cached per layer, keyed by `(spec, fps, first, signature of the
  layers the target is evaluated from)`; dissipate keeps the last
  `round(D × fps)` frames; off the grid the live point is added.
- Traced point: a simulation's `point(state)` (default: drawing centre) + offset
  through its world transform; a plain root's clip-state centre + offset through
  its world transform; a part or child object: its drawing's world centre +
  offset through its world transform.
- Sampling ends at the frame's own time, so the target's buffers end in the frame's state
  (a sampling pass before drawing was planned and proved redundant: mutation-checked).
- `frame_cache._closure` adds traces of changed layers; `remove_layer` deletes
  traces of a deleted layer.
- Python export: traces and simulations make it exact.

## UI

- Library *Simulation > Traced path* traces the selected object (refused with a
  message when nothing is selected); simulations appear under their section.
- Properties: the target chooser (layers that can be traced), offset, dissipate.
- The timeline's Add clip menu is empty for simulated layers, with a note.
- `examples/plugins/swinging_pendulum.py` (a damped pendulum, RK4).

## Steps

| step | content | acceptance |
|---|---|---|
| P4c.1 | schema, Simulation API, adapter, evaluator (replay, traces, sampling order, signatures), closure, remove cascade, export | random access = sequential for traces of a root, a Point on Axes, a part and a simulation; Manim's TracedPath on one play matches; buffers stay valid; signatures re-key only on relevant edits |
| P4c.2 | library, Properties target chooser, clip menu note, example simulation | trace a selected object from the library; edit its target and dissipate |
| P4c.3 | acceptance, docs | the Goal's scenario with the real worker, preview and export processes |
