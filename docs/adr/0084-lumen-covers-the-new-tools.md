# 0084. Lumen covers the tools added after the first design

- **Status:** Accepted
- **Date:** 2026-11-01
- **Deciders:** João Victor
- **Extends:** [ADR 0063](0063-lumen-interface.md)

## Context

Lumen ([design](../design/lumen.md)) was drawn before the camera layer, beat sheet, ripple editing, sequences,
recipes, snapshots, bundles, plugin permissions, resumable exports and "explain this moment" (ADR 0066-0083).
They were built with Lumen's tokens but each found its own place: the camera announced itself with a banner
laid over the video, the new dialogs differ in size and layout, and the Deliver and Code pages have no home for
export health, resumable jobs, the Python farm or an error that names its layer and time. A design that does not
mention a feature leaves the next person to place it by guess.

## Decision

The design document gains a section, *The tools added since the first design*, and three mock-up boards
(`Camera`, `Tools`, `Dialogs`) that place every one of those features with the existing components. The rules it
sets, which code can be checked against:

1. **The picture is never covered by prose.** View state (Scene / Game, Draft / Exact) is a segmented control or
   chip in the stage header; explanations are tooltips or the status bar.
2. **One dialog shape.** Icon header, one task, a body no wider than 560 px, the primary action last; lists use
   the list-row component with chips, not bare text.
3. **Pages own their state.** Export health and resumable jobs are on Deliver, the farm and error cards on
   Code, the camera and guides on the stage, sequences on the timeline.
4. **Every command is in the palette** (it lists the menus), and a shortcut exists only for the few used
   all day.

The implementation follows in plan P17.6; where the running UI differs from the mock-ups, the mock-ups are the
target and a difference is a bug in the UI unless this ADR or the design says otherwise.

## Consequences

Easier: a new feature has a place to go and a review checklist. Harder: several existing dialogs and the stage
header change their layout; tests that asserted the old arrangement change in the same commit with a reason.

## Alternatives considered

- **Leave each feature where it landed** - the arrangement then depends on who built it that day.
- **A separate design for each feature** - the mock-ups would drift from one another and from the components.

## Evidence

- Design: [lumen.md](../design/lumen.md), [Camera](../design/mockups/project/Camera.dc.html),
  [Tools](../design/mockups/project/Tools.dc.html), [Dialogs](../design/mockups/project/Dialogs.dc.html)
- Plan: [P17.6](../plans/p17-lumen.md)
