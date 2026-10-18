# 0018. Keyable properties and auto-key

- **Status:** Accepted (implemented in P2a, 2026-10-09)
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

ADR 0016 set the stopwatch rule for moving objects: a property with a
keyframe track gets a key at the playhead, otherwise its base value changes.
P2a extends editing to scale and rotation (canvas handles) and to every
transform field in the Properties panel, and adds auto-key.

Keyframe sampling (`evaluator._sample`) holds the first key's value before it
and the last key's value after it, so a track with one key is constant over
the whole timeline.

## Decision

- Every transform property (position, scale, rotation, opacity) can be keyed
  from the Properties panel. Editing a keyed property's field sets a key at the
  playhead frame; the field shows the value at the playhead.
- **Auto-key** (a toggle): the first edit of an untracked property at playhead
  frame t creates its track with **two keys** — the previous value at the
  layer's lifetime start s and the new value at t — so the edit animates. When
  t is within half a frame of s, one key. Further edits follow ADR 0016.
- With auto-key off, untracked edits change the base value (ADR 0016).

## Amendment 2026-10-18 (user report, P7.1)

Auto-key was stressful on a new object: placing it at a later time created keys at its start
and the playhead (it glided in from the middle), and an edit at its first frame created a
one-key track that equals the base but switches the stopwatch rule on, so every later move
became a key. Now `edits.auto_key_places`: **an edit with nothing to animate from changes the
base** - at the object's first frame, and for an object with no clip, no keys and no Appears at
(it is drawn from the start of the scene; it has no entrance yet). The status bar says so.
Auto-key animates once the object has an entrance (a clip, keys or Appears at) and the
playhead is past its start. The stopwatch (Keys) still keys anything, anywhere.

## Consequences

- Posing an object at two times animates it, without touching the stopwatch.
- The layer's start, not 0, receives the first key: a layer that appears at
  3 s needs no key before it exists.
- Every edit stays one undo step (snapshots, ADR 0014).

## Alternatives considered

- **One key at the playhead (Blender-style)** — a one-key track is constant,
  so the first auto-keyed edit would look like a base edit and animate nothing.
- **First key at 0 s** — creates keys outside the layer's lifetime for layers
  that appear later.

## Evidence

- `evaluator._sample` (one key = constant).
- [Decision session 8](../logs/decision-sessions.md).
