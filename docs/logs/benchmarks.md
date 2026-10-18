# Benchmark log

Append-only record of performance measurements. ADRs cite entries by id (B1, B2, …).
Never edit a past entry; if a number changes, add a new entry that references the old one.

**Machine (unless noted):** Intel Core 5 210H, 16 GB RAM, RTX 4050 Laptop (unused —
Cairo is CPU), Windows 11, Python 3.13.16, Manim 0.22.0, PySide6 6.12.0.

**Stress scene** (`benchmarks/bench_preview.py::stress_project`): 20 MathTex
layers, 3 concurrent Write clips (0–3 s), 10 layers with position + rotation
keyframes, 4 s at 30 fps.

Reproduce: `uv run python benchmarks/bench_preview.py`.

---

### B1 — Evaluator cost per frame · 2026-10-09
Stress scene, 960×540, median over 40 frames.

| version | evaluate |
|---|---|
| `mobject.copy()` (deepcopy) per layer per frame | 89.9 ms |
| per-layer scratch proxy + numpy affine | **14.3 ms** |

→ ADR 0002, 0006.

### B2 — Draw cost and resolution scaling · 2026-10-09
Same frames as B1 (after the B1 fix).

| renderer, 960×540 | draw |
|---|---|
| QPainter (`render/qt_paths.py`) | 13.6 ms |
| Manim Cairo camera | **10.5 ms** |

Evaluator + Cairo, median (max): 960×540 25.7 ms (60.8); 1920×1080 28.0 ms (30.5);
2560×1440 31.7 ms (77.8).

QPainter vs Cairo fidelity on the Euler demo at 960×540: mean abs difference
0.016–0.021 / 255; pixels off by more than 32 levels ≤ 0.001 %.

→ ADR 0006.

### B3 — Full evaluator rebuild after an edit · 2026-10-09
`Evaluator(project)` + first frame, median of 15: Euler demo at t=5 s **108.7 ms**;
stress scene at t=2 s **224.7 ms**. Cached frame for comparison: 2.8 ms.

→ ADR 0008 (rebuilding per edit is too slow for drags).

### B4 — Camera framed to a zoomed viewport · 2026-10-09
New `manim.Camera` at 1920×1080 framed to a 400 % zoom region + render of the
stress frame: **20.1 ms**. → ADR 0006 (zoom by re-framing, vector-crisp).

### B5 — Invalidate one layer (clip edit) · 2026-10-09
Drag layer 1's Write clip (15 positions), `invalidate(project, {"l1"})` + frame at t=2 s:
32.1 ms; keeping the base mobject when the spec is unchanged: **27.4 ms**. → ADR 0008.

### B6 — Transform-only invalidate (gizmo drag) · 2026-10-09
Move layer 1 (active Write) with `transform_only=True` + frame: **3.1 ms**. → ADR 0008.

### B7 — Spike attribution · 2026-10-09
Per-frame trace with gen-2 GC counter, stress scene. 1920×1080: the only slow
frame (64.2 ms) is the first after the Write clips end (t = 3.07 s), with no GC —
the lazy checkpoint. 2560×1440: the only slow frame (85.2 ms) coincides with one
gen-2 collection. Other frames ≤ 33.0 ms. → ADR 0009.

### B8 — Spike mitigation · 2026-10-09
Worst frame over 3 full playthroughs (120 frames each), 1920×1080:

| setup | worst frames |
|---|---|
| lazy checkpoints, default GC | 115.1 / 81.3 / 86.1 ms |
| eager checkpoints | 82.6 / 79.6 / 78.9 ms |
| eager checkpoints + `gc.freeze()` | **35.3 / 30.9 / 33.5 ms** |

Eager checkpoint cost per idle slice ≤ 24.4 ms. → ADR 0009.

### B9 — Export throughput · 2026-10-09
`manim-studio render examples/euler.json`: 210 frames, 1280×720 @ 30 fps,
**≈ 12 s** wall time including the first LaTeX compile.

### B10 — Document copy and validation cost · 2026-10-09
Median of 200. 3-layer Euler demo / 20-layer stress / 100-layer, 400-clip project:
deep copy 0.09 / 0.51 / **3.15 ms**; full re-validate 0.02 / 0.12 / **0.87 ms**;
structural edit of one layer + validating it **0.02 ms**; `Project.model_validate`
over 20 existing layers 0.02 ms. → ADR 0014 (immutable snapshots, validate every edit).

### B11 — Timeline widget repaint · 2026-10-09
`QGraphicsView` with 400 clip rectangles: move one item and repaint a 1200×300
viewport — **0.17 ms** median (0.26 ms p95). → the timeline is not a bottleneck.

### B12 — Clip drag cost with clip-class invalidation · 2026-10-09
Stress scene + a `TransformMatchingShapes` morph between two MathTex layers; per
drag step: `invalidate(layer)` + evaluate + Cairo 960×540. Morph clip spanning the
playhead: **94.3 ms** median (147.1 max). Same with a 480×270 draft render:
**93.9 ms** — drawing is not the cost, `begin()` is. → ADR 0013.

### B13 — Timing-only edits that keep caches (prototype) · 2026-10-09
Same scene, adopting the edited document without dropping caches: Write-clip drag
**21.2 ms**, morph-clip drag **16.3 ms** per step; frames identical to a freshly
built evaluator (max diff 0, 12 positions each). → ADR 0013.

### B14 — Morph with keyframed partners, transform-keyed cache (prototype) · 2026-10-09
Source layer has position keyframes over 0–1 s; morph cache keyed by baked
start/end transforms. Dragging the morph where partners are settled (start
2.0–2.2 s): **15.4 ms** per step. Dragging while the source is mid-motion (start
0.3–0.5 s): **104.8 ms** (re-begins each step). → ADR 0013, known slow path.

### B15 — Drag step through the edit API (S1.1 implementation) · 2026-10-09
`benchmarks/bench_edits.py`: `edits.move_clip` + `Evaluator.apply` + evaluate +
Cairo 960×540 on the stress scene + a MathTex morph. Write-clip drag **21.7 ms**;
morph drag with static partners **15.0 ms**; with keyframed partners that have
settled **14.9 ms**; while the source is mid-motion **105.8 ms** (known slow
path). Confirms the B13/B14 prototype numbers. → ADR 0013 accepted.

### B16 — S1 acceptance: clip drag in the editor window · 2026-10-09
`benchmarks/bench_timeline_drag.py`: `MainWindow` offscreen at 1280×820 (canvas
1157×651), stress scene + MathTex morph, idle checkpoints done; synthetic mouse
drags on the timeline, timed from the mouse-move event to the end of the
event-loop turn (edit + validation + evaluator + Cairo canvas + timeline rebuild).
Write-clip drag **24.1 ms** median (25.4 p90); morph drag **19.2 ms** (19.8 p90);
same with a keyframed morph source (settled): 24.1 / 19.3 ms. Within the 33 ms
budget → S1 accepted.

### B17 — Building text objects: first time vs Manim's disk cache · 2026-10-09
Building through `adapter.build_mobject` with the in-memory cache cleared. A new
string: MathTex **1287 ms**, Tex **1238 ms**, Text **557 ms**. The same string
again (disk cache only): **11–18 ms**. Shapes for comparison: Circle/Square/Star
0.4 ms, Arrow 1.6 ms. → ADR 0015.

### B18 — Building text off the UI thread: thread vs process · 2026-10-09
Thread: MathTex 1312 ms total, worst UI-thread stall **11 ms** (LaTeX is a
subprocess); Text 567 ms total, worst stall **375 ms** (manimpango holds the
GIL). Separate process: startup + `import manim` **3–4 s** each time; afterwards
the editor process builds the same Text in **32 ms** and MathTex in **16 ms**
(disk cache shared across processes). → persistent worker, ADR 0015.

### B19 — Which params create new text cache entries · 2026-10-09
Changing one thing on an already-cached object (in-memory cache cleared). Text:
same string 27 ms, `font_size` 31 ms, `color` param 27 ms, style 26 ms, **font
269 ms**, new string 558 ms. MathTex: same 10 ms, `font_size` 9 ms, `color` 9 ms,
style 9 ms, new string 1261 ms. → warm key = params minus `font_size`/`color`,
style excluded (ADR 0015).

### B20 — Large image layer build · 2026-10-09
ImageMobject from a 4000×4000 RGBA PNG (1.4 MB, gradient): **197 ms** and
**199 ms** cold; from the adapter's in-memory spec cache (copy) **16 ms**. Image
edits stay synchronous (no disk cache for the worker to warm).

