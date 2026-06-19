# Review

## Reviewer

User spec review.

## Status

Approved with required revisions.

## Findings and Disposition

| Item | Disposition |
| --- | --- |
| State schema version decision must not remain open. | Accepted. The spec now requires additive `0.2.0` state schema support in the same implementation slice while preserving `0.1.0` validation. |
| `primary_model` needs a deterministic selection algorithm. | Accepted. The spec now chooses largest observed token usage, then sorted key order, then records `primary_model` as unknown. |
| `unknowns` needs a controlled vocabulary. | Accepted. The spec now defines allowed unknown values and requires schema/test updates for new values. |
| Consumers must distinguish no provenance from provenance with unknown primary model. | Accepted. Consumer rules now require checking `reviewer_provenance` presence. |
| Token usage normalization should be deferred but explicit. | Accepted. The spec keeps nullable usage fields, preserves raw usage where safe, and records `token_usage` in `unknowns` when not normalized. |
| Backward compatibility needs a concrete fixture test. | Accepted. Acceptance criteria and verification now require a frozen v0.1.1 envelope fixture without `reviewer_provenance`. |
| Data flow should capture model-resolution uncertainty. | Accepted. The data flow now records resolution failures into controlled `unknowns` instead of throwing. |

## External Review

Not requested for this design-only revision. The implementation slice will require Claude Code review if it changes schemas, adapter behavior, state management, or completion criteria.
