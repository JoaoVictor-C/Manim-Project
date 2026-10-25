# The Code workspace

The **Code** page (`Ctrl+3`) is where code layers and Python objects are written, and where the
editor keeps its **presets**: pieces of code you reuse. It works like a small code editor, with
the viewer beside it so every run shows at once.

## Layout

- **Explorer** (left; the button at the left of the tabs, or `Ctrl+B`, hides and shows it). **This project** lists the code layers (Manim scenes) and Python objects of
  the scene; **Presets** are grouped as *built in*, *mine* and *downloaded*. Type in the filter to
  narrow the lists. A dot after a name means unapplied changes, `!` an error, `?` code that has
  not been allowed to run yet. Each row has the Python logo: blue for a Python object, yellow for a
  Manim scene. Right-click a row for what you can do with it.
- **Tabs** (top of the editor): one for each layer you opened. Close the ones you do not need; the
  layer stays in the project, and unapplied text stays with it.
- **Editor**: highlighting, line numbers, auto-indent, brackets and quotes that close themselves.
  Under it the **Output** (`Ctrl+J`, or its button, shows or hides it) says how the last run went and
  links an error to its line, and a **status strip** shows the line and column, the indent size,
  what the layer is and whether it may run.
- **The picture** beside the editor is plain: the blue selection outline and handles are not drawn
  over it while you are on this page, so you can see what the code makes. The **outline** button in
  the toolbar brings them back (remembered); the other pages always draw them.

## Writing code

`Ctrl+Enter` (or **Run**) applies the text to the layer and runs it - one undo step. Nothing runs
while you type. While the code is being applied, built or rendered, a progress bar shows under the
toolbar and **Run** reads *Running...* and waits: when they go, the object or scene is ready to use.
While it works Run also shows the seconds it has taken, and afterwards how long the last run took.

**Values** is a second tab next to **Output**, for a Python object: one field per parameter its `PARAMS`
declares, so you can try values while you read the code. It is the same state as Properties - a value changed
in either shows in the other, and each change is one undo step. Add or rename a parameter in `PARAMS` and the
fields follow when you run.

**Live** (Editor menu) applies a Python object's code after you pause typing, so the picture follows the
code. It only runs text that parses, whose `PARAMS` can be read and that does not use files, processes, the
network or the import machinery (`open`, `os`, `subprocess`, `socket`, ...), and only for an object you have
already run once; otherwise the status bar says why and **Run** stays the way to decide. The whole stretch of
live changes is one undo step. It is a courtesy while typing, not a sandbox: running code is never sandboxed.

| key | does |
|---|---|
| `Ctrl+F`, `Ctrl+H`, `F3`, `Shift+F3` | find, replace, next, previous (the bar offers match case, whole word, regex) |
| `Alt+G` | go to a line (`Ctrl+G` is Group in the editor) |
| `Ctrl+P` | quick open: type a few letters of a layer's or preset's name |
| `Ctrl+/` | comment or uncomment the lines |
| `Alt+Up`, `Alt+Down` | move the lines |
| `Shift+Alt+Up`, `Shift+Alt+Down` | copy the lines up or down |
| `Ctrl+Shift+K`, `Ctrl+L` | delete the line, select the line |
| `Ctrl+=`, `Ctrl+-`, `Ctrl+0`, `Ctrl+wheel` | zoom |

The **Editor** menu next to Run holds every setting, and the editor remembers them: word wrap,
line numbers, highlighting the current line, showing spaces and tabs, closing brackets and quotes,
trimming trailing spaces when running, the indent size (2, 4 or 8) and the font size.

## Help while you write

