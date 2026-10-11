# 0033. Simulated layers: traced paths and plugin simulations

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** João Victor

## Context

Manim's updaters draw things that depend on what happened before: a
`TracedPath` behind a moving dot, a pendulum stepped by `dt`. The editor's
frame is a pure function of the project and the time (ADR 0002) and is asked
for in any order (scrubbing, render-ahead, ADR 0028). Code layers (ADR 0019)
run such scenes but cannot be edited visually or traced.

## Decision

- **Two simulated layer kinds.** A built-in **TracedPath** layer follows a
  point of another layer (a plain object, a child object such as a Point on
  Axes, a part, or a simulation; never another trace): params `target`,
  `offset` (in the target's units) and `dissipate` (seconds, 0 = keep
  everything); its stroke is the layer's style. Plugins add **simulations**:
  `register(Simulation(name, start, step, draw, point=None, params, section,
  label))` with `start(params) -> state`, `step(state, dt, params) -> state`,
  `draw(state, params) -> VMobject` and `point(state, params) -> (x, y)` (what a
  trace follows; default: the drawing's centre).
- **The fps grid is the clock.** Both advance once per canvas frame with
  `dt = 1/fps` from the layer's first grid frame, as Manim's updaters do; a time
  between frames shows the last frame's state. Simulation drawings are not
  re-centred.
- **A trace** is the polyline through the target's point on every grid frame
  from its first frame to the current one (plus the live point between frames).
  Frames where the target is not drawn add no point and break the line.
  `dissipate` keeps the last `round(D × fps)` frames. Within one `play()` this
  is exactly Manim's TracedPath; Manim also adds a corner at the end of each
  `play()` ([deviations](../deviations.md)).
- **Replay from checkpoints.** Each process caches trace points and simulation
  states (a state every 30 frames and the latest one; states are deep-copied
  before stepping), keyed by what they are computed from: the layer's spec, fps,
  first frame and the layers the target is evaluated from. Sampling evaluates
  the target at earlier times in its own drawing buffers, always ending at the
  frame's time, so a target already drawn in the frame keeps that frame's state
  (the session planned a sampling pass before drawing; it proved redundant).
  Render-ahead drops a trace's frames when its target changes.
- **No clips** on simulated layers: lifetime and keyed transform and opacity
  only. Python exports with simulated layers are exact (ADR 0031). Simulations
  get the first-use determinism check of ADR 0032; load refuses a trace of a
  trace or of a missing layer.

## Consequences

- Traces and simulations change with the frame rate, as in Manim.
- The first look at a late frame replays from the start once (300 frames ≈
  50 ms); afterwards random access costs at most 29 simulation steps.
- Connectors (lines between objects) and value readouts are not covered yet.

## Evidence

- Probe: B46 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 25.
- Plan: [../plans/p4c-simulated-layers.md](../plans/p4c-simulated-layers.md).
