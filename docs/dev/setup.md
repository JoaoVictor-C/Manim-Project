# Development setup

## Requirements

| tool | why | install (Windows) |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Python + dependencies | `winget install astral-sh.uv` |
| Python 3.13 | runtime (3.12 is not supported, see below) | `uv python install 3.13` |
| MiKTeX or TeX Live | `MathTex` / `Tex` objects | `winget install MiKTeX.MiKTeX` |
| git | | |

FFmpeg is **not** needed: video is encoded through PyAV, which Manim installs.

## First run

```bash
uv sync
```

```bash
uv run pytest
```

```bash
uv run manim-studio edit examples/euler.json
```

Enable automatic LaTeX package installs once, so the first `MathTex` compile
does not stall on a dialog:

```bash
initexmf --set-config-value=[MPM]AutoInstall=1
```

## Useful commands

| task | command |
|---|---|
| quick tests (no real subprocesses) | `uv run pytest -m "not slow"` |
| all tests (parallel) | `uv run pytest` |
| tests without LaTeX / Qt | `uv run pytest -m "not latex and not ui"` |
| lint | `uv run ruff check src tests benchmarks scripts` |
| format | `uv run ruff format src tests benchmarks scripts` |
| documentation links | `uv run python scripts/check_docs.py` |
| regenerate the shortcuts page | `uv run python scripts/gen_shortcuts.py -o docs/guide/shortcuts.md` |
| benchmark | `uv run python benchmarks/bench_preview.py` |
| render | `uv run manim-studio -v render examples/euler.json out/euler.mp4` |
| release check (builds and installs the wheel) | `uv run python scripts/release_check.py` |

## Pinned dependencies

| pin | why | lift when |
|---|---|---|
| `manim==0.22.0` | the adapter relies on Manim internals (ADR 0003) | the suite passes on the new version |
| `pillow<13` | Manim 0.22's camera calls `Image.fromarray(..., mode=...)`, removed in Pillow 13 | Manim stops passing `mode=` |

## Where things go at runtime

| path | content | in git? |
|---|---|---|
| `.venv/` | environment | no |
| `.cache/manim/`, `.cache/test-workers/` | the tests' Manim cache (shared, and one per parallel worker) | no |
| `<project folder>/.cache/manim/` | Manim's cache of `manim-studio render` / `python` (default `--cache-dir`) | no |
| `out/`, `media/` | your renders and screenshots; Manim's own output when run directly | no |
| `projects/` | your own projects, if you keep them in the checkout | no (ignored) |
| `%LOCALAPPDATA%\Manim Studio\cache\manim\` | the editor's Manim cache | - |
| `%LOCALAPPDATA%\ManimStudio\logs\` | application log (ADR 0011) | - |

The user-facing list (preferences, recovery copies, trust store, library, plugins) is in
[the user guide](../guide/troubleshooting.md#where-files-live).

Environment variables:

| variable | effect |
|---|---|
| `MANIM_STUDIO_SETTINGS` | the preferences file (ADR 0044) |
| `MANIM_STUDIO_CACHE` | the editor's Manim cache folder |
| `MANIM_STUDIO_LOG_DIR` | the log folder |
| `MANIM_STUDIO_RECOVERY` | the recovery copies folder (ADR 0038) |
| `MANIM_STUDIO_TRUST_FILE` | the trusted-code store (ADR 0019, 0051) |
| `MANIM_STUDIO_LIBRARY` | the user's presets, themes and templates (ADR 0039) |
| `MANIM_STUDIO_PLUGINS` | plugin folders, `os.pathsep`-separated (ADR 0032) |
| `MANIM_STUDIO_WORKER=0` | no build worker: text is built on the UI thread - slower, handy when debugging (ADR 0015) |
| `MANIM_STUDIO_PREVIEW=0` | no preview process: frames are not rendered ahead (ADR 0028) |
| `MANIM_STUDIO_CODE=0` | code layers are not rendered (ADR 0019) |
| `MANIM_STUDIO_AUDIO=0` | no sound output: playback follows the wall clock (ADR 0034) |
| `MANIM_STUDIO_IDLE_SECONDS=N` | seconds a helper may sit unused before it is released (default 600; `0`: never) (ADR 0064) |
| `MANIM_STUDIO_NATIVE_THREADS=N` | threads numpy's BLAS/OpenMP pools may start in each process (default 1) (ADR 0064) |
| `MANIM_STUDIO_LIFELINE=0` | helpers do not end with the editor (no job object, no watcher): to debug one on its own (ADR 0064) |

The test suite sets most of these to temporary folders or `0` (`tests/conftest.py`).

## Troubleshooting (Windows)

**`uv` fails with "Missing expected target directory for Python minor version link".**
Happens when the user profile path has non-ASCII characters (e.g. `C:\Users\João`):
uv's version junction under `%APPDATA%\uv\python` is broken. Point uv at the
interpreter explicitly:

```bash
uv venv --python "%APPDATA%\uv\python\cpython-3.13.16-windows-x86_64-none\python.exe"
```

```bash
uv sync --python "%APPDATA%\uv\python\cpython-3.13.16-windows-x86_64-none\python.exe"
```

Running `.venv\Scripts\python.exe -m pytest` directly also avoids uv's interpreter lookup.

**`ModuleNotFoundError: manim_studio` on Python 3.12.** Python 3.12 reads the
editable-install `.pth` file with the legacy code page; non-ASCII paths (e.g.
`Programação`) break. Use 3.13, which reads `.pth` as UTF-8.

**`latex failed but did not produce a log file` / "MiKTeX cannot retrieve
attributes for the directory ...\claude.exe\".** MiKTeX aborts when PATH contains
an entry that is a file. `adapter.configure()` removes such entries for the
process and appends MiKTeX's `bin\x64` folder, so this only bites when calling
Manim outside the app.

**`pyproject.toml: Invalid statement (at line 1, column 1)`.** The file was saved
with a UTF-8 BOM (PowerShell's `Set-Content -Encoding utf8` does this). Save it
as UTF-8 without BOM.
