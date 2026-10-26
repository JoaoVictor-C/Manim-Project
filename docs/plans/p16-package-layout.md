# P16 — Package layout: folders named for what the code does

- **Status:** Done
- **Date:** 2026-10-25
- **ADR:** [0062 — Package layout](../adr/0062-package-layout.md)

## Goal

**Done when** `core/`, `ui/` and the tests are grouped in folders named for what the code does, the layering
that was already true is written down and fails a test when broken, and *nothing else changed*: same tests, same
results, same frames, same wheel.

## Method (why it is safe)

A refactoring that moves 123 modules, 217 test files and 44 data files, and rewrites 460 files, is only as good
as the proof that it changed nothing else. So the work was a script, run first on a copy of the repository,
with checks that do not depend on the script being right:

| check | what it proves |
|---|---|
| import graph, before vs after | every module has exactly the imports it had (same kind: static, lazy, typing), renamed |
| syntax tree, before vs after | every moved file is the same code once imports and path strings are set aside; the only other differences are the 12 places that depend on where a file lives |
| each module imported alone, in a fresh process, in both trees | no import-order accident; the same public names |
| the full test suite | same tests, same results as the baseline run |
| `scripts/check_docs.py` | every link in the documentation still resolves |
| wheel + `scripts/release_check.py` | the data files are packaged and found in a clean environment |
| a sample project rendered before and after | pixel-identical frames |

Research that shaped it: rope and LibCST move symbols well but miss string and path references (both say so);
import-linter's layer contracts are the model for the architecture test, which is written with `ast` so it needs
no new dependency; the PySide6 guidance found says only "keep logic out of the UI package", which the layering
test now enforces.

## Order of work

1. Baseline: full test run, a backup of the working tree (nothing was committed yet).
2. Import graph of the code; score candidate groupings by whether the **static package graph stays acyclic**.
   Five modules moved out of the group their name suggested because of that.
3. Write the move list; validate it (every file placed once, nothing overwritten).
4. Codemod: rewrite imports from the syntax tree, names and paths in text, line endings kept; `git mv`.
5. The few edits a script cannot make (files found through `__file__`, the theme test's scan root).
6. Rehearse on a copy; run every check; fix the script; repeat from a clean copy.
7. Do it for real; run every check again.
8. Docs: ADR, this plan, the architecture page, the lookup of old paths, README, changelog.

## Results

All checks passed on the real tree after the rehearsal had found and fixed what it should:

- Moved: 123 modules, 217 test files and 2 fixtures, 44 data files; 460 files had imports, names or paths
  rewritten. Import graph: 115 modules, 541 imports, identical to the old one but for the two modules that now
  find their data through `manim_studio.data`. Syntax trees: identical but for 13 files whose location mattered
  (the data lookups, `welcome.py`'s parent depth, the tests' `__file__` depths, the theme test's scan root,
  `conftest.py`).
- Tests: 4342 passed, 12 skipped, none failing (before: 4330 passed and the zoom-key test failing, which fails
  on the untouched code). Rendered frames of three sample projects, one with a Code layer (so the renderer
  subprocess starts by its new name): identical. The wheel built and ran the editor from a clean environment
  with its 32 presets, 5 themes and 6 templates found.
- **What the rehearsal caught** (each would have been a broken release or a hidden failure):
  - the text pass rewrote an already rewritten import (`ui.canvas` was a module and is now a package): the
    passes now run text first, imports last;
  - an import written inside a string (the editor snippet in `scripts/release_check.py`): found by the wheel
    check, fixed by hand; the scan for such strings found no other;
  - the theme test scanned `Path(theme.__file__).parent`, which would have shrunk from the whole `ui/` package
    to `ui/style/` and kept passing: it scans the package again and fails if it sees fewer than 60 files;
  - two isolation gaps in the tests, exposed by the new order (see the ADR's Consequences).
- Left alone on purpose: `docs/` and `benchmarks/` keep their layout (their names already carry the order), and
  the committed `.restructure/` drafts of the first attempt are untouched (they are stale and can be deleted).
