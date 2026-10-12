# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (0.x: anything may change).

## [Unreleased]

### Added
- `core/edits.py` (S1.1): `move_clip`, `trim_clip`, `update_clip`, `update_layer`
  return validated snapshots plus an edit kind computed by diffing; `Evaluator.apply(edit)`.
- Edit kind **timing** keeps every evaluator cache; morph animations are reused
  while their baked start/end transforms are unchanged (ADR 0013). Clip drags on
  the stress scene: 94 ms → 15–22 ms per step (B15).
- MIT license.
- Project structure: `cli.py`, `logging_config.py`, `ui/` (canvas split from main window),
  `benchmarks/`, tests split into `core/`, `render/`, `ui/` with shared `support.py`.
- Logging: console (`-v`/`-vv`) and per-user rotating log file (ADR 0011).
- Documentation: architecture, project format, roadmap, ADRs 0001–0012,
  developer setup/coding standards/testing guides, benchmark and decision-session logs,
  `CONTRIBUTING.md`, `.editorconfig`.
- Test: Qt paths vs Cairo fidelity (`tests/render/test_qt_paths.py`).
- Test: idle checkpoint precompute drains (`test_missing_checkpoints_drain`).
- Tooling: ruff (lint + format), pytest markers `latex` and `ui`, dev dependency group.

- Validation: unknown clip kinds, non-positive durations, negative starts,
  morph target rules, clips after a morph, duplicate layer ids, unsupported
  schema versions, bezier x outside [0, 1] are rejected on load.
- Tests: 45 → 200 (images, schema, adapter, easing, lifetime, export, CLI,
  logging, editor behaviour, seeded property tests); coverage 77 % → 93 %; `pytest-cov`.

- S1 timeline plan (`docs/plans/s1-timeline.md`), proposed ADRs 0013–0014, benchmarks B10–B14.

- `ui/document.py` (S1.2): the open project as immutable snapshots with a
  `QUndoStack`; drags preview freely and record one undo step (Escape cancels).
  Edit menu with Undo/Redo; window title marks unsaved changes.

- `ui/timeline/model.py` (S1.3): pure timeline geometry — time↔x scale with zoom
  about the cursor, frame quantisation, 8 px snapping (frames, clip edges,
  playhead, 0, end), move/trim clamping that never produces an overlap.

- Timeline (S1.4–S1.6): under the canvas, one row per layer with its lifetime band
  and clip bars coloured by category; ruler scrubbing; drag a bar to move it or an
  edge to trim it (snaps to frames, clip edges and the playhead; Alt = frames only;
  Escape cancels); Ctrl+wheel zooms; drags are coalesced and record one undo step.
  Measured 19–24 ms per drag step in the editor (B16).
- Lifetime inference is a pure function (`schema.infer_lifetime`, `Project.lifetime`)
  shared by the evaluator and the timeline.

- S2 panels plan (`docs/plans/s2-panels.md`), proposed ADR 0015 (build worker,
  warm-then-commit), benchmarks B17–B20.
- Structural edits (S2.1): `add_layer` (id `<type>-<n>`, on top), `remove_layer`
  (also removes the morph clip into the deleted layer), `move_layer` (z-order, a
  cache-keeping timing edit), `add_clip`, `remove_clip`, `new_layer_id`,
  `new_clip_id`. The random-edit property test now mixes them in.
- Validation: duplicate clip ids on a lane and vector-only clip kinds on image
  layers are rejected.
- `Document.apply` records nothing for an edit that changes nothing.
- Build worker (S2.2, ADR 0015): `python -m manim_studio.worker` warms Manim's
  disk cache for Text/Tex/MathTex in another process; `ui/worker_process.py`
  queues requests during startup, restarts on a 20 s timeout or a crash, and
  falls back to synchronous builds if it cannot start (`MANIM_STUDIO_WORKER=0`
  disables it). LaTeX errors are reported as LaTeX's own message.
