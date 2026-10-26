# 0063. Lumen: a new interface for the editor, built on the existing design system

- **Status:** Accepted
- **Date:** 2026-10-26
- **Deciders:** João Victor

## Context

The editor's functions are settled; its look was built a panel at a time ([0040](0040-design-system.md),
[0041](0041-workspace-pages.md)) and reads as a utility: flat grey docks edge to edge, a page bar under the
timeline, one font size, one blue for everything, numbers that can only be typed, state that is visible only
on the page that produced it, and commands that can only be found by knowing the menu. The request: design a
new interface focused on experience and beauty, then build it. The design is in
[docs/design/lumen.md](../design/lumen.md) with mock-ups of every page; the plan is
[P17](../plans/p17-lumen.md).

Constraints that decide how, measured on the code: the widgets are Qt Widgets with ~1 800 UI tests that find
widgets by attribute and drive them by signal; panels are single instances **re-parented between pages**
([0041](0041-workspace-pages.md)); every colour of the chrome already comes from `Colours` tokens and one
generated stylesheet, and `test_theme` refuses colour literals in `ui/`; the timeline, canvas and curve
editor paint themselves from the same tokens; the architecture test ([0062](0062-package-layout.md)) fixes
what may import what.

## Decision

- **Evolve the design system, do not replace the toolkit.** The tokens keep every existing name and gain
  the new roles (`surface_2`, `surface_3`, `line`, `line_strong`, `faint`, `accent_2`, `accent_soft`,
  `accent_line`, `stage`, `shadow`, ...), with two sets: **Ink** (dark, default) and **Paper** (light),
  chosen in Preferences (Ink, Paper, follow the system) and switchable while running (`theme.set_theme`
  re-applies the palette and stylesheet and emits `themeChanged`; custom-painted widgets repaint from the
  live tokens).
- **Typography is bundled**: Inter, JetBrains Mono and Newsreader (SIL Open Font License) under
  `ui/style/fonts/`, registered at start-up; if a font fails to load the system fonts are used. Sizes come
  from a scale in `theme` (`TYPE`), not from point sizes in widgets.
- **Icons become one family** (Phosphor through `qtawesome`, regular and fill), tinted by role.
- **A component layer in `ui/style/`** (`Card`, `PageSwitcher`, `Chip`, `Pill`, `Toast`/`ToastHost`,
  `Popover`, `ScrubField`, `Section`, `CommandPalette`) that the pages compose. They are plain `QWidget`
  subclasses with stable object names; behaviour stays where it was (signals, models, edits).
- **The shell changes, the parts do not.** The top bar (menus, page switcher, undo/redo, search, panel
  toggles, Export) replaces the page bar at the bottom through `QMainWindow.setMenuWidget`; the real
  `QMenuBar` lives in it, so every shortcut and every test that reads a menu keeps working. The shared panels
  are wrapped in `Card`s once, in `MainWindow`, and the pages place the cards (`Shared` keeps its four
  names). `PageHost.bar` keeps its API (`currentIndex`, `tabData`, `currentChanged`) but is the switcher's
  model, so existing navigation tests pass unchanged.
- **Floating chrome over the stage**: the tool pill and the transport pill are children of the viewer (they
  are hidden in the full-screen presenter, which has its own player bar, [0057](0057-code-workspace.md)).
  The slider bar under the canvas is retired; seeking is the timeline's job and the pill has a scrub bar
  that appears on hover.
- **Messages become toasts**: `statusBar().showMessage` keeps working (it is called ~200 times) but a
  `ToastHost` listens to the status bar's messages and shows them as toasts; the status bar itself shows
  only persistent state (saved, activity, selection facts). The status bar's own message area is left empty
  while a toast is up.
- **Command palette** (Ctrl K) is built from the window's actions (walks `menuBar()` recursively), the
  layers, and the Code page's symbols; ranking reuses `quick_open.score`.
- **Motion** is a small helper (`style/motion.py`): property animations of 90/160/220 ms with one easing
  curve; all of them go through `motion.enabled()`, which is false when the preference *Reduce motion* is on
  or under test, so no test waits for an animation.
- **Windows title bar** is made dark (and Paper-light) with `DwmSetWindowAttribute` on supporting versions,
  so the OS frame does not break the look; elsewhere nothing changes.
- **Nothing in the model, the commands, the project format or the shortcuts changes.** Page keys move from
  `Shift+1..5` aliases to `Ctrl+1..5` as before; the top bar shows them.

## Consequences

- Every page looks different and the same: one set of components, two themes, one type scale. New UI is
  built from the components and the tokens and cannot drift.
- A theme switch costs a stylesheet re-application and a repaint of the painted views: measured in P17.1.
- The UI tests keep their handles because attributes and signals stay; tests that asserted geometry or the
  old chrome (the bottom page bar, the transport slider row, status-bar text) are rewritten with the slice
  that moves it, and `tests/ui/test_layout_checks.py` keeps proving that every page fits 1024 x 640.
- Fonts add about 1.5 MB to the wheel (three families, nine files) and their licences to
  `THIRD-PARTY-NOTICES.md`.
- Native look (system menus and dialogs) is given up for consistency; file dialogs and the OS title bar stay
  native.

## Alternatives considered

- **Rewrite the UI in QML** - the best animation and styling story, but the canvas, timeline and editor are
  custom-painted widgets with 1 800 tests behind them; a rewrite is a second product. QML would only be
  worth it for a new application.
- **A web view for the chrome** - the mock-ups are HTML, so it is tempting, but two runtimes, focus and
  shortcut bridging, and the memory of an embedded browser are a poor trade for an editor.
- **A third-party Qt theme** (qt-material, QDarkStyle, ...) - gives a different generic look quickly, not this
  one; it also fights the token system that the painted views depend on.
- **A frameless custom title bar** - nicer, but loses native snapping and accessibility on Windows and needs
  per-platform code; the dark DWM frame gets most of the effect.

## Evidence

- Mock-ups: [docs/design/mockups](../design/mockups/project/canvas.json) (Compose, Animate, Code, Audio,
  Deliver, Welcome, Palette, Paper, Foundations, Components).
- Contrast and token tests: `tests/ui/style/test_theme.py` (extended in P17.1).
- Layout: `tests/ui/test_layout_checks.py`.
