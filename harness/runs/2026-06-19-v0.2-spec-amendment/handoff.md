# Handoff

## What Changed

- Clarified that incomplete-usage models are excluded from token-total comparison when any complete usage exists.
- Added invariants for `model_name`, `primary_model`, `models`, and scalar `reviewer_model`.
- Reordered migration so additive state schema compatibility lands before new v0.2 provenance output emission.
- Added acceptance criteria requiring schema failure for out-of-vocabulary `unknowns`.
- Replaced the remaining CLI semver open question with an explicit deferred decision.
- Added a second append-only amendment run instead of rewriting the completed design run.

## Evidence

- `docs/superpowers/specs/2026-06-19-v0.2-reviewer-provenance-design.md`
- `harness/runs/2026-06-19-v0.2-spec-amendment/review.md`
- `harness/runs/2026-06-19-v0.2-spec-amendment/verification.md`

## State

Ready for checkpoint commit, then v0.2 implementation planning.

## Risks

- The next implementation plan must preserve the order constraint: state schema compatibility before output schema or adapter emission of v0.2 provenance.
- Live pip hash validation remains optional and was not rerun for this documentation amendment.

## Next Step

Commit the design checkpoint, then write the v0.2 implementation plan.
