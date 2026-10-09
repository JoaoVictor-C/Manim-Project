# 0001. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-10-09
- **Deciders:** João Victor

## Context

Manim Studio's design rests on non-obvious rules (who owns the clock, why clips
cannot overlap, why preview uses Cairo). Several were reached through structured
reasoning sessions and then corrected by measurements. Without a record, those
reasons get lost and the rules get "simplified" away.

## Decision

Keep Architecture Decision Records in `docs/adr/`, one file per decision, using
[template.md](template.md). Every accepted ADR cites its evidence. Decisions
made before this ADR (0002–0011) are recorded retroactively with the evidence
gathered at the time.

## Consequences

- Reviews can check a change against a numbered rule ("violates ADR 0004").
- Tests reference the ADR they protect in their docstrings.
- Small overhead per significant change.

## Evidence

- Reasoning sessions: [../logs/decision-sessions.md](../logs/decision-sessions.md)
