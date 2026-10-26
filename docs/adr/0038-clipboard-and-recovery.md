# 0038. Clipboard, duplicate and crash recovery

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** João Victor

## Context

Long editing sessions had no copy, paste or duplicate (every repeated object was
rebuilt by hand) and no safety net: a crash lost everything since the last save.
Presets and templates (P5e) also need a way to put a ready-made piece of a project
into another one. Copying is not trivial here: layers refer to each other by id
(parts and objects on axes by `parent_id`, morphs by `to_layer`, MoveAlongPath by
`params.path`, objects on axes by their graph, traced paths and connectors by their
targets), a layer may be the target of only one morph, and sounds and subtitles
share the layers' id space.

## Decision

- **Edit > Cut / Copy / Paste / Duplicate** (Ctrl+X / C / V / D) act on the
  selection: a layer, a clip, a sound or a subtitle. Each is one undo step. A text
  field with the focus keeps its own Ctrl+C / V / X.
- **Layers are copied with their whole subtree** (parts, objects on axes), with
  their tracks, clips, lifetime and style. On paste every layer gets a fresh
  `<type>-<n>` id (`part-<n>` for parts), unique across layers, sounds and
  subtitles. References inside the copied set are remapped to the new ids.
  References to layers outside it are kept when the destination has a layer with
  that id **and the same object type** as when it was copied (so a paste into
  another project never attaches a connector to an unrelated layer); otherwise a
  morph or MoveAlongPath clip is left out, a traced path or connector is not
  pasted, and an object on axes whose graph is missing is not pasted. A morph to an
  outside layer is also left out when that layer is already the target of a morph.
  Everything left out is reported in the status bar.
- **A copy keeps its visible span.** A copied morph target whose morph source is
  not copied gets its lifetime "in" set to the end of that morph; a copy whose
  morph clip is left out gets its lifetime "out" set to the end of that clip (both
  only when unset). The copy therefore appears and disappears on the same frames as
  the original.
- **Parts cannot be copied** (they are defined by a span of their equation's TeX).
  A copied object on axes pastes onto its original axes and is refused where those
  axes do not exist.
- **Placement.** Pasted layers go right above the selected layer's object (on top
  without a selection), objects on axes after their axes' other objects; top-level
  names get " copy" (then " copy 2"...) when the name is taken; the pasted layer
  becomes selected. A clip pastes onto the selected layer at the playhead with its
  own length, where the timeline would add a clip (`place_new_clip`, the obstacles
  of ADR 0012); it is refused when there is no room, when the kind is not allowed
  for that layer (ADR 0007) or when its morph target or path is not valid there. A
  sound pastes at the playhead; a subtitle pastes at the playhead if it overlaps no
  other subtitle. Duplicate puts a clip, sound or subtitle right after the
  original, a layer right above it, and leaves the system clipboard alone.
- **Clipboard format.** JSON `{"format": "manim-studio-clipboard", "version": 1,
  "kind": "layers" | "clip" | "audio" | "cue", "payload": ...}` under the mime type
  `application/x-manim-studio+json`, and as plain text so it survives between
  instances; paste validates it with the schema. Paste never trusts code: code
  layers run only when their code hash is trusted (ADR 0019), so clipboard text
  from another program cannot run code. The logic is pure (`core/editing/clipboard.py`);
  every paste is an ordinary edit through `core.edits` (kind `clip` for new layers,
  `timing` for sounds and subtitles), so undo, render-ahead and the evaluator's
  caches work unchanged.
- **Autosave.** While the document has unsaved changes, every 30 s the window
  writes a recovery copy (skipping drags and snapshots it already wrote): the
  project JSON and a sidecar `.meta.json` (original path, pid, time), each written
  to a temporary file and moved into place with `os.replace`, the sidecar last. The
  folder is `QStandardPaths.AppDataLocation/recovery` (`MANIM_STUDIO_RECOVERY`
  overrides it). Files are named `<sha1 of the path, 16 hex>-<pid>` or
  `untitled-<pid>-<n>`, so two running instances editing the same file never
  overwrite each other's copy. The window deletes its copy when the document
  becomes clean (Save, undo to the saved state, New, Open) and when it closes after
  the user discards the changes.
- **Recovery.** At start-up and when a file is opened, recovery copies whose owner
  process is no longer running (psutil if installed, else `OpenProcess` on Windows
  and `kill(pid, 0)` elsewhere) and that are newer than the saved file are offered
  (`ask_recover`: restore, discard, later). Restore opens the newest as an unsaved
  document bound to the original path, writes its copy under the current process
  first and then deletes the old one; discard deletes the offered copies; later
  keeps them. Copies older than the saved file are neither offered nor deleted
  (file times are changed by sync tools and checkouts); they are pruned after 14
  days, as are project files without a sidecar. Copies of running instances are
  never touched.

## Consequences

- A clip, sound or subtitle can be moved between projects; a whole object with its
  animation can be reused (the base of P5e's templates).
- One selection means one thing copied at a time; the payload already holds several
  layers for multi-select (P6c).
- A process id reused by an unrelated program hides a dead owner's copy until that
  program exits. With several crashed copies, one is restored per start; the others
  are offered at the next one.
- Autosave runs on the GUI thread: B51 measures it.

## Evidence

- Probe: B51 in [../logs/benchmarks.md](../logs/benchmarks.md) (autosave write time).
- Design: [../logs/decision-sessions.md](../logs/decision-sessions.md), session 31.
- Plan: [../plans/p5d-clipboard.md](../plans/p5d-clipboard.md).
