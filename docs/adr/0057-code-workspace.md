# 0057. The Code workspace: presets, an import window, safe online sources and drag and drop

- **Status:** Accepted
- **Date:** 2026-10-24
- **Deciders:** João Victor
- **Amends:** [0041](0041-workspace-pages.md) (the Code page), [0051](0051-python-objects.md) (where object templates live)

## Context

The Code page held a list of code layers, a few templates in the code, and some buttons that wrote and
read `.py` files directly. The user asked for: a question (replace, skip, keep both) when an export
meets a file that exists; the page reworked after a code editor's workspace; importing a file to open a
window where its properties are chosen first, including whether it becomes an object or a layer (the
right one preselected); importing presets from the internet; and presets usable from the timeline and
the scene by dragging.

## Decision

1. **Files** (`core/code_files.py`, no Qt): reading (UTF-8 with or without a byte-order mark, at most
   1 MB), syntax-only inspection (`object`, `scene` or `unknown`; the scene classes, `PARAMS`, a name and a
   summary - nothing runs), Windows-safe names, and `export_files`, which writes atomically and asks
   `decide(file name)` - `replace`, `skip`, `copy` (`Name (2).py`) or `None` to cancel - only when the
   file exists. The window's `ConflictAsker` adds "do this for the rest". A preset name that is taken
   asks the same way (`CodeImporter.store_preset`); a built-in preset is never replaced.
2. **The import window** (`core/code_import.py`, `ui/import_code_dialog.py`): for each file, what it can
   become - a Python object, a Manim scene (one code layer per chosen scene) or a preset only - with the
   detected kind preselected, the impossible ones disabled with the reason, and name, scenes, when and
   where it appears, "allow it to run now" (off) and "also keep as a preset". The same window serves
   files chosen, a folder (preselecting "preset only"), files dropped from the desktop and presets
   downloaded. Newlines are made plain and a byte-order mark is dropped, so the editor never shows an
   imported layer as edited.
3. **Presets** (`core/preset_library.py`): one library of built-in (from `python_templates`, never
   saved), yours and downloaded presets, saved as JSON beside the user's other data
   (`MANIM_STUDIO_PRESETS`), never raising on a damaged file (it is set aside as `.bad`). The old
   `python_code_templates` setting moves in once.
4. **The internet** (`core/preset_online.py`, standard library only): `resolve(link)` understands a `.py`
   link, a manifest (`index.json`, format 1: `{"format": 1, "presets": [{"name", "file", "description",
   "kind"}]}`, files relative to it), GitHub files, folders, repositories and gists. HTTPS only (plain
   HTTP for localhost, for tests), redirects limited and never from https to http, 1 MB per file, a
   timeout, friendly errors. Downloaded text is only a string: it is never imported, compiled or run
   where it is fetched, and a layer made from it is untrusted until the user runs it (a preset the editor
   ships is trusted like its starter). Exporting can write an `index.json` so a folder can be put on the
   internet and imported again by its link. No source is built in: the user pastes links, and the ones
   used are remembered.
5. **The workspace** (`ui/pages/code.py` and `code_explorer`, `find_bar`, `quick_open`, `editor_settings`):
   an explorer with this project's layers and the preset groups; tabs with a dot for unapplied changes;
   a read-only preview for presets (add to the project, edit a copy, rename, delete, export); a find and
   replace bar; go to line (`Alt+G`; `Ctrl+G` is Group); quick open (`Ctrl+P`); an output panel
   (`Ctrl+J`) and a status strip; every editor setting in a menu and remembered (font size, indent size,
   wrapping, line numbers, whitespace, current line, bracket pairing, trimming on run); editing commands
   (comment, duplicate, move, delete line, zoom).
6. **Drag and drop** (`ui/code_drag.py`): explorer rows drag out as `application/x-manim-studio-code`
   (JSON: from `preset`/`layer`, id, name, kind). The timeline (the drop time, snapped like clips), the
   canvas (the drop point in scene units) and the layers list accept them and call
   `MainWindow.place_code`; `.py` files dropped there or on the explorer or the editor call
   `import_code_files`. A dropped preset or layer is added where it was dropped (time -> "appears at",
   point -> position) in one undo step; the hooks run after the drop so the import window never opens
   inside the system drag loop.

## Consequences

- Nothing is written over a user's file or preset without being asked, and "Cancel" stops cleanly.
- Code that arrives from the internet or a file cannot run until the user allows it, in the same way
  as code in a project they open (ADR 0019).
- The old `list`-based page API is gone (`page.explorer` replaces `page.list`); the tests use the
  helpers in `tests/ui/code_page_helpers.py`.
- With the 3D camera turned, a drop on the canvas sends flat scene coordinates (the canvas already turns
  object clicking off in that state).
- No central catalogue of presets is shipped or hosted; the index format makes one possible.
