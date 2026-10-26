# Where the modules went

The package layout changed in [ADR 0062](../adr/0062-package-layout.md): the same files, in folders named
for what they do. **No file was renamed and no code changed** - only the folder - so a bare `schema.py`
in an older ADR, plan, changelog entry or traceback is still the right file. This page is the lookup for
the old *paths* you may meet there. Names other things were written against did not move:
`manim_studio.manim_scene` (exported scenes import it), `manim_studio.plugins` (the plugin API),
`manim_studio.cli` and `python -m manim_studio`.

Generated from the move list of the restructure; it is a record, not a file to keep in sync by hand.

## Source modules

| was | is |
|---|---|
| `manim_studio.code_runner` | `manim_studio.processes.code_runner` |
| `manim_studio.core.adapter` | `manim_studio.core.engine.adapter` |
| `manim_studio.core.audio` | `manim_studio.core.sound.audio` |
| `manim_studio.core.clipboard` | `manim_studio.core.editing.clipboard` |
| `manim_studio.core.code_cache` | `manim_studio.core.code.code_cache` |
| `manim_studio.core.code_export` | `manim_studio.core.exchange.code_export` |
| `manim_studio.core.code_files` | `manim_studio.core.exchange.code_files` |
| `manim_studio.core.code_frame` | `manim_studio.core.code.code_frame` |
| `manim_studio.core.code_history` | `manim_studio.core.code.code_history` |
| `manim_studio.core.code_import` | `manim_studio.core.exchange.code_import` |
| `manim_studio.core.completion` | `manim_studio.core.assist.completion` |
| `manim_studio.core.diagnostics` | `manim_studio.core.assist.diagnostics` |
| `manim_studio.core.edits` | `manim_studio.core.editing.edits` |
| `manim_studio.core.equation_steps` | `manim_studio.core.editing.equation_steps` |
| `manim_studio.core.error_hints` | `manim_studio.core.assist.error_hints` |
| `manim_studio.core.error_tally` | `manim_studio.core.assist.error_tally` |
| `manim_studio.core.evaluator` | `manim_studio.core.engine.evaluator` |
| `manim_studio.core.expressions` | `manim_studio.core.model.expressions` |
| `manim_studio.core.frame_cache` | `manim_studio.core.engine.frame_cache` |
| `manim_studio.core.glyph_colours` | `manim_studio.core.model.glyph_colours` |
| `manim_studio.core.helper_extract` | `manim_studio.core.assist.helper_extract` |
| `manim_studio.core.helpers` | `manim_studio.core.code.helpers` |
| `manim_studio.core.layer_index` | `manim_studio.core.model.layer_index` |
| `manim_studio.core.levels` | `manim_studio.core.sound.levels` |
| `manim_studio.core.library` | `manim_studio.core.editing.library` |
| `manim_studio.core.limits` | `manim_studio.core.code.limits` |
| `manim_studio.core.live_guard` | `manim_studio.core.assist.live_guard` |
| `manim_studio.core.manim_names` | `manim_studio.core.assist.manim_names` |
| `manim_studio.core.morph` | `manim_studio.core.engine.morph` |
| `manim_studio.core.motion_paths` | `manim_studio.core.model.motion_paths` |
| `manim_studio.core.outline` | `manim_studio.core.assist.outline` |
| `manim_studio.core.params_edit` | `manim_studio.core.assist.params_edit` |
| `manim_studio.core.parts` | `manim_studio.core.model.parts` |
| `manim_studio.core.placement` | `manim_studio.core.engine.placement` |
| `manim_studio.core.preset_library` | `manim_studio.core.exchange.preset_library` |
| `manim_studio.core.preset_online` | `manim_studio.core.exchange.preset_online` |
| `manim_studio.core.python_export` | `manim_studio.core.engine.python_export` |
| `manim_studio.core.python_object` | `manim_studio.core.code.python_object` |
| `manim_studio.core.python_templates` | `manim_studio.core.code.python_templates` |
| `manim_studio.core.recovery` | `manim_studio.core.model.recovery` |
| `manim_studio.core.run_to_cursor` | `manim_studio.core.assist.run_to_cursor` |
| `manim_studio.core.scene_analysis` | `manim_studio.core.code.scene_analysis` |
| `manim_studio.core.scene_import` | `manim_studio.core.exchange.scene_import` |
| `manim_studio.core.scene_length` | `manim_studio.core.model.scene_length` |
| `manim_studio.core.scene_split` | `manim_studio.core.code.scene_split` |
| `manim_studio.core.schema` | `manim_studio.core.model.schema` |
| `manim_studio.core.shape` | `manim_studio.core.model.shape` |
| `manim_studio.core.shift_timing` | `manim_studio.core.editing.shift_timing` |
| `manim_studio.core.snippets` | `manim_studio.core.assist.snippets` |
| `manim_studio.core.source_text` | `manim_studio.core.assist.source_text` |
| `manim_studio.core.standalone` | `manim_studio.core.engine.standalone` |
| `manim_studio.core.subtitles` | `manim_studio.core.sound.subtitles` |
| `manim_studio.core.tables` | `manim_studio.core.editing.tables` |
| `manim_studio.core.trust` | `manim_studio.core.code.trust` |
| `manim_studio.core.warm` | `manim_studio.core.engine.warm` |
| `manim_studio.helper_check` | `manim_studio.processes.helper_check` |
| `manim_studio.preview` | `manim_studio.processes.preview` |
| `manim_studio.scene_probe` | `manim_studio.processes.scene_probe` |
| `manim_studio.scene_recorder` | `manim_studio.processes.scene_recorder` |
| `manim_studio.ui.arrange` | `manim_studio.ui.canvas.arrange` |
| `manim_studio.ui.audio_player` | `manim_studio.ui.playback.audio_player` |
| `manim_studio.ui.autosave` | `manim_studio.ui.shell.autosave` |
| `manim_studio.ui.build_service` | `manim_studio.ui.session.build_service` |
| `manim_studio.ui.canvas` | `manim_studio.ui.canvas.canvas` |
| `manim_studio.ui.canvas_tools` | `manim_studio.ui.canvas.canvas_tools` |
| `manim_studio.ui.chapters` | `manim_studio.ui.code.chapters` |
| `manim_studio.ui.clipboard_actions` | `manim_studio.ui.shell.clipboard_actions` |
| `manim_studio.ui.code_drafts` | `manim_studio.ui.code.code_drafts` |
| `manim_studio.ui.code_drag` | `manim_studio.ui.session.code_drag` |
| `manim_studio.ui.code_editor` | `manim_studio.ui.code.code_editor` |
| `manim_studio.ui.code_explorer` | `manim_studio.ui.code.code_explorer` |
| `manim_studio.ui.code_helpers` | `manim_studio.ui.code.code_helpers` |
| `manim_studio.ui.code_history_dialog` | `manim_studio.ui.code.code_history_dialog` |
| `manim_studio.ui.code_importer` | `manim_studio.ui.exchange.code_importer` |
| `manim_studio.ui.code_render` | `manim_studio.ui.services.code_render` |
| `manim_studio.ui.code_syntax` | `manim_studio.ui.code.code_syntax` |
| `manim_studio.ui.conflict_dialog` | `manim_studio.ui.exchange.conflict_dialog` |
| `manim_studio.ui.curve_editor` | `manim_studio.ui.timeline.curve_editor` |
| `manim_studio.ui.document` | `manim_studio.ui.session.document` |
| `manim_studio.ui.editor_settings` | `manim_studio.ui.session.editor_settings` |
| `manim_studio.ui.elided_label` | `manim_studio.ui.style.elided_label` |
| `manim_studio.ui.equation_steps_dialog` | `manim_studio.ui.panels.equation_steps_dialog` |
| `manim_studio.ui.export_code_dialog` | `manim_studio.ui.exchange.export_code_dialog` |
| `manim_studio.ui.export_dialog` | `manim_studio.ui.deliver.export_dialog` |
| `manim_studio.ui.export_job` | `manim_studio.ui.deliver.export_job` |
| `manim_studio.ui.fields` | `manim_studio.ui.style.fields` |
| `manim_studio.ui.find_bar` | `manim_studio.ui.code.find_bar` |
| `manim_studio.ui.gizmo` | `manim_studio.ui.canvas.gizmo` |
| `manim_studio.ui.glyph_colours_dialog` | `manim_studio.ui.panels.glyph_colours_dialog` |
| `manim_studio.ui.graph_editor` | `manim_studio.ui.timeline.graph_editor` |
| `manim_studio.ui.graph_model` | `manim_studio.ui.timeline.graph_model` |
| `manim_studio.ui.helper_checker` | `manim_studio.ui.services.helper_checker` |
| `manim_studio.ui.icons` | `manim_studio.ui.style.icons` |
| `manim_studio.ui.import_code_dialog` | `manim_studio.ui.exchange.import_code_dialog` |
| `manim_studio.ui.layers_panel` | `manim_studio.ui.panels.layers_panel` |
| `manim_studio.ui.motion_overlay` | `manim_studio.ui.canvas.motion_overlay` |
| `manim_studio.ui.new_project_dialog` | `manim_studio.ui.shell.new_project_dialog` |
| `manim_studio.ui.online_presets_dialog` | `manim_studio.ui.exchange.online_presets_dialog` |
| `manim_studio.ui.param_handles` | `manim_studio.ui.canvas.param_handles` |
| `manim_studio.ui.params_definition` | `manim_studio.ui.code.params_definition` |
| `manim_studio.ui.places` | `manim_studio.ui.session.places` |
| `manim_studio.ui.player_bar` | `manim_studio.ui.playback.player_bar` |
| `manim_studio.ui.plugins_dialog` | `manim_studio.ui.shell.plugins_dialog` |
| `manim_studio.ui.preferences` | `manim_studio.ui.session.preferences` |
| `manim_studio.ui.presenter` | `manim_studio.ui.playback.presenter` |
| `manim_studio.ui.presets_browser` | `manim_studio.ui.panels.presets_browser` |
| `manim_studio.ui.preview_client` | `manim_studio.ui.services.preview_client` |
| `manim_studio.ui.properties_panel` | `manim_studio.ui.panels.properties_panel` |
| `manim_studio.ui.quick_open` | `manim_studio.ui.code.quick_open` |
| `manim_studio.ui.render_activity` | `manim_studio.ui.style.render_activity` |
| `manim_studio.ui.render_ahead` | `manim_studio.ui.services.render_ahead` |
| `manim_studio.ui.render_queue` | `manim_studio.ui.deliver.render_queue` |
| `manim_studio.ui.scene_import` | `manim_studio.ui.services.scene_import` |
| `manim_studio.ui.selection` | `manim_studio.ui.session.selection` |
| `manim_studio.ui.shortcuts_help` | `manim_studio.ui.shell.shortcuts_help` |
| `manim_studio.ui.snap_guides` | `manim_studio.ui.canvas.snap_guides` |
| `manim_studio.ui.snippet_dialog` | `manim_studio.ui.code.snippet_dialog` |
| `manim_studio.ui.theme` | `manim_studio.ui.style.theme` |
| `manim_studio.ui.values_panel` | `manim_studio.ui.panels.values_panel` |
| `manim_studio.ui.viewport` | `manim_studio.ui.canvas.viewport` |
| `manim_studio.ui.welcome` | `manim_studio.ui.shell.welcome` |
| `manim_studio.ui.worker_process` | `manim_studio.ui.services.worker_process` |
| `manim_studio.worker` | `manim_studio.processes.worker` |

