# P12 - Code workspace

Status: in progress. Asked for: (1) exporting onto an existing file asks replace / skip / keep both;
(2) the Code page reworked after a code editor's workspace, everything customisable, importing a file
opens a window to set its properties first (object or layer, with the right one preselected);
(3) importing presets from the internet; (4) presets and code usable from the timeline and the scene by
dragging; (5) everything else left to us.

## Slices

| Slice | What | Where |
|---|---|---|
| P12.1 | Core: reading/inspecting/exporting code files, the conflict policy | `core/code_files.py` |
| P12.2 | Core: the preset library (built-in + yours + online), saved in a file | `core/preset_library.py` |
| P12.3 | Core: fetching presets from the internet, safely | `core/preset_online.py` |
| P12.4 | Dialogs: conflict (replace / skip / copy, "for all"), import (properties before adding) | `ui/` |
| P12.5 | The Code page as a workspace: explorer, tabs, panel, status bar, quick open | `ui/pages/code.py`, `ui/code_*.py` |
| P12.6 | Online presets window | `ui/online_presets_dialog.py` |
| P12.7 | Drag and drop: presets and code layers to the timeline / canvas / layers; `.py` files from the desktop | timeline, canvas, layers panel |

## Contracts (so the slices can be built apart)

**Source kinds.** `object` = a Python object (`PARAMS` + `build(p)`, ADR 0051). `scene` = a Manim
scene (a code layer, ADR 0019). `unknown` = neither.

**`core/code_files.py`** (no Qt)

- `read_source(path) -> str`: UTF-8 with or without a BOM; at most 1 MB; raises `SourceError(reason)`.
- `inspect(source, filename="") -> Inspection(kind, scenes, params, problem, suggested_name, summary)`:
  syntax only, never runs anything.
- `safe_stem(label, fallback) -> str`: a file name stem that is valid on Windows (no reserved names,
  characters, trailing dots/spaces).
- `free_name(filename, taken) -> str`: `Name (2).py`, case-insensitive against `taken`.
- `export_files(items, folder, decide) -> ExportResult`: writes `.py` files (UTF-8, no BOM, atomic).
  `decide(filename) -> "replace" | "skip" | "copy" | None` is asked only when the file exists;
  `None` cancels the rest. Result lists written / replaced / copied / skipped / failed.

**`core/preset_library.py`** (no Qt)

- `Preset(id, name, kind, code, origin, description, tags, source_url)`; origin is `builtin`, `user`
  or `online`.
- `PresetLibrary(path)`: built-in presets (from `python_templates`) first, then the saved ones;
  `add / remove / rename / get / presets()`; saved as JSON (`{"format": 1, "presets": [...]}`) at
  `MANIM_STUDIO_PRESETS` or next to the settings file; unreadable files are set aside, never raise.
  `import_legacy(templates: dict[str, str])` moves the old `python_code_templates` setting in.

**`core/preset_online.py`** (no Qt, standard library only)

- `resolve(url) -> list[OnlineEntry]`: a `.py` URL, a manifest (`{"format": 1, "presets": [{"name",
  "file", "description", "kind"}]}`), or a GitHub file / folder / gist link.
- `fetch_entry(entry) -> str`: the text, size-capped. HTTPS only (plain HTTP only for localhost).
  Downloaded code is data: nothing is imported, compiled or run here, and it is untrusted until the
  user runs it.

**Drag and drop (MIME).** `application/x-manim-studio-code`, UTF-8 JSON
`{"from": "preset" | "layer", "id": str, "name": str, "kind": "object" | "scene"}`. A drop target calls
`window.place_code(payload, t=None, position=None)`; a `.py` file dropped from the desktop calls
`window.import_code_files(paths, t=None, position=None)` (opens the import window).
