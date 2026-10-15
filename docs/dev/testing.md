# Testing

```bash
uv run pytest                 # everything, in parallel (up to 8 workers)
uv run pytest -m "not slow"   # the quick loop: no real subprocesses (~30 s)
uv run pytest -n 0 -s tests/core/test_edits.py   # one worker: for pdb, print, -s
```

The suite runs in parallel by default (`pytest-xdist`, `--dist=worksteal`,
see `addopts` in `pyproject.toml`). Each worker gets its own Manim cache under
`.cache/test-workers/<worker>`, seeded with the shared cache's compiled LaTeX
and text, so workers never write the same file at once. Tests marked **`slow`**
start real processes — the build worker, the renderer, the code runner — and
pay Manim's import (5-8 s here) each time; skip them while iterating.

`conftest.py` puts Manim back on the shared cache after every test: CLI tests
point it at their own folder, and leaving it there made every later LaTeX build
compile from scratch (that alone cost a minute, B32).

No module may move Manim's cache when it is imported: every test fails with
"a module imported by the tests moved Manim's cache" if one does. A benchmark
imported by a test once did, so parallel workers shared one folder and broke
each other's LaTeX files and export snapshots (intermittent failures in
`test_export_job` and `test_worker_process`). Benchmarks configure Manim in
their `main()`.

In tests marked `ui`, an exception raised inside a Qt slot (a menu action, a
timer, a signal handler) fails the test: Qt only prints such exceptions, so a
broken handler used to pass unnoticed.

## Layout

```
tests/
├── conftest.py        Manim cache + LaTeX setup, session `qt_app`, auto-skip of `latex`
├── support.py         shared constants (CANVAS, SQUARE, TEXT, …) and frame helpers
├── test_logging.py    logging setup (ADR 0011)
├── core/
│   ├── test_random_access.py   frames == Manim's sequential loop, incl. extreme easings
│   ├── test_properties.py      random projects: order independence, invalidation
│   ├── test_images.py          ImageMobject layers vs an independent reference
│   ├── test_invalidation.py    edit classes (ADR 0008)
│   ├── test_lifetime.py        visibility rules
│   ├── test_edits.py           edit API, edit kinds, structural edits through the evaluator
│   ├── test_warm.py            warm keys and the warm gate (ADR 0015)
│   ├── test_schema.py          validation rules, JSON round trip, examples
│   ├── test_adapter.py         registry parity, builders, clamping, patches
│   ├── test_registry.py        object library: every type builds, every exposed param has an effect
│   ├── test_easing.py          cubic-bezier vs CSS reference, keyframe sampling
│   └── test_transforms.py      numpy transforms == Manim methods
├── render/            Qt paths vs Cairo; video export and CLI
└── ui/                editor: load/save, errors, wall-clock playback, stepping;
                       document/undo, timeline, build service (fake worker),
                       worker process (stand-in programs + the real worker)
```

Coverage: `uv run pytest --cov=manim_studio --cov-report=term-missing`
(93 % at the last count; the full suite takes 75-100 s in parallel, most of it real
subprocesses — the build worker and the renderer — and LaTeX).

