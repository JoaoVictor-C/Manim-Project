# P6b.3 — The Code page

- **Status:** Done
- **Date:** 2026-10-12
- **Decided in:** [decision session 36](../logs/decision-sessions.md) (Terza, `fast`, confidence 0.91)
- **Evidence:** B57 in [../logs/benchmarks.md](../logs/benchmarks.md)
- **ADR:** [0041 — Workspace pages](../adr/0041-workspace-pages.md); parent plan [p6b-pages.md](p6b-pages.md)

## Goal

**Done when** the Code page lists the project's code layers, edits one in a real editor
(Python highlighting, line numbers, auto-indent, Tab = 4 spaces), runs it with Ctrl+Enter
as one undo step, and shows the renderer's status and errors under the editor, where an
error's line number moves the cursor to that line - with the shared viewer showing the
result - and every existing UI test passes.

## The model (session 36)

| question | decision |
|---|---|
| when does text reach the project | only on **Run** (Ctrl+Enter or the button): trust the exact text, then `set_param` through `BuildService.submit` - one undo step, the same path as the Properties field. Typing never applies or renders (a render is a process, 6-8 s cold, B30). Run with unchanged text only trusts and retries a failed or untrusted render. |
| unapplied text | a **draft** per layer id (text, cursor, the project text it started from), kept while the editor text differs from the project's (exact equality, recomputed on every text and project change) |
| layer or page switch | the draft is parked and comes back; leaving the page changes nothing (one editor lives in the page) |
| the project moves underneath (undo, redo, Properties) | clean editor: shows the new code; dirty editor: keeps its text, shows a notice; Revert shows the project's code (one step of the editor's own undo) |
| a layer is deleted | its draft is kept, so undoing the delete brings the text back |
| New/Open | drafts are dropped (layer ids repeat between projects), and the status bar says how many |
| dirty marker | "Unapplied changes" beside the layer name, an asterisk in the layer list, Revert enabled |
| errors | `CodeStatus` carries one message and a line: a state line and a monospace message whose "line N" is a link; it moves the cursor (kept inside the text) and tints the line; while dirty it says "from the last run" and the line is not tinted (the lines have moved) |
| Ctrl+Z | inside the editor it is the editor's own text undo; the Edit menu's undo is the project's, one step per Run |

## Steps

| step | content | acceptance |
|---|---|---|
| P6b.3.1 | `ui/code_syntax.py` (lexer: spans and a line state), `ui/code_drafts.py` (drafts, error line helpers) - no Qt; theme tokens for the syntax and the tinted lines | unit tests: tokens, triple quotes across lines, no overlap or crash on any text, draft rules |
| P6b.3.2 | `ui/code_editor.py` (`CodeEditor`, `PythonHighlighter`), `ui/pages/code.py` (`CodePage`), registered after Compose | `tests/ui/test_code_page.py` through the real `MainWindow`: list, selection, editing keys, Run, drafts, Revert, errors |
| P6b.3.3 | acceptance `tests/ui/test_acceptance_p6b3.py`: create, edit, run with the real code runner, an error clicked to its line, fixed, the frame on the canvas | passes |
| P6b.3.4 | B57 (`benchmarks/bench_code_editor.py`), mutation check of the draft/Run guards, docs | every non-equivalent mutant killed |

## Out of scope

- Mapping an error line through unapplied edits (the line is labelled "from the last run").
- Completion, folding, search and replace, a traceback pane (the runner reports one line).
- Several cursors, split editors, a code layer inside a group.
