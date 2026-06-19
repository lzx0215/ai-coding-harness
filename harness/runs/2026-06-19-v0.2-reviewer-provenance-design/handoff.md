# Handoff

## What Changed

- Revised the v0.2 reviewer provenance spec after user review.
- Resolved state schema versioning as an implementation decision: accept both `0.1.0` and `0.2.0` additively.
- Added deterministic `primary_model` selection rules.
- Added a controlled `unknowns` vocabulary.
- Clarified consumer behavior when provenance exists but the primary model is unknown.
- Deferred token usage normalization while preserving nullable usage fields and raw usage where safe.
- Added backward compatibility fixture testing to acceptance criteria.
- Recorded user review disposition in this run.

## Evidence

- `docs/superpowers/specs/2026-06-19-v0.2-reviewer-provenance-design.md`
- `harness/runs/2026-06-19-v0.2-reviewer-provenance-design/review.md`
- `harness/runs/2026-06-19-v0.2-reviewer-provenance-design/verification.md`

## State

Design checkpoint ready to close. Next work should start from an implementation plan for the revised v0.2 spec.

## Risks

- The implementation slice must update state schema compatibility before new runs can truthfully claim `0.2.0`.
- The revised spec defines contract behavior but does not implement adapter/schema/test changes.

## Next Step

Write the v0.2 implementation plan from the revised spec.
