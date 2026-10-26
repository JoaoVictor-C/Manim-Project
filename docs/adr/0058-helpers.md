# 0058. Helpers: project modules that code layers and Python objects can import

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** João Victor
- **Amends:** [0019](0019-code-layers.md) (what trust covers), [0051](0051-python-objects.md) (what a build can import)

## Context

Code layers and Python objects are single files. Anything reused - a function that draws a grid, a colour
palette, a formula, data - has to be copied into each one. The user asked to import helpers, or make them
inside the app, "similar to new object but for helper functions or other things that are not necessarily
Manim".

## Decision

1. **A helper is a module of the project**: `Project.helpers: list[Helper]`, `Helper(name, code,
   description="")`, saved in the project file (omitted when empty). It is plain Python, not necessarily
   Manim: functions, classes, constants, data. The Code page lists helpers with the code layers.
2. **Importable by name**: in a code layer, a Python object or another helper, `import grid_tools` or
   `from grid_tools import make_grid` works. Names are Python identifiers, unique, and must not shadow the
   standard library, Manim, numpy or the names the runners provide (`np`, `math`, `m`). Limits: 64 KB per
   helper, 50 helpers.
3. **How it is imported** (`core/code/helpers.py`, pure): while user code runs, a meta-path finder serves the
   project's helper sources as modules (`__file__` = `<helper name>`, so tracebacks say where an error is);
   the modules are removed afterwards, so an edit is always picked up. A helper may import another.
4. **Trust is per helper and enforced where the import happens.** Helper code is a program like any other
   (ADR 0019): the finder serves only helpers whose own hash is in the trust store, and an untrusted helper
   raises `ImportError` saying to select it and press Run. Static scanning (`imports_of`, `needed`) is only
   for showing a layer what it needs and for opening a project ("these helpers ask to run"); it is not the
   gate. Run on a helper applies its text, trusts it, and imports it once in a throwaway process so its
   top-level errors and prints show in the Output.
5. **Caches**: the signature of every code layer and Python object includes `helpers.digest(project)`, so
   editing a helper rebuilds all of them (coarse on purpose: correct without dependency tracking).
6. **Export and CLI**: the readable and exact Python exports embed the helpers a scene imports as modules
   registered before use; `render --trust-code` trusts helpers as well.
7. **Where they come from**: New helper (a starter with a docstring), the import window (a file with
   neither a `build(p)` nor a Scene is offered as a *helper*), presets of kind `helper` (the library, the
   internet and drag and drop use the same flows), and "Extract to helper" from a selection.

## Consequences

- Reuse without copying; a shared helper file can be published like any preset.
- A project that uses helpers asks once for each, like its code layers.
- A helper's top level runs inside the build and render processes of every layer that imports it, so a slow
  helper slows those builds (the 30 s build limit still applies).
- Project format: a new optional `helpers` list (documented in `docs/project-format.md`); older files are
  unaffected.
