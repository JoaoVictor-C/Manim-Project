# P3f — Render-ahead cache: implementation plan

- **Status:** In progress
- **Date:** 2026-10-10
- **Decided in:** [decision session 20](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** benchmark B41 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0028 — Render-ahead cache](../adr/0028-render-ahead-cache.md)

## Goal

Heavy projects play smoothly. **Done when** a project whose frames take over
100 ms plays at full rate once its frames are rendered ahead, the frames shown
equal the live ones, an edit to a late layer keeps the early frames, and a view
change refills the cache.

## Core (no Qt)

- `core/frame_cache.py`:
  - `frame_index(t, fps)` / `frame_time(i, fps)`: the grid (as `frame_times`).
  - `changed_spans(old, new)`: `None` (everything) when anything but the layers
    differs; otherwise the old and new lifetimes of the **closure** of changed
    layers - added, removed, edited or moved in z-order (layers outside the
    longest common order), their morph partners, their whole object (root and
    descendants), and layers whose MoveAlongPath follows one of them.
  - `FrameStore`: compressed frames by index for one view id; `invalidate`
    (spans or all) bumps the generation and records it per index; `accept(view,
    generation, index, data)` refuses another view or a generation older than
    the index's last invalidation; `missing(start, count, total)` from the
    playhead forward, wrapping; a byte budget (512 MB) evicting farthest from
    the playhead.
- `render/preview.py`: `PreviewView` (device pixel size, frame size, centre,
  background) and `preview_camera(view)`, used by the canvas and the process.
- `Evaluator.object_frame(layer_id, t)`: the pairs `frame_layers(t)` yields for
  that layer's object (its root, parts and child objects).

## Process and client

- `manim_studio/preview.py` (`--cache-dir`): JSON lines. In: `project`
  (snapshot + generation), `view` (id + `PreviewView`), `want` (indices),
  `media`. Out: `ready`, `frame` (view id, generation, index, zlib base64). A
  reader thread queues input; between frames the loop applies the newest
  messages. A new snapshot is applied with `invalidate` on its changed layers
  (a new evaluator when the canvas changed).
- `ui/preview_client.py`: the `QProcess` (restart on crash, give up after three
  failed starts), a `frame` signal; `make_preview` returns none when
  `MANIM_STUDIO_PREVIEW=0` (tests).

## Editor

- `ui/render_ahead.py` (`RenderAhead`): owns the store and the client. On a
  document change it drops `changed_spans` at once and sends the snapshot
  ~150 ms after the last change; on a view change it clears and sends the view;
  it asks for the next 60 missing frames from the playhead when frames arrive,
  after an invalidation or when the playhead moves. Code renders finishing and
  media reloads drop those layers' lifetimes (and send `media`).
- Canvas: on the grid with a cached frame for its current view, it shows that
  frame and builds the outline from `object_frame`; otherwise it renders live.
- Playback quantises `t` to the grid. View → Render Ahead (on by default). The
  readout shows how many frames are ready.

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P3f.1 | `frame_cache`, `preview_camera` (canvas uses it), `object_frame` | spans for every kind of edit; store acceptance, budget, missing order; object_frame == the object's part of frame_layers |
| P3f.2 | preview process and client | a real process renders frames equal to the canvas's; stale generations and views are refused; crash restart |
| P3f.3 | `RenderAhead`, canvas and playback wiring, View option; acceptance, docs | the Goal's scenario through the editor |
