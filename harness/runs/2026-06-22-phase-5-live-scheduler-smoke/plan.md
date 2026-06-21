---
run_id: 2026-06-22-phase-5-live-scheduler-smoke
schema_version: 0.1.0
workflow: standard-agent-adapter-change
acceptance:
  - "queue-generic-agent writes a queued job under jobs/phase5-live-scheduler-agent."
  - "run-scheduler --once executes the queued job and reports executed=1 skipped=0."
  - "The scheduler does not mutate state.json."
  - "aggregate-jobs writes jobs/aggregation.json and reports consumed=1 incomplete=0."
  - "Codex indexes agent-job, agent-result, and aggregation evidence in order."
  - "The run reaches completed with verification, review waiver, and handoff evidence."
verification:
  - "python -m unittest tests.test_async_job_artifacts.Phase4ClosureRunTest.test_phase5_live_run_was_produced_by_scheduler_path -v"
  - "python -m harness.cli validate harness/runs/2026-06-22-phase-5-live-scheduler-smoke"
  - "git diff --check"
review_plan:
  - "Use review-waiver.md scoped to this run record only; do not waive review for harness/cli.py, CI, tests, or scheduler implementation code."
constraints:
  - "External agent must read HARNESS_AGENT_INPUT_FILE."
  - "External agent must write HARNESS_AGENT_OUTPUT_FILE."
  - "External agent stdout must be exactly phase5 live scheduler agent wrote output."
  - "Scheduler and external agent must not edit state.json."
recovery_strategy: "Remove this new run directory and the targeted test assertion if the live scheduler smoke cannot be made valid."
residual_risk_owner: codex
---

# Plan

## Goal

Produce a source-controlled Phase 5.2 run whose async artifacts are created by the real local scheduler path.

## Files

- `scripts/scheduler-smoke.py`
- `jobs/phase5-live-scheduler-agent/*`
- `jobs/aggregation.json`
- `verification.md`
- `review-waiver.md`
- `handoff.md`
- `state.json`

## Steps

1. Initialize this run with `harness.cli init-run`.
2. Advance the run through `triaged`, `planned`, and `in_progress`.
3. Fill `task.md`, `triage.md`, and `plan.md`.
4. Add `scripts/scheduler-smoke.py`.
5. Queue `phase5-live-scheduler-agent` through `queue-generic-agent`.
6. Execute the queued job through `run-scheduler --once`.
7. Aggregate terminal jobs through `aggregate-jobs`.
8. Index `agent-job`, `agent-result`, and `aggregation` evidence in that order.
9. Advance to `implemented`, write and index verification, review waiver, and handoff evidence.
10. Advance through `verified`, `reviewed`, and `completed`, then validate the run.

## Out of Scope

Watch mode, multi-worker concurrency, cloud queue integration, automatic stale-running recovery, and orphaned running job recovery are out of scope. Orphaned running jobs are skipped, not recovered.
