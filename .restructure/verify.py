"""Checks that a restructure changed nothing but places. Run from the root of the NEW tree.

    python verify.py graph  OLD_ROOT moves.json     # the import graph is the old one, renamed
    python verify.py ast    OLD_ROOT moves.json     # every moved file is the old file except imports and path strings
    python verify.py names  OLD_ROOT moves.json     # every module imports on its own and exposes the same names
"""

from __future__ import annotations

import ast
import collections
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

mode, old_root, moves_file = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
new_root = Path.cwd()
moves: dict[str, str] = json.load(open(moves_file))
PKG = "manim_studio"


def modname(root: Path, p: Path) -> str:
    parts = list(p.relative_to(root / "src").with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def src_modules(root: Path) -> dict[str, Path]:
    return {modname(root, p): p for p in (root / "src").rglob("*.py")}


def rename(m: str) -> str:
    old_path = "src/" + m.replace(".", "/") + ".py"
    new = moves.get(old_path)
    if new:
        return modname(Path("."), Path(".") / new)
    return m


def graph(root: Path) -> dict[str, set[tuple[str, str]]]:
    """module -> set of (kind, imported module), kind in static / lazy / typing; names resolved to modules."""
    mods = src_modules(root)
    out: dict[str, set[tuple[str, str]]] = collections.defaultdict(set)
    for cur, p in mods.items():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        for n in ast.walk(tree):
            if not isinstance(n, (ast.Import, ast.ImportFrom)):
                continue
            targets: list[str] = []
            if isinstance(n, ast.Import):
                targets = [a.name for a in n.names]
            else:
                if n.level:
                    base = cur.split(".") if p.name == "__init__.py" else cur.split(".")[:-1]
                    base = base[: len(base) - (n.level - 1)]
                    m = ".".join(base + ([n.module] if n.module else []))
                else:
                    m = n.module or ""
                if m.split(".")[0] != PKG:
                    continue
                subs = [f"{m}.{a.name}" for a in n.names if f"{m}.{a.name}" in mods]
                targets = subs if subs else [m]
                # `from pkg import name` where name is not a module: the edge is to pkg itself
                for a in n.names:
                    if f"{m}.{a.name}" not in mods and m in mods:
                        targets.append(m)
                targets = sorted(set(targets))
            kind = "static"
            q = n
            while q in parents:
                q = parents[q]
                if isinstance(q, ast.If) and "TYPE_CHECKING" in ast.dump(q.test):
                    kind = "typing"
                    break
                if isinstance(q, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    kind = "lazy"
            for t in targets:
                if t.split(".")[0] == PKG and t in mods:
                    out[cur].add((kind, t))
    return out


def check_graph() -> int:
    old, new = graph(old_root), graph(new_root)
    mapped = {rename(a): {(k, rename(b)) for k, b in edges} for a, edges in old.items()}
    bad = 0
    for mod in sorted(set(mapped) | set(new)):
        a, b = mapped.get(mod, set()), new.get(mod, set())
        if a != b:
            bad += 1
            print(f"DIFFERENT {mod}\n   only old: {sorted(a - b)}\n   only new: {sorted(b - a)}")
    edges = sum(len(v) for v in new.values())
    print(f"import graph: {len(new)} modules, {edges} imports; {bad} modules differ")
    return bad


# -- AST equality modulo imports and moved path strings -----------------------------------------------------


def strip(tree: ast.AST, rewrite) -> str:
    class T(ast.NodeTransformer):
        def visit_Import(self, node):
            return None

        def visit_ImportFrom(self, node):
            return None

        def visit_Constant(self, node):
            if isinstance(node.value, str):
                node.value = rewrite(node.value)
            return node

    tree = T().visit(tree)
    ast.fix_missing_locations(tree)
    # docstring-less comparison of Expr statements is not needed: constants were rewritten the same way
    return ast.dump(tree, annotate_fields=False, include_attributes=False)


def check_ast() -> int:
    import codemod

    names = codemod.Names(moves, old_root)
    texts = codemod.Texts(names, moves)
    bad = 0
    count = 0
    for old, new in moves.items():
        if not old.endswith(".py"):
            continue
        count += 1
        a = ast.parse((old_root / old).read_text(encoding="utf-8"))
        b = ast.parse((new_root / new).read_text(encoding="utf-8"))
        if strip(a, texts.rewrite) != strip(b, texts.rewrite):
            bad += 1
            print("DIFFERENT (beyond imports/strings):", old, "->", new)
    # files that did not move: same rule
    for p in list(new_root.glob("src/**/*.py")) + list(new_root.glob("tests/**/*.py")):
        rel = p.relative_to(new_root).as_posix()
        if rel in set(moves.values()) or not (old_root / rel).exists():
            continue
        count += 1
        a = ast.parse((old_root / rel).read_text(encoding="utf-8"))
        b = ast.parse(p.read_text(encoding="utf-8"))
        if strip(a, texts.rewrite) != strip(b, texts.rewrite):
            bad += 1
            print("DIFFERENT (unmoved):", rel)
    print(f"ast: {count} files compared; {bad} differ beyond imports and path strings")
    return bad


# -- every module imports alone and exposes the same names ---------------------------------------------------

PROBE = r"""
import importlib, json, sys
m = importlib.import_module(sys.argv[1])
names = sorted(n for n in dir(m) if not n.startswith("__") and getattr(getattr(m, n, None), "__module__", None) in (None, m.__name__) )
print(json.dumps({"ok": True, "names": names, "all": sorted(getattr(m, "__all__", []))}))
"""


def probe(root: Path, module: str) -> dict:
    env = {"PYTHONPATH": str(root / "src"), "QT_QPA_PLATFORM": "offscreen", "MANIM_STUDIO_CODE": "0"}
    import os

    env = {**os.environ, **env}
    r = subprocess.run(
        [sys.executable, "-c", PROBE, module], capture_output=True, text=True, env=env, cwd=root, timeout=300
    )
    if r.returncode != 0:
        return {"ok": False, "error": r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "?"}
    return json.loads(r.stdout.strip().splitlines()[-1])


def check_names() -> int:
    old_mods = src_modules(old_root)
    jobs = sorted(old_mods)
    with ThreadPoolExecutor(8) as pool:
        old_res = dict(zip(jobs, pool.map(lambda m: probe(old_root, m), jobs)))
        new_res = dict(zip(jobs, pool.map(lambda m: probe(new_root, rename(m)), jobs)))
    bad = 0
    for m in jobs:
        a, b = old_res[m], new_res[m]
        if a != b:
            bad += 1
            print("DIFFERENT", m, "->", rename(m), "\n   old:", str(a)[:300], "\n   new:", str(b)[:300])
    failed_old = [m for m in jobs if not old_res[m]["ok"]]
    print(f"names: {len(jobs)} modules imported alone in both trees; {bad} differ; failing before: {failed_old}")
    return bad


if __name__ == "__main__":
    sys.exit({"graph": check_graph, "ast": check_ast, "names": check_names}[mode]() and 1)
