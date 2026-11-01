# Exporting

Video exports are rendered by Manim's own Cairo renderer from the same evaluator the canvas
uses, so the video matches what you see. They run in a separate process: you keep editing
while a video renders, and an existing file is only replaced once the new video is complete.

## Export Video

**File > Export Video...** (`Ctrl+E`) renders the whole scene, as it is when you press
**Export** (saved or not), to an MP4 at the project's size and frame rate, with its sound and
subtitles. The dialog shows the frames done, a progress bar and the time left; **Cancel** stops
it without touching an existing video; **Open folder** shows the result. A project never saved
suggests a file next to your last project (else in `Documents/Manim Studio` if that folder
exists, else in Documents).

## The Deliver page

`Ctrl+5` is the full export, with its own settings (they start from the project's canvas and
do not change the project):

| setting | choices |
|---|---|
| **Save as** | the MP4 file (**Browse...**) |
| **Size** | the project's size; 480p, 720p, 1080p, 1440p or 2160p at the canvas's proportions; or **Custom** width x height |
| **Frame rate** | 1-240 fps |
| **Range** | **Whole scene**, **From - to** (seconds), or **Between two markers** |
| **Quality** | Draft (crf 28), Standard (crf 23), High (crf 18, the default), Archive (crf 12) |
| **Subtitles** | burned into the video and an `.srt` beside it; an `.srt` beside the video only; none |

**Add to queue** adds an export. The **render queue** runs its exports one after another while
you keep editing - each uses the project as it was when it was added. **Start queue**,
**Cancel**, **Remove**, **Clear finished** and **Open folder** (or double-click a row) manage it.
A queue is not saved: queued renders are lost when the editor quits.

**Long exports resume.** A video of 20 seconds or more is rendered in 10-second segments kept in a
folder beside it (`clip.export/` for `clip.mp4`) and joined when the last one is done. If the
export is cancelled, crashes or the computer turns off, adding the same export again (same project,
same settings, same file) asks **Resume export (N of M segments done)** or **Start over**; resuming
renders only the segments that are missing or damaged. The folder is removed when the video is
complete; one left untouched for a week is removed by the next long export to the same folder. It
holds about as much as the finished video.

The page also shows the **Python scene** the project would export, says whether it is readable
or exact (and why), and saves it with **Save as...**.

## Python export

**File > Export Python...** (or the Deliver page, or `manim-studio python`) writes the project
as a Manim scene file you can keep working on in code. It is one-way: a Python file cannot be
opened back in the editor.

### Readable or exact

- **Readable** (preferred): plain Manim code - configuration, one variable per object, and
  `self.play(...)` / `self.wait(...)` in time order. It needs only Manim. Keyframed objects are
  written as data tables drawn by a small `Keyed` helper class in the file; Python objects'
  code is written once at the top. Every built-in preset and `examples/euler.json` export
  readable.
- **Exact**: when the project uses something plain `self.play` code cannot reproduce exactly,
  the file plays the project through Manim Studio's evaluator (`manim_studio.manim_scene`), so
  it needs the `manim_studio` package installed. Its header lists every reason.

Things that make the export exact include: parts of an equation and objects on axes (they are
evaluated as one object), groups, code layers, plugin objects, traced paths and simulations,
a turned or scaled object that also has clips (unless it is keyed), turning along a path, some
keyed connectors and keyed objects moving along a path, a morph target with its own lifetime,
objects appearing or disappearing during other animations, a trimmed or faded sound or one
longer than the scene, and burned-in subtitles. The exact list is printed when you export (see
below) and shown on the Deliver page.

Render the file with Manim as usual, for example:

```bash
manim render scene.py SceneName
```

## Command line

`manim-studio render` renders a project without the editor:

```bash
manim-studio render project.json out.mp4
```

| option | meaning |
|---|---|
| `--size WxH` | video size in pixels (default: the project's canvas) |
| `--fps FPS` | frames per second (default: the project's canvas) |
| `--start START` / `--end END` | the range in seconds (default: 0 to the scene's end) |
| `--crf CRF` | H.264 quality, 0 best to 51 worst (default: 18) |
| `--subtitles {burn,srt,none}` | burned in and an `.srt` beside the video; only the `.srt`; neither (default: as the project) |
| `--trust-code` | run the project's Python code: code layers not rendered yet and Python objects not in your trusted store |
| `--cache-dir DIR` | Manim's cache (default: `.cache/manim` next to the project file) |
| `--progress {text,json}` | `json`: one JSON object per line, for scripts |
| `--fresh` | start again from the first frame instead of resuming the segments an interrupted export left (by default it resumes) |
| `--segment-seconds S` | render a video of two segments or more in segments this long, so an interrupted export can resume (default: 10) |

Without `--trust-code`, code layers not rendered yet and untrusted Python objects are drawn as
placeholders and a warning says which. A bad project or option prints one `error:` line and
exits with status 2.

`manim-studio python` writes the Python scene:

```bash
manim-studio python project.json scene.py
```

It prints `wrote scene.py (readable)` or `(exact)`, followed by each `exact because:` reason.
`--scene NAME` sets the scene class name (default: from the output file's name), and
`--cache-dir` points at the editor's cache for code layers' frames (exact form).

Add `-v` (info) or `-vv` (debug) before the command for console logging:
`manim-studio -v render ...`. `manim-studio --version` prints the versions.

## See also

- [Sound and subtitles](sound-and-subtitles.md) - what the export carries
- [Objects](objects.md#python-objects) - Python objects and code layers, and trust
- [Troubleshooting](troubleshooting.md) - when an export fails or is slow
- [User guide index](index.md)
