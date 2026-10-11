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

## Session 14 — P2g more clip kinds plan · 2026-10-10

- **Tool / profile:** Terza, `fast`; 2 iterations, 1 pass, halted on
  `max_loops`, confidence **0.84**, no open critical item.
- **Input:** ADR 0007 (allow-list), ADR 0012 (part trees), measurement B35,
  a read of the evaluator's checkpoints and tree clips.
- **Decisions:** nine new kinds and params on three existing ones; four
  rejected with measured reasons; overlay clips; `only_types`; a clip-param
  registry; a Succession patch (→ ADR 0022). Plan:
  [../plans/p2g-clip-kinds.md](../plans/p2g-clip-kinds.md).
- **Critiques that changed the plan:** overlay clips would checkpoint the
  overlay instead of the object → checkpoint the object; images were never
  measured → measured (SpiralIn is vector only, the overlays work); strict
  param validation would reject documented hand-written kwargs → a direction
  is a name or a vector, unregistered keys pass through; changing a kind kept
  params the new kind rejects → dropped; an overlay on a root whose glyphs all
  belong to parts would vanish → members with an overlay are drawn; type
  restrictions only in the menus → validated on load like `vector_only`.

## Session 15 — P3a viewport zoom/pan plan · 2026-10-10

- **Tool / profile:** Terza, `fast`; 2 iterations, 1 pass, halted on
  `max_loops`, confidence **0.83**, no open critical item.
- **Input:** ADR 0016 (canvas geometry), measurement B36, a read of the canvas,
  MoveTool and the window's shortcuts.
- **Decisions:** a Fit mode plus an absolute scale and centre; a camera
  re-framed over the whole widget with a dimmed pasteboard; Ctrl+wheel zoom
  about the cursor, wheel and middle-drag pan, Ctrl+0/Ctrl+1 (→ ADR 0023). Plan:
  [../plans/p3a-viewport.md](../plans/p3a-viewport.md).
- **Critiques that changed the plan:** zoom relative to Fit would turn an
  explicit 100 % into 87 % after a resize → absolute scale with a Fit mode;
  Space+drag pan would toggle playback → middle-drag; a wheel during a drag
  would make the dragged object jump → view changes wait for the drag to end;
  the dimming as one fill with a hole → four rectangles.

## Session 16 — P3b axes and function graphs plan · 2026-10-10

- **Tool / profile:** Terza, `fast`; 2 iterations, 1 pass, halted on
  `max_loops`, confidence **0.82**; the last question (do clips on the axes
  animate their graphs?) was decided in the synthesis: no, in v1.
- **Input:** ADR 0005, 0007, 0012, 0015, 0022; measurement B37; a read of the
  schema's tree rules, `frame_layers`, `move_layer`, `remove_layer` and the
  timeline's key menu.
- **Decisions:** child layers with their own spec under accepting roots;
  graphs locked to their axes; a whitelist expression compiler; curves split
  at bad values; numbered axes warmed (→ ADR 0024). Plan:
  [../plans/p3b-graphs.md](../plans/p3b-graphs.md).
