# 0081. Resumable exports: long videos rendered in segments that an interrupted export resumes from

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

An export writes `<stem>.partial<suffix>` and renames it when complete (ADR 0017); any failure deletes the
partial file. That keeps the old video safe, but a long export that is cancelled, crashes or loses power
restarts from frame 0: an hour of 4K at 60 fps can take longer than the user's session. The frames are
independent (the evaluator is a function of time, ADR 0002) and the encoder can be restarted at any frame, so
nothing but the file layout forces the restart.

## Decision

- **Segments.** An export of at least two segments (`RenderOptions.segment_seconds`, 10 s by default, a
  whole number of frames: `round(seconds * fps)`, at least one) renders in segments aligned to the export's
  first frame: `[first + k*n, first + (k+1)*n)`, the last one shorter. A shorter export renders in one pass
  as before, with no work folder, so short videos and every earlier test are unchanged.
- **The work folder** is `<stem>.export/` beside the output: `segment_0000.mp4`, ... and `state.json`
  (`render/resume.py`). Each segment is its own encoder session written to `segment_NNNN.mp4.tmp` (MP4
  whatever the output's suffix, no sound), renamed when the encoder is flushed and closed, and only then
  recorded in the state with its frame range, size and SHA-256; `state.json` is replaced atomically
  (`state.json.tmp`, fsync, `os.replace`). A crash, a kill or a power cut loses at most the segment being
  written; a `.tmp` left behind is removed on the next start.
- **What the folder is for.** The state records two hashes: the **project key** (SHA-256 of the project as
  rendered, i.e. with the options applied, so size, fps and subtitle style are in it, as is every layer, clip,
  sound and the canvas) and the **options key** (range, crf, encoder choice, subtitles, segment length and
  whether Python code may run - the number of render processes is left out: it does not change the pixels;
  `1` and `1.0` seconds hash alike), plus the frame window, segment length and fps. An export that finds a
  folder with the same keys resumes from it; any other folder (or an unreadable state, or another format) is
  removed and replaced. `--fresh` (CLI) or **Start over** (Deliver) discards it on purpose.
- **Resume.** Each recorded segment is checked (file present, same size, same SHA-256); a missing or changed
  one is rendered again. The missing segments are drawn in runs of consecutive frames, each run by one stream
  of frames - so the farm (ADR 0065) starts once for the tail of an interrupted export, not once per segment -
  and progress continues from the frames already done.
- **One encoder for all segments.** The first segment picks the encoder exactly as a single-pass export does
  (`encoders.candidates` for the whole window, falling through to x264); its codec is recorded and the other
  segments, in this run and on resume, use it (`encoders.by_codec`). If the recorded encoder cannot be opened
  any more (the card's encoder on another machine or driver), the folder is discarded and the export starts
  again rather than mixing encoders.
- **Joining.** Every segment starts with an IDR frame and references nothing outside itself (each is a
  separate encoder session, so its GOPs are closed by construction - no x264 or NVENC options were needed).
  The final step copies the segments' packets in order into the partial file with PyAV
  (`add_stream_from_template` of the first segment, packets' pts/dts moved by the segment's start in its own
  time base) - the equivalent of ffmpeg's concat demuxer, without re-encoding. Segments whose codec
  extradata (SPS/PPS) differs from the first are refused (the folder is discarded and the error says to
  export again); with one encoder and one setting it does not differ, which was verified for both x264 and
  NVENC. The sound is then encoded under the whole window exactly as before (`_mux_sound`, the same code as
  the single-pass path), then the partial file replaces the output as before (ADR 0017).
- **Lifetime.** On success the folder is removed. On a failure or a cancel it stays (the partial file is still
  removed): the CLI says so on Ctrl+C, the Deliver page says "The finished segments are kept in
  `<stem>.export`". The next long export to a folder removes the `*.export` folders in it that hold a
  `state.json` and were untouched for 7 days; only files an export writes (`state.json*`, `segment_*.mp4*`)
  are deleted, and a folder holding anything else is left.
- **CLI.** `manim-studio render` resumes by default when the keys match and prints "Resuming: N of M
  segments already rendered" (`{"stage": ..., "resumed": N, "segments": M}` with `--progress json`, which
  the editor shows before the first frame). `--fresh` starts again; `--segment-seconds S` sets the length.
- **Deliver page.** Adding an export whose output already has a matching folder asks **Resume export (N of M
  segments done)**, **Start over** or **Cancel** (`DeliverPage.ask_resume`; the count checks files by size
  only, the export checks their hashes). Start over sets `QueueJob.fresh`, which `ExportJob` passes as
  `--fresh`. A path that becomes `name (2).mp4` because a queued job writes there is not offered.

## Consequences

- **Disk.** The segments hold about as much as the finished video (the same encoder and quality), and the
  joined copy is written beside them before the folder is removed, so a long export needs about twice the
  video's size free at the end, against once before.
- **Quality.** A key frame every segment adds a little to the size (one IDR per 10 s against x264's default
  of at most 250 frames between key frames) and nothing visible: segmented and single-pass exports of the
  test scene decode within 0.4 of 255 on average per frame, x264 and NVENC alike.
- **Time.** Each segment opens its own encoder session, hashes its file once, and the join reads every
  segment once more (copying, not encoding) - small next to drawing ten seconds of frames.
- Untrusted placeholders vs trusted code are part of the options key, so trusting a project's code after an
  interruption starts again rather than mixing placeholder and real frames.
- Not covered: a code layer whose cached frames change without the project changing (its key is its code and
  the canvas, ADR 0019, so this does not happen in normal use), and a font or LaTeX installation changed in
  between, which can change glyphs between segments.

## Alternatives considered

- **Resume inside one MP4** (append to the partial file): an MP4 is unreadable until its index is written at
  the end, and fragmented MP4 still loses the fragment being written and makes every export pay for it.
- **Keep the partial file and re-encode its decoded frames**: double encoding loses quality and time.
- **Segments for every export**: a short export would gain nothing and pay a work folder and a join.
- **One farm per segment**: render processes take seconds to start and each builds the scene; one stream of
  frames per run of missing segments keeps the farm's start-up once per export.
