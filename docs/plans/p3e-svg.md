# P3e — SVG import: implementation plan

- **Status:** Done
- **Date:** 2026-10-10
- **Decided in:** [decision session 19](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.90)
- **Evidence:** benchmark B40 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0027 — SVG layers and media files](../adr/0027-svg-layers-and-media-files.md)

## Goal

Bring vector drawings in. **Done when** you can add an SVG from the library,
draw it on with DrawBorderThenFill, see a change saved in another program when
you come back to the editor, see a placeholder and a message when the file is
gone, and the export shows what the editor shows.

## Model

- Layer type **`SVGMobject`**: params `path` (absolute, required) and `height`
  (default 2, 0.05–50). The file's colours are kept; `style` keys override them
  when present (as on every other vector object).
- Not a raster type: every clip kind applies. It can be a MoveAlongPath path
  (the longest of its drawn paths is followed; a drawing that cannot be read
  sends the follower to its placeholder's centre).
- Manim's own SVG cache is keyed by the file's name, not its contents, so it is
  bypassed; builds are cached per signature here.
- Library: **Media → SVG**, which asks for a file (`*.svg`); cancelling adds nothing.

## Media files

- `adapter.media_signature(spec)`: `"<mtime_ns>:<size>"` for `ImageMobject` and
  `SVGMobject` specs, `"missing"` when the file cannot be stat-ed, `None` for
  other types. Builds of media specs are cached by (spec, signature).
- A media build that fails (any error while reading the file - B40 saw `OSError`
  and `ParseError` - or an SVG with no drawable path) returns a **dashed
  placeholder** box of the layer's height (16:9); `adapter.media_problem(spec)`
  gives the message.
- The evaluator records the signature each media layer's base was built from
  (path signatures of MoveAlongPath clips include it). **`check_media()`**
  re-stats media layers and invalidates the changed ones like a spec edit,
  returning their ids; **`media_errors()`** maps layer ids to problems.
- The main window runs `check_media` when a project loads, when the application
  becomes active, and from **View → Reload Media**, then refreshes and shows
  `Missing media: <layer> (<file>)` in the status bar when there are problems.

## Work breakdown

| step | content | acceptance |
|---|---|---|
| P3e.1 | type and params, signature cache, placeholder builder, `check_media` / `media_errors`, longest path, missing images fixed | builds keep colours; a rewritten file rebuilds after `check_media` (checkpoints too); missing / broken / empty files draw the placeholder; path followers re-key; export of a project with a missing file succeeds |
| P3e.2 | library entry, Properties (File re-pick with an SVG filter, Height), activation and menu checks, status message; acceptance, docs | the Goal's scenario through real events, scrub = play, export = editor |
