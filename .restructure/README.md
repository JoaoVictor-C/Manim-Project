# Package restructure (ADR 0062): working files

One-off tooling for moving `core/`, `ui/` and the tests into folders named for what they do. It is
**not applied yet**: the repository is still in its original layout. Delete this folder when done.

State when this was saved (2026-10-25, branch `wip/p15-chapters-and-restructure-prep`):

- Baseline before any move: `uv run pytest` = 4330 passed, 12 skipped, 1 failed (the zoom test
  `test_zoom_keys_change_the_font_and_report_the_new_size`, which fails on untouched HEAD too), 160 s.
- A rehearsal on a throwaway copy ran `pipeline.sh` fine. Checked there: import graph equal to the old one
  under the renaming (`verify.py graph`; only `library.py` and `manim_names.py` differ, they now import
  `data`, as intended), moved files equal modulo imports/path strings (`verify.py ast`; the 12 differences
  are the intended `parents[N]`, `test_theme`, `library` and `manim_names` edits - confirm), ruff has no new errors.
- NOT done yet on the rehearsal: `verify.py names`, full pytest, `test_architecture.py` (fix whatever it
  finds), wheel + `scripts/release_check.py`, a pixel-identical sample render, docs link check.

How to resume (everything in this folder uses absolute scratch paths; edit `SP=` / paths first):

1. Extract a copy of the repo (`git archive HEAD | tar -x -C ../rehearsal`), `git init` it, commit.
2. `plan.py moves.json` regenerates the move list (validates every file has a home).
3. `pipeline.sh` = `codemod.py apply moves.json` + `manual_fixes.py` + ruff. `codemod.py` rewrites imports
   from the AST and dotted names/paths textually; it keeps line endings.
4. Run `verify.py graph|ast|names OLD_TREE moves.json` from the new tree, then pytest.
5. Only then run it on the real repo, add `drafts/test_architecture.py` as `tests/test_architecture.py`,
   `drafts/adr-0062.md` as `docs/adr/0062-package-layout.md`, generate `docs/dev/moved-modules.md` with
   `gen_moved.py`, update `docs/architecture.md`, `README.md`, `tests/README.md`, the ADR index, CHANGELOG.

Layout decisions are in `layout.py` (source) and `testlayout.py` (tests); the reasoning is in the ADR draft.
Do not write the ADR into `docs/` before running the codemod: it would rewrite the old names it quotes.