### B21 — Hit-testing a click on the canvas · 2026-10-09
`benchmarks/bench_canvas_interaction.py`, stress scene + MathTex morph at
t = 2.5 s (21 visible layers), every layer tested without a prefilter: bounding
boxes **0.69 ms**, filled Qt paths (`QPainterPath.contains` on `vmobject_path`)
**6.7 ms**, filled + `QPainterPathStroker` 0.1 u **69.8 ms**, numpy distance to
cubic chords **3.8 ms**. With a bounding-box prefilter, Qt fill + numpy stroke
over 40 random clicks: median **0.05 ms**, max **1.14 ms**. → ADR 0016.
As shipped (S3.2: prefilter, alpha gate, numpy winding and flattened strokes —
Qt containment turned out wrong on some lines, see ADR 0016): median **0.78 ms**,
max **1.86 ms** over the same 40 clicks.

### B22 — Selection outline and move-drag steps · 2026-10-09
Same scene, 960x540. Outline of a MathTex (path mapped to pixels, drawn with its
bounding box): **0.72 ms** per frame. One move step (edit + `Evaluator.apply` +
evaluate + Cairo render): static layer, base position **15.1 ms**; keyframed
layer, key at the playhead **15.1 ms** (both `transform` kind, caches kept);
keyframed morph source mid-morph **93.8 ms** (re-begin). → ADR 0016.

### B23 — Morph drag lag and clip-driven visibility · 2026-10-09
Moving a morph source by 1.0 u moves the drawn morph by **0.93 u** at 25 %,
**0.50 u** at 50 % and **0.07 u** at 75 % of the morph (smooth rate): a drag
cannot follow the cursor → drags refused during a morph. A filled Square at the
first frame of its FadeIn has its full geometry but fill and stroke alpha
**0.0** (0.001 one frame later) → hit-testing is gated on alpha > 0.02. Of the 17
easings the panel offers, only `there_and_back` does not end at 1. → ADR 0016.

### B24 — S3 acceptance: canvas drag in the editor window · 2026-10-09
`benchmarks/bench_canvas_drag.py`: `MainWindow` offscreen at 1280x820 with both
docks (canvas 616x346), stress scene + MathTex morph, idle checkpoints done,
playhead at 1.5 s; synthetic mouse drags on the canvas, timed from the
mouse-move event to the end of its event-loop turn (edit + validation +
evaluator + Cairo render + outline + panels). Static layer (base position):
**18.4 ms** median (19.7 p90); keyframed layer (key at the playhead): **18.5 ms**
(19.4 p90). Within the 33 ms budget → S3 accepted.

### B25 — Exporting from a separate process · 2026-10-09
`manim-studio render examples/euler.json` (1280x720@30, 210 frames): render
**2.5 s** (84 frames/s) after ~**4 s** of process start-up (6.6 s wall).
Killing a 60 s render after 8 s leaves a **48-byte unreadable** file at the
output path. `os.replace` onto a file held open by another handle raises
**PermissionError** (succeeds once closed). A child process printing without
`flush`, read through a pipe, delivers its first line only **at exit** (0.98 s
for three lines 0.3 s apart). → ADR 0017.

