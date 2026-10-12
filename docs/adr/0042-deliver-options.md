# 0042. Deliver options: size, fps, range, quality, subtitles and a render queue

- **Status:** Accepted
- **Date:** 2026-10-12
- **Deciders:** João Victor

## Context

Export (ADR 0017) rendered the whole scene at the project's canvas size and frame rate, at one
quality, from a dialog that ran one video at a time. The Deliver page (ADR 0041, P6b.5) needs to
choose a size, a frame rate, a part of the scene, a quality and what happens to the subtitles, and
to line several exports up. The renderer is `manim-studio render` in its own process (ADR 0017),
and code layers are rendered by that command into a cache keyed by canvas size and fps (ADR 0019).

## Decision

- **Options are flags of `manim-studio render`**, parsed into a frozen `RenderOptions`
  (`render/options.py`, no Qt, no Manim): `--size WxH`, `--fps N`, `--start S`, `--end E`,
  `--crf N` (0-51, default 18 as before) and `--subtitles burn|srt|none`. The page and the CLI
  share the type; `ExportJob(options=...)` turns it into flags. Bad options exit with code 2 and
  one message, before any code runs or any file is written.
- **Size and fps** are applied by one pure function, `apply_options`, to a copy of the project's
  canvas: both sides are made even (H.264 with 4:2:0 chroma needs it; halves go up), `frame_height`
  and the duration stay, so the picture is framed exactly as in the editor. The presets (480p to
  2160p) are heights at the canvas's aspect ratio. Code layers are rendered *after* the options
  are applied, so they are drawn at the exported size (their cache key contains it). A different
  fps also changes simulated layers and traces a little, because they step at `1/fps`.
- **A range is the frame window `[a, b)`**, `a = round-half-up(start * fps)`, `b` likewise for
  `end` (default and maximum: the scene's last frame). Output frame `k` shows time `(a + k) / fps`.
  A range that is empty after rounding (shorter than one frame at that fps), starts after the
  scene ends, or ends before it starts is an error. The mix is sliced to the same window and padded
  with silence if short, so a sound at 2 s in a range from 1 s plays at 1 s; the `.srt` is shifted by
  `a / fps` and cut at both edges (a cue straddling an edge is clipped, one outside is dropped; no
  cue in the range: no file).
- **Subtitles**: `burn` draws them into the video and writes an `.srt` beside it (what exports did),
  `srt` only the `.srt`, `none` neither. Without the flag the project's own burn-in setting rules.
- **A render queue** (`ui/render_queue.py`, no Qt): jobs are *queued*, *rendering*, *done*, *failed*
  or *cancelled*; Start runs the queued jobs in order, one `ExportJob` at a time; Cancel works on the
  selected (or the running) job and the queue goes on; a rendering job cannot be removed; Clear
  finished drops the finished ones. **A job holds the project as it was when it was added**
  (documents replace their project on every edit, so this is a reference), its options and its
  output path, and whether code layers may run (decided then, like the snapshot). What was queued is
  what renders; edits made while the queue runs change nothing already queued. A pending job's output
  path is never reused: the next gets `name (2).mp4`.
- **File > Export Video...** keeps the quick dialog (ADR 0017); the Deliver page is the full path. The
  editor asks before quitting while the queue renders and then stops it, removing the partial video.
- **Python panel**: `to_python` of the current project, recomputed 0.4 s after the last edit while the
  page is shown, with the reasons an exact scene is exact; Save as... is File > Export Python... (ADR 0031).

## Consequences

- The command line can do everything the page does.
- Rendering a range or a smaller size is proportionally cheaper (B59); a range from a marker costs
  the frames before it nothing, except simulations and traces, which are replayed from frame 0 (ADR 0033).
- The queue holds a reference to each project until the job is removed.
- The quick dialog and the queue can render at the same time (two processes).
- Queued jobs are lost when the editor quits (cancelled, not saved).

## Alternatives considered

- **A live project at run time** - the output would depend on when the job runs, and a later edit or a
  closed project would change a promise already made.
- **Baking size, fps and burn-in into the snapshot JSON** - the CLI would not gain the options, and the
  range cannot be baked into a project without trimming clips.
- **Keeping the dialog as the only exporter** - no queue, no range.

## Evidence

- Tests: `tests/render/test_options.py`, `tests/ui/test_render_queue.py`,
  `tests/ui/test_deliver_page.py`, `tests/ui/test_acceptance_p6b5.py`.
- B59 in [../logs/benchmarks.md](../logs/benchmarks.md); decision session 38
  ([../logs/decision-sessions.md](../logs/decision-sessions.md)); plan
  [../plans/p6b5-deliver.md](../plans/p6b5-deliver.md).
