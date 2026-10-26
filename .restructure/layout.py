"""The target layout: every module of src/manim_studio and the package it moves to.

Keys are module names relative to ``manim_studio`` (dotted); values are the new dotted name.
A module that stays is not listed. File names never change: only the folder does.
"""

GROUPS: dict[str, list[str]] = {
    # -- processes: what runs as ``python -m manim_studio.processes.X`` ------------------------------
    "processes": ["worker", "preview", "code_runner", "scene_recorder", "scene_probe", "helper_check"],
    # -- core: the model and the engine, no Qt -------------------------------------------------------
    "core.model": [
        "core.schema",
        "core.layer_index",
        "core.parts",
        "core.expressions",
        "core.glyph_colours",
        "core.shape",
        "core.motion_paths",
        "core.scene_length",
        "core.recovery",
    ],
    "core.editing": ["core.tables", 
        "core.edits",
        "core.shift_timing",
        "core.clipboard",
        "core.equation_steps",
        "core.library",
    ],
    "core.engine": ["core.placement", 
        "core.adapter",
        "core.evaluator",
        "core.morph",
        "core.frame_cache",
        "core.warm",
        "core.python_export",
        "core.standalone",
    ],
    "core.sound": ["core.audio", "core.levels", "core.subtitles"],
    "core.code": [
        "core.code_cache",
        "core.code_frame",
        "core.code_history",
        "core.python_object",
        "core.python_templates",
        "core.trust",
        "core.limits",
        "core.helpers",
        "core.scene_analysis",
        "core.scene_split",
    ],
    "core.assist": [
        "core.completion",
        "core.diagnostics",
        "core.error_hints",
        "core.error_tally",
        "core.manim_names",
        "core.snippets",
        "core.outline",
        "core.source_text",
        "core.run_to_cursor",
        "core.live_guard",
        "core.params_edit",
        "core.helper_extract",
    ],
    "core.exchange": [
        "core.code_files",
        "core.code_export",
        "core.code_import",
        "core.preset_library",
        "core.preset_online",
        "core.scene_import",
    ],
    # -- ui: the editor (PySide6) --------------------------------------------------------------------
    "ui.style": ["ui.render_activity", "ui.theme", "ui.icons", "ui.elided_label", "ui.fields"],
    "ui.session": ["ui.editor_settings", "ui.code_drag", 
        "ui.document",
        "ui.selection",
        "ui.build_service",
        "ui.places",
        "ui.preferences",
    ],
    "ui.shell": ["ui.autosave", "ui.clipboard_actions", 
        "ui.welcome",
        "ui.new_project_dialog",
        "ui.shortcuts_help",
        "ui.plugins_dialog",
    ],
    "ui.services": [
        "ui.worker_process",
        "ui.preview_client",
        "ui.render_ahead",
        "ui.code_render",
        "ui.helper_checker",
        "ui.scene_import",
    ],
    "ui.playback": ["ui.audio_player", "ui.player_bar", "ui.presenter"],
    "ui.deliver": ["ui.export_dialog", "ui.export_job", "ui.render_queue"],
    "ui.canvas": [
        "ui.canvas",
        "ui.canvas_tools",
        "ui.gizmo",
        "ui.motion_overlay",
        "ui.param_handles",
        "ui.snap_guides",
        "ui.viewport",
        "ui.arrange",
    ],
    "ui.timeline": ["ui.graph_editor", "ui.graph_model", "ui.curve_editor"],  # joins model.py, view.py
    "ui.panels": ["ui.values_panel", 
        "ui.layers_panel",
        "ui.properties_panel",
        "ui.presets_browser",
        "ui.equation_steps_dialog",
        "ui.glyph_colours_dialog",
    ],
    "ui.code": [
        "ui.code_editor",
        "ui.code_syntax",
        "ui.code_drafts",
        "ui.code_explorer",
        "ui.code_helpers",
        "ui.code_history_dialog",
        "ui.find_bar",
        "ui.snippet_dialog",
        "ui.quick_open",
        "ui.chapters",
        "ui.params_definition",
    ],
    "ui.exchange": [
        "ui.code_importer",
        "ui.import_code_dialog",
        "ui.export_code_dialog",
        "ui.online_presets_dialog",
        "ui.conflict_dialog",
    ],
}


def mapping() -> dict[str, str]:
    """old dotted name (without the ``manim_studio.`` prefix) -> new dotted name."""
    out: dict[str, str] = {}
    for package, modules in GROUPS.items():
        for module in modules:
            leaf = module.rsplit(".", 1)[-1]
            out[module] = f"{package}.{leaf}"
    return out


DOCS = {
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
