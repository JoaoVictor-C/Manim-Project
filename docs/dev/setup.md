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
| tests | `uv run pytest` |
| tests without LaTeX / Qt | `uv run pytest -m "not latex and not ui"` |
| lint | `uv run ruff check src tests benchmarks` |
| format | `uv run ruff format src tests benchmarks` |
| benchmark | `uv run python benchmarks/bench_preview.py` |
| render | `uv run manim-studio -v render examples/euler.json out/euler.mp4` |

## Pinned dependencies

| pin | why | lift when |
|---|---|---|
| `manim==0.22.0` | the adapter relies on Manim internals (ADR 0003) | the suite passes on the new version |
| `pillow<13` | Manim 0.22's camera calls `Image.fromarray(..., mode=...)`, removed in Pillow 13 | Manim stops passing `mode=` |

## Where things go at runtime

| path | content | in git? |
|---|---|---|
| `.venv/` | environment | no |
| `.cache/manim/`, `examples/.cache/` | Manim's Tex/Text SVG cache (per project folder) | no |
| `out/` | your renders and screenshots | no |
| `%LOCALAPPDATA%\ManimStudio\logs\` | application log (ADR 0011) | — |

Environment variables: `MANIM_STUDIO_LOG_DIR` moves the log folder;
`MANIM_STUDIO_WORKER=0` turns the build worker off (text is then built on the
UI thread — slower, but handy when debugging the worker, ADR 0015).
`MANIM_STUDIO_SETTINGS` is the preferences file (recent files, window, panel sizes, view toggles; ADR 0044).

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
