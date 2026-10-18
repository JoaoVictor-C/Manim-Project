# Manim Studio user guide

Manim Studio is a visual editor for [Manim](https://www.manim.community/) animations: you
build a scene from objects on a canvas, animate them with clips and keyframes on a timeline,
and Manim renders every frame - the preview is the video you export. These pages describe
version 0.3.0 (proposed, not yet released).

| page | read it to |
|---|---|
| [Getting started](getting-started.md) | install, open the editor and make a first animation in five minutes |
| [The editor](the-editor.md) | find your way around: the five pages, the panels, the canvas and the timeline |
| [Objects](objects.md) | add and edit shapes, text, equations and their parts, groups, images, graphs, Python objects and code layers |
| [Animation](animation.md) | animate with clips, presets, keyframes, curves, motion paths and markers; retime many things at once |
| [Sound and subtitles](sound-and-subtitles.md) | add sounds, mix them, write subtitles and use `.srt` files |
| [Exporting](exporting.md) | render MP4 videos, use the render queue, export a Python scene, render from the command line |
| [Keyboard shortcuts](shortcuts.md) | every shortcut and mouse gesture (generated from the editor) |
| [Troubleshooting](troubleshooting.md) | fix missing LaTeX, trust prompts, slow previews; find logs and recovery copies |

Conventions: menu paths are written **File > Export Video...**; keys as `Ctrl+E` (Windows
names; Ctrl is Cmd on macOS). "The playhead" is the current time on the timeline.

In the editor, **Help > Keyboard Shortcuts...** (`F1`) lists every shortcut with a search
field, and most buttons and menu items explain themselves in a tooltip.

## See also

- [README](../../README.md) - the project at a glance
- [Project file format](../project-format.md) - the JSON a project is saved as
- [Documentation index](../README.md) - developer documentation, decisions and plans