### B26 — S4 acceptance: the editor during an export · 2026-10-09
`benchmarks/bench_export_ui.py`: `MainWindow` offscreen with `examples/euler.json`,
export started from the dialog (210 frames, 1280x720, 5.6 s including the
renderer's start-up), a 16 ms `QTimer` on the UI thread: lateness median
**0.0 ms**, p99 **14 ms**, max **50 ms** (one tick, at process start) over 343
ticks. The UI does not freeze → S4 accepted.

### B27 — Named Manim eases as cubic beziers · 2026-10-09
`benchmarks/fit_ease_beziers.py`: grid search + refinement of (x1, y1, x2, y2)
per named ease, max vertical error over 41 curve samples. Within 0.022: linear
0.0, rush_into/rush_from 0.0007, ease_in/out/in_out_sine ≤ 0.0009, the cubic
family ≤ 0.0032, smooth 0.004, ease_in/out_back 0.006, ease_in_out_back 0.0215.
Not representable: double_smooth 0.092, ease_out_bounce 0.140, ease_out_elastic
0.636, there_and_back 1.0. The fit takes ~1.4 s per ease (23.5 s for 17) → the
results ship as a table (`adapter.EASE_BEZIER_FITS`), rechecked by a test.

### B28 — Addressing parts of an equation · 2026-10-09
`benchmarks/bench_tex_parts.py`, three equations (`e^{i\pi} + 1 = 0`,
`a^2 + b^2 = c^2`, `\int_0^1 x^2\,dx = \frac{1}{3}`), fresh LaTeX each build.
Building with `substrings_to_isolate` or with the editor's own span markers
(`\special{dvisvgm:raw <g id=...>}` around exactly one span) costs the same as a
plain build (4.1-4.4 s cold, all three), keeps the glyph count, and renders
**pixel-identical** (max diff 0) at rest and during Write, Create and
DrawBorderThenFill at alpha 0.3 and 0.6. Each marker group holds exactly the
chosen glyphs (`\frac{1}{3}` → glyphs 8, 9, 10; only the chosen `1`), and the
group's glyphs are the same objects as the root's, so regions are glyph
indices. Nested spans work (`x^2` → 3, 4 and `x` → 3). A marker right after `^`
fails LaTeX ("Missing { inserted"); braced (`^{...}`) it is identical.
`substrings_to_isolate` marks every occurrence of a key. → ADR 0012.

### B29 — Frame cost of an object with parts · 2026-10-09
`benchmarks/bench_part_frames.py`: `a^2 + b^2 = c^2` (font size 96) at
1280x720@30 with Write, warm caches, 120 frames. Plain: evaluate **0.63 ms**,
evaluate + render **9.2 ms** per frame. With three parts (Split terms), an
Indicate, a FadeOut and a keyed move: evaluate **3.8 ms**, evaluate + render
**12.6 ms**. Well inside the 33 ms frame budget → P2c.2 accepted.

### B30 — Code layers: capture, cache and compositing · 2026-10-09
`benchmarks/bench_code_layer.py`, 1280x720@30, an orbit scene (ValueTracker,
updater, TracedPath; 3 s). Capturing a real `Scene` through a `CairoRenderer`
subclass that keeps frames (no video encode): 90 frames in **0.6-0.7 s**
(~7 ms/frame), transparent background (0.6 % of pixels non-transparent). Per
frame: raw 3.7 MB; PNG (level 1) 55 kB, encode 70 ms, decode 18 ms; zlib
(level 1) of the raw array **34 kB**, encode 40 ms, decode **13 ms**.
Compositing one cached frame into a 5.2 ms editor frame: full-frame
`ImageMobject` 214-304 ms; numpy float blend 175 ms; cropped integer numpy
blend 28 ms; a cropped premultiplied crop painted with **Cairo** between two
capture runs **no measurable cost** (5.2 ms total), max channel error 1.5.
A fresh process per render: Python up 0.2-0.3 s, Manim imported at **5.8-7.8 s**,
first frame at 6.6-8.7 s, done at 7.2-9.3 s — the import is ~85 % of the wait.
→ ADR 0019.

### B31 — Code layer edit to frames with a warm spare · 2026-10-10
`tests/ui/test_code_render.py::test_a_warm_spare_renders_real_code_in_about_a_second`:
`CodeRenderService` with a spare that has already imported Manim; the code of a
layer changes to a 1 s scene (`Create(Square())`, 32x18 @ 10 fps). From
`sync()` to every frame in the cache: **0.15-0.24 s** (3 runs), against 6.6-8.7 s
to the *first* frame for a cold process (B30). → P2d.3 accepted.

### B32 — Test suite wall time · 2026-10-10
642 tests, this machine (12 logical cores, busy). Serial: **293 s**. Most of it
was two things: (1) CLI tests re-pointed Manim's cache at their own folder and
never restored it, so every later LaTeX build compiled from scratch (~3 s each)
— restoring the shared cache after each test: **230 s**; (2) tests that start
real processes (build worker, renderer, code runner) each pay Manim's import
(5-8 s). In parallel with `pytest-xdist` and a per-worker cache seeded from the
shared one: `-n auto` (12) 89-97 s, `-n 6` 79 s, **`-n 8` 74 s** (worksteal) —
more workers oversubscribe the CPU with Manim subprocesses. The default is now
at most 8 workers; on a loaded machine a full run takes 75-110 s. The quick
lane `-m "not slow"` (no real subprocesses): **~28-38 s** for 611 tests.

### B33 — Keyed matching between two equations · 2026-10-10
`benchmarks/bench_matching_tex.py`: `a^2 + b^2 = c^2` -> `a^2 = c^2 - b^2`,
parts a^2, b^2, c^2 on both. A `TransformMatchingAbstractBase` subclass fed
pre-grouped pieces: parts keyed by TeX, other glyphs by normalized shape. Shape
keys agree across separately compiled equations (`=` matches; `+` vs `-` do
not). Matched: a^2, b^2, c^2 (TeX) and `=` (shape); `+` fades out, `-` fades
in. Frames at shuffled alphas equal frames in order: **max diff 0**. Begin
**15 ms**, interpolate + render **1.3 ms**/frame. Alpha 1 vs the target
equation: mean diff 0.01 (re-aligned paths on a few pixels; the target layer
takes over at the clip end). Unequal duplicate groups (`a^2+b^2+c^2` ->
`x^2+y^2`: three `2` vs two, two `+` vs one) also exact. → ADR 0020.

### B34 — Anchor point model and compensation · 2026-10-10
`benchmarks/bench_anchor.py`, 1000 random transforms (rotation ±360°, scale
0.1-4) and 20 points each, with `world(p) = A (p - P) + P + position`:
anchor (0, 0) vs the old `A p + position`: **max error 0**; moving the anchor
and adding `(I - A)(old - new)` to the position: image unchanged, **max error
1.4e-14**; the world pivot `anchor + position` under any other rotation and
scale: **0**. The limit: with rotation keyed 0° -> 90° and the anchor moved at
45°, the same rigid offset is exact at that time (6e-17) and **1.06 units off**
at 0° (a 3-unit line, anchor moved from its middle to its top). → ADR 0021.

### B35 — Candidate clip kinds against the random-access rule · 2026-10-10
`benchmarks/bench_clip_kinds.py`: each candidate rendered as `Scene.play` would
(begin, interpolate in order) vs a fresh animation per frame vs one animation
scrubbed in shuffled order, on Square, Text and MathTex (320x180 @ 15 fps).
**Exact (max diff 0):** GrowFromEdge, GrowFromPoint, SpiralIn, FadeIn/FadeOut
with `shift`, AddTextLetterByLetter / RemoveTextLetterByLetter (Text), Flash,
FocusOn, Indicate with `color`/`scale_factor`, ClockwiseTransform,
CounterclockwiseTransform, FadeTransformPieces; begin + one frame 0.3-17 ms.
Broadcast exact but **111 ms** (Text) / **299 ms** (MathTex) to begin.
ShowPassingFlash raises on all three. Circumscribe and Blink are `Succession`s:
they need a scene and only play forward; with a patch that snapshots the drawn
family before each part and restores it per frame they match Manim's
sequential output **exactly in reversed and shuffled order** (begin 0.1-0.3 ms
for Circumscribe). Blink leaves a Square **98 levels** off its shape at the end.
On a 60x40 RGBA image: the same exact set except SpiralIn (raises) and
ShowPassingFlash (VMobjects only). → ADR 0022.

*Correction (same day, during P2g.3):* the Circumscribe numbers above drew the
Succession's own `mobject`, which is an **empty** group — a scene shows the
frame because `_setup_scene` adds the parts' mobjects separately — so they
compared nothing. Re-measured (`check_circumscribe` in the script) against
unpatched Circumscribe played forward, drawing the object and the parts'
mobjects: the frame is visible (up to 230 levels off the plain object) and the
patched animation matches **exactly** (diff 0) in reversed and shuffled order
on Square, Text, MathTex and an image, for the default, `shape=Circle`, and the
three-part `fade_in=True, fade_out=True` variant; at the end the object is
unchanged. The adapter now draws the parts' mobjects.

### B36 — A re-framed preview camera · 2026-10-10
`benchmarks/bench_viewport.py`, the stress scene of `bench_preview.py` (20
MathTex, 3 concurrent Writes, 10 keyed layers), median per frame over 30 frames:
letterboxed frame 806x453 **18.2 ms**; camera covering the whole widget
806x598 at the same scale **20.2 ms** (+11 %); zoom 4x about (1, 0.5) **17.4 ms**;
zoom 0.25x **18.0 ms**. A camera zoomed 2x about (1, 0.5) vs the matching crop of
a 1612x906 render of the whole frame: max 120, **mean 0.7** — edges only (the
crop is aligned to whole pixels, anti-aliasing differs). → ADR 0023.

### B37 — Axes, function graphs and a safe expression compiler · 2026-10-10
`benchmarks/bench_graphs.py`. A whitelist compiler over Python's `ast` (numbers,
`x`, `pi`, `e`, `+ - * / **`, unary signs, `sin cos tan exp log sqrt abs`) vs
`eval` on 1001 points for five expressions: **max diff 0**; compile 0.01-0.03 ms,
evaluate 0.00-0.03 ms; imports, attributes, other calls, comprehensions,
lambdas and conditionals are rejected. `Axes(x_range [-5, 5, 1], y_range
[-3, 3, 1], 10 x 6)`: **9 ms**; with number labels **7.6 s cold** (LaTeX
digits, empty Manim cache), **31 ms** warm. `axes.plot(sin)` on [-5, 5]:
**4.2 ms**, 400 points. Create on a graph and Transform between two graphs,
in order vs shuffled: **scrub diff 0** (the graph is visible: 191-206 levels).
Bad values: `log(x)` and `sqrt(x)` on [-5, 5] leave 204 of 400 points NaN;
`tan(x)` reaches |y| 85 and `1/x` 5.6e13 (rendered as spikes). → ADR 0024.

### B38 — MoveAlongPath · 2026-10-10
`benchmarks/bench_move_along_path.py`: a dot moved along a circle (8 curves), a
line (1) and a sin(x) graph on default axes (399), in order vs shuffled:
**scrub diff 0** on all three. With a linear rate the dot's centre lands on
`path.point_from_proportion(alpha)` to **2e-16**. One `interpolate`: **0.09 ms**
(line), **0.48 ms** (circle), **23.6 ms** (graph) - `point_from_proportion`
measures every curve on every call. An arc-length table built once gives the
same points (max diff **1e-16**) in **0.005 ms**. → ADR 0025.

### B39 — Curved position segments · 2026-10-10
`benchmarks/bench_spatial_paths.py`, an S-shaped cubic Bezier (p0 (-4, -1),
p1 (3, 1.5), handles (4, 5) and (-1, 3)) walked at 61 uniform steps of u.
Raw `B(u)`: step lengths vary **3.4x**. By arc length with an n-sample table:
n=16 1.100 (error 1.2e-2 units), n=32 1.037 (2.8e-3), n=64 1.010 (6.9e-4),
**n=128 1.002 (1.6e-4)**; 12 us per sample, **37 us** to build the table. Zero
tangents: raw walking is not linear in u (6.7e-1 off); arc-length walking
through the table is 9.6e-4 off the exact linear formula - so straight
segments keep the formula. → ADR 0026.

### B40 — SVG import · 2026-10-10
`benchmarks/bench_svg.py`, Manim's `SVGMobject` on a 3-path SVG (rect, circle,
open path; fills and strokes) and a 400-path one. Small: **7 ms** to build,
1 ms again; large: **198 ms** cold, 64 ms again (Manim caches the parse - keyed
by the file *name*, not its contents, so P3e bypasses it and caches per file
signature). Colours survive (one fill per path), height normalised to 2. Create,
DrawBorderThenFill, Write and FadeIn played in order vs scrubbed in a shuffled
order: max diff **0**, the drawing visible (~249 levels). A missing file raises
`OSError`, malformed XML `ParseError`, an empty `<svg/>` builds 0 paths of
height 0; a `stat` costs ~35 us. → ADR 0027.

