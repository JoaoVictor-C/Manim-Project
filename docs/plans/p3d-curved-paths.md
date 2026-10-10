# P3d — Curved position paths: implementation plan

- **Status:** In progress
- **Date:** 2026-10-10
- **Decided in:** [decision session 18](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.84)
- **Evidence:** benchmark B39 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0026 — Curved position paths](../adr/0026-curved-position-paths.md)

## Goal

Bend the path an object takes between its position keys. **Done when** you can
set two position keys, drag a tangent handle of the motion path on the canvas,
and the object follows the curve at an even speed in the editor and the export.

## Model

- Position keys gain optional **`in_tangent`** and **`out_tangent`**: offsets in
  the track's units, relative to the key. Only on position tracks; omitted when
  absent, so files and frames without them are unchanged.
- A segment is **curved** when its first key has an out tangent or its second
  an in tangent: the cubic Bezier `p0, p0 + out, p1 + in, p1`.
- A key is **smooth** when both handles exist and point in opposite directions
  (within 1°); nothing else is stored.

## Evaluation

- Curved segments are walked by **arc length**, so the key's ease still means
  speed along the path (B39: raw walking is 3.4× uneven on an S bend; a 128-sample
  table makes it 1.002 with 1.6e-4 units error, 37 µs to build, cached by the
  control points).
- Straight segments keep today's exact linear formula.
- An overshooting ease continues along the end (or start) tangent by the
  overshoot × the arc length, as a straight segment overshoots.

## Edits

- `set_key`, `retime_keys`, `set_key_ease` keep tangents (copy, don't rebuild).
- A **new key inside a curved segment** (auto-key) splits it with de Casteljau
  at the arc-length point: the shape stays (the timing changes, as on straight
  segments today).

## Canvas

For the selected layer with two or more position keys (hidden while playing):

- the motion path (for a part, in its parent's frame at the playhead);
- a square per key: drag = the key's value (*Move key*);
- the key's tangent handles: drag = that tangent; on a smooth key the other
  handle turns to stay opposite but keeps its length; **Alt** moves only the
  dragged one (*Bend path*);
- double-click a square: make the key smooth (handles from its neighbours) or
  straight again (*Smooth key* / *Straighten key*).

Squares and handles are hit after the transform handles, before the body.

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P3d.1 | schema, `core/motion_paths.py`, evaluation, edits keep tangents, split | old frames unchanged; arc-length positions; overshoot; edits keep tangents; split keeps the shape |
| P3d.2 | canvas overlay and gestures | drag a square, bend a handle (aligned / Alt), smooth/straight toggle, one undo step each |
| P3d.3 | acceptance, ADR 0026, docs | the Goal's scenario through real events, export = editor |
