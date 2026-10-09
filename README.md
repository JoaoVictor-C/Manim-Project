# Manim Studio

Animate with [Manim](https://www.manim.community/) the way you would in After
Effects or Premiere: layers, a timeline of animation clips, keyframes and easing
— no Python required. Manim itself renders every frame, so the preview is
exactly what gets exported.

**Status:** early development (0.1). The core engine, video export, the
previewer and an editable timeline with undo work; panels to build scenes
without JSON are next. See the [roadmap](docs/roadmap.md).

## Quick start (Windows)

Needs [uv](https://docs.astral.sh/uv/) and, for LaTeX equations, MiKTeX.
Details and troubleshooting: [docs/dev/setup.md](docs/dev/setup.md).

```bash
uv sync
```

Open the example in the previewer (Space play/pause, ←/→ step a frame):

```bash
uv run manim-studio edit examples/euler.json
```

In the timeline: click the ruler to scrub, drag a clip to move it, drag its edge
to trim it (it snaps to frames, clip edges and the playhead; hold Alt to snap to
frames only; Escape cancels), Ctrl+wheel to zoom, Ctrl+Z / Ctrl+Y to undo/redo.

In the Layers panel: **Add** creates an object from the library (shapes, Text,
MathTex, Tex, images) on top; Delete removes the selected layer; Up/Down
(Ctrl+] / Ctrl+[) or dragging changes the stacking order; double-click renames.
The Properties panel edits the selected layer or clip (a timeline click selects
a clip); each finished field is one undo step, and new LaTeX appears in italics
until it has been built.

Render it to video:

```bash
uv run manim-studio render examples/euler.json out/euler.mp4
```

## How it works

Manim's `play()` is a loop of `begin()` → `interpolate(alpha)` → `finish()`. Manim
Studio runs that loop itself from a JSON project, so any frame can be computed at
any time — that is what makes a scrubbable timeline possible.
More in [docs/architecture.md](docs/architecture.md).

## Repository layout

```
src/manim_studio/   application code (core engine, renderers, Qt UI, CLI)
tests/              pytest suite (core, render, ui)
benchmarks/         performance scripts
examples/           example projects
docs/               architecture, file format, ADRs, guides, logs
```

## Documentation

- [Documentation index](docs/README.md)
- [Architecture decision records](docs/adr/README.md)
- [Project file format](docs/project-format.md)
- [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE) © 2026 João Victor
