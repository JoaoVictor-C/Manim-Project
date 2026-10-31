# 0066. Export health report: what will be slow or will not work, found before the export starts

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

An export of the five-minute angular momentum project took 7.5 minutes cold ([0065](0065-parallel-export-and-gpu-encoding.md)),
about half of it rendering code layers at the export size, and nothing said so: the dialog read "Starting the
renderer" for minutes. Other things go wrong silently: code and Python objects not trusted are drawn as placeholders,
an 8K export asked for on the card opens an encoder that cannot do it and falls back to x264 only after the cost,
and a video can fill the disk. Each is knowable from the project, the options and the cache folders.

## Decision

- `processes/export_health.py`: `check(project, options, cache_dir, output, trust_code, frame_seconds)` returns a
  `Report` of `Finding(severity, title, detail, seconds)` ordered problem, warning, info and by time. It never runs the
  user's code, starts LaTeX or draws a frame, so the Deliver page shows it on every change. Checks: code layers missing
  from the frame cache (0.8 s of rendering per second of scene, shared by the runners the plan would use, never less
  than the longest layer; a layer's scene is capped at the scene's duration, as an unrendered layer has no end); layers
  and Python objects that will be placeholders for lack of trust; LaTeX objects against the LaTeX files in the cache
  (a heuristic: Manim names files by a hash of the whole composed expression, which is not reproduced here); frame size
  and memory; above 4K; the encoder, including that the card's H.264 stops at 4096 px on a side (now enforced by
  `encoders.candidates`, which sends 8K to x264 at once); free disk against the estimated video.
- The cost of a frame is measured only on request (`measure`: a few frames drawn here), so only the command line does it.
  `manim-studio render PROJECT OUT --check` prints the report and exits (1 on a problem); the Deliver page shows the
  warnings and problems (up to four) under its summary.

## Consequences

- The code-layer figure comes from one project; the estimate says "about" and the findings are advice, never a gate:
  the page ignores a failure of the check itself.
- The LaTeX check can say too much (a warm cache holding other projects' drawings) or too little; it is `info`.

## Alternatives considered

- **Time every stage by running it** - that is the export.
- **A modal "are you sure" before slow exports** - the user asked for the export; a line under the summary informs
  without getting in the way.

## Evidence

- Tests: `tests/processes/test_export_health.py`, `tests/ui/pages/test_deliver_page.py::test_the_page_warns_about_what_an_export_cannot_do`.
- Measured on the real project: [logs/benchmarks.md](../logs/benchmarks.md) B75.
