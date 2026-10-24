# P13 - Code assistance and helpers

Status: in progress. Asked for: everything from the Code page review (plain-language errors, live syntax
marker, history and revert, a parameters-definition panel, snippets, tags and search, thumbnails,
completion and hover, outline, Live mode and a Values tab, cancel, run to cursor, copy as Manim code) and
**helpers**: importing, or creating inside the app, reusable Python modules (functions, constants, data,
anything - not necessarily Manim) that code layers and Python objects can `import`, made like "new
object" but for helper code.

The review behind this plan is in the session notes; the decisions that matter are in ADR 0058 (helpers)
and in the list below. Order is ours to decide.

## Order

| Slice | What | Where |
|---|---|---|
| P13.0 | `manim_names.json` + generator + version stamp | `core/manim_names.json`, `scripts/gen_manim_names.py` |
| P13.1 | Structured errors from both runners; `error_hints` with did-you-mean; `diagnostics` (syntax); error tally | core + the two runners |
| P13.2 | Helpers: model, import machinery, trust, cache signature, export, CLI | `core/helpers.py`, schema, adapter, runners, python_export |
| P13.3 | Pure helpers for the UI: snippets, PARAMS editing, code history, outline, run-to-cursor, preset search/tags | `core/snippets.py`, `params_edit.py`, `code_history.py`, `outline.py`, `run_to_cursor.py` |
| P13.4 | UI: hints and syntax marker, elapsed time, history/revert/diff, Parameters definition, trust wording | `ui/pages/code.py` and new `ui/` modules |
| P13.5 | UI: helpers (explorer section, tabs, New helper, import as helper, presets of kind helper) | same |
| P13.6 | UI: snippet gallery, tags/search, outline, completion and hover, thumbnails | same |
| P13.7 | UI: Live mode, Values tab, Cancel for code layers, Run to cursor, Copy as Manim code | same |

## Contracts

**Structured errors (P13.1).** A runner error message carries `{"error": str, "type": "NameError",
"line": int | None, "where": "code" | "helper:<name>", "traceback": str (at most 4 KB)}`; `CodeStatus` and
`CodeProblem` gain `error_type`, `where` and `traceback` (all optional, default empty, so old messages still
work). `core/error_hints.hint(error_type, message, source) -> Hint | None`, `Hint(text, suggestions)`.
`core/diagnostics.syntax_problem(source) -> SyntaxProblem(line, column, message) | None`.
`core/manim_names.json`: `{"manim_version": "0.22.0", "names": [...], "methods": {class: [...]}, "kwargs":
{callable: [...]}}`; `core/manim_names.py` loads it lazily.

**Helpers (P13.2)** - see ADR 0058. `Project.helpers: list[Helper]`; `Helper(name, code, description="")`;
`core/helpers.py` (pure): `check_name`, `imports_of`, `needed(project, code)`, `digest(project)`,
`install(sources)` (context manager), edits `add_helper`, `update_helper`, `rename_helper`,
`remove_helper` in `core/edits.py`.

**Pure UI helpers (P13.3).**

- `snippets.SNIPPETS: tuple[Snippet(id, title, category, description, code)]`, code with `${1:default}` tab stops;
  `snippets.expand(code) -> (text, stops)`.
- `params_edit.edit_params(source, op) -> str`, raising `ParamsEditError(reason)`; ops: add, remove, rename,
  change (kind / default / min / max). Only the `PARAMS` assignment's own span is rewritten.
- `code_history.CodeHistory`: chains keyed by (layer id, content chain); `record(layer_id, text, working)`,
  `last_working(layer_id, before=None)`, `versions(layer_id)`, `diff(a, b)`; caps 50 versions and 1 MB per chain;
  `forget(layer_id)`.
- `outline.symbols(source) -> list[Symbol(kind, name, line)]`.
- `run_to_cursor.truncate(source, line) -> str | None`.
- `PresetLibrary.search(query)`, `set_tags(id, tags)`, `tags()`.
