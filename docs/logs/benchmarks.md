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
