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

Phase 6 bounded local scheduler watch mode is implemented in `harness/runs/2026-06-22-phase-6-scheduler-watch-mode`. The live run queued `phase6-watch-agent`, executed it with `run-scheduler --watch --poll-interval-seconds 0.1 --max-iterations 3 --worker-id phase6-live-watch`, exercised `stop-scheduler`, and aggregated `jobs/aggregation.json` with `consumed=1 incomplete=0`. The scheduler wrote `jobs/scheduler/worker.json`, `jobs/scheduler/heartbeat.json`, and JSONL `jobs/scheduler/events.log`; the heartbeat ended with `status=stopped`, events included `worker_started` and `job_completed`, and the scheduler did not mutate `state.json`. Codex indexed `agent-job`, `agent-result`, `aggregation`, external Claude review output, structured review evidence, raw review log, and `reviews/phase6-code-review/review-decision.json` before final validation. The final external review returned `findings` with no medium, high, or critical findings after follow-up commits added `max_seconds` and failed-job watch coverage. Residual risks: heartbeat is observational only, stop requests are cooperative and do not interrupt running jobs, double-claim risk remains if multiple workers are launched against the same run, and `events.log` is append-only diagnostics without rotation or fsync. Multi-worker claim locking, automatic stale-running recovery, cloud queue execution, and cross-run queue execution are not implemented.

The Phase 5.2 `master` baseline also adds team-repeatable validation entrypoints and packaged CLI hardening:

- `harness.cli` now separates package resources (`harness/schemas`, `harness/templates`) from repository root discovery used for evidence paths. Packaged console-script execution can validate absolute run directories from outside the repository.
- `.github/workflows/ci.yml` runs editable install, the full unittest suite, every source-controlled run validation, non-editable package smoke validation from outside the repo, and merge-base scoped `git diff --check`.
- `pyproject.toml` defines the `ai-coding-harness` package and `harness = harness.cli:main` console script.
- `harness/core/run-lifecycle-sop.md` captures the repeatable create-run / advance-state / index-evidence / handoff flow; it should become a Codex skill only after at least two real reuses or explicit user request.

The pre-merge local verification baseline for the Phase 5.2 scheduler work is:

- `python -m unittest discover -s tests` -> 253 tests OK, 1 skipped
- all 12 source-controlled `harness/runs/*` directories validated successfully, including `2026-06-22-phase-5-live-scheduler-smoke`
- local non-editable package smoke passed from outside the repository cwd: packaged `harness.exe` validated every source-controlled run, queued a scheduler smoke job, ran `run-scheduler --once`, generated aggregation, indexed `agent-job` / `agent-result` / `aggregation`, and validated the temporary package-smoke run
- `git diff --check` passed locally with no whitespace errors
- Phase 6 local verification baseline includes `python -m unittest discover -s tests` -> 266 tests OK, 1 skipped; all 13 source-controlled `harness/runs/*` directories validated successfully; local non-editable package smoke from outside the repository cwd exercised both `run-scheduler --once` and bounded `run-scheduler --watch`; `python -m unittest tests.test_generic_agent_adapter -v` -> 52 tests OK after review follow-ups; and merge-base scoped `git diff --check` passed. Local bash parity could not run because this Windows host routes `bash` to an unavailable WSL environment; GitHub Actions has not run for this branch yet.
- real Claude Code review adapter output is indexed under the Phase 3 run and under the Phase 5.2 live scheduler smoke run; the Phase 5.2 review returned `findings` with no medium, high, or critical findings, and `reviews/phase5-code-review/review-decision.json` records `findings-triaged -> reviewed`
- real Claude Code review adapter output is also indexed under the Phase 6 live scheduler watch run; `reviews/phase6-code-review/review-decision.json` records `findings-triaged -> reviewed` with no medium, high, or critical findings remaining.

Follow-up Phase 3 provenance hardening now rejects empty `source_evidence` for review-result decisions, duplicate indexed `review-decision.json` artifacts, and mismatched `severity_counts` when linked review findings can be computed. Historical runs still validate because none indexed a pre-existing `review-decision.json` except the updated Phase 3 run.

## Next Step

Phase 6 implementation closure is complete locally on `codex/phase6-scheduler-watch-mode`; the branch has not been pushed and GitHub Actions has not run for this branch yet. The current remote branch status was verified with `git ls-remote --heads origin master codex/phase5-live-scheduler codex/phase4-run-ci-package`: `refs/heads/master` and `refs/heads/codex/phase5-live-scheduler` both point at `fca6ae36aaf68c6927ae931afea2df70ecbecb08`, while `refs/heads/codex/phase4-run-ci-package` points at `c15fea2c6f897fd2a7b8decc5da28d4c054fa22e`. The old concern that `codex/phase5-live-scheduler` was stale relative to `master` is no longer current; the branch is a cleanup candidate but is not stale relative to `master` per that verified command.

Next implementation choice: implement multi-worker claim locking or automatic stale-running recovery before claiming concurrent scheduler safety.