- `core/warm.py` and `ui/build_service.py`: panel edits are operations; one that
  builds a cold text object waits for the worker and is then re-run on the
  current snapshot, so edits and undos made meanwhile are kept; latest wins per
  field; a failed build commits nothing; nothing commits mid-drag.
- Object registry (S2.3): `adapter.MOBJECT_PARAMS` lists the constructor params
  each type exposes (kind, default, range, choices), `adapter.LIBRARY` the
  library sections, `adapter.default_spec()` new objects; 2D `point` params are
  lifted to 3D for Manim. A test proves every exposed param changes the object.
  The editor pre-warms the library's text defaults at startup.
- Layers dock (S2.4): the layer list front-to-back, an Add menu with the object
  library, Delete (with the morph cascade), Up/Down and drag-to-reorder for
  z-order, double-click to rename; each action is one undo step through the
  build service, and a new MathTex appears when the worker has built it.
- Properties dock (S2.5): for a layer — name, the object's params generated from
  the registry, fill/stroke style, position/scale/rotation/opacity (disabled when
  keyframed), lifetime in/out ("Auto" = inferred); for a clip — animation (same
  family only), start, duration, easing (Manim rate functions and CSS-style
  curves), morph target. One undo step per finished field; refused values
  revert with the reason in the status bar; new LaTeX shows in italics until
  the worker has built it. Selecting a layer or a timeline clip shows it.
- `adapter.EASE_NAMES`, `adapter.BEZIER_PRESETS`.
- Keyframe edits (S3.1, ADR 0016): `edits.set_key` (frame-quantized; replaces a
  key within half a frame; new keys inherit the previous ease unless it does
  not end at 1) and `edits.clear_track` (keeps the value at a time as the base);
  `Evaluator.frame_layers(t)` names the layer of each drawn object;
  `evaluator.layer_transform`; `Document.apply(..., merge_key, merge)` merges
  repeated edits (an arrow key held down) into one undo step.
- Hit-testing (S3.2, `render/hit_test.py`): all layers under a point,
  front-most first; only what is drawn counts (alpha > 0.02); text by its box,
  images by their rectangle, shapes by fill (nonzero winding) or within 4 px of
  their stroke. 0.8 ms per click on the stress scene.
- Shared selection (S3.3, `ui/selection.py`): one layer/clip selection for the
  canvas, Layers panel, timeline and Properties; deleted clips fall back to
  their layer, deleted layers clear it.
- Canvas editing (S3.4-S3.5, `ui/canvas_tools.py`): click selects the
  front-most object (Alt+click: the one behind), the selection is outlined with
  its box and anchor; drag moves it (one undo step, Shift = one axis, Escape
  cancels); arrow keys nudge 1 px / 10 px with Shift, a held key is one undo
  step. Layers with position keyframes get a key at the playhead (snapped to the
  frame); others get their base position changed. Morphing layers cannot be
  dragged while their morph plays.
- Stopwatch toggle (S3.6): Properties > Transform > Keyframes turns position
  keyframes on (one key at the playhead holding the current value) or off
  (keeps the value at the playhead as the base). Base fields of a keyframed
  property are disabled live.
- `manim-studio render --cache-dir DIR --progress json` (S4.1): choose Manim's
  cache, and report progress as flushed JSON lines for the editor. Exports write
  `<name>.partial.mp4` and replace the output only when complete, so a failed or
  cancelled export never damages a previous video; a locked output (open in a
  player) is saved as `<name> (2).mp4` with a warning (ADR 0017).
- `ui/export_job.py` (S4.2): one export in a separate process — snapshot to a
  JSON file in the cache, live progress, `finished(path, warning)` /
  `failed(message)`, `cancel()` that leaves no partial file. A folder given as
  the output is now a clear error instead of a misleading "in use" rename.
