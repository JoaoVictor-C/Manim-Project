# P4b — Plugin API for custom objects

- **Status:** In progress
- **Date:** 2026-10-11
- **Decided in:** [decision session 24](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** B45 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0032 — Plugins add object types](../adr/0032-plugin-api.md)

## Goal

**Done when** a `.py` file dropped in the plugin folder adds an object to the
library that you can place, edit in Properties, animate with clips, render ahead
and export (video and Python), and a project using a type nobody provides opens
with a placeholder and a message.

## `manim_studio/plugins.py` (public)

```python
from manim_studio.plugins import ObjectType, Param, register

def build(params):
    ...  # returns a VMobject, a pure function of params

register(ObjectType("Pendulum", build, params=(Param("length", "float", 2.0),), section="Physics"))
```

- `ObjectType(name, build, params=(), section="Plugins", label=None, slow=False)`.
- `register` adds it to `MOBJECT_TYPES`, `MOBJECT_PARAMS`, `LIBRARY` (its section
  after the built-in ones) and `LIBRARY_LABELS`; a taken name raises.
- `unregister(name)` (tests), `loaded` (plugin → types), `problems` (plugin →
  error).
- `load_plugins()`: entry points (group `manim_studio.plugins`; a module whose
  import registers, or a callable that is called), then `*.py` in the
  `MANIM_STUDIO_PLUGINS` folders (os.pathsep list; default
  `~/.manim-studio/plugins`), sorted, as modules `manim_studio_plugin_<stem>`.
  Called at the end of `core/adapter.py`.

## Building

- `build_mobject` for a plugin type calls `build(params)` (defaults filled,
  points as `[x, y, 0]`), checks the result is a VMobject, applies style and
  centres it. The first build of each type in a process builds twice and
  compares points and colours.
- Failures and unknown types return the dashed placeholder;
  `build_problem(spec)` (was `media_problem`) gives the reason;
  `Evaluator.build_errors()` (was `media_errors`) feeds the status message.
- `warm_key` for `slow` plugin types; Python export: plugin types → exact.

## UI

- Library sections from plugins; Help > Plugins... (loaded plugins, their types,
  problems); a status message at startup when a plugin failed.
- `examples/plugins/pendulum.py`.

## Tests

- conftest sets `MANIM_STUDIO_PLUGINS` to an empty folder.

| step | content | acceptance |
|---|---|---|
| P4b.1 | module, loading, registries, building, checks, placeholders, warm, export | a plugin folder adds a type; failures listed; determinism check; unknown type → placeholder + reason; clip harness on a plugin object |
| P4b.2 | library sections, Plugins dialog, startup message | add from the library; dialog lists plugins and problems |
| P4b.3 | acceptance, example, docs | the Goal's scenario with a real plugin folder (export process and preview process included) |
