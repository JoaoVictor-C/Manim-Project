# 0078. Plugin manifests: declared metadata, app compatibility and approved permissions

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

Plugins ([0032](0032-plugin-api.md)) are Python files in a plugin folder or entry points, imported in every
process when the engine loads. Nothing describes them before they run: not who made them, which app versions
they were written for, or what they do. A plugin written for another version fails in odd ways (or half
registers), and the user has no point at which to say yes or no to it. The editor already asks before running a
project's code ([0019](0019-code-layers.md)); plugins ran without a word.

## Decision

- **A manifest beside the plugin, read before any of its code runs.** `<stem>.plugin.json` next to a plugin
  file `<stem>.py`; for an entry point, `plugin.json` in its top-level package (or `<module>.plugin.json` beside
  a single-module one), found with `importlib.util.find_spec` without importing it. A `MANIFEST` dict inside the
  module was rejected: reading it means running the plugin first.
- **Fields:** `name` and `version` (required), `author`, `description`, `requires` (an app version range) and
  `permissions`. Unknown keys are ignored, so later fields do not break older apps.
- **Permissions are a closed list:** `reads_project`, `edits_project`, `files`, `network`, `runs_code`, `ui`. An
  unknown name makes the manifest invalid rather than silently ignored.
- **Compatibility:** `requires` is comma-separated `>=`, `<=`, `>`, `<`, `==`, `!=` or `~=` clauses (`==0.3.*`
  matches a prefix; a bare version means `==`), compared by their leading numbers with
  `manim_studio.__version__` by a small comparator in the module (no new dependency; `0.3` equals `0.3.0`,
  `0.3.0rc1` counts as `0.3.0`). A plugin whose range excludes the running app is not loaded and is listed as
  `incompatible: needs >=0.4 (this is Manim Studio 0.3.0)`. An app of unknown version (`0+unknown`, a
  source tree without metadata) runs every plugin.
- **A broken manifest never stops startup:** unreadable JSON, a missing field, a bad version or range or an
  unknown permission lists the plugin as `broken manifest: <why>` and skips it; the other plugins load.
- **Approval before the first load.** A plugin with a valid, compatible manifest loads only when an approval
  covers it; otherwise it waits, and Help > Plugins shows it with its author, description and one chip per
  permission (the riskier ones - `edits_project`, `files`, `network`, `runs_code` - in the warning tone) and an
  **Allow** button. Allowing stores the approval; the plugin loads at the next start, like any plugin change,
  so the editor and its helper processes keep the same types. The status bar says when a plugin waits.
- **The approval record** is kept per plugin id (its file path, or `entry point <name>`) with the name, version,
  the approved permissions and the sha256 of that permission set, in `plugin-approvals.json` beside the trusted
  code store (`%LOCALAPPDATA%\ManimStudio\` on Windows, `~/.local/share/manim-studio/` elsewhere; override
  `MANIM_STUDIO_PLUGIN_APPROVALS`). It is not the editor's ini file because the processes that load plugins
  (build worker, preview, export, exported scenes) have no Qt settings. A plugin is approved when a record exists,
  its hash fits its list, and the plugin asks for nothing outside the list: an update asking for the same or
  fewer permissions keeps its approval, one asking for more waits again and its new permissions are marked
  `(new)`.
- **Plugins without a manifest still load** as before, listed as `no manifest: unknown permissions`. Requiring
  one would break every plugin written so far.
- **This is consent and disclosure, not a sandbox.** A plugin is Python imported into the app's processes with
  the user's full rights: it can read and write any file, use the network and run programs whatever its manifest
  says, and a hostile plugin can simply lie. The dialog says so above the list. Approval tells the user what an
  honest plugin intends and gives one decision point before its code first runs.
- **One pure module.** `manim_studio/plugin_manifest.py` (beside `plugins.py`, under everything, no Qt) parses
  manifests, compares versions, diffs permissions and builds and reads approval records; `plugins.py` applies it
  while loading (`manifests`, `pending`, `approved`, `approvals`, `approve()`), and `ui/shell/plugins_dialog.py`
  shows it.

## Consequences

- Plugin authors can say which versions they support; users see what a plugin declares before it runs.
- A manifest-carrying plugin does nothing until allowed once in the editor, including in `manim-studio render`
  and exported scenes on a machine where it was never allowed: their objects draw the placeholder.
- Approving takes a restart to take effect. A helper process restarted mid-session (after a crash) reads the new
  approval before the editor does; it then knows a type the editor does not yet, which is harmless.
- The id is the plugin's path: moving the file asks again. Two plugins cannot share an approval by claiming the
  same name.

## Alternatives considered

- **A real sandbox** (a separate restricted process per plugin) - plugins build Manim objects inside the
  engine's processes; isolating them is a different architecture, and Python offers no in-process sandbox.
- **Re-ask on every version change** - updates that ask for nothing new would nag; growth is what matters.
- **`packaging.specifiers`** - not a declared dependency; the needed subset is a few lines.

## Evidence

- Tests: `tests/test_plugin_manifest.py`, `tests/test_plugins.py` (manifests, compatibility and permissions),
  `tests/ui/shell/test_plugins_ui.py`.