- **Errors explain themselves.** An error in Output says what kind it is and, when it can, what to do: a
  misspelt Manim name offers the nearest real ones, a missing `from manim import *` has a one-click
  *Insert* button, a missing `PARAMS` key lists the keys that exist. Below it the traceback shows only
  your own lines (and your helpers'), not Manim's.
- **Syntax errors are marked** with a wavy underline after you pause typing - never on the line you are
  still writing, and not while a bracket or a triple-quoted string is still open.
- **Names are suggested** as you type (two letters, or `Ctrl+Space`): Manim's names, the names your code
  defines, a Manim object's methods after a dot (when the code shows what it is: `circle = Circle()`), and
  a call's keyword arguments inside its brackets. `Enter` or `Tab` takes one, `Esc` closes. Hover a name for
  a one-line description. Not in comments or strings; the Editor menu can turn it off.
- **Snippets** (`Ctrl+Shift+I`, Editor > Insert snippet): about fifty small pieces of Manim - shapes, an
  equation written in parts, axes and a graph, a number that counts up, a Python object. They are pasted at
  the cursor, indented to it, with their blanks selected one at a time: `Tab` moves to the next, `Esc`
  stops. All of it is one undo step.
- **Go to symbol** (`Ctrl+Shift+O`) lists the scenes, classes, functions, `PARAMS` and constants of the
  code in the editor.
- **Run to cursor** (Editor menu) shows a scene only as far as the statement under the cursor, by giving
  the layer a shortened copy of the code (one undo step; line numbers stay the same). The editor keeps the
  whole text; Run shows all of it again.
- **Cancel** appears next to Run while a scene renders and stops it. Run renders it again.
- **Copy as a Manim scene** (Editor menu) puts a Python object on the clipboard as a scene that runs by
  itself with `manim`, using the values the object has now.
- **History** (Editor menu): every Run keeps a version of the layer's code for this session. *Revert to
  last working version* puts the last version that ran without an error in the editor; *History...* lists
  the versions with a diff against the editor. Neither applies anything; Run does.
- **Parameters** is a third tab next to Output and Values for a Python object: add, rename, remove or
  change a parameter in `PARAMS` with buttons instead of typing the dictionary. It edits the text in the
  editor (one editor-undo step) and keeps your comments and layout; Run applies it.
- **Tags**: a saved preset can have tags (right-click > Tags...). The explorer's filter finds a preset by
  its name, description, tags, kind (`object`, `scene`) or origin (`mine`, `downloaded`).

## Presets

Choose a preset in the explorer to read its code (read-only). Then:

- **Add to project** puts it in the scene at the playhead (double-click does the same).
- **Edit a copy** adds it and opens the copy to change; the preset stays as it is.
- **Rename**, **Delete** (asks first) and **Export...** - for presets you added; the built-in ones can
  only be copied or exported.
- **Save as preset...** (Editor menu, or right-click a layer) keeps the code in the editor as a
  preset of yours. If the name is taken you are asked whether to replace the old one, skip, or keep
  both.

Presets you added are kept between sessions in your user data folder. Code from presets you added
or downloaded is **not** trusted until you run it; the built-in presets are the editor's own.

## Adding files

- **Add file...** opens the **import window** for the `.py` files you choose. For each one it shows
  what it was detected as - a *Python object* (a top-level `build(p)`) or a *Manim scene* (a `Scene`
  class) - and offers anything else that is possible, with the reason when something is not:
  - **Add it as**: a Python object, a Manim scene (a code layer; if the file has several scenes you
    tick which, one layer each), or **Preset only**, to keep it in your library without adding it.
  - **Name**, **Appears** (a time, or the playhead) and **Position** (a place on the canvas, or
    where it fits), when it goes into the project.
  - **Allow it to run now** (off by default) and **Also keep a copy in my presets**.
  - A preview of the code and, for objects, its parameters.
  Files that are neither are shown with the reason and cannot be imported. The files are only read:
  nothing runs until you allow it.
- **Import folder...** offers every `.py` file of a folder in the same window, set to *Preset only*.
- Drag `.py` files from the desktop onto the explorer, the editor, the timeline, the canvas or the
  Layers list to open the window for them (the timeline and canvas fill in the time and place you
  dropped them at).

## Getting presets from the internet

**Get online...** asks for a link and lists what it finds:

- a link to one `.py` file;
- a GitHub file, folder or repository, or a gist;
- an `index.json` (see below).

Tick the ones you want and press *Download and import*; they go to the import window (as presets to
keep). Links you used are kept in the list. Only HTTPS links work, each file may be up to 1 MB, and
what is downloaded is text that is never run by the download. If GitHub says you made too many
requests, wait a while.

To **share** presets, export them with *Also write index.json* ticked and put the folder on any
web page or repository; others paste the link to the `index.json`:

```json
{
  "format": 1,
  "name": "My pack",
  "presets": [
    {"name": "Matrix", "file": "Matrix.py", "kind": "object", "description": "Any size"},
    {"name": "Orbit", "file": "Orbit.py", "kind": "scene"}
  ]
}
```

`file` is relative to the `index.json`; `kind` and `description` are optional.

## Exporting

**Export...** (or *Export...* in a row's menu) opens a window: tick the layers and presets to write,
choose the folder, the line endings (LF or CRLF), whether each file starts with a comment naming it,
and whether to write the `index.json`. Your choices are remembered. The text written is what is in
the editor, applied or not. When a file with that name is already in the folder you are asked, for
each one: **Replace**, **Skip** or **Keep both** (the new one is written as `Name (2).py`), with a
box to do the same for all the rest; **Cancel** stops, keeping what was already written.
**Save code...** writes just the code in the editor to a file of your choice.

## Dragging

Drag a row of the explorer - a preset or a layer - onto:

- the **timeline**: a line shows the time it will appear at (it snaps like a clip; hold `Alt` to
  not snap);
- the **canvas**: a cross shows where it will be placed;
- the **Layers list**: it is added at the playhead.

A preset becomes a Python object or a code layer; a layer becomes a copy of itself (code, values,
keys and clips). Each is one undo step.

## See also

- [Objects](objects.md#python-objects) - what a Python object is and its rules
- [Troubleshooting](troubleshooting.md#run-code-from-this-project) - code that asks to be trusted