`ui/test_acceptance_p2a.py`, `ui/test_acceptance_p2b.py` and
`ui/test_acceptance_p2c.py` are the Phase 2 acceptance tests (scale/rotate and
auto-key; keyframes on the timeline and the curve editor; terms of an equation
as part layers, with the exported video checked against hand-built Manim).
`ui/test_acceptance_p4a.py` exports a project built in the editor with File >
Export Python... both ways (readable, then exact after a key is set) and renders
each file with `manim render` against the editor's frames;
`core/test_python_export.py` checks the reasons for the exact form, a text
snapshot (`golden_readable_export.txt` - regenerate it when the output changes
on purpose), the code-frame painter, and renders both forms.
`ui/test_acceptance_p3h.py` builds the area under sin(x), rectangles and labels
through Parts > Add to axes and checks them against Manim's helpers (scrub =
play, export = editor); `core/test_axes_objects.py` renders every type against
the helper, checks references, cascades, rebuilds, NaN-free areas and warm keys.
`ui/test_acceptance_p3g.py` draws and indicates axes with a graph from the
timeline and rides a triangle along the graph with Turn: along (scrub = play,
export = editor); `core/test_child_trees.py` compares figure clips with Manim
animating `VGroup(axes, graph)`, and covers graph morphs, paths and rebuilds in
the tree; `core/test_rotate_along.py` the turning (one turn per circle, clamped
overshoot, scrub = play).
`ui/test_acceptance_p3f.py` opens the stress scene with the real preview
process, waits for every frame, then checks playback shows kept frames equal
to live ones, an edit to a late layer keeps the early frames and a zoom
refills; `ui/test_render_ahead.py` drives the same wiring with an in-process
stand-in, `ui/test_preview_process.py` the process itself (bit-exact frames,
generations, views, restart), `core/test_frame_cache.py` the spans (checked
exhaustively against rendered frames) and the store. Tests run with
`MANIM_STUDIO_PREVIEW=0` unless they opt in.
Tests never load the developer's plugins: conftest points
`MANIM_STUDIO_PLUGINS` at an empty folder before the adapter is imported.
`core/test_plugins.py` registers types directly and loads plugin folders and
fake entry points (load order, a broken file, a name clash), and covers the
build checks (VMobject, determinism, failures, missing plugins), the clip
harness on a plugin object, warm keys and the exact Python export;
`ui/test_plugins_ui.py` the library, Properties, *Help > Plugins...* and the
messages. `ui/test_acceptance_p4b.py` copies `examples/plugins/pendulum.py`
into a plugin folder and runs the editor with its real build worker and
preview process: the pendulum is added, edited, drawn on, rendered ahead,
exported to video and to an exact Python scene rendered by `manim render`, all
matching the editor.
`core/test_subtitles.py` covers the cue lane, the file format, subtitle edits
(no frame dropped, other edits keep them), placing a new cue, `.srt` reading
(byte-order mark, CRLF, missing indices, dot milliseconds, tags, overlaps) and
writing, wrapping and shrinking, lines growing upwards, drawing over the layers
without being a layer, fades, random access, render-ahead spans, the export's
burned-in frames and `.srt`, and both Python forms (`manim render` writes the
same `.srt`). `ui/test_subtitles_ui.py` covers Add Subtitle, Properties, `.srt`
import and export, moving, trimming and deleting on the row, and the canvas.
`ui/test_acceptance_p5a.py` imports an `.srt`, edits a cue and the style, checks
frames rendered ahead, the export process's video and `.srt`, and the exact
Python scene.
`ui/test_theme.py` measures the contrast of every text role and clip label,
checks the WCAG formula, the tokens, that the stylesheet raises no Qt warnings,
Fusion, the palette and the font, every icon (drawn, tinted, dimmed when
disabled), the icon buttons, that no colour literal remains in `ui/` outside
`theme.py`, and that document colours are drawn as saved. The tests' application
fixture applies the theme, so every UI test runs under the real look.
The Animate page (P6b.2) has three test files:
- `ui/test_graph_model.py` tests the graph editor's Qt-free rules: curves, including
  opacity only for a graph on axes; ranges; the value window; frame-all; hits; the drag
  rule (one track, its neighbours, snapping, never back to its own time, clamped and
  rounded values); added keys that keep the motion; the props filter. It also checks the
  segment-walk sampler against `evaluator._sample` on random tracks with every ease and
  curved path segments.
- `ui/test_animate_page.py` drives the page through the real window. It covers the
  layout and Shift+2, the legend, the selection shared with Properties and the timeline,
  drags in time and value as one undo step, frozen ranges, Escape, Shift and Alt, a key
  grabbed off-centre, double-click, Delete, the ease menu and the curve editor, zoom, pan,
  scrubbing and reset.
- `ui/test_acceptance_p6b2.py` auto-keys a move, edits it in the graph, checks the
  canvas pixels at the playhead and undoes it all.

