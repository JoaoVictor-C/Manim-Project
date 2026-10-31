# 0067. Code errors know their time: an error says how far the scene got, and the page can show that frame

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

A code layer's error ([0019](0019-code-layers.md), P13.1) carries the line, the exception's type, where it came from
and the user's traceback. It said nothing about *when*: a scene that plays for forty seconds and fails at second
thirty-one looked the same as one that failed on its first line, and the user had to guess which moment to look at.
The runner knows: every frame drawn goes through its capturing renderer.

## Decision

- `CodeError.frame` is the number of frames the scene had drawn when it failed (0 when it failed at once), sent as
  `"frame"` in the runner's error message; readers that do not know the key ignore it ([0019](0019-code-layers.md)).
  It counts frames of this render, so for a chapter ([0061](0061-incremental-code-layers.md)) it is relative to the
  chapter's start, as the cache is.
- `CodeStatus.seconds` is `frame / fps` (None when unknown or zero). The status text reads "Error - line 12 after
  4.3 s ...", and an export's warning reads "code layer 'x' failed (line 12, after 4.3 s): ...".
- The Code page shows **Show frame at 4.3 s** beside the error: it moves the playhead to the layer's start plus that
  time and shows the Animate page, where the layer's last good frame is on the stage. It is not offered for errors
  in helpers, which have no place on the timeline.

## Consequences

- Only the runner's new message carries the time; a cached error from before shows none.
- The frame is the last one drawn, not a replay: the error stopped the scene after it, and a failed render's frames
  are not kept (a failed render writes nothing to the cache).

## Alternatives considered

- **Keep the partial frames** so the page could replay the run up to the error - it would put half-written caches in
  front of the evaluator, which reads a cache only when complete ([0019](0019-code-layers.md)).

## Evidence

- Tests: `tests/processes/test_code_runner.py::test_an_error_says_how_many_frames_the_scene_had_drawn`,
  `::test_a_runner_process_reports_the_frame_of_an_error`,
  `tests/ui/code/test_code_page.py::test_an_error_with_a_time_offers_the_frame_where_the_scene_stopped`.
