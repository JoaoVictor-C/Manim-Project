# P15 — Incremental code layers: cheaper renders, chapters, declared layers

- **Status:** Done
- **Date:** 2026-10-25
- **Decided in:** a Terza session (4 rounds, balanced) plus measurements; see Evidence
- **ADR:** [0061 — Incremental code layers](../adr/0061-incremental-code-layers.md)

## Goal

**Done when** editing one phase of a long scene re-renders that phase only, editing a comment or the
spacing re-renders nothing, every render is cheaper than before, and the user can move code into its own
layer in one step. Every split is **proved** against the full render before it is kept.

## Evidence (what decided the design)

Profiles of the real render path (1280x720, 30 fps) on the 7-section video:

| scene | frames | Cairo drawing | frame storage | updaters (Python) |
|---|---|---|---|---|
| hook | 806 | 18% | 22% | 15% |
| conservation | 1179 | 9.5% | 11% | 47% (DecimalNumber rebuilds its MathTex each frame) |
| momentum | 1466 | 4.8% | 8.6% | 63% |

Consequences: drawing is cheap and logic is expensive, so skipping drawing (tile caches, content digests,
per-play memoisation) saves at most 13-40%. Real savings need the unaffected part's **logic** skipped, which
means rendering it separately. Splitting by object (alpha layers) was judged unsound or empty by the critique
(depth interleaving, coupled run_times, shared trackers; every scene in the corpus shares trackers or beats).
Splitting by **time** (chapters) is sound and cheap: the segments are concatenated, not composited.

## Not attempted (and why)

- Raster tile caching, content-digest replay, Manim CE's per-play cache: measured not worth, or unstable.
- Restoring a saved scene state mid-scene: closures and updater state cannot be serialised; a long-lived process
  breaks ADR 0019's single-use, killable model.
- Automatic split by object (name strands): the gate was "at least 3 of 8 corpus scenes yield two strands of at
  least 25% each once time is factored out"; the hand estimate is zero, so it is not built. Two simultaneous
  independent objects are handled by the declared route (**New layer from selection**).
- Memoising Text/MathTex construction: copying large objects is itself slow; needs a benchmark first.

## Design

### 1. Cheaper renders (every scene)

- **Overlap storage with drawing.** `CacheWriter.add` copies the cropped bytes in the render thread
  (Manim redraws into the same array) and compresses them in a small bounded thread pool (`zlib` releases the
  GIL); `finish` waits for the pool. The stored bytes are identical.
- **Comment- and spacing-insensitive key.** The cache key uses `render_hash(code)`: the Python token stream
  without comments, blank lines and inline spacing; strings and docstrings are kept (a scene can read
  them). The trust store keeps using `code_hash`, so trust is unchanged. Old cache entries are orphaned
  (their keys change once) and evicted by the existing size rule.

### 2. Probes: facts the runner records while it renders

The runner traces the lines of `construct` that start a top-level statement. At each statement boundary it
records `{stmt, frame, scene time, survivors digest, updater count}`, where the survivors digest covers every
mobject alive in the scene (points, fill/stroke colours and opacities, widths, z-index, updater counts) and
which of them are visible. The probes are stored in the cache entry (`index.json`, key `probes`), so they are a
by-product of the render the user already paid for.

### 3. Chapters

`core/code/scene_analysis.py` reads the code (AST) and the probes and finds **cut points**: a boundary `k` is a valid
cut when all hold.

1. **Visible state is back to the baseline:** the visible survivors at `k` have the same digest as at the end of
   the prelude (the statements before the first frame is emitted: backdrop, ground line, constants).
2. **Nothing alive can reach the visible state:** every survivor that is invisible (a `ValueTracker`, an empty
   `Mobject` carrying an updater) is either in the baseline or its updaters' closures reference no visible
   survivor.
3. **No later statement needs an earlier chapter's names:** the names that statements after `k` read, written
   by statements between the prelude and `k`, must be empty; otherwise the chapters merge.
4. **No Python-level state is carried:** statements before `k` that mutate a prelude container
   (`d[k] = v`, `.append`, `.update`, augmented assignment on a subscript or attribute) merge the chapters.

A chapter's code is the original source with the other chapters' statements removed (the module level and the
prelude are kept, comments inside kept statements survive). Its job starts at **frame `n_k`** (`start_frame` on
the job), the scene clock starting at `n_k / fps` so `self.time` and `at(self, i)`-style helpers behave as they
did. Its cache key includes the start frame.