- **Critiques that changed the plan:** the part rules (no overlap with an
  ancestor's clip, no morphs) would forbid the plan's own acceptance scenario →
  parts only; a graph with a free transform would plot `f` against the wrong
  ticks → locked; the timeline's key menu could create tracks the schema
  refuses → one `keyable_props` for schema and UI; the harness only built root
  specs → extended to child specs; an axes edit left graph morph caches stale →
  children classified `spec`.

## Session 17 — P3c MoveAlongPath plan · 2026-10-10

- **Tool / profile:** Terza, `fast`; 2 iterations, 1 pass, halted on
  `max_loops`, confidence **0.80**; the last question (refuse or explain a drag
  the path fully compensates) was decided in the synthesis: explain.
- **Input:** ADR 0005, 0013, 0022, 0024; measurement B38; a read of
  `remove_layer` and the checkpoint keys.
- **Decisions:** Manim semantics in the mover's local frame with the path
  layer's rest shape mapped in at clip start; signature-keyed caches; roots
  only; an arc-length table patch (→ ADR 0025). Plan:
  [../plans/p3c-move-along-path.md](../plans/p3c-move-along-path.md).
- **Critiques that changed the plan:** checkpoints keyed by (layer, clip)
  would go stale when the path layer moves → keyed by path signatures, also in
  the idle precompute and morph bake keys; parts (tree clips) and locked graphs
  as movers → roots only; deleting the path layer → its clips are dropped; the
  harness had only one layer → a two-layer case; reading the path's animated
  state would let layers recurse → rest shape only; an un-keyed drag after the
  run would silently do nothing → a status hint.

## Session 18 — P3d curved position paths plan · 2026-10-10

- **Tool / profile:** Terza, `fast`; 2 iterations, 1 pass, halted on
  `max_loops`, confidence **0.84**; the last question (show the motion path
  always or on demand) was decided in the synthesis: always for the selected
  layer, hidden while playing.
- **Input:** ADR 0016, 0018, 0021, 0023; measurement B39; a read of the
  key-rebuilding edits and the Easing validator.
- **Decisions:** optional tangents on position keys; arc-length walking;
  linear formula kept for straight segments; a canvas motion-path overlay;
  de Casteljau split on insert (→ ADR 0026). Plan:
  [../plans/p3d-curved-paths.md](../plans/p3d-curved-paths.md).
- **Critiques that changed the plan:** overshooting eases had no meaning on a
  curve → continue along the end tangent; mirrored handle lengths forced
  symmetric keys → align direction, keep length; inserting a key keeps the
  shape but not the timing → stated; the edits rebuilt keys and would drop
  tangents → copied; key squares over the object's middle → harmless, same edit.

## Session 19 — P3e SVG import plan · 2026-10-10

- **Tool / profile:** Terza, `fast`; 2 iterations, 2 passes, halted on
  `halt_signal`, confidence **0.90**.
- **Input:** ADR 0019, 0022, 0025; measurement B40; a probe of the failures
  (missing, malformed, empty SVG; missing image); a read of the evaluator's
  base, checkpoint and path caches.
- **Decisions:** an `SVGMobject` layer (path, height), file colours kept with
  style overrides; a media signature (mtime, size) in the build cache and the
  evaluator; checks on load, on application activation and from a menu; one
  builder draws a placeholder for missing, unreadable, broken or empty media so
  the export agrees; MoveAlongPath follows an SVG's longest path; absolute paths
  in v1; SVG elements as parts later (→ ADR 0027). Plan:
  [../plans/p3e-svg.md](../plans/p3e-svg.md).
- **Critiques that changed the plan:** a missing image already broke frames, not
  loads → the builder makes the placeholder, shared with the export; a new base
  alone would leave checkpoints from the old drawing → a changed file is a spec
  edit of its layer and path signatures include it; a paused canvas would never
  notice a save in another program → check on activation (watchers break on
  atomic saves); a stat before every frame scales with media layers → dropped;
  the first path of a logo may be a dot → the longest path.

## Session 20 — P3f render-ahead cache plan · 2026-10-10

- **Tool / profile:** Terza, `fast`; 2 iterations, 2 passes, halted on
  `halt_signal`, confidence **0.90**.
- **Input:** ADR 0009, 0013, 0015, 0019, 0023, 0027; measurement B41 and a
  single-object evaluation probe; a read of the canvas render path, the build
  worker client and the code cache.
- **Decisions:** a long-lived preview render process with its own evaluator;
  frames on the fps grid, playback quantised to it; one shared preview camera so
  cached frames equal live ones; zlib frames in a 512 MB store evicting far from
  the playhead; invalidation by diffing projects (closure of changed layers,
  their old and new lifetimes); overlays from `Evaluator.object_frame`; live
  rendering when a frame is not cached (→ ADR 0028). Plan:
  [../plans/p3f-render-ahead.md](../plans/p3f-render-ahead.md).
- **Critiques that changed the plan:** two camera constructions could differ →
  one shared function, device pixels; media changes are not project diffs → a
  media message; hiding the outline while playing (and rendering live when
  paused with a selection) would keep scrubbing slow → evaluate the selected
  object alone (measured ~3 ms); a view change is not an edit → frames carry
  their view; code renders finishing → invalidate that layer; two timing rules
  in one playback → always quantise.

## Session 21 — P3g child objects in the tree, turning along a path · 2026-10-10

- **Tool / profile:** Terza, `fast`; 2 iterations, 2 passes, halted on
  `halt_signal`, confidence **0.90**.
- **Input:** ADR 0012, 0020, 0024, 0025; a read of the tree and morph code; the
  example projects' clip overlaps (none); a probe showing MoveAlongPath on an
  equation with a part crashes on master.
- **Decisions:** child objects join their root's tree (root clips animate the
  whole figure); member morphs inside trees; the overlap rule extended; path
  clips supported on tree roots; build keys include children; `rotate` =
  `no` | `along`, relative to the clip's start (→ ADR 0029). Plan:
  [../plans/p3g-child-trees.md](../plans/p3g-child-trees.md).
