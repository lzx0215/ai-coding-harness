# Review

## Reviewer

User spec review, second pass.

## Status

Approved with pre-implementation amendments.

## Findings and Disposition

| Item | Disposition |
| --- | --- |
| Incomplete token usage in `primary_model` selection was ambiguous. | Accepted. The algorithm now excludes incomplete-usage models from token-total comparison when any complete usage exists. |
| `model_name` and `primary_model` unknown invariants were under-specified. | Accepted. The spec now defines invariants for empty models, null primary model, and scalar `reviewer_model`. |
| Migration order could create a half-migrated state/output window. | Accepted. State schema compatibility now comes before v0.2 output artifact emission. |
| Out-of-vocabulary `unknowns` should fail schema validation. | Accepted. Acceptance criteria now requires schema failure for non-vocabulary values. |
| CLI semver should be a deferred decision, not an open question. | Accepted. The open question was replaced with a deferred parsing section. |
| Data flow should point to the unknown vocabulary. | Accepted. The data-flow note now references the controlled vocabulary. |
| Design checkpoint should be committed before implementation planning. | Accepted. This amendment run includes checkpoint commit as an acceptance criterion. |

## External Review

Not requested for this design-only amendment.
