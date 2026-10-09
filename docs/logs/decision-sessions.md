# Decision sessions log

Record of structured reasoning sessions (Terza MCP: generate → critique →
synthesise loops) that produced or changed decisions. Append-only, newest last.
Each session lists what was decided, what evidence it rested on, and what it
left open, so ADRs can cite it.

---

## Session 1 — Overall architecture · 2026-10-09

- **Tool / profile:** Terza, `deep`; 4 iterations, halted on `ewma_ungrounded`
  (too many claims about Manim internals were from memory), confidence **0.77**.
- **Question:** design a desktop app that uses Manim as its engine but animates
  visually like Premiere/After Effects, starting from an empty folder, solo dev.
- **Paths considered:** JSON document + code generation; embedded Manim with
  random-access evaluation; web UI + Python geometry server.
- **Outcome:** "After Effects-lite over Manim" — JSON document as source of
  truth, an evaluator that owns Manim's clock with checkpoints, one clip lane per
  layer with motion as keyframes, world-space morph hand-offs, layer tree with
  part layers, one-way Python export.
- **Critiques that changed the design:** overlapping clips on one object have no
  meaning in Manim (→ ADR 0004); keyframes applied after a Transform pull it off
  target (→ ADR 0005); history-dependent objects break random access (→ updaters
  deferred); sub-object animation and Axes+graph need a layer tree (→ ADR 0012).
- **Left open:** hide vs. replay non-random-access animations; Manim details
  stated from memory (fill rule, line width, tex isolation).
- **Follow-up:** Manim 0.22 source read to confirm `play()` = begin/interpolate/finish,
  Cairo `fill_preserve` with default (winding) rule, line width `× 0.01`.
  Phase 0 prototype built; 35 tests written.

## Session 2 — Preview renderer, unsafe animations, build order · 2026-10-09

- **Tool / profile:** Terza, `balanced`; 3 iterations, 2 passes, halted on
  `halt_signal`, confidence **0.92**.
- **Input:** measured evidence only (benchmarks B1, B2, test results, the Wiggle
  defect). The critic required every load-bearing premise to be measured; the
  missing measurements (B3–B8) were taken during the session.
- **Decisions:**
  - Preview content via Manim's Cairo camera; Qt only for overlays (→ ADR 0006).
  - Allow-list keyed by (kind, type, params) + adapter patches; replay only for
    future simulated layers (→ ADR 0007).
  - Edit classes and incremental invalidation (→ ADR 0008), implemented and
    tested during the session.
  - Frame-dropping playback, idle checkpoints on the UI thread, `gc.freeze()`
    (→ ADR 0009), justified by B7/B8.
  - Build order S0 previewer → S1 timeline → S2 panels → S3 canvas interaction
    → S4 export dialog ([../roadmap.md](../roadmap.md)).
- **Left open:** ImageMobject in `qt_paths`; GC attribution based on 3 runs;
  projects heavier than the stress scene.