- **Critiques that changed the plan:** tree animations had no path target (a
  crash today) → passed, with path signatures in tree keys; a graph edit would
  not rebuild the group → children in the root's build key; a moved path would
  leave a later graph morph where it was → path signatures in member morph
  ends; the old child drawing path would drift → removed; an absolute rotation
  would jump at the clip start → relative.

## Session 22 — P3h objects on axes · 2026-10-10

- **Tool / profile:** Terza, `fast`; 2 iterations, 2 passes, halted on
  `halt_signal`, confidence **0.90**.
- **Input:** ADR 0024, 0029; measurement B42; a read of Manim's `get_area`,
  `get_riemann_rectangles` and `get_graph_label`.
- **Decisions:** Point, Area, RiemannRectangles, AxisLabels, GraphLabel as
  locked child objects built with Manim's helpers; a `graph` parameter kind
  for sibling references, validated, cascaded on delete, classified on edit;
  clamped function attributes on graphs; own graph-label placement; label
  types not offered as paths (→ ADR 0030). Plan:
  [../plans/p3h-axes-objects.md](../plans/p3h-axes-objects.md).
- **Critiques that changed the plan:** `get_graph_label` moves labels onto
  Manim's default screen, not the project's → own placement; an area's spec
  does not change when its graph does → classified changed, build keys include
  the graph; text glyphs as paths → excluded.

## Session 23 — P4a Python export · 2026-10-10

- **Tool / profile:** Terza, `fast`; 2 iterations, 2 passes, halted on
  `halt_signal`, confidence **0.90**.
- **Input:** ADR 0010; probes B43 (both forms rendered by Manim); a list of the
  editor's semantic differences from plain Manim code.
- **Decisions:** whole-project choice between readable and exact; the readable
  subset; code shape (variables, z_index, clusters, waits, morph replacement,
  fresh path shapes); helpers for clamped eases, Wiggle's pivot and Bézier
  eases; deterministic text checked by compile; exact form through a package
  `StudioScene` (→ ADR 0031). Plan:
  [../plans/p4a-python-export.md](../plans/p4a-python-export.md).
- **Critiques that changed the plan:** the adapter's clamped eases and pinned
  Wiggle are not plain Manim → helpers; a later-added object would draw on top
  → z_index per layer; a morph target with its own lifetime could be in the
  scene before the morph → exact; missing media would raise in plain Manim →
  exact; the text must be deterministic → snapshot test too.

## Session 24 — P4b plugin API · 2026-10-11

- **Tool / profile:** Terza, `fast`; 1 iteration, 1 pass, halted on
  `halt_signal`, confidence **0.90**.
- **Input:** the adapter's registries, the processes that build objects, ADR
  0015, 0019, 0027, 0031; probe B45.
- **Decisions:** a public `manim_studio.plugins` module (`ObjectType`,
  `register`); loading at the end of `core.adapter` (entry points, then plugin
  folders); no prompt (installed code); vector objects only; a lazy determinism
  check; placeholders for failures and missing types; warm keys for slow types;
  plugin objects make Python exports exact (→ ADR 0032). Plan:
  [../plans/p4b-plugins.md](../plans/p4b-plugins.md).
