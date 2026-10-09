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