### B41 — Render-ahead: making, keeping and showing a preview frame · 2026-10-10
`benchmarks/bench_render_ahead.py`, camera 1100×620 (a typical canvas widget),
frames warmed first (checkpoints and active clips built). Evaluate + Cairo per
frame: stress scene median **58 ms** (p90 70, max 182); heavy scene (stress + a
400-path SVG drawn on + axes with two graphs) median **131 ms** (p90 178, max
301) - about 7 fps. Keeping a frame: raw RGBA 2.6 MB (196 frames in 512 MB, shown
in 1-3 ms); zlib level 1: compress 14 ms, decompress + QImage **8-12 ms**, 23-50×
smaller (0.05-0.11 MB, 4500-9700 frames in 512 MB); zlib 6: compress 23-26 ms,
show 8-16 ms, 28-68×. A second probe (machine loaded): whole-frame evaluation
97 / 146 ms, one keyed MathTex alone **2.6-3.7 ms**, the 400-path SVG mid-draw
alone 50 ms. → ADR 0028.

### B42 — Objects on axes with Manim's helpers · 2026-10-10
`benchmarks/bench_axes_objects.py`, the editor's default axes and graphs
(sin(x), x²/10 - 1) given `function` / `underlying_function` / `t_min` /
`t_max` so Manim's helpers accept them (without, `get_area` fails: our graphs
are plain VMobjects). Build cold (again): Dot at `c2p` **0.4 ms**; `get_area`
**30 ms** (between two graphs 60 ms); `get_riemann_rectangles` dx 0.25 **12 ms**
(12 leaves); `get_axis_labels` **2.6 s** cold, 5.6 ms warm (LaTeX); a graph label
1.3 s cold, 4.9 ms warm. Create, FadeIn and DrawBorderThenFill on each, played
in order vs scrubbed: diff **0**, all visible. → ADR 0030.

### B43 — Exported Python rendered by Manim · 2026-10-10
Probes for P4a at 320×180, 10 fps, rendered with `manim render` and compared
frame by frame with the editor's export (both h264). **Exact form** (a holder
whose updater sets its submobjects to the evaluator's frame, then `wait`):
mean abs diff **0.3** levels per frame, aligned. Two traps: a plain updater
(not dt-based) makes Manim freeze the `wait` into one repeated frame, and
accumulating dt in a tracker shows each frame one step late; reading
`self.renderer.time` inside a dt updater gives the frame's own time.
**Readable form** (hand-written: `self.add`, `AnimationGroup(Create(..),
Succession(Wait(0.5), FadeIn(..)))`, `self.wait`, `Indicate`): mean abs diff
≤ **0.5** per frame. Code-layer frames are plain Mobjects Manim's camera skips;
`Camera.display_funcs` (checked in insertion order) lets them paint themselves.
→ ADR 0031.

### B44 — Generated Python rendered by Manim · 2026-10-10
`benchmarks/bench_python_export.py`, the test suite's rich project (an
overlapping group, a gap, a morph, MoveAlongPath, Wiggle, clamped and Bézier
eases) at 320×180, 10 fps. Readable form: generated in **2.5 ms** (98 lines),
`manim render` 2.6 s, worst per-frame mean difference from the editor **0.52**.
Exact form (a keyframed dot added): generated in 0.5 ms, rendered in 2.2 s,
worst **1.39** (h264 on a moving dot). Follows B43. → ADR 0031.

### B45 — Plugins: discovery, loading, building · 2026-10-11
`benchmarks/bench_plugins.py`. Scanning the `manim_studio.plugins` entry points:
**20-31 ms** per process (none installed). Loading a plugin file: **1.5 ms** once
Manim is imported (5.5 s if the plugin is the first to import Manim - it never
is in our processes). Building the sample (a rod and a bob): **2.7-3.7 ms**; the
determinism check (a second build compared point by point) adds **1.6 ms**,
once per type per process. The result is a VGroup (vector). → ADR 0032.

### B46 — Simulated layers: Manim's TracedPath, replay costs · 2026-10-11
`benchmarks/bench_simulation.py`. Manim's own play loop at 10 fps with a
`TracedPath` following a dot: within one `play()` the trace on every rendered
frame is exactly the polyline through the dot's centre on the frames so far
(**30/30** frames, one 3 s MoveAlongPath). Across plays Manim adds one more
corner per `play()` - the end state, never shown as a frame (2 plays + wait:
10/25 frames equal, the rest differ only by those corners). `dissipating_time`
keeps about D x fps segments. Costs: the target's point at one frame
**0.11-0.16 ms**; a 300-corner trace built in **0.19 ms**, drawn in
**1.8-2.1 ms** at 1280x720; a pendulum RK4 step **0.7 us**, its drawing
**0.33 ms**; a checkpoint copy of 2000 particles **0.003 ms**. With a state every
30 frames a seek replays at most 29 steps. -> ADR 0033.

### B47 — An audio track: decoding, mixing, Qt playback, muxing · 2026-10-11
`benchmarks/bench_audio.py`. Decoding 60 s to 48 kHz float32 stereo with PyAV:
WAV **74 ms**, MP3 **110 ms**, AAC **91 ms**. Mixing three 50 s clips with gain
and fades into 90 s (numpy): **116 ms**. Waveform peaks (100/s) of 60 s:
**8 ms**. Qt: the default output takes Int16 48 kHz stereo; a `QAudioSink`
first consumes data **0.4-0.55 s** after the first start in a process, ~0.1 s
afterwards; the offset between the wall clock and `processedUSecs` stays
constant (no drift over 5 s), and `processedUSecs` advances every **10 ms**
(13 ms at most) with a 250 or 60 ms buffer. Muxing 3 s of H.264 + AAC:
**181 ms**, both streams 3.000 s, audio from pts 0; clicks mixed at known times
decode back with a best alignment lag of **0 samples**. Manim's
`add_sound(file, time_offset=0.5)` puts the sound at ~0.5 s (48 kHz); it has
no trimming or fades. -> ADR 0034.

