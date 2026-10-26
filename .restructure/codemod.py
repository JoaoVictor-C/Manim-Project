"""Move files and rewrite every reference to them. One-off tool for the restructure (ADR 0062).

    python codemod.py plan  moves.json            # dry run: print what would change, touch nothing
    python codemod.py apply moves.json            # move files (git mv when tracked) and rewrite references

Imports are rewritten from the syntax tree (exact); dotted names and file paths in strings, comments,
docstrings and documentation are rewritten textually, longest name first. Line endings are preserved byte
for byte. Nothing is renamed: only folders change, so a bare ``schema.py`` stays true.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
PKG = "manim_studio"
SRC = ROOT / "src"


# -- names ---------------------------------------------------------------------------------------------


def module_of(path: str) -> str | None:
    """Dotted import name of a repository path (``src/..`` or ``tests/..`` .py file), or None."""
    p = Path(path)
    if p.suffix != ".py":
        return None
    parts = list(p.with_suffix("").parts)
    if parts[0] == "src":
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


class Names:
    """Old dotted module name -> new, for source modules (``manim_studio.x``) and test modules."""

    def __init__(self, moves: dict[str, str], root: Path | None = None):
        root = root or ROOT
        src = root / "src"
        self.moves = moves
        self.mod: dict[str, str] = {}
        for old, new in moves.items():
            o, n = module_of(old), module_of(new)
            if o is None:
                continue
            self.mod[o] = n
            if old.startswith("tests/"):
                # pytest's ``pythonpath = ["tests"]`` also lets tests import each other as ``ui.test_x``
                self.mod[o.removeprefix("tests.")] = n.removeprefix("tests.")
        # every module that exists today (old tree), to tell "from pkg import module" from "from pkg import name"
        self.exists: set[str] = set()
        for p in list(src.rglob("*.py")) + list((root / "tests").rglob("*.py")):
            rel = p.relative_to(root).as_posix()
            m = module_of(rel)
            if m:
                self.exists.add(m)
                if rel.startswith("tests/"):
                    self.exists.add(m.removeprefix("tests."))
        # packages (directories) that exist today
        self.packages = {m for m in self.exists if (src / Path(*m.split("."))).is_dir()} | {
            m
            for m in self.exists
            if (root / "tests" / Path(*m.removeprefix("tests.").split("."))).is_dir()
        }

    def new(self, module: str) -> str:
        return self.mod.get(module, module)


# -- import rewriting ----------------------------------------------------------------------------------


def package_of(module: str, is_init: bool) -> str:
    return module if is_init else module.rpartition(".")[0]


def absolute(base_pkg: str, level: int, module: str | None) -> str:
    if not level:
        return module or ""
    parts = base_pkg.split(".")
    parts = parts[: len(parts) - (level - 1)]
    return ".".join(parts + ([module] if module else []))


def relative(from_pkg: str, target: str) -> tuple[int, str]:
    """(level, module) that reach ``target`` from the package ``from_pkg``."""
    a, b = from_pkg.split("."), target.split(".")
    common = 0
    while common < min(len(a), len(b)) and a[common] == b[common]:
        common += 1
    return len(a) - common + 1, ".".join(b[common:])


def emit(level: int, module: str, names: list[ast.alias]) -> str:
    items = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in names)
    return f"from {'.' * level}{module} import {items}"


class Rewriter:
    def __init__(self, names: Names):
        self.names = names
        self.warnings: list[str] = []

    def rewrite(self, text: str, old_mod: str, new_mod: str, is_init: bool, label: str) -> str:
        """Return ``text`` with every ``from X import Y`` of a moved module pointing where it moved to."""
        tree = ast.parse(text)
        lines = text.splitlines(keepends=True)
        old_pkg = package_of(old_mod, is_init)
        new_pkg = package_of(new_mod, is_init)
        edits: list[tuple[int, int, str]] = []  # (first line idx, last line idx, replacement)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                continue  # dotted names: the textual pass
            if not isinstance(node, ast.ImportFrom):
                continue
            if any(a.name == "*" for a in node.names):
                self.warnings.append(f"{label}:{node.lineno}: star import")
                continue
            base = absolute(old_pkg, node.level, node.module)
            top = base.split(".")[0]
            if top not in (PKG, "tests", "core", "ui", "render", "support", "qt_support", "acceptance") and not node.level:
                continue
            groups: dict[tuple[int, str], list[ast.alias]] = {}
            order: list[tuple[int, str]] = []

            def add(level: int, module: str, alias: ast.alias) -> None:
                key = (level, module)
                if key not in groups:
                    groups[key] = []
                    order.append(key)
                groups[key].append(alias)

            def target_of(absolute_module: str) -> tuple[int, str]:
                """How to write ``absolute_module`` from the NEW file, in the style the old one used."""
                if node.level:
                    return relative(new_pkg, absolute_module)
                return 0, absolute_module

            if base in self.names.mod and base not in self.names.packages:
                # from .schema import Project - the module moved
                lv, mod = target_of(self.names.new(base))
                for a in node.names:
                    add(lv, mod, a)
            elif base in self.names.mod and base in self.names.packages:
                # an old module became a package of the same name (ui.canvas): the names are in the module
                lv, mod = target_of(self.names.new(base))
                for a in node.names:
                    add(lv, mod, a)
            else:
                for a in node.names:
                    sub = f"{base}.{a.name}" if base else a.name
                    if sub in self.names.exists and sub not in self.names.packages:
                        newsub = self.names.new(sub)
                        parent, _, leaf = newsub.rpartition(".")
                        lv, mod = target_of(parent)
                        add(lv, mod, ast.alias(name=leaf, asname=a.asname))
                    else:
                        # a name defined in a package's __init__ (or in a module that did not move): the
                        # target stays, but a relative path to it is written from the NEW place
                        add(*(target_of(base) if node.level else (0, base)), a)
            # one statement per target, written in the order first met
            tail = ""
            first, last = node.lineno - 1, node.end_lineno - 1
            end_line = lines[last]
            m = re.search(r"(\s*#.*)$", end_line.rstrip("\r\n"))
            if m:
                tail = m.group(1)
            elif first != last:  # ``from x import (  # noqa: E402``: the comment sits after the bracket
                m = re.search(r"\(\s*(#.*)$", lines[first].rstrip("\r\n"))
                if m:
                    tail = "  " + m.group(1)
            if any("#" in lines[i] for i in range(first + 1, last)):
                self.warnings.append(f"{label}:{node.lineno}: comment inside an import (kept on the first line only)")
            indent = re.match(r"\s*", lines[first]).group(0)
            eol = "\r\n" if end_line.endswith("\r\n") else "\n"
            new_lines = [indent + emit(lv, mod, groups[(lv, mod)]) + tail for (lv, mod) in order]
            replacement = eol.join(new_lines) + eol
            old = "".join(lines[first : last + 1])
            if replacement.replace("\r\n", "\n") != old.replace("\r\n", "\n"):
                edits.append((first, last, replacement))
        for first, last, replacement in sorted(edits, reverse=True):
            lines[first : last + 1] = [replacement]
        return "".join(lines)


# -- textual rewriting ---------------------------------------------------------------------------------


class Texts:
    """Dotted names and paths in comments, strings, docstrings and Markdown."""

    def __init__(self, names: Names, moves: dict[str, str]):
        self.dotted: list[tuple[re.Pattern, str]] = []
        entries = {}
        for old, new in names.mod.items():
            if old.startswith(PKG + "."):
                entries[old] = new
        # an old module whose name is now a package (ui.canvas): ``ui.canvas.gizmo`` is already new
        leaves: dict[str, list[str]] = {}
        for new in entries.values():
            parent, _, leaf = new.rpartition(".")
            leaves.setdefault(parent, []).append(leaf)
        for old in sorted(entries, key=len, reverse=True):
            guard = ""
            if old in leaves:
                guard = r"(?!\.(?:" + "|".join(sorted(set(leaves[old]))) + r")\b)"
            self.dotted.append((re.compile(re.escape(old) + guard + r"(?![\w])"), entries[old]))
        # paths: ``src/manim_studio/core/schema.py`` and the short forms ``core/schema.py``
        self.paths: list[tuple[re.Pattern, str]] = []
        for old, new in sorted(moves.items(), key=lambda kv: len(kv[0]), reverse=True):
            variants = {old: new}
            for prefix in ("src/manim_studio/", "src/", "tests/"):
                if old.startswith(prefix):
                    variants[old[len(prefix) :]] = new[len(prefix) :]
            for o, n in variants.items():
                # a link may reach it through ``../``; a longer name ("mycore/schema.py") must not match
                start = r"(?<![\w.-])" if o.startswith(("src/", "tests/")) else r"(?<![\w./-])"
                self.paths.append((re.compile(start + re.escape(o) + r"(?![\w])"), n))
        # directory mentions of the moved data
        self.paths.append((re.compile(r"(?<![\w.-])src/manim_studio/library(?=[/`)\s\"'.,]|$)"), "src/manim_studio/data/library"))
        self.paths.append((re.compile(r"manim_studio/library/"), "manim_studio/data/library/"))

    def rewrite(self, text: str) -> str:
        for pattern, new in self.dotted:
            text = pattern.sub(new, text)
        for pattern, new in self.paths:
            text = pattern.sub(new, text)
        return text


# -- driver --------------------------------------------------------------------------------------------

TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".txt", ".cfg", ".ini", ".yml", ".yaml"}
SKIP_DIRS = {".git", ".venv", ".cache", ".ruff_cache", "media", "out", "projects", "__pycache__", "node_modules", "dist", "build"}


def files_to_scan() -> list[Path]:
    out = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix not in TEXT_SUFFIXES:
            continue
        rel = p.relative_to(ROOT).parts
        if any(part in SKIP_DIRS or part.startswith(".cache") for part in rel):
            continue
        if p.name == "uv.lock" or p.name == "moves.json":
            continue
        out.append(p)
    return out


def main() -> int:
    mode, moves_file = sys.argv[1], sys.argv[2]
    moves: dict[str, str] = json.load(open(moves_file))
    names = Names(moves)
    rewriter = Rewriter(names)
    texts = Texts(names, moves)
    new_of = {v: k for k, v in moves.items()}

    changed: dict[str, str] = {}   # path (new location) -> new text
    for path in files_to_scan():
        rel = path.relative_to(ROOT).as_posix()
        old_rel = new_of.get(rel, rel)  # nothing has moved yet: rel is the OLD path
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        original = text
        if path.suffix == ".py":
            old_mod = module_of(rel)
            new_mod = module_of(moves.get(rel, rel))
            text = rewriter.rewrite(text, old_mod, new_mod, path.name == "__init__.py", rel)
        text = texts.rewrite(text)
        if path.suffix == ".py" and rel in moves:
            # a file that moved one folder deeper reaches the repository root one parent further
            delta = len(Path(moves[rel]).parts) - len(Path(rel).parts)
            if delta:
                text = re.sub(
                    r"(__file__\)(?:\.resolve\(\))?\.parents\[)(\d+)(\])",
                    lambda m: f"{m.group(1)}{int(m.group(2)) + delta}{m.group(3)}",
                    text,
                )
        if text != original:
            changed[rel] = text
    print(f"{len(moves)} files move; {len(changed)} files change text")
    for w in rewriter.warnings:
        print("WARNING", w)
    if mode == "plan":
        return 0

    # 1. rewrite text in place (old locations), keeping line endings
    for rel, text in changed.items():
        (ROOT / rel).write_bytes(text.encode("utf-8"))
    # 2. move files; git mv when tracked, so history follows
    tracked = set(subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=ROOT).stdout.split("\n"))
    for old, new in moves.items():
        dest = ROOT / new
        dest.parent.mkdir(parents=True, exist_ok=True)
        if old in tracked:
            subprocess.run(["git", "mv", old, new], check=True, cwd=ROOT)
        else:
            (ROOT / old).replace(dest)
    # 3. the new packages: a docstring each, so the folder says what it is for
    sys.path.insert(0, str(Path(__file__).parent))
    import layout

    for package, doc in layout.DOCS.items():
        init = SRC / Path(*package.split(".")) / "__init__.py"
        if package == "manim_studio.data":
            body = (
                f'"""{doc}"""\n\nfrom pathlib import Path\n\n'
                "FOLDER = Path(__file__).resolve().parent\n"
            )
        else:
            body = f'"""{doc}"""\n'
        init.parent.mkdir(parents=True, exist_ok=True)
        init.write_text(body, encoding="utf-8", newline="\n")
    # 4. folders the moves emptied
    for folder in sorted({(ROOT / old).parent for old in moves}, key=lambda p: -len(p.parts)):
        leftovers = [p for p in folder.iterdir() if p.name != "__pycache__"] if folder.exists() else None
        if leftovers == []:
            for cache in folder.glob("__pycache__"):
                import shutil

                shutil.rmtree(cache, ignore_errors=True)
            folder.rmdir()
    return 0


if __name__ == "__main__":
    sys.exit(main())
