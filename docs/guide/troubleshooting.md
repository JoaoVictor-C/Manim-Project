# Troubleshooting

## Equations show a dashed box

`MathTex` and `Tex` objects need a LaTeX distribution. Without one they are drawn as a dashed
placeholder and the status bar says *LaTeX is not installed (latex was not found): install
MiKTeX or TeX Live*. Everything else keeps working.

- **Windows:** install [MiKTeX](https://miktex.org/) (`winget install MiKTeX.MiKTeX`) and let it
  install missing packages on the fly, so the first formula does not stall on a dialog:

  ```bash
  initexmf --set-config-value=[MPM]AutoInstall=1
  ```

  Manim Studio finds a per-user MiKTeX in `%LOCALAPPDATA%\Programs\MiKTeX` even when it is not on
  PATH. MiKTeX also aborts when a PATH entry is a *file* rather than a folder; the editor drops
  such entries for its own process, but other tools you run by hand may still trip on them.
- **Linux / macOS:** install TeX Live (or MacTeX) so that `latex` and `dvisvgm` are on PATH.
- **A LaTeX error** in your formula is reported with LaTeX's own message; fix the formula and
  apply it again (`Ctrl+Enter`).
- **The first formula is slow:** a new formula takes about a second to build, longer when MiKTeX
  downloads a package. Built formulas are cached, so they are instant afterwards.

## "Run code from this project?"

A project can contain Python code - [code layers](objects.md#code-layers) and
[Python objects](objects.md#python-objects). Opening a project whose code you have not trusted
on this computer lists that code and asks before running it. Answer **Yes** only if you trust
where the project came from. If you answer **No**, those objects are drawn as dashed
placeholders ("code not trusted yet"); running the code on the Code page later trusts it.
Running code is not sandboxed: it can read and write your files and use the network, like any
program you start.

Trust is remembered per exact code (a hash) in a store file (see
[below](#where-files-live)); changed code asks again. From the command line, `--trust-code`
runs everything in that one render. Plugins are code you installed yourself; one with a manifest
is allowed once in Help > Plugins before it loads, and none of them is sandboxed.

## Playback is slow or stutters

- Leave **View > Render Ahead** on: frames are rendered ahead of the playhead in a second
  process and kept. The readout under the canvas counts them (`ahead 120/150`); once they are
  ready, playing and scrubbing are smooth. An edit only re-renders the frames it changes.
- Turn on **View > Half-resolution playback** for heavy scenes.
- A Python object's or code layer's first build takes longer; so does the first build of each
  formula.
- If a video plays without sound, check that a sound output device exists: without one,
  playback follows the wall clock instead of the sound card.

## Manim Studio uses a lot of memory

Behind the window are helper processes - the one that builds text and formulas, the one that renders frames
ahead, one for each code layer being rendered - and each is a Python with Manim loaded, about 120 MB. Several
`python.exe` entries under Manim Studio in the Task Manager are normal while a project is open. They start when
there is work for them (the welcome page runs none), they are given back after ten minutes without work (the
next build or frame then takes a few seconds longer), and closing the window - or ending the editor in any
other way - ends all of them. To give them back sooner, start the editor with `MANIM_STUDIO_IDLE_SECONDS=120`
(`0` keeps them for good). Playback keeps at most 256 MB of rendered frames.

## Manim Studio closed without saving

While you have unsaved changes, a recovery copy is written every 30 seconds. The next time
Manim Studio starts (or when you open that file) it asks **Recover unsaved work?**:
**Restore** opens the most recent copy as unsaved changes to its original file, **Discard**
deletes the copies, **Later** keeps them for next time. Copies are deleted once you save.

## Something else went wrong

**Help > Open Log Folder** opens the folder of the editor's log (`manim-studio.log`, rotated at
2 MB, three old copies kept). Attach it when reporting a problem, with the project file (or a
small one that shows the problem). Start the editor with `manim-studio -vv edit` for debug
output in the console too.

A project that cannot be opened shows why (the file is checked when it is read). Images, SVGs or
sounds that moved show as placeholders or warnings - they are referenced by absolute path.

## Windows installation problems

These affect running from source; see [docs/dev/setup.md](../dev/setup.md#troubleshooting-windows)
for details.

- A user or project folder with non-ASCII characters (such as `C:\Users\João` or
  `Programação`) breaks uv's interpreter lookup and Python 3.12's handling of editable
  installs; use Python 3.13 and point uv at the interpreter explicitly.

## Where files live

Paths on Windows; each can be moved with the environment variable in the last column.

| what | where | variable |
|---|---|---|
| Preferences (recent files, window, panel sizes, view toggles, last page) | `%LOCALAPPDATA%\Manim Studio\manim-studio.ini` | `MANIM_STUDIO_SETTINGS` (the file) |
| Log | `%LOCALAPPDATA%\ManimStudio\logs\manim-studio.log` | `MANIM_STUDIO_LOG_DIR` |
| Recovery copies | `%APPDATA%\Manim Studio\recovery\` | `MANIM_STUDIO_RECOVERY` |
| Manim's cache for the editor (built text and formulas, code layer frames) | `%LOCALAPPDATA%\Manim Studio\cache\manim\` | `MANIM_STUDIO_CACHE` |
| Trusted code store | `%LOCALAPPDATA%\ManimStudio\trusted-code.json` | `MANIM_STUDIO_TRUST_FILE` |
| Your presets, themes and templates | `~\.manim-studio\library\` | `MANIM_STUDIO_LIBRARY` |
| Plugins | `~\.manim-studio\plugins\` | `MANIM_STUDIO_PLUGINS` (several folders, `;`-separated) |
| Plugin approvals | `%LOCALAPPDATA%\ManimStudio\plugin-approvals.json` | `MANIM_STUDIO_PLUGIN_APPROVALS` |
| New projects and exports, by default | next to your last project, else `Documents\Manim Studio` if it exists, else Documents | - |

On Linux the log is in `~/.local/state/manim-studio/logs/` and the trusted code store in
`~/.local/share/manim-studio/`; preferences, recovery copies and the cache follow Qt's standard
locations for an application named "Manim Studio". `manim-studio render` (without the editor)
caches next to the project, in `.cache/manim`, unless given `--cache-dir`.

Deleting the preferences file resets the editor; deleting the cache only costs rebuild time.

## See also

- [Getting started](getting-started.md) - installation
- [Developer setup](../dev/setup.md) - running from source, Windows details
- [Exporting](exporting.md#command-line) - command-line options
- [User guide index](index.md)
