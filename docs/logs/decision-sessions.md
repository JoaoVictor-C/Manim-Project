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

## Session 3 — Test-suite expansion priorities · 2026-10-09

- **Tool / profile:** Terza, `fast`; 3 iterations, 2 passes, halted on
  `halt_signal`, confidence **0.91**.
- **Input:** coverage report (77 %, 846 statements), five suspected defects from
  code reading (D1–D5), the 20 s suite budget.
- **Decision:** defects first, each proven by a failing test before the fix,
  then the uncovered modules, then a bounded property harness.
- **Critiques that changed the plan:** a crash not on the suspect list — any clip
  after a morph on the same lane (reproduced: `ValueError`) → rejected by the
  schema; kind validation in the schema would import the adapter (circular,
  loads Manim) → kind metadata moved into `schema.CLIP_KIND_INFO`; a purity test
  that passed despite D1 → rewritten against an independent reference and
  mutation-checked; rules claimed but untested → tested before continuing.
- **Outcome:** D1, D2 (image layers) and D4 (lifetime precedence) were real
  bugs, fixed; D3 and D5 were not defects (tests pass). Also found: CLI tracebacks
  on bad input, Pillow 13 incompatibility (pinned). Suite: 45 → 200 tests,
  coverage 77 % → 93 %, 11 s.

## Session 4 — S1 timeline plan · 2026-10-09

- **Tool / profile:** Terza, `balanced`; 2 iterations, halted on `halt_signal`,
  confidence **0.90**.
- **Input:** S1 scope, measured costs (B10–B11 taken for the session, B5/B6
  invalidation, Cairo draw), schema rules, ADRs 0004/0005/0008/0009.
- **Decisions:** immutable snapshots + `core/edits.py` + Qt `Document` with
  `QUndoStack` now (→ ADR 0014); clamp drag semantics with snapping; pure
  timeline geometry model + thin `QGraphicsView`; coalesced drag application;
  a new **timing** edit kind that keeps caches, with morph entries keyed by baked
  transforms (→ ADR 0013). Plan: [../plans/s1-timeline.md](../plans/s1-timeline.md).
- **Critiques that changed the plan:** an unmeasured morph drag → measured at
  94 ms (B12); the proposed half-resolution draft → measured, no help (B12),
  which led to the timing kind (B13); a reorder through start values would fool
  a naive "timing" diff → order must be unchanged; keyframed morph partners →
  transform-keyed cache measured (B14); trims of a morph clip need the canvas
  end as a bound.
- **Left open:** dragging a morph while its partner is mid-motion (~105 ms/step,
  coalesced, documented).

## Session 5 — S2 panels plan · 2026-10-09

- **Tool / profile:** Terza, `balanced`; 3 iterations, 2 passes, halted on
  `halt_signal`, confidence **0.90**.
- **Input:** S2 scope from the roadmap, measured build costs (B17, B18 taken for
  the session), edit/undo architecture (ADR 0013, 0014), allow-list (ADR 0007),
  schema rules for morphs.
- **Decisions:** a persistent build worker and warm-then-commit (→ ADR 0015);
  properties generated from a hand-curated `adapter.MOBJECT_PARAMS`, committed
  on `editingFinished`, one undo step per field; layers dock with a morph-cascade
  delete; timeline context menu for clips. Plan:
  [../plans/s2-panels.md](../plans/s2-panels.md).
- **Critiques that changed the plan:** "only the text is slow" → measured (B19):
  `font_size`/`color`/style are cache-neutral but the Text font is not, so the
  key keeps every unmeasured param; replies racing with edits and undo → pending
  changes are operations re-run on the current snapshot, latest wins; worker
  hangs and crashes → timeout, restart, startup queue; "Add MathTex layer" is not
  a field change → the gate is keyed by the specs an edit builds, not by UI
  operation; re-sending per field duplicated builds → one request per key;
  pending structural edits → re-runnable operations; a refresh would clobber a
  pending field → the panel shows pending values; large images → measured (B20),
  stay synchronous.
- **Left open:** opening a project with many unseen strings is slow once
  (synchronous, documented).

## Session 6 — S3 canvas interaction plan · 2026-10-09

- **Tool / profile:** Terza, `balanced`; 3 iterations, 2 passes, halted on
  `halt_signal`, confidence **0.90**.
- **Input:** S3 scope, measured hit-test and drag costs (B21–B22, taken for the
  session), edit kinds (ADR 0013), document undo (ADR 0014), morph hand-offs (ADR 0005).
