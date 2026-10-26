"""Write docs/dev/moved-modules.md from the move list: where every module and test went (ADR 0062)."""

import json
import sys
from pathlib import Path

moves = json.load(open(sys.argv[1]))
out = Path(sys.argv[2])


def dotted(path: str) -> str:
    parts = list(Path(path).with_suffix("").parts)
    if parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


src = sorted((o, n) for o, n in moves.items() if o.startswith("src/") and o.endswith(".py"))
data = sorted((o, n) for o, n in moves.items() if o.startswith("src/") and not o.endswith(".py"))
tests = sorted((o, n) for o, n in moves.items() if o.startswith("tests/"))

lines = [
    "# Where the modules went",
    "",
    "The package layout changed in [ADR 0062](../adr/0062-package-layout.md): the same files, in folders named",
    "for what they do. **No file was renamed and no code changed** - only the folder - so a bare `schema.py`",
    "in an older ADR, plan, changelog entry or traceback is still the right file. This page is the lookup for",
    "the old *paths* you may meet there. Names other things were written against did not move:",
    "`manim_studio.manim_scene` (exported scenes import it), `manim_studio.plugins` (the plugin API),",
    "`manim_studio.cli` and `python -m manim_studio`.",
    "",
    "Generated from the move list of the restructure; it is a record, not a file to keep in sync by hand.",
    "",
    "## Source modules",
    "",
    "| was | is |",
    "|---|---|",
]
for old, new in src:
    lines.append(f"| `{dotted(old)}` | `{dotted(new)}` |")
lines += ["", "## Files that ship with the package", "", "| was | is |", "|---|---|"]
folders = {}
for old, new in data:
    if old.startswith("src/manim_studio/library/"):
        folders[("src/manim_studio/library/", "src/manim_studio/data/library/")] = (
            folders.get(("src/manim_studio/library/", "src/manim_studio/data/library/"), 0) + 1
        )
    else:
        lines.append(f"| `{old}` | `{new}` |")
for (old, new), n in folders.items():
    lines.append(f"| `{old}` ({n} files) | `{new}` |")
lines += ["", "## Tests", "", "The tests follow the code they test. Each test file kept its name:", ""]
by_dir: dict[str, list[str]] = {}
for old, new in tests:
    by_dir.setdefault(str(Path(new).parent).replace("\\", "/"), []).append(
        f"`{Path(old).name}`" if Path(old).parent == Path(new).parent else f"`{Path(old).name}` (from `{Path(old).parent.as_posix()}/`)"
    )
for folder, names in sorted(by_dir.items()):
    lines.append(f"- `{folder}/`: " + ", ".join(names))
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(len(src), "modules,", len(tests), "tests ->", out)
