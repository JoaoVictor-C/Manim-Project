# 0011. Logging: console plus per-user rotating file

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

The editor is a GUI app: errors that happen while users work must be
recoverable after the fact. Manim logs every LaTeX compile at INFO through its
own rich handler, which floods the console.

## Decision

`manim_studio.logging_config.setup_logging(verbosity)`, called by the CLI and by
the editor when launched directly:

- logger namespace `manim_studio.*`; modules use `get_logger(__name__)`;
- console: WARNING by default, `-v` INFO, `-vv` DEBUG;
- file: DEBUG, rotating (2 MB × 3) at `%LOCALAPPDATA%\ManimStudio\logs\manim-studio.log`
  (Windows) or `~/.local/state/manim-studio/logs/` — override with
  `MANIM_STUDIO_LOG_DIR`;
- Manim's logger capped at WARNING.

What to log: project open/save/export (INFO), invalidation decisions and
timings (DEBUG), every caught exception with traceback (`log.exception`).
Never log document contents in bulk.

## Consequences

- Bug reports can attach the log file.
- Logging failures (read-only disk) never stop the app.