- **Decisions:** bounding-box prefilter + Qt path fill + numpy stroke distance,
  alpha-gated, all hits front-to-back with Alt+click cycling; `frame_layers`;
  one shared `Selection`; the stopwatch rule with frame-snapped keys and ease
  inheritance; no drags during a morph; auto-repeat nudges merge into one undo
  step (→ ADR 0016). Plan: [../plans/s3-canvas.md](../plans/s3-canvas.md).
- **Critiques that changed the plan:** a proposed pure-numpy winding test was
  unmeasured and off-roadmap → Qt paths with a prefilter, measured at 0.05 ms
  median; dragging during a morph → measured lag (B23), refused; a wide text box
  hides objects behind it → Alt+click cycling; the preview time and the key time
  differed → the playhead snaps to the frame first; inheriting `there_and_back`
  would freeze a segment → measured which easings end at 1; holding an arrow
  key flooded the undo stack → auto-repeat merging; objects invisible because of
  a clip were clickable → measured, alpha gate.
- **Left open:** none structural; Qt key-event details are handled in tests.

## Session 7 — S4 export dialog plan · 2026-10-09

- **Tool / profile:** Terza, `fast`; 1 iteration, halted on `halt_signal`,
  confidence **0.90**.
- **Input:** the roadmap item, the render CLI, measured render speed and the
  corrupt output a killed render leaves (B25).
- **Decisions:** export the current snapshot through the CLI in a `QProcess`
  with `--cache-dir` and flushed `--progress json`; write a partial file and
  replace the output only when complete; non-modal dialog with progress, ETA,
  cancel and Open folder (→ ADR 0017). Plan: [../plans/s4-export.md](../plans/s4-export.md).
- **Critiques that changed the plan:** the replace fails when a player holds
  the old video → measured, retry then save as `name (2).mp4`; progress over a
  pipe is buffered → measured, every line flushed and `PYTHONUNBUFFERED=1`;
  quitting during an export → ask, then clean up.

## Session 8 — P2a transform gizmos plan · 2026-10-09

- **Tool / profile:** Terza, `fast`; 1 iteration, halted on `halt_signal`,
  confidence **0.90**.
- **Input:** the Phase 2 roadmap items, the S3 stopwatch rule (ADR 0016), the
  transform model (pivot = position), measured transform edit costs (B22, B24).
- **Decisions:** corner scale handles and a rotate knob on the oriented box,
  pivot at the layer position; all four transform properties keyable from the
  panel; auto-key with two keys on a track's first edit (→ ADR 0018). Plan:
  [../plans/p2a-gizmos.md](../plans/p2a-gizmos.md).
- **Critiques that changed the plan:** handles on the axis-aligned box drift off
  rotated shapes → oriented box; one-key auto-key animates nothing (a one-key
  track is constant, from `_sample`) → two keys from the layer's start; the
  roadmap's anchor gizmo must not silently disappear → kept as the next item,
  motivated by pendulums and clock hands.

## Session 9 — P2b keyframes and curve editor plan · 2026-10-09

- **Tool / profile:** Terza, `fast`; 1 iteration, halted on `halt_signal`,
  confidence **0.90**.
- **Input:** the P2a gap (keys exist but are invisible), the timeline's row
  model (S1), the easing model, the shared selection (S3).
- **Decisions:** merged diamonds per key time on the layer row; retime / delete /
  add on the timeline; the selection gains a key time; a key view in
  Properties; a curve editor starting from fitted beziers. Plan:
  [../plans/p2b-keyframes.md](../plans/p2b-keyframes.md).
- **Critiques that changed the plan:** diamonds overlap clip bars → press
  priority and nearest-key choice; the last key's ease does nothing → shown
  disabled; editing a named ease from a fixed default jumps the curve →
  measured fits (B27), refusal for the four eases no bezier can express.

## Session 10 — P2c part layers plan · 2026-10-09

- **Tool / profile:** Terza, `balanced`; 3 iterations, 2 passes, halted on
  `halt_signal`, confidence **0.90**.
- **Input:** ADR 0012 (proposed), the evaluator's per-layer checkpoints, the
  build worker's warm keys (ADR 0015), measurement B28.
- **Decisions:** part layers keyed by `{tex, occurrence}`, resolved to one exact
  span marked by the adapter; one marked build per root, drawn and animated;
  subtree checkpoints keyed by finished clips, each layer drawing its own
  glyphs; root-first selection on the canvas with double-click drill-in
  (→ ADR 0012 accepted). Plan: [../plans/p2c-part-layers.md](../plans/p2c-part-layers.md).
