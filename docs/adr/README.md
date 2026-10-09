# Architecture Decision Records

An ADR records one significant decision: the context, what was decided, the
consequences, and the evidence behind it. ADRs are immutable once accepted —
to change a decision, write a new ADR that supersedes the old one and update
the old one's status.

## When to write one

Write an ADR when a change:

- alters how the document model maps to Manim (evaluator, clips, keyframes);
- adds or replaces a dependency, renderer, file format or process boundary;
- changes a rule other code relies on (overlap rule, invalidation, allow-list);
- is expensive to reverse.

Bug fixes, refactors and new clip kinds that pass the existing harness do not
need one.

## How

1. Copy [template.md](template.md) to `NNNN-short-title.md` (next free number).
2. Status `Proposed`; open it for discussion (PR or issue).
3. Back claims with evidence: a test, a benchmark in [../logs/benchmarks.md](../logs/benchmarks.md),
   or a source reference. Unmeasured claims are labelled as such.
4. On acceptance set `Accepted` and add it to the index below.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-editor-owns-manims-clock.md) | The editor owns Manim's clock | Accepted |
| [0003](0003-stack-python-pyside6-pinned-manim.md) | Stack: Python 3.13, uv, PySide6, pinned Manim behind an adapter | Accepted |
| [0004](0004-one-clip-lane-per-layer-keyframes-for-motion.md) | One clip lane per layer; motion and style as keyframes | Accepted |
| [0005](0005-morph-clips-are-world-space-hand-offs.md) | Morph clips are world-space hand-offs | Accepted |
| [0006](0006-preview-renders-with-manims-cairo-camera.md) | Preview renders with Manim's Cairo camera | Accepted |
| [0007](0007-allow-list-and-adapter-patches.md) | Allow-list and adapter patches for unsafe animations | Accepted |
| [0008](0008-incremental-invalidation-edit-classes.md) | Incremental invalidation with edit classes | Accepted |
| [0009](0009-playback-scheduling.md) | Playback scheduling: frame dropping, idle checkpoints, gc.freeze | Accepted |
| [0010](0010-python-round-trip-is-export-only.md) | Python round-trip is one-way export | Accepted |
| [0011](0011-logging.md) | Logging: console plus per-user rotating file | Accepted |
| [0012](0012-layer-tree-and-part-layers.md) | Layer tree and part layers | Proposed |
| [0013](0013-timing-edits-keep-caches.md) | Edit kinds: timing edits keep caches | Accepted |
| [0014](0014-document-snapshots-and-undo.md) | Document snapshots and undo | Proposed |
