# Progress

## Current Phase

Phase 4 async job substrate first slice is merged into `master` and pushed to
GitHub. Local `master`, `origin/master`, and GitHub `refs/heads/master` are at
`e75ca84` (`fix(harness): require aggregation job classification`).

Phase 4 delivered:

- async job and aggregation artifact schemas
- controlled evidence vocabulary additions: `agent-job`, `agent-result`,
  `aggregation`
- validation for indexed terminal `agent-job` evidence
- validation and semantic checks for indexed `aggregation` evidence
- Strict-track policy blocking direct
  `external_review_unavailable -> risk_accepted`

The final verification baseline before this progress update was:

- `python -m unittest discover -s tests` -> 121 tests OK, 1 skipped
- `python -m pytest tests/` -> 120 passed, 1 skipped
- all 8 existing `harness/runs/*` directories validated successfully
- `git diff --check` -> exit 0
- final Claude review completed with no high/medium/critical findings

## Next Step

The report-correction follow-up declared root Python dependencies, added locked
runtime/dev dependency snapshots, documented the Strict unavailable-review
policy and Phase 4 evidence types, and corrected the pytest verification record.

The next implementation slice should decide whether to formalize `agent-result`,
add job timestamp semantics, or cross-check job and aggregation `run_id` values
against `state.run_id`.