- **Critiques that changed the plan:** a circular import if plugins load
  before the adapter is complete → load at its end, lazy imports; random
  builds would break caches and render-ahead → checked at first use; the test
  suite would load the developer's own plugins → conftest points at an empty
  folder.

## Session 25 — P4c simulated layers · 2026-10-11

- **Tool / profile:** Terza, `fast`; 2 iterations, 2 passes, halted on
  `halt_signal`, confidence **0.90**.
- **Input:** the evaluator's caches and shared frame buffers, frame_cache's
  closure, ADR 0002, 0019, 0028, 0031, 0032; probe B46 (plus a single-play
  measurement run during the session: 30/30 frames equal).
- **Decisions:** a built-in TracedPath layer and plugin simulations
  (`Simulation(start, step, draw, point)`); the fps grid as clock (dt = 1/fps);
  a trace is the polyline through the target's point on every frame so far,
  broken where the target is not drawn; per-process caches keyed by what they
  are computed from, simulation states every 30 frames; trace points sampled
  before drawing; no clips on simulated layers; exact Python export
  (-> ADR 0033). Plan: [../plans/p4c-simulated-layers.md](../plans/p4c-simulated-layers.md).
- **Critiques that changed the plan:** traces must follow child objects (a Point
  on Axes) and simulations, not only plain objects -> a traced-point rule per
  kind and `Simulation.point`; a cache key without the trace's own offset would
  reuse stale points; numpy simulations mutate their state in place -> deep
  copies before stepping; frames where the target is absent -> no point, the
  line breaks; the dependency signature must follow everything the target is
  evaluated from (keyed axes move a Point).

## Session 26 — P4d audio track · 2026-10-11

- **Tool / profile:** Terza, `fast`; 2 iterations, 2 passes, halted on
  `halt_signal`, confidence **0.91**.
- **Input:** the playback loop, the export encoder, frame_cache's project
  diff, ADR 0027, 0028, 0031; probe B47 (plus two measurements run during the
  session: AAC round-trip alignment, the sink clock's step size).
- **Decisions:** audio clips as a project-level list; one pure mix module for
  playback, export and exact scenes; the sound card's played time as the
  playback clock when there is audio (the wall clock otherwise); AAC in the
  export; one timeline row per clip with a waveform; readable `add_sound` only
  for plain clips; audio edits drop no frame (-> ADR 0034). Plan:
  [../plans/p4d-audio.md](../plans/p4d-audio.md).
- **Critiques that changed the plan:** decoded audio is large (384 KB/s) -> a
  bounded cache, peaks kept apart; decoding on Play would stall -> decode at
  import and load; tests and headless machines have no sound -> an off switch
  and a fallback to the wall clock; a step clock would stutter -> measured: it
  advances every 10 ms; a song longer than the scene cannot be a plain
  `add_sound` -> exact.

## Session 27 — Phases 5 and 6 · 2026-10-11

- **Tool / profile:** Terza, `fast`; 2 iterations, 1 pass, halted on `halt_signal`, confidence
  **0.90**.
- **Input:** the user's direction (built-ins first, then a studio-like UI with presets, handles and
  Resolve-like pages); the pain points of the 95 s explainer; the main window's structure; a count
  made during the session (39 of 51 UI test files drive the main window directly).
- **Decisions:** Phase 5 = subtitles, readouts and connectors, markers and snapping, clipboard and
  autosave, presets and templates; Phase 6 = design system (look only), workspace pages over one
  app controller with a compatibility layer, canvas interaction (handles, guides, multi-select),
  polish and the visual-bug sweep, release preparation. Plan:
  [../plans/phases-5-6.md](../plans/phases-5-6.md).
- **Critiques that changed the plan:** editing essentials were missing (duplicate, copy, paste,
  autosave) -> P5d; multi-select is slice-sized and belongs with canvas interaction -> P6c; the
  design system must not touch layout so pages are built once; the page refactor must keep the
  window's attributes for the existing UI tests; "handlers" is an interpretation to confirm.