### B48 — Subtitles: building and drawing a line of text · 2026-10-11
`benchmarks/bench_subtitles.py`. A new subtitle line (Manim's Text, Pango) at size
26: **424 ms** cold, **33 ms** when Manim's disk cache has it (a new object), +14 ms
for a copy. An 88-character line is **15.9 units** wide (the frame is 14.2), about
0.18 units per character; as two lines it builds in 99 ms (cached afterwards).
Drawing a 1280x720 frame with a subtitle and its band: **3.1 ms** (1.0 ms empty).
Also checked: `Scene.add_subcaption(text, duration, offset)` makes `manim render`
write `<scene>.srt` beside the video. -> ADR 0035.

### B49 — Value readouts and connectors · 2026-10-11
`benchmarks/bench_readouts.py`. Manim's `DecimalNumber`: first build **1351 ms**
(its digits compile in LaTeX once), another value **3.5 ms**, `set_value`
**4.2 ms**; composing cached glyphs 2.4 ms. A connector rebuilt per frame: Line
**0.07 ms**, Arrow **1.17 ms**. Checked during the design session: a centred
`DecimalNumber` with `ChangeDecimalToValue` interpolated at 21 alphas in
shuffled order equals fresh animations (21/21), keeps its left edge and ends on
the target value. -> ADR 0036.

### B50 — Markers and snapping · 2026-10-11
`benchmarks/bench_markers.py` on `examples/explainer.json` (59 layers, 31 sounds
placed by hand): **27 of 31** sounds start within half a frame of a clip edge, none
on a key time. Gathering every snap point (clip edges, key times, sound and
subtitle edges, 0 and the end: **183** points) and finding the nearest takes
**0.047 ms**, so drags can rebuild the list on every mouse move. -> ADR 0037.

### B51 — Autosave and the clipboard · 2026-10-11
(B50 is P5c's.) `benchmarks/bench_autosave.py`. A recovery copy (`core.recovery.write`: the
project's JSON, a temporary file and `os.replace`, then the sidecar the same way) of a project
whose layers each have two clips and two keyed properties: 20 layers **2.4 ms** (15 KB), 200
layers **5.8 ms** (150 KB), 1000 layers **20.9 ms** (750 KB), 2000 layers **41.3 ms** (1.5 MB);
the JSON alone is 0.3 / 3.3 / 18.1 / 38.3 ms, so the files cost about 2-3 ms. Once per 30 s
on the GUI thread, only while there are unsaved changes: kept there. Duplicating one object
costs what any structural edit costs (`edits.add_layer` for comparison): 0.4 / 7.6 / 172 /
923 ms against 0.2 / 6.8 / 173 / 921 ms - the time is the project's validation and edit
classification, which grow faster than linearly with the layer count (not the clipboard's).
Copying axes with 40 graphs makes 10 KB of clipboard text; reading and pasting it **2.9 ms**.
-> ADR 0038.

### B52 — Presets and templates · 2026-10-11
`benchmarks/bench_presets.py` on `examples/explainer.json` (59 layers, 105 clips):
**93 of 105** clips share kind, duration and ease with another (17 x FadeIn 0.3 s,
17 x FadeOut 0.3 s, 9 x FadeOut 0.8 s, 9 x Transform 1.2 s); **30 layers** are
exactly FadeIn -> FadeOut; no keyframe tracks; layer groups rebuilt by hand: 4
section headers. (B51 is P5d's autosave measurement.) -> ADR 0039.

### B53 — Validation and edit cost by project size · 2026-10-11
(B51 found that duplicating an object costs what any structural edit costs and grows faster than
linearly; B52 is P5e's.) `benchmarks/bench_validation.py`, best of 9, projects of 20 to 2000 layers
(clipped shapes, axes with graphs, a MathTex with parts, morph pairs, motion along a path, traces and
connectors per 100 layers, so every validator has work). cProfile of `add_layer` at 2000 layers
(1.2 s): **`edits.classify` 1.13 s** - `Project.referenced_graphs` built an `{id: layer}` table for
every layer (0.56 s), `parts.build_spec` rescanned the layer list for every root (0.50 s: `layer()` and
`children()`), `old.layer(parent)` per child; the project validators were minor (`ids.count` in the
duplicate check 0.04 s, a list scan per morph target, `descendants()` per motion clip, `traceable_ids()`
per trace and connector). Fix: `classify` indexes both snapshots once and resolves a root's parts only
when their `(id, parent, key)` differ between the snapshots; the validators use one `by_id` table, a
`Counter`, an ancestor walk instead of `descendants()`, and a predicate instead of `traceable_ids()`;
`frame_cache._closure` finds an object's members from one children map. Before -> after (ms):

| layers | validate | add_layer | update_layer | classify | changed_spans |
|-------:|---------:|----------:|-------------:|---------:|--------------:|
| 20     | 0.3 -> 0.4 | 0.2 -> 0.1 | 0.3 -> 0.2 | 0.1 -> 0.0 | 0.1 -> 0.1 |
| 200    | 4.9 -> 4.3 | 7.0 -> 0.9 | 6.9 -> 0.9 | 5.9 -> 0.3 | 0.6 -> 0.5 |
| 1000   | 39 -> 27 | 171 -> 4.8 | 172 -> 4.9 | 156 -> 1.6 | 3.3 -> 3.0 |
| 2000   | 110 -> 60 | 838 -> 11 | 835 -> 11 | 783 -> 3.5 | 8.8 -> 7.7 |

2000 layers cost 12x what 200 layers do for `add_layer` (was 120x); what is left is pydantic
re-validating the new layer list (linear). No rule or message changed (the full suite passes
unchanged); one crash became a message: a morph aimed at a sound's id raised `StopIteration`.

### B54 — The design system · 2026-10-11
`benchmarks/bench_design.py`. QtAwesome 1.4 (icon fonts): warm, importing it takes
**174 ms**, the first icon **57 ms** (its fonts load), 23 more **0.5 ms**, drawing 23 at
20 px **2.2 ms**; the very first run after installing took 3.2 s + 8.4 s (cold disk and
virus scan, once). All 23 Phosphor icons the editor needs exist. Applying a 300-rule
application stylesheet with the main window open takes **11 ms**, opening a window
under it **20 ms**. (B53 is the validation performance slice.) -> ADR 0040.

### B55 — Workspace pages · 2026-10-11
`benchmarks/bench_pages.py` with the showcase project at 1600x1000: moving the one
canvas (with its transport) and the timeline into another page's splitter and back,
repaint included, takes **13.6 ms** per switch; hiding and showing both docks
**18.7 ms**; building a second `CanvasWidget` 1.6 ms (rejected: it would duplicate the
frame cache and the selection wiring). With the pages built (P6b.1), a real
`show_page` round trip - parking, re-parenting, splitter sizes, repaint - takes
**22.8 ms** per switch. -> ADR 0041.

### B56 — The graph editor · 2026-10-12
`benchmarks/bench_graph_editor.py`: one layer with position, scale, rotation and opacity keyed
(five curves), `keys` keys per track with mixed eases, the Animate page at 1600x1000. Times
are in ms, best of 7. The machine was shared with other test runs, so expect ±30 %.

| keys | sample 5 curves: segment walk | `_sample` per point | repaint after an edit | repaint after a seek | drag step |
|-----:|------:|------:|------:|------:|------:|
| 10   | 6.3   | 6.8   | 15.9  | 5.5   | 19.6  |
| 50   | 7.2   | 22.5  | 27.8  | 7.4   | 38.9  |
| 200  | 11.4  | 61.9  | 60.6  | 28.3  | 86.0  |
| 1000 | 51.2  | 674   | 176   | 87.8  | 268   |

- **Stroking:** the first version stroked each curve as one 2 px antialiased
  `QPainterPath`. At 200 keys `drawPath` took 62 ms per curve, and a repaint after a seek
  took 323 ms. A probe on 760 points gave these stroke times:

  | stroke | time |
  |---|---:|
  | antialiased path, 2 px | 33 ms |
  | cosmetic pen | 33 ms |
  | `drawPolyline` | 32 ms |
  | 1 px pen | 1.0 ms |
  | not antialiased | 9.9 ms |
  | `drawLines` of separate 2 px segments | **1.8 ms** |

  The curves are now cached as segments (`QLineF`) and drawn with `drawLines`.
- **Drag step:** a per-curve cache keyed by the track and the base value leaves the curves
  that are not dragged as they are, which took a drag step at 200 keys from 405 ms to
  86 ms.
- **Sampling:** the segment walk is 5x faster than calling `_sample` at every point at
  200 keys, and 13x faster at 1000 keys.
- **What a drag step costs:** the rest of a drag step goes to `drag_key` (about 13 ms: two
  validated edits) and the window's existing reactions: the timeline's sync, the canvas
  render and Properties. Typical layers (under 50 keys per track) repaint after a seek in
  under 8 ms. -> decision session 35.

### B57 — The Code page's editor · 2026-10-12
`benchmarks/bench_code_editor.py` on a generated 2000-line scene (162 KB), offscreen, the
quiet-machine run (a second batch ran 2-3x slower while other jobs shared the machine; the
shape was the same). The pure lexer (`code_syntax.scan`) over the whole text takes **20 ms**;
putting the text in the editor (highlight, layout, line numbers, repaint) **43 ms**. One typed
character in the middle takes **4.4 ms** (6.6 ms typing and deleting a quote after an open
triple quoted string, which flips the state of every line below - Qt re-highlights only while the
block state changes, so it is the same order); the page's per-keystroke dirty check
(`toPlainText` and the comparison with the project's code) **0.25 ms**, and typing through the
whole page 11-15 ms, the same with the check disconnected (so it is Qt layout and painting of a
large window, not the page). A Compose <-> Code round trip with the 2000 lines open takes
**68-72 ms** (B55: 23 ms for Compose and a small page; the editor lays its text out again on show).
A typical code layer (under 100 lines) is far below all of this. -> ADR 0041, decision session 36.

### B58 — The Audio page · 2026-10-12
`benchmarks/bench_audio_page.py`: a 5-minute project with four 60 s sounds (gain -3 dB, 2 s fades) and
200 subtitles, medians. Reading the mix's level at the playhead: the whole mix rebuilt after an edit
(its cache key changes) and sliced costs **115-129 ms** (the slice itself 0.01 ms); `levels.level_at`
(the 100 ms window mixed straight from the decoded files, fades computed for the slice) **0.24-0.41 ms**,
**0.13 ms** at the start of the video where the window is half; decoding the four files, paid once
(the timeline's waveforms already pay it), 250-600 ms. The window is bit-identical to the same span of
`audio.mix` (tested, including clipping and fades) - which settled the windowed read, since the whole
mix would cost its 115 ms after every gain edit while a table cell is being edited. In the real window
(1600x1000, Audio page): the meter alone (`level_at`, readout, bars repainted) **1.0 ms**, so playback
ticks barely notice it (a seek to an uncached frame 49 ms without the meter, 57 ms with it, 42 ms on
Compose; the canvas dominates and the runs are noisy); refreshing both tables (4 sounds, 200 cues) after
an edit **0.7-1.3 ms**; a cell edit end to end (`setData` -> undo step -> evaluator -> tables -> meter)
**36-56 ms**, almost all of it the evaluator and canvas of the 300 s project. -> ADR 0041, plan
[p6b4-audio](../plans/p6b4-audio.md).

### B59 — The Deliver page · 2026-10-12
`benchmarks/bench_deliver.py` with the showcase project at 1400x860, warm. `to_python`
of the showcase (an exact scene, 11 reasons, 15.6 k characters) takes **0.5 ms**, of a small
readable project **0.1 ms**, so the Python preview is recomputed 0.4 s after the last edit
without a worker. The first `show_page("deliver")` (which builds the preview) takes
**19 ms**, again **12 ms**; `add_to_queue` (a reference, the options, one row) **0.2 ms**.
Exporting a 1.5 s range of the showcase (45 frames) in the exporter: 480p (854x480)
**0.92 s** (21 ms/frame), 720p **1.44 s** (32 ms/frame), 1080p **2.15 s** (48 ms/frame),
so a draft size is about twice as cheap as 1080p. (A first run, with a cold disk cache, was
47 ms for the first show and 1.0 ms for the showcase's `to_python`.) -> ADR 0042.

### B60 — Canvas interaction · 2026-10-12
`benchmarks/bench_handles.py` at 960x540 (B56-B59 belong to the page slices). A
parameter handle drag edits the spec on every mouse move - the edit, the evaluator's
rebuild and the frame - in **3.4 ms** for a rectangle's width, a line's end or a
circle's radius, **6.5 ms** for a text's font size with cached glyphs. Gathering 24
objects' world boxes and finding the nearest edge for snapping: **0.63 ms**. Moving 20
objects as 20 chained edits: **2.3 ms**. -> ADR 0043.

### B61 — Preset thumbnails · 2026-10-12
`benchmarks/bench_preset_thumbs.py`: every built-in preset (32) applied to a square at
t = 0 in a 160x90 project, 8 frames across its run with the in-process evaluator and
Cairo. First frame (clip activation included) **0.5 ms** median, 3.1 ms worst; the other
frames **0.1 ms**; a whole thumbnail **1.7 ms** median, 6.0 ms worst; all 32 in **62 ms**.
A probe confirmed the frames are drawn (about 1300 lit pixels mid-entrance). Thumbnails
can be rendered eagerly when the browser opens. -> ADR 0044.

### B62 — The release check · 2026-10-15
`scripts/release_check.py` on the tree at 0.1.0 (warm uv cache). `uv build`: **0.3 s**; every
one of the 124 files under `src/` (the 43 library JSON items too) is in the wheel. A fresh
Python 3.13 venv at the system temp folder's ASCII (8.3) path: **0.1 s**; installing the wheel
**3.6 s**; `--version` **0.7 s**; rendering `examples/euler.json` from the installed package
(210 frames, MiKTeX) **14.8 s**, all 210 frames in the file; the editor opened offscreen from
the installed package with five pages, 32 presets, 5 themes and 6 templates **10.4 s**. Whole
check about **31 s**. -> ADR 0045.

### B63 — Presets browser · 2026-10-15
`benchmarks/bench_presets_browser.py` (offscreen, the 32 built-in presets): the first
*Browse Presets...* - the dialog built and shown with every thumbnail drawn - takes
**101 ms**; showing it again **1.4 ms** (the frames are kept); a search keystroke (the cards
rebuilt) **1.3 ms** median, 3.2 ms worst; a tab switch **1.0 ms**; one frame of a hovered
card **0.14 ms**. Drawing everything when the dialog opens is cheap enough that no
background thread is needed. -> ADR 0044.

### B64 — A long scene: do 10+ minutes scale? · 2026-10-17 (golden path G4)
`benchmarks/bench_long_scene.py`. **This entry is the 2-minute `--quick` run, measured on battery**
(single runs, noise of +-30 %: three quick runs gave 11-17 ms for the same layer move and 121-155 ms
for the same easing change), plus a `--model-only` run of the full 15 minutes, which builds and draws
nothing and so costs seconds. **The full 15-minute run on mains power is still to do**, as is the
column of the table it fills:

```
python benchmarks/bench_long_scene.py            # 15 minutes: a few minutes warm (the first run builds ~270 texts, much longer), ~1.5-2 GB of RAM
python benchmarks/bench_long_scene.py --quick    # 2 minutes (this entry)
python benchmarks/bench_long_scene.py --model-only [--profile]   # 15 minutes, no objects built or drawn
```

The synthetic explainer is seeded and shaped like a real one: a 15 s slide with a Text title, a MathTex
(8 formulas reused), 2-4 shapes entering (FadeIn / Write / GrowFromCenter / Create), one Indicate and
FadeOut exits; the title or a shape of some slides enters with the built-in "Pop in" preset (keyframed
scale), applied through `library.apply_preset`. Full: 900 s, **295 root layers, 650 clips, 50 keyframed
layers, 200 cues**, 27 000 frames, a 38 MB mono 22.05 kHz tone over the whole scene, 344 KB of JSON.
Quick: 120 s, **40 layers, 88 clips, 7 keyframed, 27 cues**, 3600 frames, 47 KB. Both 1280x720 at 30 fps.
(The first run also fills Manim's text cache: 1.2 s for titles and formulas, 5.0 s for the 27 cues when
warm; cold Pango/LaTeX takes minutes at 15 minutes, once.)

| quick run (120 s, 40 layers) | result | what it means |
|---|---:|---|
| validation / save / load | 3.1 / 3.2 / 2.9 ms | the document, linear |
| first frame at t = 0 / slide 1 on screen | 0.2 / 302 ms | the second builds the slide's five objects |
| first (cold) seek to 95 % | 433 ms (+16.8 ms drawn) | builds only that slide; **same with new evaluator, builds warm: 167 ms** |
| scrub, 100 random frames | evaluate 14 ms median, p95 416 (first visits); evaluate + draw 19 / 68 ms | 1100x620, second pass is the warm one |
| memory (RSS) | 195 MB base; open + deep seek +0; scrub **+63 MB**; every slide visited +0; every checkpoint +5 | grows with the slides visited (below) |
| idle checkpoint pass | 40 checkpoints, 1.3 s (34 ms each) | `missing_checkpoints()` scan 0.3 ms per tick |
| move one layer, end to end | 14 ms (1.2 `update_layer`, 0.0 `apply`, 12.2 drawn frame) | a drag step |
| move one clip / change an easing | 13.6 / 155 ms | the second drops the layer's checkpoints and rebuilds |
| `add_layer` / `remove_layer` | 0.9 / 0.9 ms | B53 held up |
| `changed_spans` (move / add / ease) | 0.6 ms each; 420 / 3600 / 390 frames | |
| autosave `recovery.write` | 12 ms | |
| audio: decode / mix rebuild / `level_at` | 360 ms (+46 MB) / 92-101 ms / 0.44 ms | mix 44 MB |
| timeline: `set_document` / sync / whole paint / window repaint / edit + repaint | 463 (cold sound) 32 ms / 10 ms / 33 ms (1465x1203 px) / 13 ms / 27 ms | |
| render-ahead (zlib 1, 1100x620) | 34 KB per frame; whole scene 121 MB (100 % of 512 MB) | accept 0.001 ms, `missing(60)` 0.83 ms |
| export, 60 frames at 1280x720 | 3.21 s = **53.6 ms/frame** | x264 + burned-in subtitles; AAC 3.0 s per 60 s of sound |
| in the real window (1600x1000) | open 0.5-0.7 s; seek 192 / 678 ms cold, 22 / 58 ms warm; move a layer 43-62 ms | median / p95 |

**The same code at 120 / 300 / 900 s (`--model-only`, ms; 40 / 97 / 295 root layers, 88 / 214 / 650
clips):** validation 2.7 / 8.8 / 33; save 3.5 / 6.4 / 20; load 2.3 / 6.0 / 24; `update_layer` 0.8 / 1.8 / 6.3;
`add_layer` 0.7 / 1.8 / 6.0; `changed_spans` 0.4 / 1.3 / 3.5; autosave 9.9 / 10.4 / 23.2; evaluating a frame
with nothing alive 0.08 / 0.23 / 0.87; `missing_checkpoints()` 0.2 / 0.5 / 1.6; mix rebuild 84 / 257 / **614**;
sound decode 187 / 886 / 2146; **timeline sync 10 / 26 / 151**; **an easing change (`apply` + a frame) 2.0 / 7.2 /
48.8**; **a layer moved in the real window 46 / 79 / 176**; `set_document` with a cold sound 375 / 1523 / 3047.
The edit pieces, the document, the autosave and the evaluator's walk are **linear** (about 0.1 ms per layer
for validation) and small. The first deep seek does not depend on the scene's length (635 / 472 / 433 ms at
30 / 60 / 120 s: it builds the slide it lands on).

**What grows faster than linearly or too large, with the numbers:**
1. **Timeline `sync()` is quadratic.** It rebuilds the whole scene on every document change: 10 ms at 40
   layers, 26 ms at 97, 151 ms at 295 (per layer 0.25 -> 0.27 -> 0.51 ms). `--profile` at 900 s: `Project.children()`
   885 calls from `rows()`/`descendants()` (16 ms), `Project.morph_sources()` rebuilt on each of the 295
   `lifetime()` calls (15 ms) and `Project.layer()` (3 ms) are about half of a 110 ms sync; the 650 `ClipItem`s
   cost 21 ms. A layer moved in the real window is 176 ms (timeline sync ~106 ms, `LayersPanel.sync` 35 ms - its
   `children()` again - and the repaint 36 ms): a timeline drag of the 15-minute project would run at ~5 fps.
   An index built once per sync (children map, morph map, id map) would make it linear. `Evaluator.invalidate`
   ("clip"/"spec" edits) also grows by ~n^1.6 (2 / 7 / 49 ms).
2. **Sound memory and mix time.** The engine's rate is 48 kHz stereo float32: decoding the one 15-minute sound
   holds **332 MB**, its mix **331 MB**, and `audio._MIXES` keeps two, so an audio edit peaks near 1 GB for one
   38 MB file (RSS was 813 MB with the decode and one mix). The mix rebuild after an audio edit is **614 ms**
   (0.68 ms per second of scene, linear; B58's 115 ms was for 4 sounds of 60 s); decode **2.1 s**, paid on the
   GUI thread by the first timeline sync (`set_document` 3.0 s against 0.27 s warm).
3. **Render-ahead does not fit.** At 34 KB per frame the whole scene is **923 MB against the 512 MB budget:
   55 % (14 979 frames, 8.3 min) fits** (B41's richer frames, 50-110 KB, would keep 2.5-5.4 min). A full store
   evicts with a `max()` over every kept frame: **7.4 ms per accepted frame** and **6.2 ms per `missing(60)`**
   on the GUI thread (0.001 and 0.8 ms when the store is small): not alarming, but O(frames kept).
4. **The evaluator keeps everything it builds.** The scrub over the 8 slides of the quick run took RSS from 195
   to 255 MB (2 slides: +19 MB, 4: +35, 8: +61-63), about **8 MB per slide** (five objects, their clip states,
   the slide's cues); dropping the evaluator and the adapter's build caches gives back 44-46 MB of that. At 60
   slides that extrapolates to **~470 MB** on top of the ~190 MB base and the ~660 MB of sound - about 1.3-1.5 GB
   for the full scene, to be confirmed by the full run.
5. **The timeline cannot show a long scene whole.** `MIN_PX_PER_SECOND` is 10, so *Fit Timeline* fits only up
   to ~145 s in a 1600 px window; the 15-minute scene is 9041 px wide (a window repaint is still 22 ms and
   painting every item 195 ms).
6. **Export:** 53.6 ms per frame is 24 min for 27 000 frames (and ~45 s of AAC); linear, on battery.
   Autosave is 23 ms at 344 KB (every 30 s on the GUI thread); the 650-checkpoint idle pass is ~17-22 s of
   background work at 26-34 ms each.

### B65 — Manim's 3D camera at the default view · 2026-10-17
`.cache/gp/probe3d.py` (a probe, battery): the showcase project's frames at 12 times, drawn by
Manim's `Camera` and by `ThreeDCamera` at phi = 0, theta = -90 degrees, 640x360. Maximum pixel
difference **0** on every frame (the frames are drawn: 15 939 lit pixels mid-scene); tilting the
3D camera 60 degrees changes the picture (mean difference 5.9). Time per frame: 2D **6.2-7.1 ms**,
3D **7.8-8.7 ms** (about 25 % more). -> P7.5, decision session 43.

### B66 - P7.2: the long scene made linear · 2026-10-17
`benchmarks/bench_long_scene.py --model-only` and `--quick`, before (master at B65) and after, on a
machine that was sharing its CPU with other jobs (single runs scatter by 2-3x: one quiet run
gave timeline sync 14.5 ms at 295 layers, the next three 54-170), so the table is the **minimum of 15
repeats** of a probe (`.cache/p7-2/micro.py`) that rebuilds the index on every sync, plus the bench's own
numbers where they were stable.
- **Cause (B64's profile):** `Project.children / morph_sources / layer / root_of / ancestors` each scan every
  layer; the timeline, the Layers panel and `Evaluator.invalidate` asked once per layer. Fix: `core/layer_index.py`,
  one pass per snapshot (id, children and morph maps, memoised lifetimes), used by `TimelineView` (cached per
  snapshot, rows included), `LayersPanel.sync`, `parts.resolve/build_spec`, and the evaluator (`_index`,
  `invalidate`, `_builds`, its tree walks). Tests count the scans (constant against 8x the layers).
- **Timeline sync (min of 15):** 120 s / 300 s / 900 s (40 / 97 / 295 layers): 1.6 / 19.2 / **99** ms before,
  4.4 / 12.2 / **48** ms after - what is left is Qt (3250 `ClipItem`s and `QGraphicsScene.clear` take 75 % of a
  profiled sync at 295 layers) and grows 0.11 -> 0.13 -> 0.16 ms per layer. Bench: 124.8 -> 14.5 ms (the one quiet
  run), a layer moved in the real window 263 -> 44.5 ms (quiet) / 113-195 ms (loaded), 80 -> 50 ms at 300 s.
- **`Evaluator.invalidate` ("clip"/"spec"):** 0.3 / 2.9 / **32.7** ms -> 0.1 / 0.4 / **1.1** ms; an easing change
  end to end 48.4 -> 3.5-7.7 ms at 900 s; `update_layer`+`apply`+frame for a move 6.2 -> 2.4 ms.
- **Fit Timeline:** `MIN_PX_PER_SECOND` 10 -> 0.5; a 15-minute scene fits 1600 px at 1.7 px/s; the ruler labels a
  minute (`15:30`) from 30-second steps up.
- **Render-ahead (15 000 kept frames):** accept into a full store **9.43 -> 0.01 ms**, `missing(60)`
  **9.11 -> 0.01 ms** (a sorted index of the kept frames: the farthest frame is the one behind the playhead,
  kept runs are jumped by bisection). The bytes counted are the stored payload's `len`.
- **Evaluator memory (item 4) - the premise did not hold.** Eight visited slides cost +43 MB RSS, but the
  evaluator's own caches (`_base`, `_checkpoints`, `_active`, `_proxies`) hold about 1.6 MB of arrays and clearing
  them returned 0 MB: the mobjects are shared with the adapter's `lru_cache`s (`_build_cached`, `_subtitle_cached`,
  ... each `maxsize=256`), and **clearing those returned 29.7 MB**. So the growth is already bounded by
  the LRU sizes (about 0.3 MB per cached build): no 470 MB at 60 slides, roughly 100-200 MB at saturation; capping
  the evaluator's dicts would save ~3 MB. Left as is; lowering the adapter's `maxsize` is a speed/memory choice.
- **Audio memory (item 5):** not done - it changes the stored samples that the bit-identical level and export
  tests compare against (needs a decision on int16 storage and a span mix).

### B67 — Readable export of keyframed layers rendered by Manim · 2026-10-17
`benchmarks/bench_keyed_export.py` (G3a): the G3a test projects at 256x144, 10 fps - every
kind of key (each ease, a curved path overshooting, an anchor with a turn past 180 degrees,
opacity keys), keyed layers whose clips play while keys change (an overlay, a remover, a group,
a morph, a keyed path), the committed euler example, and the 32 built-in presets on a square and
a text - exported readable and rendered with `manim render`, 36 scenes and 1200 frames: worst
per-frame mean difference from the editor **0.57** (keys), **1.19** (clips; h264 on thin red
lines), **0.73** (euler), presets **1.17** (Focus: a soft translucent disc), keyed presets
**0.14**; Pop in on a circle at 640x360, 30 fps (a 0.25 s clip ending between frames) **0.14**.
Generation: 7-12 ms for a keyed project (first call 38 ms), 1.0 ms median per preset; keyed
files are 160-290 lines, about 120 of them helpers. Rendering all 36 scenes in two `manim render
-a` processes: **51 s** on battery. Found on the way: Manim adds whatever an animation plays on
to the scene (so the object must stay out of it: `KeyedClip`); in a frame every animation
interpolates, then mobject updaters run, then the frame is drawn (the drawing's dt updater sees
the clip's state); Manim lists what it draws when a play begins (a replaced drawing must be
emptied, not dropped); `renderer.time` is a sum of frame steps (rounded to the grid, else a
jumping ease is sampled on the wrong side); a held wait draws `int(t / dt)` frames and a drawn
one `ceil(t / dt)`, so waits are chosen to give both the same count. B44's exact case is now a
turned layer with a clip (keys are readable): 1.26. -> ADR 0046.

### B68 — The project camera · 2026-10-18
`benchmarks/bench_camera.py` (P7.5): the showcase at 640x360, 12 times x 5 repeats, each frame
drawn by the pre-P7.5 camera code, the new default camera and two turned cameras, interleaved.
Two runs on battery (medians, ms): pre-P7.5 2D **6.80 / 4.28**, default **7.24 / 4.50** (the same
`m.Camera`, built by the same arguments: the 5 % is the order in the loop and noise, p90 10.6 /
10.1 against 12.3 / 10.2), phi 60 **11.1 / 7.2**, phi 60 theta -45 gamma 10 **11.4 / 6.4** - a
turned camera costs about 50-70 % more per frame here (B65 measured 25 % for the 3D camera at the
default angles; why turning costs more was not measured).
The frames of the default camera are bit-identical to before (`tests/core/test_camera.py`). Found
on the way: Manim's `ThreeDCamera` subtracts `frame_center` twice (a pan moved the picture twice as
far and changed the angle: `StudioThreeDCamera`), and its rotation matrix is refreshed only at a
capture (a code frame painted first used the old angles). -> ADR 0048.

### B69 - P7.3: the timeline with every property row expanded · 2026-10-18
`benchmarks/bench_property_rows.py`: the explainer-like projects of the scaling tests (nine layers a
slide) at 45 / 99 / 297 layers, every object with a two-key opacity fade, `TimelineView.sync` on a new
snapshot plus deleting what it replaced, minimum of 15, offscreen.
- **First version:** collapsed 2.5 / 12.5 / 19.6 ms, every row expanded 18.9 / 44.2 / **731** ms - not
  linear. A profile put 90 % in `QGraphicsScene.clear`: the property row bands (a full-width rectangle
  item per row, 1188 at 297 layers) and, after they went, a clear that took longer on every rebuild of
  the same scene (3.5 -> 19 ms over 15 rebuilds of 1221 items; a fresh scene with as many items clears in
  3 ms) - inside PySide, not the BSP index (NoIndex changed nothing), not the view's updates, not GC.
- **Fix:** the bands are painted in `drawBackground` for the rows in view; a visible timeline rebuilds
  into a new `QGraphicsScene` (scene rect set first, so the scroll position stays) and drops the old one.
- **After:** collapsed 1.8 / 3.4 / 9.4-15.7 ms, every row expanded **2.4 / 5.4 / 18.8** ms (about 0.06 ms
  per layer); the header paints in 1.7 ms (rows in view only). Scans of the project per sync stay
  constant with every row expanded (`test_long_scene_scaling`). -> ADR 0047.

### B70 - P7.2 item 5: the sound mixed per span · 2026-10-18
`benchmarks/bench_audio_spans.py`: a 15-minute 44.1 kHz mono 16-bit tone (76 MB) under a 15-minute
scene; open, play 10 s from 5:00, move the sound (an edit heard while playing), the level meter at
three times, export 5:00-5:30 (160x90, so the sound dominates; in a fresh-process state). Peak RSS
sampled every 2 ms above the RSS after imports (114 MB). The same script run against master
(`PYTHONPATH=<old src>`) for "before"; single runs on battery.

| step | before (whole decode + whole mix) | after (spans) |
|---|---:|---:|
| open: probe, problems, waveform (GUI thread) | 1478 ms, +830 MB (decode on the GUI thread) | **57-73 ms**, +2 MB (scan in the background: 1.6-2.3 s, +8 MB) |
| play 10 s from 5:00: first sound | 1125 ms (whole mix + 16-bit copy) | **23-27 ms** (one window sought, one span) |
| move the sound: first playable chunk | 1165 ms, peak +1489 MB (two mixes cached) | **0.6-1.8 ms**, +15 MB |
| `level_at`, cold / warm window | 1.0-1.7 ms (the mix's files decoded) | 35-52 ms cold (a window decoded) / 0.6-1.0 ms |
| export 5:00-5:30 | 3201 ms | 1118-1381 ms |
| **process peak above imports** | **1490 MB** | **75-76 MB** (decoded windows held: 11.7 MB) |

- **Targets:** peak extra RSS well under 200 MB (target < 100): **76 MB, met**; mix rebuild after
  an audio edit independent of the scene's length, < 50 ms to the first playable chunk: **0.6-1.8
  ms, met** (it is one 0.25 s span); the first decode off the GUI thread: **met** for sounds
  longer than 60 s (shorter ones keep their waveform at once, ~0.1 s, so the timeline tests and
  small projects see no flat row).
- **Exactness:** every output sample is unchanged. `tests/core/test_audio_spans.py`: windows of
  wav (8-96 kHz, mono/stereo), FLAC, MP3, AAC (MP4 and ADTS) decoded on demand equal the same
  samples of the whole decode; random projects and spans equal the old whole mix
  (`np.array_equal`); the exported AAC track decodes to the same samples as the old one-frame
  encode, whole and for a range; the playback device's bytes equal `to_int16` of the whole mix
  from the playhead. ADR 0034's alignment tests, B58's window test and the existing export and
  level tests pass unchanged.
- **Measured on the way:** a resampler restarted mid-file differs in its first ~16 output samples
  (up to 0.025 at 11 kHz) without the 4096-sample warm-up; AAC after a seek differs by 1e-6 to
  1e-3 even with 3 s of warm-up (caught by the scan's window hashes: decoded from the start);
  MP3 (LAME CBR) and FLAC match after a seek; a float32 `np.arange(lo, hi)` differs from
  `np.arange(n)[lo:hi]` past 2**24 (the old level-window code had that latent difference for
  fades longer than ~350 s).
- **Costs left:** a cold level-meter or playback start at a new place decodes one window
  (~25-50 ms on the GUI thread); an AAC file read deep and at random decodes from its start each
  time no open reader is behind (bounded memory, seconds at 15 minutes); `audio.mix` (the exact
  Python scene's wav) still builds the whole mix, once, in the render process. -> ADR 0034
  amendment.

### B71 - P10.2: frozen objects against their sources · 2026-10-18
`benchmarks/bench_shapes.py`: a Text, a MathTex and the two Python object templates frozen into
shapes; the spec's JSON before and after, a build with Manim's disk cache warm (the source parses
its LaTeX/text SVGs again; a Python object is built twice, its first-use determinism check)
against building the shape from its data, an edit of another layer of the same project and a
save + load; minimum of 20, two runs.

| object | pieces / points | spec JSON | build (source -> shape) | edit elsewhere | save+load |
|---|---|---|---|---|---|
| Text "Hi ok" | 4 / 376 | 52 B -> 24.9 KB | 9.1-16.6 ms -> 0.65-1.8 ms | 0.14-0.32 ms | 0.4-0.7 ms |
| MathTex `e^{i\pi}+1=0` | 7 / 488 | 63 B -> 31.9 KB | 7.5-17.1 ms -> 0.94-2.2 ms | 0.17-0.30 ms | 0.5-1.1 ms |
| Matrix template, 3x3 | 13 / 816 | 1.4 KB -> 53.9 KB | 49-87 ms -> 2.0-3.9 ms | 0.33-0.54 ms | 1.0-1.2 ms |
| Right-triangle template | 3 / 20 | 1.2 KB -> 1.0 KB | 2.2-3.1 ms -> 0.9-1.2 ms | 0.13-0.17 ms | 0.1-0.2 ms |

- **Size:** floats at full precision are tens of KB per equation (a Text's glyphs keep a z of
  ~1e-17, so they are stored as [x, y, z]); far below the 4 MB / 300 000-point limit, so no
  rounding. -> ADR 0052.
- **Pixels:** identical (`np.array_equal`) to the source in every frame tested
  (`tests/core/test_shapes.py`).
