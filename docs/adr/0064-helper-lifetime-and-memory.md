# 0064. Helper lifetime and memory: helpers end with the editor and rest when idle; numpy's threads and the editor's leaks are bounded

- **Status:** Accepted
- **Date:** 2026-10-27
- **Deciders:** João Victor

## Context

The editor starts helper processes: the build worker ([0015](0015-build-worker-warm-then-commit.md)), the frame
renderer ([0028](0028-render-ahead-cache.md)), code renderers ([0019](0019-code-layers.md)), exports
([0017](0017-export-process-and-safe-output.md)), the voice helper ([0060](0060-voice-providers-and-narration.md))
and the import helper ([0053](0053-import-manim-scenes.md)). Each is a Python process with Manim loaded. A review
of memory and of whether closing the editor really ends everything it started found, on the Windows development
machine (twelve cores, 15.6 GB), with `examples/euler.json` open and every helper up:

1. **Killing the editor left every helper running.** Ending the editor the hard way (Task Manager, a crash, a closed
   terminal) does not end a `QProcess` child on Windows, and a helper ended only when its input closed. One rendering
   code that never returns never looks at its input: with an endless `while True:` layer the helper kept a core busy
   and its memory until the computer was restarted (reproduced: it was still running after the editor was killed).
2. **numpy started a thread pool per core in every process.** OpenBLAS reserves address space and commit for each
   thread the moment numpy loads: 707 MB of committed memory per process on twelve cores, in each of the three
   processes with a project open, for work that is a few hundred numbers at a time here. Almost none of it is
   resident, so Task Manager's Memory column never showed it; the system's commit charge did.
3. **A closed project was never given back.** Opening a project ran `gc.freeze()` (it removes collection pauses
   while playing); objects frozen are never collected, so the reference
   cycles of the previous project's panels (scrub boxes, their closures) stayed for good: 3.4 MB for every project
   opened. Widgets connected to signals with lambdas or `functools.partial` stayed alive too (Qt holds the callable,
   the callable holds the widget), and parentless panels were never deleted.
4. **Helpers were never given back after use**, and the build worker started with the editor, even though the
   welcome page builds nothing.
5. Smaller: `qtawesome` was imported to draw icons and loaded every icon font it has (40 MB) where two are used; the
   frame cache kept up to 512 MB of compressed frames; the welcome animation drew 30 frames a second for as long as
   the window was open, and in the background.

## Decision