`.cache/p6b2/mutate.py` mutates the guards; all 38 mutants are killed.
`ui/test_code_syntax.py` checks the Code page's lexer (keywords, Manim names, definitions, numbers,
prefixed and triple quoted strings over lines, comments; spans never overlap or raise on any text)
and its drafts (kept only while they differ from the project, the project moving underneath,
error line helpers), neither needing Qt. `ui/test_code_page.py` drives the page through the real
`MainWindow`: the layer list and selection, the editor's keys, Run (one undo step, trust, none for
unchanged text), drafts across layer, page and project switches, Revert, the project changing under a
dirty editor, and injected render statuses with a clickable error line (code layers are not rendered
there). `ui/test_acceptance_p6b3.py` repeats it with the real code runner: a typo is run, the
NameError shows at line 4, a click puts the cursor there, the fix runs and the green square appears
on the canvas. Type a new line with `QTest.keyClick(Key_Return)`: `keyClicks` of a newline character
crashes the offscreen platform.
`ui/test_param_handles.py` and `ui/test_snap_guides.py` cover the pure geometry
of parameter handles (placement on the built drawing, delta/ratio/point drags,
limits, Shift steps and 45-degree line turns, an arrow's gap, connector ends) and
of snapping (targets, nearest line, masked axes, guide spans);
`core/test_set_params.py` the edit and its rigid shift. `ui/test_param_handles_ui.py`
drags handles with real events (turned scaled objects, a line's other end staying,
Escape, undo, small objects, connectors) and snaps moves and handles (Alt, the View
toggle, nothing snaps to itself or what follows it); `ui/test_acceptance_p6c.py`
drags every handle type on a turned, scaled object and checks it lands under the
cursor. Exact-move tests set `move_tool.snapping = False`.
`ui/test_arrange.py` covers align (each line, one object to the frame) and distribute
(equal gaps, the outermost kept, three or more); `ui/test_selection.py` the several-layer
selection (primary last, toggling, dropping deleted ones); `ui/test_multiselect_ui.py`
Shift+click, the marquee, Ctrl+click in Layers, group drags and nudges (keyed layers keyed,
a part with its object moved once, corners not grabbed), Delete, the clipboard, presets,
themes and Arrange; `ui/test_acceptance_p6c.py` does all of it on three objects, one undo
step each.
`ui/test_shortcuts_help.py` covers the shortcut rows (menu paths, panel actions once,
the search) and F1; `ui/test_layout_checks.py` runs the layout checks over every page
and the dialogs at 1024x640 - menu items with tooltips (`SELF_EXPLANATORY` and
`DATA_MENUS` are the allowlists), nothing below its minimum size hint (`SQUEEZABLE`), no
clipped non-wrapping label (eliding labels are skipped) - and checks that the checks
catch a cramped label, a squeezed button and a bare menu item. A new page or dialog
should be added to it. `ui/test_elided_label.py` covers the eliding label.
The presets browser (P6d.3) has three test files. `render/test_preset_thumbs.py` tests the
Qt-free helper: the run's length and the eight frame times, the small project a preset is
drawn from, every built-in preset's frames (eight, 160x90, moving, never blank), entrances
growing from nothing and exits going to it, the colours and the square's size, and the cache
(drawn once, keyed by content and background). `ui/test_presets_browser.py` tests the filter,
the target line and the badge, then the dialog through the real `MainWindow`: tabs, search,
tooltips, the still, hover playing frame by frame with real mouse events, applying (button,
double-click, Enter, one undo step, two selected layers, whole-or-refused, refusals on the
status line), the timeline row's menu (that layer and time only), saved and overriding user
presets, a preset a square cannot show, and the dialog being kept between openings.
`ui/test_acceptance_p6d3.py` runs the whole story: browse, search, hover, apply to two layers,
undo and redo, save a preset and find it marked. `QTest.mouseDClick` alone sends no
double-click to a list: click first, then double-click. `.cache/p6d3/mutate.py` mutates the
guards; every non-equivalent mutant is killed.
`core/test_library.py` applies every built-in preset to a shape (frames before
the playhead unchanged, or empty for an entrance), checks kind fallbacks, params
for the chosen kind, relative keys, the hold key, replaced same-frame keys,
refusals (no kind, a locked graph, overlaps, the end), parts, preset and theme
files (validation, skipped files, user items winning), saving and replaying a
layer's animation, themes by kind and by selection, and every built-in template
(inserted, drawn, references remapped, saved from an object, refused when tied to
outside layers). `ui/test_presets_ui.py` covers the menus, refusals, saving and
templates in the editor; `ui/test_acceptance_p5e.py` animates a scene with
presets, a theme and templates, checks frames rendered ahead, the export
process's video and the exact scene rendered by Manim.
`core/test_markers.py` covers the marker list (order, saving, validation, ids),
the one-per-frame rule, edits that keep markers and change no frame, and the
exports. `ui/test_timeline_model.py` checks that every row and marker is a snap
point and the dragged item never is, and the marker drag rule;
`ui/test_markers_ui.py` covers M, [ and ], the flags (pick, drag with snapping,
Alt, Escape, one undo step, menus, Delete), exclusive selection, the guide line
and sounds at a clip or marker; `ui/test_acceptance_p5c.py` builds a scene with
markers, drags clips and markers onto each other, adds sounds, checks frames
rendered ahead survive marker edits and saves.
`core/test_readouts.py` runs the clip harness on counting numbers (fresh,
shuffled and scrubbed frames equal Manim's play loop, with eases), chaining,
the fixed left edge and colour, the warm key's glyphs, and connectors: box-edge
and centre ends, the gap, tips and colour, moving and hidden objects, offsets
that turn, objects on axes and simulations, what may be joined, the delete
cascade, render-ahead, and the readable/exact rules, with `manim render` of a
readable count and arrow. `ui/test_readouts_ui.py` covers the library,
Properties and the timeline; `ui/test_acceptance_p5b.py` builds a count and an
arrow in the editor, renders the readable scene with Manim, then switches to
edge ends, moves an object, checks frames rendered ahead, the export process's
video and the exact scene.
`core/test_clipboard.py` covers copying and pasting layers (subtrees with parts
and axes objects, fresh ids unique across layers, sounds and subtitles, morphs
between copies or to outside layers - kept, left out when missing or taken, the
visible span kept - motion paths, traces and connectors inside and outside the
copy, type-checked outside references, names, placement), copies drawing like
their originals, the clipboard JSON (round trip, foreign text, newer versions)
and clips, sounds and subtitles (placement, overlaps, allow-list, targets,
duplicates). `core/test_recovery.py` covers recovery file names, atomic writes,
what is offered (dead owners, newer than the saved file), pruning and the
process check (psutil, OpenProcess, a fake psutil). `ui/test_clipboard_ui.py`
drives the Edit menu and its shortcuts, the real `QClipboard` (private format,
plain text), selection, one undo step, the messages and untrusted pasted code;
`ui/test_autosave.py` the timer, cleanup on save, undo, New, Open and close, and
the recovery prompt (dead or running owner, restore, later, discard, stale and
damaged copies). Conftest points `MANIM_STUDIO_RECOVERY` at a temporary folder
and answers the recovery question with "later". `ui/test_acceptance_p5d.py`
builds a scene in the editor, duplicates and pastes through the menus, checks
the copies draw like the originals, then restores a simulated crash in a fresh
window. `.cache/p5d/mutate_p5d.py` is the slice's mutation check.
`core/test_audio.py` covers the mix (trim, gain, fades, clipping, silence past
a file's end, resampling), missing and unreadable files, the decode cache, the
file format and sound edits (no frame dropped, layer edits keep the sound), the
export's AAC track (aligned to the sample, measured by cross-correlation on
beeps) and the Python export's rules, rendering both forms with `manim render`
(whose sound is 1024 samples late). `ui/test_audio_ui.py` covers importing,
the timeline rows (move, trim, delete, waveforms), Properties, missing files
and playback following the sound's clock with a fake player (the real player
is checked with silence when a sound device exists); the suite plays no sound
(`MANIM_STUDIO_AUDIO=0`). `ui/test_acceptance_p4d.py` imports, places, trims and
fades a sound, then checks the export process's video and the exact Python
scene's render against the editor's mix.
`core/test_simulated_layers.py` covers simulations (stepping from their first
frame, states kept every 30 steps, failures and impure steps) and traced paths
(the polyline through the target on every frame for plain objects, a Point on
Axes and a simulation's bob, offsets, dissipation, the live point between
frames, the target's buffers left intact, what re-samples a trace) and compares
a trace with Manim's own `TracedPath` frame by frame. `ui/test_acceptance_p4c.py`
traces a dot running along a graph and the example pendulum simulation, with
the real worker, preview and export processes and an exact Python scene.
`ui/test_acceptance_p3e.py` adds an SVG through Media > SVG, draws it on with
DrawBorderThenFill, rewrites and deletes the file (redrawn on activation,
placeholder and message) and exports; `core/test_svg.py` covers colours, the
clip harness on SVGs, every kind of unreadable file, `check_media` with
checkpoints and path followers, and the export of a missing file.
`ui/test_acceptance_p3d.py` keys a dot, smooths a key and pulls its handle on
the canvas, then checks the arc, scrubbing and the export;
`core/test_motion_paths.py` covers arc-length walking, overshoot, edits that
keep tangents and the shape-keeping split.
`ui/test_acceptance_p3c.py` runs a dot along sin(x) through the menus (centre
on the curve, scrub = play, export = editor); `core/test_paths.py` checks the
path clips against Manim's MoveAlongPath, re-runs after moving either layer,
and runs the two-layer harness.
`ui/test_acceptance_p3b.py` adds axes and two graphs through the UI, draws
one with Create and turns it into the other (scrub = play, export = editor);
`core/test_graphs.py` covers expressions, the child-object rules, plotting and
evaluation against hand-built Manim, and runs the clip harness on a graph.
`ui/test_acceptance_p3a.py` zooms into a term of a split equation with
Ctrl+wheel, scales it by a corner at 400 % and fits back (export = editor);
`ui/test_viewport.py` covers the view model and the canvas input.
`ui/test_acceptance_p2g.py` circles a term of a split equation with
Circumscribe from the timeline, recolours it and fades a title in from the left
through Properties (scrub = play, export = editor); `core/test_clip_kinds.py`
samples every registered clip param through the random-access harness and
checks Circumscribe against Manim's own Succession played forward.
`ui/test_acceptance_p2f.py` drags a line's pivot cross to its top end, keys a
swing through Properties, and checks the top stays put in every frame and in
the export; `core/test_anchor.py` checks the anchored transform against Manim.
`ui/test_acceptance_p2e.py` turns one split equation into another through the
timeline menu (scrub = play, export = editor); `core/test_matching_tex.py`
checks the keyed matching against hand-built Manim.
`ui/test_acceptance_p2d.py` puts a real code layer under an equation through
the UI (random scrubbing equals playback, export equals the editor) and checks
that a project with untrusted code runs nothing. Tests never touch your trusted
code store (`MANIM_STUDIO_TRUST_FILE` points at a temporary file) and render no
code layers unless a test opts in (`MANIM_STUDIO_CODE=0` by default).
`ui/test_curve_editor.py` rechecks every fitted ease against Manim;
`core/test_part_layers.py` checks frames of objects with parts against the same
animations played on the glyphs by hand.

`ui/test_export_dialog.py` holds the S4 acceptance test (export while editing;
the video shows the scene as it was when Export was pressed), and
`ui/test_export_job.py` runs the real renderer (progress before exit, cancel,
errors).

`ui/test_acceptance_s3.py` is the S3 acceptance test: move an object on the
canvas with real mouse events, undo, redo; then animate it with the stopwatch.

`ui/test_acceptance_s2.py` is the S2 acceptance test: File > New, add a
MathTex, type an equation, add a Write clip from the timeline menu, save and
render — through the real widgets and the real worker.

Editor windows in tests build synchronously: `conftest.py` sets
`MANIM_STUDIO_WORKER=0`. The worker's own behaviour is tested in
`ui/test_worker_process.py` (lifecycle rules with tiny stand-in programs, then
one shared real worker) and its effect on edits in `ui/test_build_service.py`
with a deterministic fake.

`render/test_options.py` covers the render options: even sizes and presets at several aspect
ratios, the frame window (rounding, clamping, empty ranges), the sound and `.srt` cut to it,
real exports (frames equal the evaluator's at `(a + k) / fps`, size, fps, crf, subtitle modes,
a sound at a known time landing 0.3 s earlier in a range from 0.3 s) and the command line with
its bad options; `ui/test_render_queue.py` the queue's state machine without Qt;
`ui/test_deliver_page.py` the Deliver page through the main window with a fake `ExportJob`
(settings, markers, snapshot-at-add, the queue's buttons, closing while it renders, the Python
preview and Save as); `ui/test_acceptance_p6b5.py` queues two exports with different sizes and
ranges, edits the project while they render, runs them through the real export process, checks
frames, size, `.srt` and burned-in subtitles of both, and saves the Python scene.

## Markers

| marker | meaning | skip with |
|---|---|---|
| `latex` | needs a LaTeX install; skipped automatically when `latex` is missing | `-m "not latex"` |
| `ui` | needs Qt; runs with `QT_QPA_PLATFORM=offscreen` | `-m "not ui"` |

## What the core tests prove

The central contract (ADR 0002): **a frame is a pure function of (project, t)
and equals Manim's own sequential play loop.** The helpers in `support.py` make
that easy to state:

- `sequential_reference(kind, spec)` — frames exactly as `Scene.play` makes them;
- `render_in_order(project, order, fresh_each_frame)` — frames from the evaluator
  in any order;
- `assert_frames_equal` / `assert_evaluators_agree` — pixel comparison with a
  tolerance of 1 level (anti-aliasing rounding).

`core/test_tables.py` and `core/test_levels.py` cover the Audio page's Qt-free logic (P6b.4):
how a cell shows a sound or a subtitle, parsing what is typed (`1,5`, `-6 dB`, `1:02.5`), the edit
each cell makes and every refusal with its reason, and the meter's 100 ms window - bit-identical to
the same span of `audio.mix` with trims, gains, fades and clipping, silent at the ends of the video
and for a missing file - with known tones reading their peak and RMS. `ui/test_audio_page.py` drives
the page through the real window (`show_page("audio")`): rows for every field, a missing file
flagged, each cell edit one undo step that the timeline, evaluator and meter follow, refused edits in
the status bar, selection both ways (a subtitle row seeks, the timeline's selection does not), the
buttons, and the meter on known tones; `ui/test_acceptance_p6b4.py` imports two sounds and an `.srt`,
edits both tables, and undoes everything.

## Property tests

`core/test_properties.py` generates valid projects from fixed seeds and checks
the two contracts every project must meet. When one fails, the message names
the seed; reproduce it with `random_project(random.Random(seed))`. If you add a
feature, extend the generator so the feature appears in generated projects —
check that it does (the generator once produced no morphs at all).

## Write the failing test first

For bugs, write the test, watch it fail for the right reason, then fix. For
tests that guard a subtle property (purity, caching), also check the test fails
against the old code — a test that passes on the bug guards nothing.

## Writing a test

- Name the ADR a test protects in its module or test docstring.
- Compare pixels, not internal state, when checking rendering behaviour.
- For any new cache or edit path: render after the edit and compare with a
  freshly built `Evaluator` (`assert_evaluators_agree`).
- Keep canvases small (`support.CANVAS` is 320×180, 15 frames) — the whole suite
  should stay under ~15 s.
- Qt tests take the session `qt_app` fixture; never create your own
  `QApplication` (Qt allows one per process).

## Benchmarks

Benchmarks are not tests: run `benchmarks/bench_preview.py` when a change touches
the per-frame path, and log results that inform a decision in
[../logs/benchmarks.md](../logs/benchmarks.md).
