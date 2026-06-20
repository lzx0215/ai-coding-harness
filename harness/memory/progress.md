# Progress

## Current Phase

Phase 2 run definition/evidence implementation is merged into `master` after integrating the remote Phase 4 report-correction follow-up. The implementation adds Phase 2 Markdown frontmatter readiness checks, `check-ready`, `index-evidence`, `init-run`, and run artifact templates while preserving `validate` as the state/evidence authority. A follow-up alignment keeps `plan.md` `recovery_strategy` and `residual_risk_owner` readiness warnings Strict-only, matching the Phase 2 spec.

The remote Phase 4 report-correction follow-up documents:

- async job and aggregation artifact schemas
- controlled evidence vocabulary additions: `agent-job`, `agent-result`,
  `aggregation`
- validation for indexed terminal `agent-job` evidence
- validation and semantic checks for indexed `aggregation` evidence
- Strict-track policy blocking direct
  `external_review_unavailable -> risk_accepted`
- root Python dependency declarations and lock snapshots

The final verification baseline before this progress update is:

- `python -m unittest discover -s tests -v` -> 176 tests OK, 1 skipped
- all 8 existing `harness/runs/*` directories validated successfully

## Next Step

Start Phase 3 implementation from a fresh task/run: add the `review-decision.json` schema first, resolve process-failed review outcomes explicitly, then implement review decision and memory closure checks without adding new Harness states.
