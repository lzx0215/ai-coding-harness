# Progress

## Current Phase

Phase 3 review decision and memory closure is implemented on branch `phase-3-review-decision-memory` (commits `19669a0`..`HEAD`), pending merge to `master`. The run `harness/runs/2026-06-20-phase-3-review-decision-memory-implementation` reached `completed` end-to-end, exercising every Phase 3 gate against real artifacts and a real Claude Code review adapter output.

Phase 3 added:

- `harness/schemas/review-decision.schema.json` pinning disposition and `recommended_status` enums plus full `disposition -> recommended_status` consistency.
- `validate` loads and semantically validates an indexed `review-decision.json` (detected by basename among `review-evidence`): schema, run_id match, high/critical override, waived/risk-accepted cross-evidence, and `source_evidence` indexability.
- `validate_review_decision_transition` in `advance` rejects review-related targets that conflict with `recommended_status`, and requires a decision when advancing to the triage targets (`reviewed`, `review_blocked`) with review evidence present.
- `validate_handoff_closure` in `advance -> completed` requires Phase 2 handoff closure frontmatter and enforces `memory_update`/`memory_files` consistency.
- A soft `check-ready` warning in `harness/readiness.py` when `memory_files` is declared without `memory_update`.
- Real Claude Code review was invoked through `mcp/claude-review`; its final output was indexed as `review-output`, structured review evidence, and raw log. The review decision is now `findings-triaged -> reviewed`, with no high/critical/medium findings remaining.
- The external review found and confirmed a fixed medium issue: `risk-accepted` / `risk_accepted` decisions with high or critical severity now require non-empty `accepted_risks`. Closure now also rejects non-list `memory_files` explicitly.

No new Harness state and no new evidence type were introduced; `review-decision.json` is indexed as `review-evidence`. Historical runs remain valid without migration.

The final verification baseline is:

- `python -m unittest discover -s tests` -> 209 tests OK, 1 skipped
- all `harness/runs/*` directories validated successfully
- real Claude Code review adapter output indexed under the Phase 3 run

## Next Step

Merge `phase-3-review-decision-memory` to `master` (or open a PR), then start the next focus: hardening review-decision source attribution and duplicate decision detection, or documenting the Codex review-decision authoring flow.
