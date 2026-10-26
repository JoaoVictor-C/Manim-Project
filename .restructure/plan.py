"""Assemble every move (source, tests, data) into one list and validate it. Pure: touches nothing."""
import json, subprocess, sys, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import layout, testlayout

ROOT = Path.cwd()
moves: dict[str, str] = {}     # old path -> new path (posix, repo-relative)

# 1. source modules
for old, new in layout.mapping().items():
    o = "src/manim_studio/" + old.replace(".", "/") + ".py"
    n = "src/manim_studio/" + new.replace(".", "/") + ".py"
    moves[o] = n
# 2. data files
moves["src/manim_studio/core/manim_names.json"] = "src/manim_studio/data/manim_names.json"
for p in sorted((ROOT / "src/manim_studio/library").glob("*.json")):
    rel = p.relative_to(ROOT).as_posix()
    moves[rel] = rel.replace("src/manim_studio/library/", "src/manim_studio/data/library/")
# 3. tests
stem_dir = {}
for table in (testlayout.CORE, testlayout.UI, testlayout.ROOT):
    for d, stems in table.items():
        for s in stems:
            assert s not in stem_dir.get(d, ()), s
            stem_dir.setdefault(s, [])
            stem_dir[s].append(d)
seen_tests = []
UNPLACED = []
for sub in ("core", "ui", "render", ""):
    base = ROOT / "tests" / sub if sub else ROOT / "tests"
    for p in sorted(base.glob("test_*.py")):
        stem = p.stem[5:]
        rel = p.relative_to(ROOT).as_posix()
        if sub == "render":
            continue
        if sub == "ui" and stem.startswith("acceptance_"):
            moves[rel] = f"tests/acceptance/{p.name}"; continue
        table = {"core": {**testlayout.CORE, "processes": testlayout.ROOT["processes"]}, "ui": testlayout.UI, "": testlayout.ROOT}[sub]
        hits = [d for d, stems in table.items() if stem in stems]
        if len(hits) != 1:
            UNPLACED.append((rel, hits)); continue
        d = hits[0]
        dest = "tests" if d == "" else f"tests/{d}"
        moves[rel] = f"{dest}/{p.name}"
for old, new in testlayout.FILES.items():
    moves[old] = new
if UNPLACED:
    print("UNPLACED:", UNPLACED); sys.exit(1)
# validation: every listed stem exists, every existing test file is placed
for table, sub in ((testlayout.CORE, "core"), (testlayout.UI, "ui")):
    for d, stems in table.items():
        for s in stems:
            assert (ROOT / "tests" / sub / f"test_{s}.py").exists() or (ROOT/"tests"/f"test_{s}.py").exists(), (d, s)
    # nothing listed twice
all_stems = [s for d, stems in {**testlayout.CORE, **{"p": testlayout.ROOT["processes"]}}.items() for s in stems]
assert len(all_stems) == len(set(all_stems)), [s for s in all_stems if all_stems.count(s) > 1]
for d, stems in testlayout.ROOT.items():
    for s in stems: assert (ROOT / "tests" / f"test_{s}.py").exists() or (ROOT / "tests" / "core" / f"test_{s}.py").exists(), s
moves = {o: n for o, n in moves.items() if o != n}
tracked = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout.split()
untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], capture_output=True, text=True).stdout.split()
exist = set(tracked) | set(untracked)
missing = [o for o in moves if o not in exist]
assert not missing, missing
clash = [n for n, c in collections.Counter(moves.values()).items() if c > 1]
assert not clash, clash
unplaced = [f for f in exist if f.startswith("tests/") and f.endswith(".py") and f.rsplit("/",1)[-1].startswith("test_")
            and f not in moves and not f.startswith("tests/render/") and f.count("/") == 1 and False]
json.dump(moves, open(sys.argv[1], "w"), indent=1)
print(len(moves), "moves:", collections.Counter(("src" if k.startswith("src") else "tests") for k in moves))
dirs = collections.Counter(Path(v).parent.as_posix() for v in moves.values())
for d, n in sorted(dirs.items()): print(f"  {n:>3}  {d}")
# test files that stay where they are
stay = [f for f in exist if f.startswith("tests/") and f.rsplit("/",1)[-1].startswith("test_") and f not in moves]
print("tests that stay:", sorted(stay))
