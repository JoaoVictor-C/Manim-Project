# 0010. Python round-trip is one-way export

- **Status:** Accepted (implemented by [0031](0031-python-export.md))
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

Users may want to see or continue in Manim code. Importing existing Manim scripts
would need executing and understanding arbitrary Python (loops, updaters,
custom classes).

## Decision

- **Import of Manim code is out of scope.**
- **Export to Python** (later) is one-way: compile the timeline into readable
  `self.play(...)` / `self.wait(...)` segments; when a timeline cannot be
  expressed that way, emit a scene that loads the project file through this
  package, which is always exact.
- Correctness never depends on generated code; video export uses the evaluator.

## Consequences

- No parser for Python; the JSON document stays the only source of truth.
- A future "capture importer" (run trusted code with `play` patched to record
  clips) is possible but lossy and not planned.
