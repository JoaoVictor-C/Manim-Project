# P2b — Keyframes on the timeline and the easing curve editor: implementation plan

- **Status:** In progress
- **Date:** 2026-10-09
- **Decided in:** [decision session 9](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** benchmark B27 in [../logs/benchmarks.md](../logs/benchmarks.md)

## Goal

Make keyframes visible and editable: see them on the timeline, retime and
delete them, edit their values and easing, and shape easing with a curve.
**Done when** you can auto-key a move, retime its key on the timeline, give it a
custom curve, and the motion follows (acceptance test).

## Timeline

- One **diamond** per distinct key time per layer (keys of any property within
  half a frame merge) on the bottom strip of the row; the tooltip lists the
  properties keyed there.
- Press priority: diamonds within 5 px win over clip bars; stacked diamonds →
  the key time nearest the cursor.
- Click selects the key time; drag retimes all keys at that time together
  (preview/commit, one undo step "Move keys"), snapping like clips and clamped
  so no moved property's key comes within a frame of its neighbours.
- Delete removes the keys at that time; when a property loses its last key its
  value becomes the base, so nothing jumps.
- Row menu: **Add key at playhead** (tracked properties at their current value,
  or a choice of property when none is tracked).

## Selection and Properties

`Selection(layer_id, clip_id=None, key_time=None)` — a clip or a key time, not
both; it falls back to the layer when the keys disappear. The key view shows the
time (editing it retimes), and per property keyed there its value and its
**ease** — the shape of the motion from this key to the next, disabled on that
property's last key.

## Curve editor

A widget + dialog reached through **Custom curve...** in clip and key easing:
y from −0.5 to 1.5 (overshoot), the curve drawn with `adapter.rate_func`, two
draggable handles (x within 0..1), presets. Editing a **named** ease starts from
a bezier fitted to it (`adapter.EASE_BEZIER_FITS`, 13 of 17 within 0.022, B27);
double_smooth, ease_out_bounce, ease_out_elastic and there_and_back are not
cubic beziers — their handles are disabled with a hint to pick a preset.

## Edits (all `transform` kind)

| function | does |
|---|---|
| `retime_keys(project, layer_id, t_from, t_to)` | moves every key at `t_from`; `EditError` on a collision |
| `remove_keys(project, layer_id, t)` | removes them; a property's last key is kept as its base |
| `set_key_ease(project, layer_id, t, ease, props=None)` | sets the ease of the keys at `t` |

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P2b.1 | edits + `key_times`, retime bounds (pure) | unit tests incl. collisions, bake, clamping |
| P2b.2 | timeline diamonds and interactions | priority over clips, drag = one step, Delete, add at playhead |
| P2b.3 | key selection + Properties key view | views follow; value and ease edits; last-key ease disabled |
| P2b.4 | curve editor + fitted table | handle drag → bezier; named start; refusal; table within 0.025 |
| P2b.5 | acceptance + docs | auto-key, retime on the timeline, custom curve, motion checked |
