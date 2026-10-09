# S4 — Export dialog: implementation plan

- **Status:** In progress
- **Date:** 2026-10-09
- **Decided in:** [decision session 7](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** benchmark B25 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0017 exports run in a process and replace the output only when complete](../adr/0017-export-process-and-safe-output.md)

## Goal

Export a video from the editor without freezing it: progress, cancel, and a
previous video that is never damaged. **Done when** you can export from the UI
while editing (acceptance test).

## What is exported

The snapshot on screen when Export is clicked — saved or not. It is written to
`<cache dir>/exports/<uuid>.json` and rendered by `manim-studio render` in a
`QProcess` started in the editor's working directory (relative image paths
resolve as in the editor), with `--cache-dir` pointing at the editor's Manim
cache (no LaTeX recompiles). Later edits do not affect a running export.

## CLI

| flag | effect |
|---|---|
| `--cache-dir DIR` | Manim's cache (default: `PROJECT_DIR/.cache/manim`) |
| `--progress json` | one flushed JSON object per line: `{"frame": i, "total": n}`, then `{"done": path}`; `{"warning": text}` when relevant |

Output safety (also for terminal use): frames go to `<stem>.partial<suffix>`
beside the output; only a complete file replaces the output. On an error the
partial file is deleted. If the output is locked (open in a player on Windows),
the CLI retries for 2 s, then saves as `<stem> (2)<suffix>` (first free number)
and reports it.

## Editor

- **File > Export Video...** (Ctrl+E) opens a non-modal dialog: output path
  (default `<project dir or cwd>/out/<name>.mp4`, Browse), Export, a progress
  bar ("Starting..." for the ~4 s process start, then frames and ETA), Cancel,
  and on success "Exported to ..." with **Open folder**.
- One export at a time; editing continues meanwhile.
- Cancel kills the process and deletes the partial file and the snapshot JSON.
- Quitting during an export asks to cancel it first.
- Errors: the CLI's `error:` lines (or the last lines of stderr) in the dialog.

## Work breakdown

| step | content | acceptance |
|---|---|---|
| S4.1 | CLI `--cache-dir`, `--progress json`, partial file + replace + locked-target rename | CLI tests: progress lines, cache dir used, failure leaves the old output intact and no partial file, locked target renamed with a warning |
| S4.2 | `ui/export_job.py`: QProcess wrapper (`progress`, `finished`, `failed`, `cancel()`) | real subprocess on a tiny canvas: progress before exit, cancel cleans up, error reported |
| S4.3 | dialog, menu, quit guard | dialog states; quit while exporting asks |
| S4.4 | acceptance + docs | export from the UI while editing; the result is a playable video |