## Files that ship with the package

| was | is |
|---|---|
| `src/manim_studio/core/manim_names.json` | `src/manim_studio/data/manim_names.json` |
| `src/manim_studio/library/` (43 files) | `src/manim_studio/data/library/` |

## Tests

The tests follow the code they test. Each test file kept its name:

- `tests/`: `test_plugins.py` (from `tests/core/`)
- `tests/acceptance/`: `test_acceptance_p2a.py` (from `tests/ui/`), `test_acceptance_p2b.py` (from `tests/ui/`), `test_acceptance_p2c.py` (from `tests/ui/`), `test_acceptance_p2d.py` (from `tests/ui/`), `test_acceptance_p2e.py` (from `tests/ui/`), `test_acceptance_p2f.py` (from `tests/ui/`), `test_acceptance_p2g.py` (from `tests/ui/`), `test_acceptance_p3a.py` (from `tests/ui/`), `test_acceptance_p3b.py` (from `tests/ui/`), `test_acceptance_p3c.py` (from `tests/ui/`), `test_acceptance_p3d.py` (from `tests/ui/`), `test_acceptance_p3e.py` (from `tests/ui/`), `test_acceptance_p3f.py` (from `tests/ui/`), `test_acceptance_p3g.py` (from `tests/ui/`), `test_acceptance_p3h.py` (from `tests/ui/`), `test_acceptance_p4a.py` (from `tests/ui/`), `test_acceptance_p4b.py` (from `tests/ui/`), `test_acceptance_p4c.py` (from `tests/ui/`), `test_acceptance_p4d.py` (from `tests/ui/`), `test_acceptance_p5a.py` (from `tests/ui/`), `test_acceptance_p5b.py` (from `tests/ui/`), `test_acceptance_p5c.py` (from `tests/ui/`), `test_acceptance_p5d.py` (from `tests/ui/`), `test_acceptance_p5e.py` (from `tests/ui/`), `test_acceptance_p6b2.py` (from `tests/ui/`), `test_acceptance_p6b3.py` (from `tests/ui/`), `test_acceptance_p6b4.py` (from `tests/ui/`), `test_acceptance_p6b5.py` (from `tests/ui/`), `test_acceptance_p6c.py` (from `tests/ui/`), `test_acceptance_p6d1.py` (from `tests/ui/`), `test_acceptance_p6d3.py` (from `tests/ui/`), `test_acceptance_p7_3.py` (from `tests/ui/`), `test_acceptance_s2.py` (from `tests/ui/`), `test_acceptance_s3.py` (from `tests/ui/`), `test_acceptance_v1.py` (from `tests/ui/`)
- `tests/core/assist/`: `test_completion.py` (from `tests/core/`), `test_diagnostics.py` (from `tests/core/`), `test_error_hints.py` (from `tests/core/`), `test_error_tally.py` (from `tests/core/`), `test_helper_extract.py` (from `tests/core/`), `test_live_guard.py` (from `tests/core/`), `test_manim_names.py` (from `tests/core/`), `test_outline.py` (from `tests/core/`), `test_params_edit.py` (from `tests/core/`), `test_run_to_cursor.py` (from `tests/core/`), `test_snippets.py` (from `tests/core/`)
- `tests/core/code/`: `test_code_cache.py` (from `tests/core/`), `test_code_history.py` (from `tests/core/`), `test_code_layers.py` (from `tests/core/`), `test_helpers.py` (from `tests/core/`), `test_helpers_running.py` (from `tests/core/`), `test_limits.py` (from `tests/core/`), `test_python_objects.py` (from `tests/core/`), `test_python_templates.py` (from `tests/core/`), `test_render_hash.py` (from `tests/core/`), `test_scene_analysis.py` (from `tests/core/`), `test_scene_split.py` (from `tests/core/`)
- `tests/core/editing/`: `test_clipboard.py` (from `tests/core/`), `test_edits.py` (from `tests/core/`), `test_equation_steps.py` (from `tests/core/`), `test_equation_steps_layers.py` (from `tests/core/`), `test_library.py` (from `tests/core/`), `test_properties.py` (from `tests/core/`), `test_set_params.py` (from `tests/core/`), `test_shift_timing.py` (from `tests/core/`), `test_tables.py` (from `tests/core/`)
- `tests/core/engine/`: `euler_example.json` (from `tests/core/`), `golden_readable_export.txt` (from `tests/core/`), `test_adapter.py` (from `tests/core/`), `test_cache_lock.py` (from `tests/core/`), `test_easing.py` (from `tests/core/`), `test_frame_cache.py` (from `tests/core/`), `test_frame_store_scaling.py` (from `tests/core/`), `test_invalidation.py` (from `tests/core/`), `test_matching_tex.py` (from `tests/core/`), `test_morph.py` (from `tests/core/`), `test_morph_frames.py` (from `tests/core/`), `test_placement.py` (from `tests/core/`), `test_python_export.py` (from `tests/core/`), `test_python_export_keyed.py` (from `tests/core/`), `test_random_access.py` (from `tests/core/`), `test_registry.py` (from `tests/core/`), `test_standalone.py` (from `tests/core/`), `test_transforms.py` (from `tests/core/`), `test_warm.py` (from `tests/core/`)
- `tests/core/exchange/`: `test_code_export.py` (from `tests/core/`), `test_code_files.py` (from `tests/core/`), `test_code_import.py` (from `tests/core/`), `test_preset_library.py` (from `tests/core/`), `test_preset_online.py` (from `tests/core/`), `test_scene_import.py` (from `tests/core/`)
- `tests/core/features/`: `test_anchor.py` (from `tests/core/`), `test_axes_objects.py` (from `tests/core/`), `test_camera.py` (from `tests/core/`), `test_child_trees.py` (from `tests/core/`), `test_clip_kinds.py` (from `tests/core/`), `test_graphs.py` (from `tests/core/`), `test_groups.py` (from `tests/core/`), `test_images.py` (from `tests/core/`), `test_markers.py` (from `tests/core/`), `test_no_latex.py` (from `tests/core/`), `test_part_colour.py` (from `tests/core/`), `test_parts_build.py` (from `tests/core/`), `test_paths.py` (from `tests/core/`), `test_readouts.py` (from `tests/core/`), `test_right_triangle.py` (from `tests/core/`), `test_rotate_along.py` (from `tests/core/`), `test_simulated_layers.py` (from `tests/core/`), `test_smart_transform_file.py` (from `tests/core/`), `test_svg.py` (from `tests/core/`)
- `tests/core/model/`: `test_glyph_colour_helpers.py` (from `tests/core/`), `test_glyph_colours.py` (from `tests/core/`), `test_layer_index.py` (from `tests/core/`), `test_lifetime.py` (from `tests/core/`), `test_motion_paths.py` (from `tests/core/`), `test_part_layers.py` (from `tests/core/`), `test_parts.py` (from `tests/core/`), `test_recovery.py` (from `tests/core/`), `test_scene_length.py` (from `tests/core/`), `test_schema.py` (from `tests/core/`), `test_shapes.py` (from `tests/core/`), `test_validation_paths.py` (from `tests/core/`)
- `tests/core/sound/`: `test_audio.py` (from `tests/core/`), `test_audio_spans.py` (from `tests/core/`), `test_levels.py` (from `tests/core/`), `test_subtitles.py` (from `tests/core/`)
- `tests/processes/`: `test_helper_check.py` (from `tests/core/`), `test_code_runner.py` (from `tests/`), `test_scene_chapters.py` (from `tests/`), `test_scene_recorder.py` (from `tests/`), `test_worker_messages.py` (from `tests/`)
- `tests/ui/canvas/`: `test_arrange.py` (from `tests/ui/`), `test_camera_ui.py` (from `tests/ui/`), `test_canvas_tools.py` (from `tests/ui/`), `test_framing.py` (from `tests/ui/`), `test_gizmo.py` (from `tests/ui/`), `test_motion_path_ui.py` (from `tests/ui/`), `test_param_handles.py` (from `tests/ui/`), `test_param_handles_ui.py` (from `tests/ui/`), `test_part_canvas.py` (from `tests/ui/`), `test_path_ui.py` (from `tests/ui/`), `test_snap_guides.py` (from `tests/ui/`), `test_viewport.py` (from `tests/ui/`)
- `tests/ui/code/`: `code_page_helpers.py` (from `tests/ui/`), `test_chapters_ui.py` (from `tests/ui/`), `test_code_drop.py` (from `tests/ui/`), `test_code_explorer.py` (from `tests/ui/`), `test_code_hints.py` (from `tests/ui/`), `test_code_history_ui.py` (from `tests/ui/`), `test_code_layer_ui.py` (from `tests/ui/`), `test_code_page.py` (from `tests/ui/`), `test_code_syntax.py` (from `tests/ui/`), `test_code_workspace.py` (from `tests/ui/`), `test_editor_features.py` (from `tests/ui/`), `test_find_bar.py` (from `tests/ui/`), `test_helpers_ui.py` (from `tests/ui/`), `test_live_mode.py` (from `tests/ui/`), `test_params_definition.py` (from `tests/ui/`), `test_python_objects_ui.py` (from `tests/ui/`), `test_quick_open.py` (from `tests/ui/`), `test_snippets_ui.py` (from `tests/ui/`)
- `tests/ui/deliver/`: `test_export_dialog.py` (from `tests/ui/`), `test_export_job.py` (from `tests/ui/`), `test_render_queue.py` (from `tests/ui/`)
- `tests/ui/exchange/`: `test_code_export_ui.py` (from `tests/ui/`), `test_code_files.py` (from `tests/ui/`), `test_code_importer.py` (from `tests/ui/`), `test_conflict_dialog.py` (from `tests/ui/`), `test_import_code_dialog.py` (from `tests/ui/`), `test_online_presets_dialog.py` (from `tests/ui/`)
- `tests/ui/pages/`: `test_animate_page.py` (from `tests/ui/`), `test_audio_page.py` (from `tests/ui/`), `test_deliver_page.py` (from `tests/ui/`), `test_pages.py` (from `tests/ui/`)
- `tests/ui/panels/`: `test_axes_objects_ui.py` (from `tests/ui/`), `test_equation_steps_ui.py` (from `tests/ui/`), `test_glyph_colours_ui.py` (from `tests/ui/`), `test_groups_ui.py` (from `tests/ui/`), `test_layers_panel.py` (from `tests/ui/`), `test_part_colour_ui.py` (from `tests/ui/`), `test_presets_browser.py` (from `tests/ui/`), `test_presets_ui.py` (from `tests/ui/`), `test_properties_panel.py` (from `tests/ui/`), `test_property_rows.py` (from `tests/ui/`), `test_readouts_ui.py` (from `tests/ui/`), `test_shapes_ui.py` (from `tests/ui/`), `test_simulated_layers_ui.py` (from `tests/ui/`), `test_svg_ui.py` (from `tests/ui/`), `test_values_panel.py` (from `tests/ui/`)
- `tests/ui/playback/`: `test_audio_spans_ui.py` (from `tests/ui/`), `test_audio_ui.py` (from `tests/ui/`), `test_player_bar.py` (from `tests/ui/`)
- `tests/ui/services/`: `test_code_render.py` (from `tests/ui/`), `test_preview_process.py` (from `tests/ui/`), `test_render_ahead.py` (from `tests/ui/`), `test_scene_import_ui.py` (from `tests/ui/`), `test_worker_process.py` (from `tests/ui/`)
- `tests/ui/session/`: `test_build_service.py` (from `tests/ui/`), `test_document.py` (from `tests/ui/`), `test_places.py` (from `tests/ui/`), `test_preferences.py` (from `tests/ui/`), `test_selection.py` (from `tests/ui/`)
- `tests/ui/shell/`: `test_autosave.py` (from `tests/ui/`), `test_clipboard_ui.py` (from `tests/ui/`), `test_plugins_ui.py` (from `tests/ui/`), `test_shortcuts_help.py` (from `tests/ui/`)
- `tests/ui/style/`: `test_elided_label.py` (from `tests/ui/`), `test_render_activity.py` (from `tests/ui/`), `test_theme.py` (from `tests/ui/`)
- `tests/ui/timeline/`: `test_curve_editor.py` (from `tests/ui/`), `test_graph_model.py` (from `tests/ui/`), `test_graph_ui.py` (from `tests/ui/`), `test_markers_ui.py` (from `tests/ui/`), `test_multiselect_ui.py` (from `tests/ui/`), `test_shift_timing_ui.py` (from `tests/ui/`), `test_timeline_model.py` (from `tests/ui/`), `test_timeline_multiselect.py` (from `tests/ui/`), `test_timeline_view.py` (from `tests/ui/`)
