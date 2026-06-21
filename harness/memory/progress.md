# Progress

## Current Phase

Phase 3 review decision and memory closure is merged and pushed to `master`. The original Phase 3 merge was `c0151b5`; the follow-up hardening/document reconciliation PR merged at `610bcc1` and became the baseline for the current Phase 4 closure branch. The run `harness/runs/2026-06-20-phase-3-review-decision-memory-implementation` reached `completed` end-to-end, exercising every Phase 3 gate against real artifacts and a real Claude Code review adapter output.

Phase 3 added:

- `harness/schemas/review-decision.schema.json` pinning disposition and `recommended_status` enums plus full `disposition -> recommended_status` consistency.
- `validate` loads and semantically validates an indexed `review-decision.json` (detected by basename among `review-evidence`): schema, run_id match, high/critical override, waived/risk-accepted cross-evidence, and `source_evidence` indexability.
- `validate_review_decision_transition` in `advance` rejects review-related targets that conflict with `recommended_status`, and requires a decision when advancing to the triage targets (`reviewed`, `review_blocked`) with review evidence present.
- `validate_handoff_closure` in `advance -> completed` requires Phase 2 handoff closure frontmatter and enforces `memory_update`/`memory_files` consistency.
- A soft `check-ready` warning in `harness/readiness.py` when `memory_files` is declared without `memory_update`.
- Real Claude Code review was invoked through `mcp/claude-review`; its final output was indexed as `review-output`, structured review evidence, and raw log. The review decision is now `findings-triaged -> reviewed`, with no high/critical/medium findings remaining.
- The external review found and confirmed a fixed medium issue: `risk-accepted` / `risk_accepted` decisions with high or critical severity now require non-empty `accepted_risks`. Closure now also rejects non-list `memory_files` explicitly.

No new Harness state and no new evidence type were introduced; `review-decision.json` is indexed as `review-evidence`. Historical runs remain valid without migration.

Phase 4 async job substrate is implemented in the current source tree. It added run-local async job schemas, aggregation schemas, explicit `agent-job` / `agent-result` / `aggregation` evidence validation, consumed-job duplicate/status checks, aggregation cross-checking, and Standard versus Strict unavailable-review policy. A formal source-controlled Phase 4 closure run exists at `harness/runs/2026-06-21-phase-4-async-substrate-closure`, indexing terminal `agent-job`, `agent-result`, and `aggregation` artifacts. A live smoke run now exists at `harness/runs/2026-06-21-phase-4-live-generic-agent-smoke`; its `jobs/phase4-live-generic-agent/` artifacts were produced by the real `run-generic-agent` CLI path, and `raw.log` contains deterministic smoke-agent stdout.

Phase 5.2 local scheduler smoke is implemented in `harness/runs/2026-06-22-phase-5-live-scheduler-smoke`. The live run queued `phase5-live-scheduler-agent` with `queue-generic-agent`, executed it with `run-scheduler --once` (`executed=1 skipped=0`), and wrote `jobs/aggregation.json` with `aggregate-jobs` (`consumed=1 incomplete=0`). The scheduler did not mutate `state.json`; Codex indexed `agent-job`, `agent-result`, and `aggregation` evidence explicitly before completing the run. Residual risks: watch mode, multi-worker concurrency, cloud queue behavior, and automatic stale-running recovery remain unverified; this proves local single-process scheduler execution only; orphaned running jobs are skipped, not recovered.

The current branch also adds team-repeatable validation entrypoints and packaged CLI hardening:

- `harness.cli` now separates package resources (`harness/schemas`, `harness/templates`) from repository root discovery used for evidence paths. Packaged console-script execution can validate absolute run directories from outside the repository.
- `.github/workflows/ci.yml` runs editable install, the full unittest suite, every source-controlled run validation, non-editable package smoke validation from outside the repo, and merge-base scoped `git diff --check`.
- `pyproject.toml` defines the `ai-coding-harness` package and `harness = harness.cli:main` console script.
- `harness/core/run-lifecycle-sop.md` captures the repeatable create-run / advance-state / index-evidence / handoff flow; it should become a Codex skill only after at least two real reuses or explicit user request.

The current verification baseline is:

- `python -m unittest discover -s tests` -> baseline before this change: 217 tests OK, 1 skipped
- all 10 pre-existing `harness/runs/*` directories validated successfully before this change
- `python -m pip install -e .` succeeded locally
- `harness validate harness/runs/2026-06-21-phase-4-async-substrate-closure` passed locally
- `python -m harness.cli validate harness/runs/2026-06-21-phase-4-live-generic-agent-smoke` passed locally
- `python -m unittest tests.test_async_job_artifacts.Phase4ClosureRunTest.test_phase4_live_run_was_produced_by_run_generic_agent -v` passed locally
- real Claude Code review adapter output is indexed under the Phase 3 run

Follow-up Phase 3 provenance hardening now rejects empty `source_evidence` for review-result decisions, duplicate indexed `review-decision.json` artifacts, and mismatched `severity_counts` when linked review findings can be computed. Historical runs still validate because none indexed a pre-existing `review-decision.json` except the updated Phase 3 run.

## Next Step

Run final full-suite/package verification for the current branch, then choose the next focus: live async worker/scheduler integration, CI hardening after the first GitHub Actions run, or documentation for the Codex review-decision authoring flow.