- **A helper cannot outlive the editor, in three layers** (`manim_studio/lifeline.py`, `ui/services/children.py`):
  1. *A job object (Windows).* Each helper the editor starts is assigned to one job with
     `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; the system closes it when the editor's process ends, however it ends,
     and with it everything the helpers started (LaTeX, ffmpeg). The editor itself is not in the job, so programs it
     opens for the user (a video player, a file manager) survive it.
  2. *A watcher in each helper (every platform).* Every helper starts with `lifeline.die_with_editor()`: a thread
     waits for the editor named in `MANIM_STUDIO_EDITOR_PID` (Windows: `WaitForSingleObject` on its handle; elsewhere
     a once-a-second `kill(pid, 0)`) and ends the process. It does not need the helper's main thread, so it ends a
     helper stuck in user code, and it covers platforms without jobs.
  3. *The editor's bookkeeping.* Every service builds its helper's environment with `children.environment()` and
     starts it with `children.start()`, which assigns it to the job and remembers it weakly. On `aboutToQuit`,
     `children.stop_all()` closes every input, waits up to 1.5 s for all together, and ends what is left with
     `lifeline.kill_tree` (descendants found with a Toolhelp snapshot, `/proc` or `ps`). Closing the window asks every
     helper to stop at once instead of one after another.

  `MANIM_STUDIO_LIFELINE=0` turns layers 1 and 2 off, to debug a helper that must outlive the editor.
- **Helpers start when there is work and rest when there is none.** The build worker starts with the first request
  (`WorkerProcess(lazy=True)`; library defaults are warmed when a project opens or the New project dialog opens, not at
  start-up, so the welcome page runs no helper), and the build worker, the frame renderer and the code renderer's ready
  spare are released after `IDLE_SECONDS = 600` without work and start again with the next request, which waits for
  Manim's import (3-4 s). `MANIM_STUDIO_IDLE_SECONDS=N` changes it; `0` keeps them for good. A helper with work on its
  hands, or still starting, is never released.
- **numpy's pools are capped at one thread** in every process, by `lifeline.limit_native_threads()` called in
  `manim_studio/__init__` before numpy is imported anywhere (`OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`,
  `MKL_NUM_THREADS`, `NUMEXPR_NUM_THREADS`, `VECLIB_MAXIMUM_THREADS`); a variable already set wins, and
  `MANIM_STUDIO_NATIVE_THREADS=N` raises the default.
- **A project is given back when the next one opens.** `MainWindow._on_reset` thaws everything (`gc.unfreeze()`),
  collects, then freezes again. Panels connect bound methods of QObjects (Qt disconnects those) and not lambdas that
  capture widgets; panels are parented, so they are deleted with their window.
- **Smaller costs.** Icon fonts are located without importing `qtawesome` and only the two families used are loaded
  (`ui/style/icons.py`); the frame cache budget is 256 MB (`BUDGET`), farthest frames dropped first; the welcome
  animation draws every 32 ms while something moves, every 60 ms after 6 s of calm, and only looks for the pointer
  (every 400 ms) after 90 s, and stops while the application is not active.
- **The test suite frees what a test makes** (`tests/conftest.py`): the editor's top-level widgets a test created, and
  the attributes of them and of the editor's objects below them, are dropped at its end; a test process that held
  8.5 GB now holds 2.4 GB.

## Consequences

- With a project open and every helper up, the editor and its helpers commit 516 MB (it was 2638 MB) and have
  529 MB resident; once the helpers rest, 236 and 249 MB. The welcome page holds the editor alone: 221 and 232 MB
  (the build worker was 130 and 117 MB more). [B74](../logs/benchmarks.md)
- The first build, frame or code render after ten minutes of rest is a few seconds slower, once. Anyone who prefers
  the old behaviour sets `MANIM_STUDIO_IDLE_SECONDS=0`.
- A helper started by hand (a debugging session: `python -m manim_studio.processes.worker`) has no
  `MANIM_STUDIO_EDITOR_PID`, so it never watches for an editor and runs until it is stopped.
- Any new helper must be started with `children.environment()` and `children.start()`, and call
  `lifeline.die_with_editor()` first thing in its `main`: `test_every_module_that_runs_a_helper_starts_it_through_children`
  and `test_every_process_entry_point_ends_with_its_editor` fail until it does, and `tests/test_architecture.py`
  keeps `lifeline` free of package imports so a helper can use it before anything else loads.
- One thread per native pool would slow numpy work that is large and parallel; the editor's is a few hundred
  numbers at a time, and three example projects exported in the same time with one thread and with twelve (B74).
- Anything that keeps a Python object in a connection (a lambda in `connect`) keeps what it captured alive for as
  long as the signal's owner lives; a panel that must come and go connects a method.

## Alternatives considered

- **Put the editor itself in the job.** Everything it starts for the user (a player, an Explorer window) would die
  with it.
- **Close the helper's input and nothing else** (what it was). Does not reach a helper busy in user code, nor an editor
  that was killed.
- **A heartbeat over the pipe.** A helper that is busy cannot answer one; the watcher thread needs no reply.
- **`psutil`.** One more dependency for what `ctypes`, `/proc` and `ps` do.
- **Keep every helper for good** (and keep `gc.freeze` as it was). 100-250 MB per helper and 3.4 MB per project
  opened, for a build that is idle most of the time.
- **A smaller frame cache only** or **fewer helpers**: the largest part was neither (the thread pools).

## Evidence

- Test: `tests/test_lifeline.py` (job object, watcher, `kill_tree`, thread cap)
- Test: `tests/ui/services/test_children.py` (environment, start, `stop_all`)
- Test: `tests/ui/services/test_idle_release.py` (release and restart of the three helpers; lazy start)
- Test: `tests/test_editor_lifetime.py::test_killing_the_editor_leaves_no_helper_behind`,
  `::test_killing_the_editor_ends_a_code_render_stuck_in_an_endless_loop`,
  `::test_closing_the_window_ends_every_helper_quickly` (the real editor and helpers; slow)
- Test: `tests/ui/test_editor_memory.py` (frozen garbage collected at the next project; the welcome page starts no
  worker)
- Test: `tests/ui/style/test_icons.py` (the drawn icons are pixel-identical to qtawesome's)
- Benchmark: [logs/benchmarks.md](../logs/benchmarks.md) B74, `benchmarks/bench_editor_memory.py`
- Source: `src/manim_studio/lifeline.py`, `src/manim_studio/ui/services/children.py`,
  `src/manim_studio/ui/main_window.py` (`_on_reset`)
