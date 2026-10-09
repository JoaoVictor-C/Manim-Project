# 0019. Code layers

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

The editor owns Manim's clock (ADR 0002): a frame is a pure function of
(project, t). Much of what Manim users write cannot be expressed that way —
updaters, `ValueTracker`, `TracedPath`, `always_redraw` — because each frame
depends on the frames before it. Chasing full GUI parity is not realistic; the
editor needs an escape hatch that still composites with visual layers.

## Decision

- A **code layer** is a root layer with `Spec(type="Code", params={"code": ...})`
  holding one `Scene` subclass. It has no clips, parts or morphs; its lifetime,
  transform, keyframes and opacity apply.
- Real Manim plays the scene once, sequentially, into a **frame cache**; the
  editor maps `t` to a cached frame (`floor((t - start) * fps)`, last frame held).
  Random access therefore holds for code layers too, once rendered.
- Code runs **only in separate, single-use processes**: warm spares that have
  imported Manim in advance (a cold start costs 6.6–8.7 s to the first frame,
  a warm one ~0.9 s, B30). Never in the editor process.
- Frames are cropped, premultiplied RGBA, zlib-compressed, in the editor's
  cache dir, keyed by the code and the project's pixel size, fps and frame
  height; evicted by size. They are painted with Cairo between capture runs
  (no measurable cost, B30), which also applies the layer transform and opacity.
- **Trust:** opening a project never runs its code silently. Code runs only if
  its sha256 is in the user's trusted store; code applied in the editor is
  trusted; opening a project with untrusted code asks once; export passes
  `--trust-code` only when every code layer is trusted.

## Consequences

- Code layers are raster at the project's resolution: zooming the canvas
  scales pixels, not vectors.
- Code layers cannot interact with other layers (no morphing into them, no
  parts) — they are opaque.
- Non-deterministic code (clock, unseeded randomness) can differ between a
  cached render and a re-render after eviction.
- A camera moved inside the code does not line up with the editor's units.

## Evidence

- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 11.
- Measurements: B30 in [../logs/benchmarks.md](../logs/benchmarks.md).
- Plan: [../plans/p2d-code-layers.md](../plans/p2d-code-layers.md).
