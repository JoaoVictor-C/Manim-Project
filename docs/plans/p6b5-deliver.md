# P6b.5 — The Deliver page

- **Status:** Done
- **Date:** 2026-10-12
- **Decided in:** [decision session 38](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.91)
- **Evidence:** B59 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADRs:** [0041 — Workspace pages](../adr/0041-workspace-pages.md), [0042 — Deliver options](../adr/0042-deliver-options.md)
- **Parent plan:** [p6b-pages.md](p6b-pages.md), step P6b.5

## Goal

**Done when** the Deliver page (Shift+5 in the end) lets you set up an export (file, size,
fps, range, quality, subtitles), add it to a queue, run several exports one after another
in the real export process, and save the Python scene with a readable/exact preview - and
both exported files have the right frame count, size and sound.

## Decisions (session 38)

- **Snapshot at queue time.** A queued job holds the `Project` as it was when "Add to queue"
  was pressed (documents replace their project on every edit, so this is a reference, not a
  copy), plus its options, output path and whether code layers may run (trust is fixed when
  the job is added, like the project). What was queued is what renders; editing while the
  queue runs changes nothing already queued.
- **Options are CLI flags** of `manim-studio render`: `--size WxH`, `--fps N`, `--start S`,
  `--end E`, `--crf N`, `--subtitles burn|srt|none` (ADR 0042). They are parsed into a frozen
  `RenderOptions` (`render/options.py`, no Qt) and applied by one pure function
  (`apply_options`: canvas width/height - even - and fps; `frame_height` unchanged so the
  framing is the same; burn-in). Code layers are rendered by the CLI after the options are
  applied, at the new size (their cache key contains the size and fps).
- **Range = frame window `[a, b)`**, `a = round(start * fps)`, `b = round(end * fps)`
  (clamped to the scene's frames; empty after rounding is an error). Output frame `k` shows
  time `(a + k) / fps`; the audio mix is sliced to the same window (padded with silence if
  short); the `.srt` is shifted by `-a / fps` and clipped at both edges.
- **Queue** (`ui/deliver/render_queue.py`, no Qt): statuses queued / rendering / done / failed /
  cancelled; Start runs queued jobs in order, one `ExportJob` at a time; Cancel cancels the
  selected job (the queue goes on); Remove (not while rendering); Clear finished. A job whose
  output path equals a pending job's gets ` (2)`.
- **File > Export Video...** keeps the quick dialog (its tests pin it); the page is the full
  path. Closing the editor asks first while the queue renders, then cancels.
- **Python panel**: `to_python` of the current project, recomputed 0.4 s after an edit while
  the page is shown; Save as... goes through the window's `ask_python_path` / `write_python`.

## Layout

The shared viewer on the left; on the right Render settings, the queue and the Python
scene stacked in a splitter.

## Steps

| step | content | acceptance |
|---|---|---|
| 1 | `render/options.py`, CLI flags, exporter window/crf/srt | unit tests: sizes, window, audio slice, srt clip; real renders |
| 2 | `ui/deliver/render_queue.py` | state machine tests |
| 3 | `ui/pages/deliver.py`, registered after Compose | `tests/ui/pages/test_deliver_page.py` through `MainWindow` |
| 4 | acceptance (slow): two exports with different sizes/ranges, Python scene saved | `tests/acceptance/test_acceptance_p6b5.py` |
| 5 | mutation check, docs | `.cache/p6b5/mutate.py` |

## Result

Quick lane 1413 passed, full suite 1475 passed. A mutation run over the options, exporter, CLI, queue and
page guards (74 mutants) first left 7 alive: one was a real defect (a late `finished`/`failed` from a
cancelled job overwrote the next job's status and dropped its process handle - now ignored), three were
redundant guards (removed), one was equivalent (`audio.mix` of the options-applied project, simplified),
and two needed tests (progress after cancel; an unrelated edit keeps the form). All 74 are killed now.

## Risks

- `fps` override changes simulated layers and traces slightly (they step at `1/fps`).
- Two exports can run at once (the quick dialog and the queue); each is its own process.
