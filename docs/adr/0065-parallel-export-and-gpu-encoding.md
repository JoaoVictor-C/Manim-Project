# 0065. Parallel export and GPU encoding: frames drawn by several processes, encoded by the graphics card when it pays

- **Status:** Accepted
- **Date:** 2026-10-31
- **Deciders:** João Victor

## Context

An export drew every frame one after another in one process (Python and Cairo on one core), converted it to RGB, and
let x264 compress it on the same thread. The canvas and the video are the same pixels because both come from Manim's
Cairo camera ([0028](0028-render-ahead-cache.md)), so the drawing cannot move to the graphics card without changing
the picture: Manim's OpenGL renderer is another class hierarchy and other pixels. What can use the card is the
encoding. Measured on the development machine (Core 5 210H, 4 performance + 4 efficiency cores, RTX 4050 Laptop):

1. **Encoding.** On Cairo frames, x264 (crf 18) takes 18.5 ms a frame at 1080p and 74 ms at 4K (133 ms of processor
   time); NVENC fed RGBA directly takes 6.9 ms and 24 ms (21 ms of processor time) because the card also does the
   colour conversion. At the same quality setting it is at least as good: crf 18 and cq 28 are within 0.5 dB and 5 %
   in size. Starting a session costs one to three seconds on a laptop.
2. **Drawing is independent per frame.** The evaluator answers any time with the same picture whatever it drew before
   (random access, [0013](0013-timing-edits-keep-caches.md)); 8 consecutive runs of an export drawn by several
   processes decoded to the identical frames as the serial export.
3. **The real project is mostly code layers.** The five-minute angular momentum example (seven code layers of 6-11 KB
   each, 8,344 frames) exported cold at 1080p in 448 s: about 230 s rendering the seven layers one after another in the
   exporting process, 215 s drawing and encoding the frames. The layers do not depend on each other.
4. **More processes do not scale linearly here.** One process draws the project's frames at 66 per second; three at
   107; six at 86. Per-process cost grows with concurrency (15, 24, 40 ms a frame), so the machine's useful limit for
   this workload is about three processes. Light scenes plateau at two to four.

## Decision

- **Encoders** (`render/encoders.py`). `RenderOptions.encoder` is `auto`, `gpu` or `cpu` (flag `--encoder`). The card
  is offered through NVENC only, with x264 always behind it: an encoder opens with its first frame, so a card that
  cannot (no driver, session limit) falls through to x264 before anything is written. `auto` uses the card for
  exports of at least 400 Full-HD frames' worth of pixels, or whenever render processes use the cores. NVENC's
  constant quality is `cq = crf + 10`. The camera's RGBA goes to either encoder as it is.
- **Farm** (`render/farm.py`, `processes/frame_worker.py`). `RenderOptions.jobs` (`--jobs`; `None` = automatic) starts
  that many render processes that draw whole frames into a shared-memory ring of frame slots (at most 256 MB) and
  hand them back in frame order. Given in order, the oldest frame not yet encoded is always held by a worker, so the
  ring cannot fill and stop. Automatic is at most six, half the cores, half the free memory over 400 MB each, and only
  after a probe (`farm_pays`) estimates at least eight seconds of drawing: a short or light export stays in one
  process. A process that stops or fails ends the farm and the exporter draws on by itself from `next_frame`, so a real
  error carries its own traceback. Workers run below normal priority, end with the editor ([0064](0064-helper-lifetime-and-memory.md)),
  and take a lock between processes (`core/engine/build_lock.py`) around builds that may compile LaTeX, so two never
  write the same cache file.
- **Code layers** (`processes/code_batch.py`). Missing code layers are rendered by up to four of the single-job runner
  processes at once, longest first; layers with the same code render once; a failure is reported as before. One layer
  or `--jobs 1` renders in the exporting process.
- **Memory.** The export no longer copies each frame three times (`render_frame(copy=False)`, RGBA straight to the
  encoder); `render_hash` is memoized (it tokenized every code layer's source on every frame: 3.6 ms a frame).
- **Reporting.** The export says what it did (`Exported.how`, `{"how"}` and `{"stage"}` messages), and the Deliver page
  has Encoder and Render processes controls.

## Consequences

- On the real project with its code layers cached, the frame stage went from 255 s to 128 s (2.0x) with a smaller file
  (17.0 MB against 18.5 MB). Code layers go from the sum of their times towards the longest one.
- NVENC files differ from x264's (another encoder), and only NVENC was verified; AMD, Intel and Apple encoders get x264.
- Each render process holds Manim (about 400 MB): the memory check and the ring bound it, and exports are the only
  time they exist.
- The throughput ceiling of about three processes on this machine is not understood beyond memory-system contention;
  a different machine may scale further, and `--jobs` overrides the automatic choice.

## Alternatives considered

- **Manim's OpenGL renderer on the card** - other pixels, so the canvas would no longer be the video.
- **Intel QSV and AMD AMF** - QSV opened here but was slower than x264 and much worse at the same setting; AMF could
  not be tried.
- **Splitting the video into contiguous parts per process** - the later parts' frames would wait in memory, or on
  disk, for the first part to be encoded.

## Evidence

- Tests: `tests/render/test_farm.py` (same frames bit for bit, ring reuse, a killed worker, a failed farm, early close,
  fallback from a broken card), `tests/render/test_encoders.py`, `tests/core/engine/test_build_lock.py`,
  `tests/processes/test_code_batch.py`, `tests/ui/deliver/test_export_job.py` (cancelling ends every render process).
- Benchmark: [logs/benchmarks.md](../logs/benchmarks.md) B75.