- Keyframes on the timeline (P2b): one diamond per key time on each row —
  click to select, drag to retime every key at that time (one undo step),
  Delete to remove (a property's last key becomes its base), right-click a row
  to add keys at the playhead. Properties shows a selected key's time, values
  and easing (disabled on a last key, where no motion follows). `edits.retime_keys`,
  `remove_keys`, `set_key_ease`; `Selection.key_time`.
- TransformMatchingTex (P2e, ADR 0020): turn one equation into another term by
  term. Pieces are keyed by their part's TeX where both equations have that
  part, and by glyph shape otherwise; matching pieces transform, the rest fade.
  Objects with parts can now morph and be morphed into (ADR 0012 amended);
  the morph cache follows the trees' finished clips and member transforms.
  Timeline: *Turn into > TransformMatchingTex* for MathTex/Tex objects.
- Subtitle track (P5a, ADR 0035): **Edit > Add Subtitle** (Ctrl+T) puts a
  subtitle at the playhead; subtitles get their own timeline row (drag to move,
  drag an edge to trim, Delete) and are edited in Properties, with one style for
  all of them (size, height, colour, a band behind the text, fade, width, burn
  in). Long lines wrap between words and shrink if still too wide; extra lines
  grow upwards. **File > Import / Export Subtitles** reads and writes `.srt`
  (tolerant of byte-order marks, CRLF, missing numbers, tags and overlapping
  cues). The exported video has them burned in and an `.srt` beside it; Python
  exports add them as subcaptions, so `manim render` writes the same `.srt`.
  Editing a subtitle re-renders only its own frames (B48).
- Markers and snapping (P5c, ADR 0037): **Edit > Add Marker** (M) puts a named
  marker at the playhead; markers are flags on the ruler, picked and dragged
  (never onto each other), renamed and deleted from their menu or with Delete,
  edited in Properties (name, time, colour), and **Previous / Next Marker** ([ and
  ]) move the playhead. Every drag - clips, keys, sounds, subtitles and markers -
  now snaps to markers, clip edges, key times, sound and subtitle edges, the
  playhead, 0 and the end, with a guide line where it rests (Alt: frames only).
  A clip's menu adds a sound at its start or end and a marker's menu at the
  marker, from the project's sounds or another file. Markers are saved with the
  project, change no frame (render-ahead keeps everything) and do not appear in
  readable Python exports.
- Value readouts and connectors (P5b, ADR 0036): **Add > Text > Number** is
  Manim's `DecimalNumber` (value, decimal places, a LaTeX unit, a + sign); a
  **ChangeDecimalToValue** clip (*Emphasis*) counts it to a new value, with
  easing, random access and chaining from the last clip's value, keeping its
  left edge. The build worker compiles every glyph a number can show ahead.
  **Add > Shapes > Connector** draws a line or arrow from the object before the
  selected one to it, redrawn every frame: its ends stop where the line between
  the centres leaves each object's box (or run between the centres or offset
  points), shortened by a gap; tips none, end or both; it has no clips, cannot
  join a trace, connector or code layer, and is deleted with either object.
  Render-ahead redraws it when an object changes. Python exports write numbers
  and counts as plain Manim, and a centre-to-centre connector as
  `always_redraw(lambda: Line(a.get_center(), b.get_center(), buff=...))`.
- Workspace pages (P6b.1, ADR 0041): the window is a set of pages switched from a
  page bar at the bottom, View > Pages or Shift+1..5, sharing one canvas,
  timeline, Layers and Properties panel (moved between pages in about 23 ms). Compose is
  the former layout; the docks are gone and View > Layers / Properties hide a
  panel on every page. Animate, Code, Audio and Deliver pages follow.
- Code page (P6b.3, ADR 0041, decision session 36): code layers in an editor of their own
  beside the viewer - Python highlighting from theme tokens, line numbers, auto-indent, Tab as
  four spaces, Run (Ctrl+Enter: trusts the text, one undo step) and Revert, unapplied text kept
  per layer through layer and page switches (marked as unapplied; dropped, with a message, when
  another project opens), and the render status under the editor, where an error's line number
  moves the cursor to that line. A typed character in a 2000-line scene costs about 11 ms (B57).
