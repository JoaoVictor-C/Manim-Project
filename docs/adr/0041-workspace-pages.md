# 0041. Workspace pages

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** João Victor

## Context

The user asked for tabs "like DaVinci does, each tab does its own thing". The
editor was one window: a canvas over a timeline with Layers and Properties docks.
Code layers were edited in a small Properties box, keyframes only as diamonds on
the timeline, sounds and subtitles in Properties, the export in a dialog.

## Decision

- **Pages**: the window's central widget is a stack of pages over a **page bar** at
  the bottom (icon and name, an accent line on the current page), with **View >
  Pages** and **Shift+1** to **Shift+5**: *Compose*, *Animate*, *Code*, *Audio*,
  *Deliver*. `window.pages`, `window.page`, `window.show_page(name)`.
- **One controller**: `MainWindow` keeps the document, selection, undo, playback,
  render-ahead and helper processes, and every attribute it had.
- **Shared views exist once** - the viewer (canvas and transport), the timeline,
  the Layers and Properties panels. Showing a page parks them in a hidden holder
  (never parentless: a parentless widget becomes a window) and the page's `place()`
  re-parents the ones it uses into its splitters (B55: about 23 ms per switch). Each
  page keeps its splitter sizes while the editor runs.
- **Docks are removed**; View > Layers and View > Properties hide a panel on every page.
- **Compose** (default) is the former layout: Layers | the viewer over the timeline |
  Properties.
- **A page** is a module in `ui/pages/` subclassing `Page` (`build`, `place`,
  `on_show`, `on_hide`) and registered in `MainWindow.__init__` before the menus are
  built. Animate (a large curve editor of the selected layer's tracks), Code (code
  layers in an editor with highlighting and run output), Audio (sound and subtitle
  tables) and Deliver (export settings, a queue and the Python export) are slices
  P6b.2-P6b.5, each settling its own details in a short design session.

## Consequences

- Panels cannot float on a second monitor (until P6d).
- The last page and panel sizes are not remembered between runs (P6d's preferences).

## Evidence

- B55 in [../logs/benchmarks.md](../logs/benchmarks.md); the unchanged UI suite and
  the framework tests in decision session 34
  ([../logs/decision-sessions.md](../logs/decision-sessions.md)).
- Plan: [../plans/p6b-pages.md](../plans/p6b-pages.md).
