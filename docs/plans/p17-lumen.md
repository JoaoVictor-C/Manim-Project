# P17 - Lumen: the new interface

- **Status:** in progress
- **Date:** 2026-10-26
- **Design:** [docs/design/lumen.md](../design/lumen.md) with mock-ups in
  [docs/design/mockups](../design/mockups/project/canvas.json); decision [ADR 0063](../adr/0063-lumen-interface.md)

## Goal

**Done when** every page, dialog and painted view of the editor is drawn in Lumen (Ink and Paper), the
shell has the top bar, cards, toasts and the command palette, every existing function works exactly as
before, the whole suite passes, and screenshots of each page next to its mock-up look like the same product.

## Order

Slices depend only on the ones above them; slices at the same level touch different files and run in
parallel.

| Slice | What | Main files |
|---|---|---|
| P17.1 | **Foundation**: bundled fonts, tokens for Ink and Paper, theme switching, type scale, icon family, the generated stylesheet, popup menus with shadow, dark title bar | `ui/style/theme.py`, `fonts/`, `icons.py`, `motion.py` |
| P17.2 | **Components**: `Card`, `Chip`, `Pill`, `Section`, `ScrubField`, `Popover`, `Toast`/`ToastHost`, `PageSwitcher`, `CommandPalette` | new `ui/style/*.py`, `ui/shell/palette.py` |
| P17.3 | **Shell**: top bar via `setMenuWidget`, `PageHost` on cards and the switcher, status bar, toasts on `showMessage`, palette on Ctrl K, panel toggles | `main_window.py`, `pages/__init__.py`, `pages/compose.py`, `pages/animate.py` |
| P17.4a | Panels: Layers rows, Properties sections and fields (scrub, colour popover), Presets browser | `ui/panels/*`, `style/fields.py` |
| P17.4b | Timeline, curve and graph editors: bars, keys, ruler, playhead, lanes | `ui/timeline/*` |
| P17.4c | Canvas: stage, pasteboard, frame shadow, floating tool and transport pills, overlays | `ui/canvas/*`, `ui/playback/*` |
| P17.4d | Code page, Audio page, Deliver page, dialogs | `ui/pages/code.py` and others, `ui/code/*`, `ui/exchange/*`, `ui/deliver/*`, `ui/shell/*dialog*` |
| P17.5 | Welcome, empty states, About, Preferences (theme, reduce motion), docs and screenshots, release notes | `ui/shell/welcome.py`, `docs/guide/*` |
| P17.6 | **The tools added since the first design** ([ADR 0084](../adr/0084-lumen-covers-the-new-tools.md)): stage header with Scene/Game and Fit, camera on the stage, dialogs in one shape, Deliver health and resume, Code error card and farm | `ui/canvas/*`, `ui/pages/*`, `ui/shell/*dialog*` |

## Rules for every slice

- **No behaviour changes.** Keep every widget attribute, object name, signal and action that a test or another
  module uses; restyle, wrap and re-lay-out. If a test only asserted the old look (a geometry, the bottom page
  bar, the transport slider), change the test in the same commit and say why.
- **Colours only from tokens**; no hex literals in `ui/` (`test_theme`). Document colours stay content.
- **Fonts and sizes only from `theme`** (`theme.font(role)`, `theme.TYPE`), never `setPointSize` in a widget.
- **Every page fits 1024 x 640** (`test_layout_checks`) and keeps its splitters between runs.
- **Both themes**: a slice is not done until its views render correctly in Paper (use the theme switch in
  the screenshot script).
- **Animations go through `motion`** so tests and *Reduce motion* never wait.
- Build with `.venv313`; run `tests/ui` (not slow) and ruff before each commit; the architecture test applies.

## Screenshot loop

`scripts/shots.py` (added in P17.1) builds the window offscreen with a real project in either theme and writes
one PNG per page, so each slice can be compared with its mock-up. Offscreen fonts are the bundled ones, so
the shots are faithful.

## Risks

- **Re-parenting cards**: the shared panels move between pages; wrapping them in cards must keep
  `parking` correct (cards are parented to the parking widget, never parentless).
- **Translucent menus** need a per-platform flag; the fallback is an opaque rounded menu.
- **Test churn** in `test_panels_and_fullscreen`, `test_main_window` and the transport tests; they are listed
  in the slice that moves what they assert.
- **Offscreen vs real rendering** differ (blur, DWM); the shots are for composition and colour, the real
  window is checked by hand.
