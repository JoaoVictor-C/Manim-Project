# 0068. Named project snapshots: milestones kept beside the file, apart from undo

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

Undo is a stack that ends with the session, and recovery copies ([0038](0038-clipboard-and-recovery.md)) exist to be offered
once after a crash and then pruned. Neither lets someone keep "the rough cut" while they work towards "the final
narration", look at what separates the two, or go back to the first without losing the second.

## Decision

- `core/model/snapshots.py` keeps a snapshot as a normal project file plus a small sidecar (name, time, layer count,
  duration) in `<project>.snapshots/` beside the project file; both are written to a temporary name and moved into
  place, the project first, so a snapshot is listed only when whole. Names need not be unique (an id is); nothing
  prunes them.
- `compare(old, new)` says what differs in the editor's words: layers added, removed, or changed in what they are,
  their timing (lifetime and clips), their position and keys, grouping, visibility or name; the canvas, camera,
  subtitle style, and the number of sounds, subtitles and markers.
- **File > Snapshots...** (Ctrl+Alt+S) lists them newest first, shows the difference between the chosen one and the
  project as it is now, and saves, renames, deletes or restores. Restoring is `edits.restore_project`: one edit,
  classified like any other, so it is one undo step and the snapshot stays. A project that was never saved is asked to
  be saved first, as its snapshots would have nowhere to live.

## Consequences

- A snapshot is the whole project, helpers and code included; the media files it points at are not copied
  (portable bundles are a separate feature), so a snapshot restores the scene, not deleted media.
- The folder travels with the project file when it is copied along with it, and is ignored otherwise.

## Alternatives considered

- **Store them inside the project file** - every save would carry every milestone, and an old milestone could not be
  read by a version that changed the format.
- **Reuse recovery copies** - they are pruned, owned by a process id, and offered once.

## Evidence

- Tests: `tests/core/model/test_snapshots.py`, `tests/ui/exchange/test_snapshots_dialog.py`.
