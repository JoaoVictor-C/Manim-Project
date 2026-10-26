"""Where each test file goes. Keys: the new folder under tests/; values: stems of test files (no ``test_``).

tests/core/<domain>/   mirrors src/manim_studio/core/<domain>/; ``features`` holds the behaviour tests that run a
                       whole project through the evaluator (they belong to no single module)
tests/ui/<area>/       mirrors src/manim_studio/ui/<area>/
tests/acceptance/      the slice-by-slice walks a user would do (``test_acceptance_*``)
"""

CORE = {
    "core/model": [
        "schema", "layer_index", "parts", "scene_length", "recovery", "glyph_colours", "glyph_colour_helpers",
        "motion_paths", "shapes", "lifetime", "validation_paths", "part_layers",
    ],
    "core/editing": [
        "edits", "shift_timing", "clipboard", "library", "equation_steps", "equation_steps_layers", "tables",
        "set_params", "properties",
    ],
    "core/engine": [
        "adapter", "registry", "easing", "random_access", "invalidation", "frame_cache", "frame_store_scaling",
        "morph", "morph_frames", "placement", "python_export", "python_export_keyed", "standalone", "warm",
        "cache_lock", "transforms", "matching_tex",
    ],
    "core/sound": ["audio", "audio_spans", "levels", "subtitles"],
    "core/code": [
        "code_cache", "code_history", "code_layers", "helpers", "helpers_running", "limits", "python_objects",
        "python_templates", "render_hash", "scene_analysis", "scene_split",
    ],
    "core/assist": [
        "completion", "diagnostics", "error_hints", "error_tally", "helper_extract", "live_guard", "manim_names",
        "outline", "params_edit", "run_to_cursor", "snippets",
    ],
    "core/exchange": [
        "code_export", "code_files", "code_import", "preset_library", "preset_online", "scene_import",
    ],
    "core/features": [
        "anchor", "axes_objects", "camera", "child_trees", "clip_kinds", "graphs", "groups", "images", "markers",
        "no_latex", "part_colour", "parts_build", "paths", "readouts", "right_triangle", "rotate_along",
        "simulated_layers", "smart_transform_file", "svg",
    ],
    "": ["plugins"],  # the public plugin API: top of tests/
}

UI = {
    "ui/style": ["elided_label", "render_activity", "theme"],
    "ui/session": ["build_service", "document", "places", "preferences", "selection"],
    "ui/shell": ["autosave", "clipboard_ui", "plugins_ui", "shortcuts_help"],
    "ui/services": ["code_render", "preview_process", "render_ahead", "worker_process", "scene_import_ui"],
    "ui/playback": ["audio_ui", "audio_spans_ui", "player_bar"],
    "ui/deliver": ["export_dialog", "export_job", "render_queue"],
    "ui/canvas": [
        "arrange", "camera_ui", "canvas_tools", "framing", "gizmo", "motion_path_ui", "param_handles",
        "param_handles_ui", "part_canvas", "path_ui", "snap_guides", "viewport",
    ],
    "ui/timeline": [
        "curve_editor", "graph_model", "graph_ui", "markers_ui", "multiselect_ui", "shift_timing_ui",
        "timeline_model", "timeline_multiselect", "timeline_view",
    ],
    "ui/panels": [
        "axes_objects_ui", "equation_steps_ui", "glyph_colours_ui", "groups_ui", "layers_panel", "part_colour_ui",
        "presets_browser", "presets_ui", "properties_panel", "property_rows", "readouts_ui", "shapes_ui",
        "simulated_layers_ui", "svg_ui", "values_panel",
    ],
    "ui/code": [
        "chapters_ui", "code_drop", "code_explorer", "code_hints", "code_history_ui", "code_layer_ui", "code_page",
        "code_syntax", "code_workspace", "editor_features", "find_bar", "helpers_ui", "live_mode",
        "params_definition", "python_objects_ui", "quick_open", "snippets_ui",
    ],
    "ui/exchange": [
        "code_export_ui", "code_files", "code_importer", "conflict_dialog", "import_code_dialog",
        "online_presets_dialog",
    ],
    "ui/pages": ["animate_page", "audio_page", "deliver_page", "pages"],
    # whole-window behaviour stays at the root of tests/ui/
    "ui": [
        "golden_path", "layout_checks", "long_scene_scaling", "main_window", "morph_default",
        "panels_and_fullscreen", "python_export_ui", "scene_settings", "subtitles_ui",
    ],
}

ROOT = {  # stay at the top of tests/ (public surface, repository checks), or follow the process modules
    "": ["docs_links", "import_cli", "logging", "version"],
    "processes": ["code_runner", "helper_check", "scene_chapters", "scene_recorder", "worker_messages"],
}

# helper / fixture files that travel with a folder
FILES = {
    "tests/core/euler_example.json": "tests/core/engine/euler_example.json",
    "tests/core/golden_readable_export.txt": "tests/core/engine/golden_readable_export.txt",
    "tests/ui/code_page_helpers.py": "tests/ui/code/code_page_helpers.py",
}


def mapping(existing: dict[str, str]) -> dict[str, str]:
    """old path -> new path, for every ``test_*.py`` listed in ``existing`` (stem -> old path)."""
    return {}