### 4. The split command (always verified)

*Code page > Editor menu > Split into chapters...* shows the proposed chapters with their frame range and the
reason for every merge, then, on OK:

1. replaces the layer by one code layer per chapter (one undo step), each with `lifetime.in` at its start and
   `lifetime.out` at the next chapter's start (so a held last frame never overdraws the next chapter);
2. renders them (the render service already runs two at a time);
3. **verifies**: every frame of the full render is compared with the frame of the chapter that covers it
   (crops equal, pixel for pixel; a tolerance of 0);
4. on any mismatch the split is **undone automatically** and the message says which frame differs.

### 5. Declared layers: New layer from selection

*Editor menu > Move selection to a new layer*: the selected top-level statements of `construct` move into a new
code layer (a copy of the scene with only those statements and the prelude). The command warns about names the
selection reads that the rest defines (and the reverse) and refuses when it cannot keep the code valid
(`ast.parse` on both results). No render check is made: the user declared the independence; the two layers
are plain code layers that cache separately.

### 6. The analysis report

*Editor menu > Analyse scene...* is read-only: it lists the statements with the names they define and read, the
probed boundaries, which are cut points and why the others are not, and the estimated gain (frames per chapter
over total frames).

## Steps

| step | content | acceptance |
|---|---|---|
| P15.0 | this plan, ADR 0061 | written |
| P15.1 | `render_hash`; threaded `CacheWriter`; code key uses it | stored frames identical to the sequential writer; comment/spacing edits keep the key; strings and docstrings change it; trust unchanged |
| P15.2 | runner probes and `start_frame`; probes in the cache entry | a probe run of a small scene reports boundaries and digests; a job with `start_frame` starts the clock there |
| P15.3 | `scene_analysis` (static + probes), the report | chapters found on synthetic scenes (a phase scene, a persistent-HUD scene, a shared-name scene, a mutated-container scene); cuts refused with reasons |
| P15.4 | `scene_split`: slicing, the edit, the verifier; split command and automatic undo | a 3-chapter scene rendered whole and by chapters is frame-identical; a deliberately coupled scene is refused or verified-and-undone |
| P15.5 | New layer from selection | statements move; warnings for crossing names; both results parse |
| P15.6 | UI: Editor menu entries, report dialog, progress/verify messages; docs, changelog, shortcuts | UI tests; guide updated |

## Results

Built as designed, with three corrections the checks forced:

- **The scene clock must be exact.** A chapter starts at the whole scene's clock value to the last bit
  (`start_time`), not `frame / fps`: a wait computed from it can round to a different number of frames.
- **Waits are drawn differently with and without a time-based updater**, so a chapter must be in the same mode
  as the whole scene was (a hidden tracker left running from an earlier chapter changed the frame count of a
  later wait by 3 frames). The probe records it (`updating`).
- **Names are not enough.** A tracker made in the setup, kept moving by its updater during an earlier chapter
  and used by a later one only through a closure, made a chapter draw differently. The probe records each
  variable's state and the analyser requires everything a later statement depends on, through the setup's own
  definitions, to be as the setup left it.

All three were found by the frame-by-frame comparison against real scenes, not by thinking: that comparison is
why the split is never trusted on analysis alone.

Measured (corpus of the 7-section video, 320x180; every proposed split verified pixel-identical): recap 3
chapters (largest 80%), inertia 3 (64%), conservation 3 (75%), momentum 3 (52%), torque 2 (98%), hook 2 (96%);
angular refused. At 1280x720 the probes cost about 1% of a render and the writing pool saves 34% (hook) and
16% (conservation). Tests: 70 new, among them real renders of a scene whole and in chapters.

## Risks

- **Nondeterminism** (unseeded `random`, clocks): chapters differ from the full render, and verification
  catches it and undoes the split.
- **Probe cost**: a digest per statement boundary; measured on the corpus (target under 2% of a render).
- **Cut table needs one render:** chapters can be proposed only after the scene has rendered once with this
  version of the runner; the report says so.
- **Cache orphaning** from the new key: a one-time re-render of existing projects.

## Tests

Pure-core tests for `render_hash`, the threaded writer, the analyser and the slicing; one slow end-to-end test
that renders a three-phase scene whole and as chapters through `render_code` and compares every frame; a UI
test for the Editor menu entries with a fake render service.
