# 0017. Exports run in a process and replace the output only when complete

- **Status:** Accepted (implemented in S4, 2026-10-09)
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

Exporting renders every frame with Manim's Cairo camera and encodes it with
PyAV: 84 frames/s at 1280x720, after ~4 s of process start-up (B25). Rendering
in the editor's process would hold the GIL and freeze the UI. Killing a render
mid-way leaves a 48-byte unreadable file at the output path, destroying any
previous video there (B25). On Windows, replacing a file that a video player
holds open fails (B25). Output read through a pipe is block-buffered unless
flushed, so progress would arrive only at exit (B25).

## Decision

- The editor exports **the current snapshot** (saved or not) by writing it to a
  JSON file in its cache directory and running `manim-studio render` in a
  `QProcess`, with `--cache-dir` (the editor's Manim cache) and
  `--progress json` (flushed JSON lines).
- The renderer writes to `<stem>.partial<suffix>` beside the output and replaces
  the output **only with a complete file**; on error the partial file is
  deleted. If the output is locked, it retries for 2 s, then saves under the
  first free `<stem> (n)<suffix>` and reports the path.
- Cancelling kills the process; the editor removes the partial file and the
  snapshot JSON.

## Consequences

- The UI stays responsive; exports start ~4 s late (process start-up).
- A previous video is never damaged by a cancelled, crashed or failed export.
- Terminal users of `manim-studio render` get the same safety.
- The CLI is now a small protocol the editor depends on (tested in both directions).

## Alternatives considered

- **Render in a thread** — Cairo and Manim hold the GIL; the UI would stall.
- **Export the saved file only** — forces a save and recompiles LaTeX in the
  project folder's cache.
- **Keep a `.partial.mp4` when the output is locked** — a successful render
  reported as a failure, under a misleading name.

## Evidence

- Benchmark B25 in [../logs/benchmarks.md](../logs/benchmarks.md).
- [Decision session 7](../logs/decision-sessions.md).
