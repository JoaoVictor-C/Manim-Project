# P3a — Viewport zoom and pan: implementation plan

- **Status:** ✅ Done (2026-10-10) — `tests/acceptance/test_acceptance_p3a.py`
- **Date:** 2026-10-10
- **Decided in:** [decision session 15](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.83)
- **Evidence:** benchmark B36 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0023 — Canvas viewport](../adr/0023-canvas-viewport.md)

## Goal

Look closer and further: zoom into a small term to grab its handles, zoom out to
see what sits outside the frame. **Done when** you can Ctrl+wheel into a small
part, its corner handles are well apart, scale it at 400 %, press Ctrl+0 to fit
again, and the export shows what the editor shows.

## View

- The canvas holds a **view**: a *Fit* flag (on by default), an absolute
  **scale** (screen pixels per export pixel, 5 %–3200 %) and a **centre** in
  Manim units.
- In Fit the view is today's letterbox, recomputed on every resize and centred
  on the origin (where the export camera looks).
- Any zoom or pan leaves Fit; scale and centre then survive resizes, so an
  explicit 100 % stays 100 %. Ctrl+0 goes back to Fit.
- Not saved in the project, not undoable; Fit again when a project opens.
- A readout beside the frame counter: `Fit (63 %)` or `200 %`.

## Rendering

- The preview camera covers the **whole widget**: pixel size = widget ×
  devicePixelRatio (× 0.5 in half-resolution playback), `frame_width` =
  widget width / ppu, `frame_center` = the view centre. Objects outside the
  video frame show (they were already clickable, just invisible).
- Outside the frame is dimmed (four rectangles) and the frame gets a 1 px border.
- B36: +2 ms at Fit on the stress scene, flat across zoom levels.
- Export is untouched: it has its own camera.

## Mapping

`frame_rect` (where the frame lies in widget pixels) replaces `target_rect`;
`px_per_unit`, `to_units` and `units_transform` follow the view. Everything
else — outline, handles and their pixel radii, hit-testing tolerance, the anchor
cross, nudges — goes through these, so it follows unchanged. Zooming spreads the
handles of a small part apart (the known P2c limit).

## Input

| input | effect |
|---|---|
| Ctrl+wheel | zoom about the cursor (the point under it stays) |
| wheel / Shift+wheel | pan vertically / horizontally |
| middle-drag | pan |
| Ctrl+= / Ctrl+- | zoom about the centre |
| Ctrl+0 / Ctrl+1 | Fit / 100 % |

Also in the View menu. View changes are ignored while a canvas drag (move,
scale, rotate, anchor) is in progress. Space stays Play/Pause, so there is no
Space+drag pan; Alt-click and arrow nudges are unchanged.

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P3a.1 | view model, mapping, re-framed render, dimming | mapping round trips at several views; cursor-anchored zoom; Fit follows resizes, a zoom does not; off-frame object drawn and selectable |
| P3a.2 | wheel, middle-drag, shortcuts, View menu, readout | input tests; no view change mid-drag |
| P3a.3 | acceptance, ADR 0023, docs | the Goal's scenario through real events, export = editor |

## Outcome

Done on 2026-10-10, as planned. The view model is pure (`ui/canvas/viewport.py`);
the canvas's camera size key now includes the world area it shows.
