"""Import graph of src/manim_studio: edges, Qt use, cycles, layer violations."""
import ast, sys, json, collections
from pathlib import Path

ROOT = Path("src")
PKG = "manim_studio"

def modname(p: Path) -> str:
    parts = list(p.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)

mods = {modname(p): p for p in ROOT.rglob("*.py")}
edges = collections.defaultdict(set)      # module -> internal modules
typing = collections.defaultdict(set)
lazy = collections.defaultdict(set)       # imports inside functions
qt = set()
ext = collections.defaultdict(set)

def resolve(cur, node):
    if isinstance(node, ast.ImportFrom):
        if node.level:
            base = cur.split(".")
            if not mods[cur].name == "__init__.py":
                base = base[:-1]
            base = base[: len(base) - (node.level - 1)]
            m = ".".join(base + ([node.module] if node.module else []))
        else:
            m = node.module or ""
        return m, [a.name for a in node.names]
    return None, []

for cur, p in mods.items():
    tree = ast.parse(p.read_text(encoding="utf-8"))
    parents = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parents[c] = n
    for n in ast.walk(tree):
        targets = []
        if isinstance(n, ast.Import):
            targets = [(a.name, []) for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            m, names = resolve(cur, n)
            targets = [(m, names)]
        for m, names in targets:
            top = m.split(".")[0]
            if top in ("PySide6", "shiboken6"):
                qt.add(cur)
            if top != PKG:
                ext[cur].add(top)
                continue
            # prefer submodule when "from pkg import sub"
            cands = [m] + [f"{m}.{x}" for x in names if f"{m}.{x}" in mods]
            dest = [c for c in cands if c in mods]
            dest = [d for d in dest if d != m] or dest
            inside_fn = False
            is_typing = False
            q = n
            while q in parents:
                q = parents[q]
                if isinstance(q, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    inside_fn = True
                if isinstance(q, ast.If) and "TYPE_CHECKING" in ast.dump(q.test):
                    is_typing = True
            for d in dest:
                (typing if is_typing else lazy if inside_fn else edges)[cur].add(d)

def top(m):  # first level under manim_studio
    parts = m.split(".")
    return parts[1] if len(parts) > 1 else "(root)"

json.dump({"edges": {k: sorted(v) for k, v in edges.items()},
           "typing": {k: sorted(v) for k, v in typing.items()},
           "lazy": {k: sorted(v) for k, v in lazy.items()},
           "qt": sorted(qt), "ext": {k: sorted(v) for k, v in ext.items()}},
          open(sys.argv[1], "w"), indent=1)

print("modules:", len(mods))
print("\nQt users outside ui:", sorted(m for m in qt if not m.startswith("manim_studio.ui")))
# package-level edge counts
cnt = collections.Counter()
for a, bs in list(edges.items()):
    for b in bs:
        cnt[(top(a), top(b))] += 1
print("\npackage edges (static):")
for (a, b), n in sorted(cnt.items()):
    if a != b: print(f"  {a:>10} -> {b:<10} {n}")
cnt = collections.Counter()
for a, bs in lazy.items():
    for b in bs:
        cnt[(top(a), top(b))] += 1
print("\npackage edges (lazy, inside functions):")
for (a, b), n in sorted(cnt.items()):
    if a != b: print(f"  {a:>10} -> {b:<10} {n}")
