# P4a — Python export

- **Status:** Done
- **Date:** 2026-10-10
- **Decided in:** [decision session 23](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** B43 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0031 — Python export](../adr/0031-python-export.md)

## Goal

**Done when** File > Export Python... writes a `.py` that `manim render` turns
into the same video as the editor's export: readable `self.play` code for a
simple project, an exact scene (with the reasons in its header) otherwise.

## Core: `core/engine/python_export.py`

- `readable_problems(project) -> list[str]`: why the project cannot be readable
  (empty = readable).
- `to_python(project, scene_name) -> PythonExport(code, readable, problems)`.
- Readable code:
  - config lines (pixel size, fps, frame size, background);
  - helpers only when used: `clamped(f)`, `cubic_bezier(x1, y1, x2, y2)`;
  - per layer, in layer order: `name = Type(params)` (text positional, points as
    `[x, y, 0]`), style (`set_fill`/`set_stroke`), `move_to(ORIGIN)`, static
    `scale`/`rotate` about the anchor, `shift`, `fade(1 - opacity)`,
    `set_z_index(i)`;
  - events in time order: `self.add` at a lifetime start without an introducer,
    clusters of overlapping clips as one `self.play`
    (`AnimationGroup(a, Succession(Wait(d), b))`, `run_time` = the cluster's
    span), `self.remove` at explicit lifetime ends, `self.wait` for gaps;
  - kinds by Manim class; Transform-family morphs with
    `replace_mobject_with_target_in_scene=True`; MoveAlongPath with a fresh rest
    shape of its path; Wiggle with its pivots at the object's centre; eases:
    named → `rate_functions` names, Bézier → `cubic_bezier`, clamped when they
    leave [0, 1] on content/emphasis clips.
  - Names from layer names or ids, made valid and unique; floats by `repr`;
    checked with `compile()`.
- Exact code: the project JSON in a raw string, `configure(PROJECT)` and a
  subclass of `manim_studio.manim_scene.StudioScene`.

## `manim_studio/manim_scene.py`

- `configure(project_json)`: pixel size, fps, frame size, background in Manim's
  config.
- `StudioScene`: a holder whose dt updater sets its submobjects to the
  evaluator's frame at `self.renderer.time`, then `wait(duration)`; its camera
  paints `CodeFrame`s (code layers) through `display_funcs`.

## UI / CLI

- File > Export Python... (save dialog, `.py`); the status bar says "readable"
  or "exact: …reasons".
- `manim-studio python PROJECT OUT.py [--scene NAME]`.

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P4a.1 | generator, StudioScene | problems for each excluded feature; snapshot of a fixed project's readable code; both forms rendered by Manim equal our frames (codec noise) |
| P4a.2 | menu, CLI | export from the menu; CLI writes the file |
| P4a.3 | acceptance, benchmark script, docs | a project exported both ways from the editor and rendered with `manim render` |
