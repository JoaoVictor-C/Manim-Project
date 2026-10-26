# 0061. Incremental code layers: cheaper renders, chapters, and layers you declare

- **Status:** Accepted
- **Date:** 2026-10-25
- **Deciders:** João Victor

## Context

A code layer is one `Scene` (ADR 0019). Any edit to its code re-ran the whole scene, which for the 7-section
explainer meant 25 to 170 s per scene at full size. Other layers were already independent.

Measured on the real render path (1280x720, 30 fps): Cairo drawing is 5-18% of a render, frame storage 9-22%,
and the rest is Python reconstructing objects in updaters (15-63%). So skipping the drawing of unchanged
objects (tile caches, content digests, Manim's per-play cache) saves at most 13-40%; real savings need the
unaffected part's logic skipped, which means rendering it separately. A Terza session (four rounds) and the
prior art (marimo's cell DAG, Salsa's red-green early cutoff, ManimGL checkpoints, Manim CE's per-play cache)
agreed on the rest of the shape: splitting by object is unsound or empty in practice (depth interleaving,
coupled run times, shared trackers); splitting by **time** is sound, because the pieces are concatenated, not
composited.

## Decision

- **Cheaper renders for every scene.** `CacheWriter` copies each frame's cropped bytes in the render thread
  (Manim redraws into the same array) and compresses them in a small bounded pool (`zlib` releases the GIL);
  the stored files are byte-identical. The cache key uses `render_hash(code)`, the token stream without
  comments, blank lines, spacing and indent width (strings and docstrings stay); the trust store keeps
  `code_hash`. Existing cache entries are orphaned once.
- **Probes.** While rendering, the runner watches the line events of `construct` (`sys.monitoring`, no cost
  elsewhere) and records, before each top-level statement, the frame and clock, digests of everything alive
  and of what is visible, the camera, updater counts, whether a hidden object's updater reaches a visible one,
  whether Manim will draw waits as real frames (a time-based updater exists), and a digest per local variable
  that holds mobjects. They are stored in the cache entry: a by-product of the render already paid for.
- **Chapters** (`core/scene_analysis.py`). A cut before statement *k* is valid when the visible picture,
  camera, visible updaters and wait mode equal what they were right after the setup (the statements before the
  first frame); no hidden updater reaches the visible picture; no later statement needs - by name, through the
  setup's closures, or by the state the setup's own variables are in - something an earlier chapter defined or
  changed; and no earlier statement changed the scene itself. A chapter is the setup plus its own statements,
  cut from the original source by line range, run from the whole scene's frame **and exact clock value**
  (`start_frame`, `start_time` on the job and in the layer's params; the clock adds up frame by frame, so
  `frame / fps` is not it to the last bit and `at(self, i)`-style waits can round the other way).
- **Split is proved, not trusted** (`Editor > Split into chapters`). The layer is replaced by one layer per
  chapter (one undo step; each ends where the next starts), they render, and every frame of the full render
  is compared pixel for pixel with the chapter that covers it, in a background thread. Any difference, a
  chapter that does not render, or a different frame count undoes the split automatically and says which frame
  differs. Analysis proposes; the comparison decides.
- **Declared independence** (`Editor > Move selection to a new layer`): the selected top-level statements get
  a copy of the layer of their own; names that cross the two programs are warned about. No comparison: the user
  stated the independence.
- **Analyse scene** is read-only and explains every boundary that is not a cut point.

## Consequences

- On the 7-section corpus (320x180 for speed) six scenes split and every proposed split verified identical
  (recap 3 chapters, inertia 3, torque 2, conservation 3, momentum 3, hook 2); angular was refused. Editing
  one chapter re-renders 52-80% in the four scenes with real phases, and the report says when a split saves
  little (hook and torque: 96-98%).
- Full-size measurements: probes cost about 1% of a render; the writing pool saves 34% (hook) and 16%
  (conservation).
- A chapter needs a first render with this runner (the cut table is recorded by it); until then Analyse says
  so. Nondeterministic code (unseeded `random`, clocks) is refused by the comparison, not by the analyser.
- The static half is conservative on purpose (any mention of a setup object by an earlier chapter counts as
  changing it); it can refuse cuts that would be sound. The comparison is what makes a wrong *accept* harmless.

## Alternatives considered

- **Per-object raster tiles / content digests / Manim's per-play cache:** at most 13-40% saved by the measured
  shares, and Manim's own hashing is unstable (ManimCommunity/manim#4896).
- **Restoring a saved scene state mid-scene (ManimGL checkpoints):** closures and updater state cannot be
  serialised, and a long-lived process breaks ADR 0019's single-use, killable model.
- **Automatic split by object (name strands, alpha layers):** the gate (three of eight scenes yielding two
  strands of at least 25% once time is factored out) was estimated at zero; not built. Simultaneous independent
  objects use the declared route.
- **Memoising Text/MathTex construction:** copying large objects is itself slow; needs a benchmark first.

## Evidence

- Plan and measurements: [../plans/p15-incremental-code-layers.md](../plans/p15-incremental-code-layers.md)
- Tests: `tests/core/test_render_hash.py`, `tests/core/test_scene_analysis.py`, `tests/core/test_scene_split.py`,
  `tests/test_scene_chapters.py` (real Manim: whole and chapters, frame-identical), `tests/ui/test_chapters_ui.py`
- Source: [scene_probe.py](../../src/manim_studio/scene_probe.py),
  [scene_analysis.py](../../src/manim_studio/core/scene_analysis.py),
  [scene_split.py](../../src/manim_studio/core/scene_split.py),
  [chapters.py](../../src/manim_studio/ui/chapters.py)
