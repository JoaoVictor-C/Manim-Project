# Manim Studio

Animate with [Manim](https://www.manim.community/) the way you would in a video editor:
objects on a canvas, a timeline of animation clips, keyframes and easing curves - no Python
required, though Python is welcome. Manim Community Edition renders every frame, so the
preview is exactly what you export.

It is for teachers, students and creators who want Manim's look (LaTeX equations, graphs,
smooth transforms) without writing a scene by hand, and for Manim users who want to lay out and
time a scene visually, then keep going in code.

**Status:** 1.0.0, the first release with the editor. See the
[release notes](docs/releases/1.0.0.md) and the [changelog](CHANGELOG.md).

## What you can do

- **Build a scene** from shapes (including a right triangle), text, LaTeX equations, counting
  numbers, images, SVG drawings, axes with function graphs, areas and Riemann rectangles,
  connectors that follow two objects, and traced paths. Select, move, scale, rotate and snap on
  the canvas; align and distribute; group objects that move together.
- **Animate equations term by term**: split an equation into parts, colour a part, indicate it,
  and morph one equation into another with `TransformMatchingTex`.
- **Animate on a timeline**: clips (Write, FadeIn, Indicate, Transform, MoveAlongPath...),
  32 presets with live previews, themes and templates; keyframes with a stopwatch per property,
  Auto-key recording, property rows, a graph editor of curves, curved motion paths, markers,
  multi-selection and Shift Timing.
- **Sound and subtitles**: import sounds with gain and fades, played in sync; write subtitles
  or read and write `.srt` files; burn them into the video.
- **Write your own objects in Python**: a `PARAMS` dict and a `build(p)` function become an
  object whose parameters are fields in Properties - or drop a whole Manim scene in as a code
  layer.
- **Export** an MP4 at any size, frame rate and range, from a render queue, with sound; and a
  Python scene file - readable plain Manim code whenever possible.
- **Work comfortably**: five workspace pages (Compose, Animate, Code, Audio, Deliver), undo for
  everything, copy and paste between projects, crash recovery, frames rendered ahead in the
  background for smooth playback, and scenes of 15 minutes and hundreds of objects.

## Install

Requirements: **Python 3.13**, **[uv](https://docs.astral.sh/uv/)**, and for equations a LaTeX
distribution (**[MiKTeX](https://miktex.org/)** on Windows, TeX Live elsewhere). Without LaTeX,
everything works except equations, which show as a dashed placeholder. FFmpeg is not needed.

From a release wheel:

```bash
uv tool install manim_studio-1.0.0-py3-none-any.whl
```

From source (development; on Windows, read [docs/dev/setup.md](docs/dev/setup.md) first - a
user or project path with non-ASCII characters such as `C:\Users\João` needs one extra step,
and MiKTeX wants on-the-fly package installs turned on):

```bash
uv sync
uv run manim-studio edit
```

## Quick start

1. `manim-studio edit` and **File > New** (`Ctrl+N`).
2. In the Layers panel, **Add > Text > Text**, then **Add > Text > MathTex**; type the words and
   the LaTeX (`a^2 + b^2 = c^2`, then `Ctrl+Enter`) in Properties.
3. Right-click the equation's timeline row: **Add clip > Appear / disappear > Write**. Or pick a
   preset from **Animate > Browse Presets...** (`Ctrl+Shift+P`). Press `Space` to play.
4. Give the title an entrance (**Animate > Apply Preset > Entrance > Fade in**), turn on
   **Edit > Auto-key**, move the playhead and drag the title: it glides there.
5. **File > Import Audio...** for a sound, **Edit > Add Subtitle** (`Ctrl+T`) for a subtitle.
6. **File > Save** (`Ctrl+S`), then **File > Export Video...** (`Ctrl+E`) for the MP4 and
   **File > Export Python...** for the scene file.

The [getting started guide](docs/guide/getting-started.md) walks through this in more detail.
Press `F1` in the editor for every shortcut.

## Command line

```bash
manim-studio edit [project.json]             # open the editor
manim-studio render project.json out.mp4     # render a video without the editor
manim-studio python project.json scene.py    # write the project as a Manim scene file
manim-studio --version                       # versions of Manim Studio, Manim and Python
```

`render` takes `--size WxH`, `--fps`, `--start` / `--end`, `--crf`, `--subtitles {burn,srt,none}`,
`--trust-code` (run the project's Python code), `--cache-dir` and `--progress {text,json}`.
`-v` / `-vv` before the command turn on console logging. Details:
[Exporting](docs/guide/exporting.md#command-line).

## Where files live

A project is a single `.json` file ([format](docs/project-format.md)); images, SVGs and sounds
are referenced by path. On Windows the editor keeps its preferences in
`%LOCALAPPDATA%\Manim Studio\manim-studio.ini`, its cache in `%LOCALAPPDATA%\Manim Studio\cache`,
recovery copies of unsaved work in `%APPDATA%\Manim Studio\recovery`, its log in
`%LOCALAPPDATA%\ManimStudio\logs` (**Help > Open Log Folder**), and your presets, templates and
plugins in `~\.manim-studio\`. The full table, with the environment variables that move each:
[Troubleshooting > Where files live](docs/guide/troubleshooting.md#where-files-live).

## Documentation

- **User guide:** [docs/guide](docs/guide/index.md) - [getting started](docs/guide/getting-started.md),
  [the editor](docs/guide/the-editor.md), [objects](docs/guide/objects.md),
  [animation](docs/guide/animation.md), [sound and subtitles](docs/guide/sound-and-subtitles.md),
  [exporting](docs/guide/exporting.md), [shortcuts](docs/guide/shortcuts.md),
  [troubleshooting](docs/guide/troubleshooting.md)
- **For developers:** [architecture](docs/architecture.md), [contributing](CONTRIBUTING.md),
  [setup](docs/dev/setup.md), [testing](docs/dev/testing.md),
  [coding standards](docs/dev/coding-standards.md)
- **History and decisions:** [roadmap](docs/roadmap.md), [decision records](docs/adr/README.md),
  [changelog](CHANGELOG.md)
- Everything else: [documentation index](docs/README.md)

## How it works

Manim's `Scene.play()` is a loop of `begin()`, `interpolate(alpha)` per frame, `finish()`.
Manim Studio runs that loop itself from the JSON project, so any frame can be computed at any
time in any order - which is what makes a scrubbable timeline possible - and uses Manim's own
Cairo renderer for the canvas and the export. More in [docs/architecture.md](docs/architecture.md).

## Repository layout

```text
src/manim_studio/   the application: core (no Qt), render, ui (PySide6), the helper processes, the CLI;
                    each in folders named for what the code does (docs/architecture.md)
tests/              pytest suite, laid out like the code; tests/test_architecture.py checks the layering
benchmarks/         performance scripts behind the numbers in docs/logs/benchmarks.md
examples/           example projects and the scripts that build them; example plugins
scripts/            release check, documentation tools
docs/               user guide, architecture, file format, ADRs, plans, logs, releases
```

## License

[MIT](LICENSE) © 2026 João Victor. Third-party licenses: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
