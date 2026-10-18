# Getting started

## What you need

- **Python 3.13** and **[uv](https://docs.astral.sh/uv/)** (on Windows: `winget install astral-sh.uv`,
  then `uv python install 3.13`).
- **A LaTeX distribution** for equations: [MiKTeX](https://miktex.org/) on Windows
  (`winget install MiKTeX.MiKTeX`) or TeX Live. It is optional - without it everything works
  except `MathTex`/`Tex` objects, which are drawn as a dashed placeholder.
- Nothing else: video is encoded by PyAV (FFmpeg included), and Manim comes as a dependency.

## Install

From a release wheel:

```bash
uv tool install manim_studio-0.3.0-py3-none-any.whl
```

This puts a `manim-studio` command on your PATH. Check it:

```bash
manim-studio --version
```

It prints the versions of Manim Studio, Manim and Python, for example
`manim-studio 0.3.0 (Manim 0.22.0, Python 3.13.16)`.

To run from a clone of the repository instead (for development), follow
[docs/dev/setup.md](../dev/setup.md); in short, `uv sync` and then `uv run manim-studio edit`.
On Windows, a user folder with non-ASCII characters (such as `C:\Users\João`) needs one extra
step described there.

## Open the editor

```bash
manim-studio edit
```

With no project open, the viewer shows a welcome panel: **New**, **Open...**, **Open Example**
and your recent files. **Open Example** (also **File > Open Example**) opens the showcase
scene as an untitled copy you can change freely - a good way to look around. To open a file
directly: `manim-studio edit path/to/project.json`.

## Your first animation in five minutes

1. **New project.** **File > New** (`Ctrl+N`). The scene is 1280x720 at 30 fps and 5 s long; it
   grows by itself when you place something past its end. With nothing selected, Properties
   shows the **Scene** settings (length, size, frame rate, background).
2. **Add a title.** In the Layers panel, **Add > Text > Text**. The object appears on the
   canvas and is selected; type your words in Properties. Drag it on the canvas to move it,
   drag a corner to scale it.
3. **Add an equation.** **Add > Text > MathTex**, then type LaTeX such as `a^2 + b^2 = c^2` in
   Properties and press `Ctrl+Enter`. New objects are placed where they do not cover the others.
   The first build of a formula takes a moment; the field shows the new LaTeX in italics until
   it is built.
4. **Animate it.** Move the playhead (click the ruler above the timeline) to where the
   equation should appear, right-click the equation's row and choose
   **Add clip > Appear / disappear > Write**. Or pick a ready-made animation:
   **Animate > Apply Preset** (or **Animate > Browse Presets...**, `Ctrl+Shift+P`, which shows
   each preset moving). Press `Space` to play.
5. **Move something over time.** Give the title an entrance first: select it, put the playhead
   at 0 and choose **Animate > Apply Preset > Entrance > Fade in**. Then turn on
   **Edit > Auto-key** (the **Record** button on the Animate page does the same), move the
   playhead later, and drag the title somewhere else: it now glides there. Auto-key only
   animates an object that already has an entrance; on a brand-new object it just places it -
   see [Animation](animation.md#auto-key).
6. **Add sound and subtitles.** **File > Import Audio...** adds a sound at the playhead; it
   gets its own row with a waveform. **Edit > Add Subtitle** (`Ctrl+T`) adds a subtitle at the
   playhead; type it in Properties.
7. **Save.** **File > Save** (`Ctrl+S`). A project is one `.json` file; images, SVGs and
   sounds stay where they are on disk and are referenced by path.
8. **Export the video.** **File > Export Video...** (`Ctrl+E`) renders an MP4 in the
   background, with the sound and burned-in subtitles. For size, frame rate, range, quality
   and a queue of several renders, use the **Deliver** page (`Shift+5`).
9. **Export Python.** **File > Export Python...** writes the scene as a Manim script you can keep
   working on in code - plain `self.play(...)` code when possible. See
   [Exporting](exporting.md#python-export).

Everything you did is undoable with `Ctrl+Z` (redo `Ctrl+Y`). While you have unsaved changes,
a recovery copy is written every 30 seconds.

## Render without the editor

```bash
manim-studio render project.json out.mp4
```

See [Exporting](exporting.md#command-line) for every option.

## See also

- [The editor](the-editor.md) - the pages, panels and gestures
- [Objects](objects.md) and [Animation](animation.md) - what you can build and how it moves
- [Troubleshooting](troubleshooting.md) - LaTeX, trust prompts, logs
- [User guide index](index.md)
