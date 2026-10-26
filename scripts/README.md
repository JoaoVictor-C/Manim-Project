# Scripts

Maintenance tools, run from the repository root. None is part of the package.

| script | what it does | run |
|---|---|---|
| `release_check.py` | builds the wheel and sdist, installs the wheel alone in a fresh Python 3.13 venv, checks `--version`, renders an example and opens the editor offscreen from the installed package (about 30 s; nothing is uploaded) | `uv run python scripts/release_check.py [--work DIR] [--example examples/euler.json] [--clean]` |
| `gen_smart_transform.py` | writes [examples/smart_transform.py](../examples/smart_transform.py): the smart morph (ADR 0056) as one self-contained Manim file; `--check` exits 1 when it is out of date | `uv run python scripts/gen_smart_transform.py` |
| `gen_shortcuts.py` | writes [docs/guide/shortcuts.md](../docs/guide/shortcuts.md) from the editor's own menus and gestures (offscreen, every user folder redirected; deterministic) | `uv run python scripts/gen_shortcuts.py -o docs/guide/shortcuts.md` |
| `check_docs.py` | checks every Markdown file: relative links, `#anchors` (GitHub slugs), fenced code languages; exit status 1 on a problem | `uv run python scripts/check_docs.py [paths...]` |

`check_docs.py` also runs in the test suite (`tests/test_docs_links.py`). Regenerate the
shortcuts page whenever a menu shortcut or a gesture in `ui/shell/shortcuts_help.py` changes.

When `uv run` cannot find the interpreter (a non-ASCII user folder on Windows, see
[docs/dev/setup.md](../docs/dev/setup.md)), use `.venv/Scripts/python scripts/<script>.py`.
