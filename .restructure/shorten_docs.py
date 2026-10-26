import pathlib

p = pathlib.Path(__file__).parent / "layout.py"
t = p.read_text(encoding="utf-8")
head = t[: t.index("DOCS = {")]
docs = {
    "manim_studio.processes": "The processes the editor starts (``python -m manim_studio.processes.X``).",
    "manim_studio.data": "Files that ship with the package (not code): the built-in library, Manim's names.",
    "manim_studio.core.model": "The project document and the rules that need nothing else (ADR 0002).",
    "manim_studio.core.editing": "Changing a project: edits, undo snapshots, shifting, clipboard (ADR 0013, 0014).",
    "manim_studio.core.engine": "Turning a project into frames with Manim: adapter, evaluator, caches (ADR 0002, 0006).",
    "manim_studio.core.sound": "Sound and subtitles without Qt: the mix, levels, tables, cues (ADR 0034, 0035).",
    "manim_studio.core.code": "Running and keeping the user's code: cache, trust, helpers, chapters (ADR 0019, 0061).",
    "manim_studio.core.assist": "Helping while code is typed, without Qt: completion, hints, snippets (ADR 0057).",
    "manim_studio.core.exchange": "Code in and out of the project: files, presets, imported scenes (ADR 0053, 0057).",
    "manim_studio.ui.style": "How the editor looks: colour tokens, icons, small field widgets (ADR 0040).",
    "manim_studio.ui.session": "What every part of the window shares: document, selection, settings (ADR 0014).",
    "manim_studio.ui.shell": "Pieces of the main window: welcome, shortcuts, plugins, autosave (ADR 0038, 0044).",
    "manim_studio.ui.services": "The editor's side of its helper processes: worker, preview, code renders (ADR 0015).",
    "manim_studio.ui.playback": "Playing the animation: audio player, control bar, full-screen presenter (ADR 0034).",
    "manim_studio.ui.deliver": "Exporting video from the editor: dialog, export process, render queue (ADR 0017, 0042).",
    "manim_studio.ui.canvas": "The canvas and what is done on it: gizmos, handles, snapping, viewport (ADR 0016, 0043).",
    "manim_studio.ui.panels": "Docks and dialogs that edit the selection: layers, properties, presets, values.",
    "manim_studio.ui.code": "The Code workspace: editor, explorer, syntax, history, helpers (ADR 0057, 0058, 0061).",
    "manim_studio.ui.exchange": "Bringing code in and writing it out: import and export windows (ADR 0057).",
}
for k, v in docs.items():
    assert len(f'"""{v}"""') <= 110, (k, len(v))
body = "".join(f'    "{k}": "{v}",\n' for k, v in docs.items())
p.write_text(head + "DOCS = {\n" + body + "}\n", encoding="utf-8")
print(len(docs), "docstrings ok")