- Design system (P6a, ADR 0040): the editor has a dark studio look - the Fusion
  style, a palette and one stylesheet generated from colour tokens in
  `ui/theme.py`, a 9 pt UI font, and Phosphor icons (QtAwesome, a new dependency)
  on the Layers panel and the transport. Every chrome colour - panels, fields,
  menus, the timeline, canvas overlays, the curve editor - comes from the tokens;
  document colours (styles, the canvas background, markers, subtitles) are never
  themed. Text contrast is measured (WCAG): clip-category colours are darker
  shades so their white labels read at 5:1 or better. Colour swatches label
  themselves in black or white, whichever reads better.
- Presets, themes and templates (P5e, ADR 0039): **Animate > Apply Preset**
  (and the timeline row's *Apply preset*) gives the selected layer one of 32
  built-in presets at the playhead - entrances (fade, pop, slides, typewriter,
  draw, grow, spin), emphasis (indicate, pulse, wiggle, circle it, flash, focus,
  wave), exits and motions (drift, bounce, spin, grow) - choosing the clip kinds the
  object accepts, keying relative to where the object is, never changing what was
  drawn before the playhead, and refusing with the reason when it cannot apply.
  **View > Themes** (Manim, Chalkboard, Paper, Blueprint, Midnight) recolours the
  selection, or everything and the background. **Add > Templates** inserts a title
  card, section header, lower third, callout, equation reveal or counter at the
  playhead. *Save Animation as Preset* and *Save Object as Template* keep your own
  in a user folder; library files are versioned and bad ones are skipped with a
  message.
- Clipboard and crash recovery (P5d, ADR 0038): **Edit > Cut / Copy / Paste /
  Duplicate** (Ctrl+X / C / V / D) for the selected layer, clip, sound or
  subtitle, each one undo step. A layer is copied with its parts or objects on
  axes, keys, clips and lifetime; pasted copies get fresh ids, references
  between them follow the copies, references to other layers are kept when the
  same layer (id and type) is there and otherwise left out and reported, and a
  copy appears and disappears when its original does. Parts cannot be copied.
  Pasted layers go above the selected layer and are selected; clips paste onto
  the selected layer at the playhead where there is room and the kind is
  allowed; sounds and subtitles paste at the playhead. The clipboard holds
  versioned JSON (`application/x-manim-studio+json` and plain text), so another
  window can paste it; pasted code is never trusted by pasting. While there are
  unsaved changes a recovery copy is written every 30 s (atomically, 2-41 ms for
  20-2000 layers, B51) and deleted when the work is saved or thrown away; at
  start-up or when its file is opened, a copy left by an instance that is no
  longer running is offered back (restore, discard, later) and restores as
  unsaved changes to the original file.
- Explainer example: `examples/build_explainer.py` builds "What is a derivative?",
  a 95-second lesson with subtitles, section headers, formulas, a secant sliding
  into the tangent, a tangent riding the curve with a traced tail, and
  synthesized sound effects (pops, whooshes, ticks, pencil strokes, chimes, a
  quiet pad) on the audio track. Render it with
  `manim-studio render examples/explainer.json out/explainer.mp4`.
- Audio track (P4d, ADR 0034): **File > Import Audio...** puts a sound at the
  playhead (WAV, MP3, OGG, FLAC, M4A/AAC). Each sound gets a timeline row under
  the layers with its waveform (gain and fades shown); drag it to move it, drag
  an edge to trim it, Delete removes it; Properties edit its start, trim,
  duration, gain (dB) and fades. Playback plays the project's mix and follows
  the sound card's clock, so frames stay in sync; the exported video carries an
  AAC track aligned to the sample; Python exports use `add_sound` for plain
  sounds and the editor's mix otherwise. Missing sound files are silent and
  reported like missing media. Sound edits never re-render frames (B47).
- Simulated layers (P4c, ADR 0033): **Add > Simulation > Traced path** draws
  where the selected object has been - a plain object, a point on axes, a part
  or a simulation - frame by frame, optionally from an offset point and fading
  after some seconds; within one play it is exactly Manim's `TracedPath` (B46).
  Plugins can add **simulations** (`Simulation(start, step, draw, point)`),
  stepped once per frame like Manim updaters; example:
  `examples/plugins/swinging_pendulum.py`. Any frame can be shown in any order:
  states are kept every 30 frames and replayed. Simulated layers have no clips
  (key their opacity) and make a Python export exact.
- Plugins (P4b, ADR 0032): a `.py` file in the plugin folder
  (`~/.manim-studio/plugins`, or the folders in `MANIM_STUDIO_PLUGINS`) or an
  installed package with a `manim_studio.plugins` entry point adds object types
  through the public `manim_studio.plugins` module (`ObjectType`, `Param`,
  `register`). They appear in the library under their own section, edit in
  Properties, animate with every clip kind, render ahead and export, since every
  process loads the same plugins. A builder must return a VMobject that depends
  only on its params (the first build of each type is done twice and compared).
  A plugin that fails to load is skipped and listed in *Help > Plugins...* (and
  the status bar says so at startup); an object whose plugin fails or is not
  installed draws a dashed box with the reason, like a missing image. Plugin
  objects make a Python export exact. Example: `examples/plugins/pendulum.py`
  (B45).
- Python export (P4a, ADR 0031): *File > Export Python...* and
  `manim-studio python PROJECT OUT.py` write a Manim scene. Projects plain Manim
  can express become readable code (a variable per layer, `self.play` groups
  with `Succession` per object, waits, z-order, helpers for the editor's
  clamped eases, Wiggle pivot and Bézier eases); any other project becomes an
  exact scene that plays it through `manim_studio.manim_scene.StudioScene`,
  with the reasons in its header. Both render with `manim render` to what the
  editor shows (B43, B44).
- Objects on axes (P3h, ADR 0030): *Parts > Add to axes* adds a Point, an Area
  (under a graph or between two), RiemannRectangles, AxisLabels and a
  GraphLabel, built with Manim's own Axes helpers and locked to their axes like
  graphs. Area, rectangles and graph labels name a graph on the same axes
  (validated; deleting the graph deletes them; editing it rebuilds them).
  Graphs now carry the function Manim's helpers read, clamped where undefined.
- Graphs animate with their axes (P3g, ADR 0029): an object with child
  objects evaluates as one tree, like an equation with parts, so a clip on the
  axes animates the axes with their graphs (FadeIn/FadeOut, Indicate, Wiggle,
  Create, MoveAlongPath, a whole-figure morph); graph clips and graph-to-graph
  morphs work as before inside the tree. A graph clip may no longer overlap a
  clip of its axes.
- MoveAlongPath `rotate: along` (P3g, ADR 0029): the object turns with the path,
  by its change of direction since the clip's start (Properties: *Turn*).
- Render ahead (P3f, ADR 0028): a preview process renders frames ahead of the
  playhead with the canvas's own camera, so a kept frame is the live frame bit
  for bit; the editor keeps them zlib-compressed (512 MB) and plays and scrubs
  from them, drawing the selection outline from the selected object alone
  (`Evaluator.object_frame`). An edit drops only the frames it can change - the
  lifetimes, before and after, of the changed layers and what depends on them
  (`core/frame_cache.changed_spans`); a zoom, pan or resize refills the cache
  for the new view; finished code renders and reloaded media drop their
  layers' frames. Playback now shows the export's frame grid. *View > Render
  Ahead* turns it off; the readout shows how many frames are ready. On the
  stress scene a cached seek costs 0.7 ms against 27 ms live.
- SVG layers (P3e, ADR 0027): *Add > SVG* brings in a vector drawing with its
  own colours (style fields override them); every clip kind applies, so it can
  be drawn on with Create, Write or DrawBorderThenFill, and MoveAlongPath can
  follow it (its longest path). Media files (SVG and images) are tracked by
  modification time and size: a file saved again in another program is redrawn
  when you come back to the editor or press **F5** (*View > Reload Media*).
  Missing, unreadable, broken or empty files no longer break frames or the
  export: a dashed placeholder is drawn and the status bar names them.
  `adapter.media_signature`, `adapter.media_problem`, `Evaluator.check_media`,
  `Evaluator.media_errors`.
- Tests fail when an exception is raised inside a Qt slot (Qt printed and
  swallowed it, so such tests passed).

- Curved position paths (P3d, ADR 0026): position keys may carry in/out
  tangents; such segments are cubic Beziers walked by arc length (the ease
  keeps meaning speed along the path; 128-sample tables, B39), straight ones
  keep the exact linear formula, overshoots continue along the end tangent.
  The canvas draws the selected layer's motion path: drag key squares, bend
  tangent handles (a smooth key stays aligned, Alt breaks it), double-click to
  smooth/straighten. Edits keep tangents; a key added inside a curve splits it
  so its shape stays. `core/motion_paths.py`, `ui/motion_overlay.py`,
  `edits.set_tangents`, `edits.smooth_key`, `Evaluator.position_frame`.
- MoveAlongPath clips (P3c, ADR 0025): a root object travels along another
  layer's shape (a graph, a circle, a line) - *Add clip > Move > MoveAlongPath*.
  The path layer's rest shape at the clip's start is mapped into the object's
  local frame and Manim's MoveAlongPath runs there; caches are keyed by the
  path's signature, so moving or editing either layer re-runs it exactly.
  Deleting the path layer drops its clips. An adapter patch measures the path
  once (23.6 ms -> 0.005 ms per frame on a graph, same points, B38). A drag that
  the path cancels out shows a hint. `Project.path_layers`; clip param kind
  `layer`; category `motion`. The graphs example now has a dot on the parabola.
- Axes and function graphs (P3b, ADR 0024): `Axes` in the library; graphs are
  child objects (`parent_id` + their own spec) added with *Parts > Add graph...*,
  plotted from a whitelist expression (`core/expressions.py`: parsed, never
  `eval`'d; validated on load). Graphs ride on their axes, are locked to them
  (only opacity is keyable), take every vector clip kind and morph into other
  graphs; editing the axes re-plots them. Curves split where the function is
  undefined or leaves the y range, ending exactly at the edge (bisection).
  Numbered axes are warmed by the build worker. `edits.add_child`;
  `schema.keyable_props`; part-only rules now apply to parts only.
  Example: `examples/graphs.json`.
- Canvas viewport (P3a, ADR 0023): Ctrl+wheel zooms about the cursor (5 %-3200 %),
  wheel / Shift+wheel / middle-drag pan, View > Zoom In/Out, Fit (Ctrl+0),
  Actual Size (Ctrl+1); a readout beside the frame counter. The preview camera
  covers the whole widget, so objects outside the frame show on a dimmed
  pasteboard (+2 ms per frame at Fit, B36). The view is not saved; zooms survive
  resizes, Fit follows them. Zooming in spreads the handles of small parts.
- More clip kinds (P2g, ADR 0022): GrowFromEdge, SpiralIn, Add/RemoveTextLetterByLetter
  (Text only), Circumscribe, Flash, FocusOn, ClockwiseTransform,
  CounterclockwiseTransform, FadeTransformPieces. **Clip params** registered per
  kind and shown in Properties (fade `shift`, grow `edge`, Indicate colour and
  scale, Circumscribe shape and colour, Flash/FocusOn colour); validated on load,
  unregistered keys pass through; changing a clip's kind drops params it does
  not take. **Overlay clips** draw the object plus what the animation adds,
  also on parts. Type restrictions (`only_types`) are validated on load.
  Circumscribe is a Succession made random-access by an adapter patch
  (deviations.md). Rejected with measured reasons (B35): GrowFromPoint,
  Broadcast, ShowPassingFlash, Blink.
- Anchor point (P2f, ADR 0021): `Transform2D.anchor`, the point a layer rotates
  and scales about (objects, parts, code layers); base only, never keyed, not
  written while (0, 0). `edits.set_anchor` keeps the drawing in place by
  compensating the base position and every position key (exact unless rotation
  or scale is keyed — the status bar says so). Canvas: Ctrl+drag the pivot cross
  (Shift snaps to the box's corners, edge midpoints and centre; Ctrl+double-click
  centres it); the handles turn about the anchor. Properties: *Anchor point*.
- LaTeX renders left half-written by a killed process (a build worker past its
  timeout) are compiled again instead of failing that formula for good
  (adapter patch on `tex_to_svg_file`, ADR 0007).
- Faster tests (B32): parallel by default (`pytest-xdist`, up to 8 workers,
  per-worker Manim caches), a `slow` marker for tests that start real
  processes (`pytest -m "not slow"` runs in ~30 s), and the shared Manim cache
  restored after each test. Full suite: 293 s -> 75-110 s.
- Code layers (P2d, ADR 0019): a layer holding a Manim `Scene` written by the
  user, for what the timeline cannot express (updaters, ValueTracker,
  TracedPath). Real Manim plays it once into a frame cache (cropped,
  premultiplied, zlib; `core/code_cache.py`) and the editor paints the frames
  with Cairo between ordinary mobjects, with the layer's transform and opacity.
  Code runs only in single-use warm spare processes (`code_runner.py`,
  `ui/code_render.py`; B30, B31) and only when trusted: a per-user hash store,
  a prompt when opening a project with untrusted code, `--trust-code` for the
  CLI. Properties shows a code editor, the render status and Run again.
- Showcase example (`examples/showcase.json`, built by `examples/build_showcase.py`).
- Part layers (P2c, ADR 0012): animate the terms of an equation as their own
  layers. A part is `{tex, occurrence}` under a MathTex/Tex object, resolved to
  one exact span that the adapter marks with its own dvisvgm group (identical
  output, B28); unresolvable parts are kept but not drawn. The evaluator treats
  an object with parts as a tree (checkpoints by finished clips, clips on their
  layer's glyphs, transforms composed with the parent's; B29). Layers panel
  tree with **Add part...** and **Split into terms**; part rows on the timeline;
  a part's key in Properties; root-first canvas clicks, double-click to drill
  in, Esc to back out; part gizmos pivot on the part; a warning when a text
  edit may move a part's match. `core/parts.py`; `edits.add_part`, `add_parts`;
  `Project.children/descendants/ancestors/root_of`; `Evaluator.layer_frame`.
- Easing curve editor (P2b): "Custom curve..." in every easing list opens a
  graph with two bezier handles and presets; named Manim eases start from a
  fitted bezier (`adapter.EASE_BEZIER_FITS`, B27) and the four that are not
  beziers are refused.
- P2b keyframes plan (`docs/plans/p2b-keyframes.md`), benchmark B27 and
  `benchmarks/fit_ease_beziers.py`.
- Transform gizmos (P2a): corner handles scale and a knob rotates the selected
  object about its position (Shift: 10 % / 15° steps; live readout), on a box
  that follows the object's rotation. Every transform property has a Keys toggle
  in Properties; a keyed field shows its value at the playhead and edits keys.
  Edit > Auto-key: the first change of an untracked property animates from the
  layer's start to the playhead (ADR 0018). `edits.set_property` holds the rule.
- P2a transform gizmos plan (`docs/plans/p2a-gizmos.md`), proposed ADR 0018.
- Phase 1 complete: `tests/ui/test_acceptance_v1.py` writes an equation, moves
  it, morphs it into a second equation, fades it out and exports MP4 through
  the UI alone.
- Export dialog (S4.3-S4.4): File > Export Video... (Ctrl+E) exports the scene
  as it is (saved or not) in the background — "Starting...", frame progress and
  time left, Cancel, Open folder; quitting during an export asks first. The UI
  stays responsive (B26: p99 14 ms timer lateness).
- S4 export plan (`docs/plans/s4-export.md`), proposed ADR 0017, benchmark B25.
- S3 acceptance (`tests/ui/test_acceptance_s3.py`): move an object on the
  canvas, undo, redo, and animate it by moving it with keyframes on; benchmark
  B24 (`benchmarks/bench_canvas_drag.py`): 18.5 ms per drag step in the window.
- S3 canvas interaction plan (`docs/plans/s3-canvas.md`), proposed ADR 0016,
  benchmarks B21–B23 (`benchmarks/bench_canvas_interaction.py`).
- New, Open and closing the window ask before discarding unsaved changes
  (Save / Discard / Cancel).
- File > New (S2.7). S2 acceptance: a MathTex layer with a Write clip is built
  from an empty project through the panels and the timeline alone.
- Timeline clips (S2.6): right-click a row to add a clip at that time (1 s,
  shortened to fit the gap; morphs pick a layer that is not yet a target; not
  offered after a morph), right-click a clip to delete it, Delete key removes
  the selected clip. Placement is the pure `timeline.model.place_new_clip`.
- `Document.dragFinished` signal; `adapter.cache_dir()`; `schema.TEXT_TYPES`, `schema.RASTER_TYPES`.

### Changed
- Timeline rows list the front-most layer first, matching the Layers panel.
- `Evaluator.invalidate(..., transform_only=...)` replaced by `invalidate(..., kind=...)` / `apply(edit)`.
- Clip-kind metadata moved from the adapter into `schema.CLIP_KIND_INFO`, so
  documents validate without importing Manim; `adapter.ANIMATION_CLASSES` maps kinds to Manim.
- `pillow<13` pinned: Manim 0.22 uses an argument Pillow 13 removes.
- Manim pinned to exactly 0.22.0 (ADR 0003).
- `render/qt_preview.py` renamed to `render/qt_paths.py` (it serves overlays and
  hit-testing, not preview content — ADR 0006).
- `DESIGN.md` replaced by `docs/architecture.md`, `docs/roadmap.md` and the ADRs.
- `zip()` calls on equal-length sequences are now `strict=True`.
- Edits that validate the whole project (add, duplicate or change a layer) no longer grow faster than linearly with the layer
  count (B53): project validation and `edits.classify` build their lookups once instead of scanning
  the layer list per layer. At 2000 layers `add_layer` takes 11 ms instead of 840 ms (200 layers:
  0.9 ms instead of 7 ms). Rules and messages are unchanged; a morph aimed at the id of a sound
  now reads "to_layer ... is missing" instead of crashing.

### Fixed
- A MoveAlongPath clip on an equation with parts crashed ("needs a target"); objects
  with parts or child objects can now travel along a path (P3g).
- The timeline drew nothing after a MoveAlongPath clip: motion clips had no
  colour and the rebuild raised (P3c).
- The build-worker cache test compared against a fixed 150 ms and failed on a
  busy machine (every build several times slower); it now compares warm builds
  with cold builds in the same run.
- Image layers rendered wrong opacity whenever they moved or had an opacity
  keyframe: the scratch copy shared the source's pixel array and used
  `ImageMobject.set_opacity`, which overwrites alpha in place.
- A clip after a morph on the same layer crashed the evaluator (`ValueError`);
  such projects are now rejected on load.
- A clip outside a layer's explicit lifetime made the layer visible again.
- `manim-studio render` printed a traceback for missing or invalid project files;
  it now prints one error line and exits with code 2.
- Qt tests crashed the run when a `QGuiApplication` was created before a
  `QApplication`; all Qt tests now share one session `qt_app`.
- Author name encoding in `pyproject.toml`.

## [0.1.0] - 2026-10-09

### Added
- Project schema (layers, clips, keyframes, easing incl. cubic-bezier).
- Manim adapter with 16 clip kinds and 12 mobject types; Wiggle pivot patch.
- Random-access evaluator: checkpoints, clip-owned working mobjects, numpy layer
  transforms, world-space morph hand-offs, incremental invalidation with edit classes.
- Cairo export to MP4 via PyAV; `manim-studio render`.
- S0 previewer: `manim-studio edit` with scrub, play, frame step, idle checkpoint
  precompute, `gc.freeze()`, half-resolution playback.
- Example project `examples/euler.json`, preview benchmark.
