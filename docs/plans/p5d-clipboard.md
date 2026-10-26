# P5d — Clipboard and safety

- **Status:** Done
- **Date:** 2026-10-11
- **Decided in:** [decision session 31](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** B51 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0038 — Clipboard, duplicate and crash recovery](../adr/0038-clipboard-and-recovery.md)

## Goal

**Done when** an object with its animation (an equation with parts, axes with
graphs, a connector), a clip, a sound and a subtitle can be duplicated, cut, copied
and pasted through the Edit menu - also into a second instance - each as one undo
step, the copies drawing exactly like the originals where they are placed; and a
crashed session's unsaved changes are offered back on the next start.

## Clipboard

- `core/editing/clipboard.py` (pure): `copy_layers`, `copy_clip`, `copy_audio`, `copy_cue`
  build a `ClipboardData`; `paste_layers`, `paste_clip`, `paste_audio`,
  `paste_cue` return a `Pasted` (the `Edit`, the new id to select, notes on what
  was left out); `duplicate_*`; `to_json` / `from_json` (validated; version
  checked); `ClipboardError` carries a plain message.
- Layers: subtree copied, fresh ids, inside references remapped, outside ones kept
  for the same id and type, otherwise left out and reported; visible span frozen
  when a morph is lost; parts refused; objects on axes need their axes.
- `ui/shell/clipboard_actions.py`: the four Edit actions, QClipboard (mime type plus
  text), clip placement with the timeline's `place_new_clip` and `obstacles`, the
  allow-list (`adapter.allowed_clip_kinds`), messages, selection of the pasted item.

## Recovery

- `core/model/recovery.py` (no Qt): file names, atomic writes of the project and its
  sidecar, listing, the owner check (`pid_alive`), offered entries, pruning.
- `ui/shell/autosave.py`: the 30 s timer, the recovery folder
  (`MANIM_STUDIO_RECOVERY` or `AppDataLocation/recovery`), delete on clean.
- `MainWindow`: `ask_recover(entries) -> "restore" | "discard" | "later"`,
  `check_recovery()` (called by `run()`), the check in `load()`, `restore(entry)`,
  delete on a discarding close.

## Steps

| step | content | acceptance |
|---|---|---|
| P5d.1 | clipboard core | remapping of subtrees, parts, morphs, paths, traces, connectors, axes objects; unique ids; placement and refusals of clips, sounds and subtitles |
| P5d.2 | clipboard in the editor | menus and shortcuts, selection, one undo step, messages, QClipboard round trip |
| P5d.3 | autosave and recovery | timer writes when dirty only, atomic files, cleanup on save and discard, prompt for a dead owner only, restore keeps the path and is unsaved, decline deletes; B51 |
| P5d.4 | acceptance, docs | a scene built in the editor, duplicated and pasted, the copies drawn identically, a simulated crash restored to the same project |