- **Critiques that changed the plan:** `substrings_to_isolate` marks every
  occurrence, so adding a part could silently retarget another and a short key
  breaks LaTeX inside scripts → measured custom span markers, which mark only
  the chosen span and nest; markers might change Write's frames → measured
  identical mid-animation; a span right after `^` fails → measured, auto-brace
  one-token spans; a count-only retarget warning misses swaps → compare the
  span's text and neighbours too; after Split terms the root would be
  unreachable on the canvas → root-first click, double-click to drill in.

## Session 11 — P2d code layers plan · 2026-10-09

- **Tool / profile:** Terza, `balanced`; 3 iterations, 2 passes, halted on
  `halt_signal`, confidence **0.90**.
- **Input:** the agreed escape hatch (code layers), the build worker and export
  process designs (ADR 0015, 0017), measurement B30.
- **Decisions:** code in `Spec(type="Code")`; rendering only in single-use warm
  spare processes; cropped premultiplied zlib frames in the editor's cache
  dir; Cairo compositing; hash-based trust with a prompt on open (→ ADR 0019).
  Plan: [../plans/p2d-code-layers.md](../plans/p2d-code-layers.md).
- **Critiques that changed the plan:** a cold process per render → measured
  6.6-8.7 s to the first frame, almost all Manim's import → warm single-use
  spares (isolation kept); "trusted because typed this session" misses undo,
  paste and shared files → trust by hash at render time; unbounded cache →
  size cap with the open project's keys kept; the renderer assumes mobjects →
  a `CodeFrame` mobject; several layers queued behind one spare → up to two
  spares; export could run untrusted code → `--trust-code` only when all
  layers are trusted.

## Session 12 — P2e TransformMatchingTex plan · 2026-10-10

- **Tool / profile:** Terza, `fast`; 2 iterations, 2 passes, halted on
  `halt_signal`, confidence **0.90**.
- **Input:** ADR 0005 (morph hand-offs), ADR 0012 (part trees; v1 refused
  morphs on them), measurement B33.
- **Decisions:** a keyed TransformMatchingTex (part TeX where it matches on
  both sides, glyph shape otherwise); morphs on and into part trees; a bake key
  with finished-clip orders (→ ADR 0020). Plan:
  [../plans/p2e-matching-tex.md](../plans/p2e-matching-tex.md).
- **Critiques that changed the plan:** the morph cache keyed only by transforms
  would reuse a stale morph after a timing edit → finished-clip order in the
  key; a clip on a part after its root's morph starts is invisible → refused;
  a part with no counterpart would fade whole although its glyphs exist on the
  other side → unmatched parts dissolve into shape-keyed glyphs; unequal
  duplicate groups were unmeasured → measured exact.

## Session 13 — P2f anchor (pivot) gizmo plan · 2026-10-10

- **Tool / profile:** Terza, `fast`; 2 iterations, 1 pass, halted on
  `max_loops`, confidence **0.82** (the one open question — how the cross's
  grab is guarded — was settled in the coda).
- **Input:** ADR 0012 (part pivots), ADR 0016/0018 (gizmos, auto-key), the
  numeric probe that became B34, a read of `MoveTool.press` and the evaluator.
- **Decisions:** a base-only `Transform2D.anchor`; compensation of the base
  position and a rigid shift of position keys; a crosshair-first gizmo with
  snapping and a centring double-click; additive format (→ ADR 0021). Plan:
  [../plans/p2f-anchor-gizmo.md](../plans/p2f-anchor-gizmo.md).
- **Critiques that changed the plan:** the cross would steal the whole body of
  a small object → grab only when the box's longer side is ≥ 36 px (a
  both-sides rule was refuted: it blocks a vertical line, the pendulum case);
  resetting a code layer's anchor to (0, 0) puts the pivot at the canvas origin
  → double-click centres on the drawing; `layer_transform` rebuilds transforms
  from the four keyable properties and would drop the anchor → carry it; the
  scale/rotate drags take their pivot from `layer_frame` → it returns the world
  pivot; keyed positions with any ease stay exact under a rigid shift
  (confirmed); keyed rotation does not (measured, warned).
- **Reversed in implementation:** the session's answer to "crosshair-first or
  body-first with a modifier" was crosshair-first. Four existing acceptance
  tests then failed because they drag a new object by its middle — where its
  cross is — so the anchor now moves with **Ctrl+drag** (Shift snaps), and the
  36 px guard was dropped.
