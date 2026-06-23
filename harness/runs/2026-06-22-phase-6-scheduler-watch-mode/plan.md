---
run_id: 2026-06-22-phase-6-scheduler-watch-mode
schema_version: 0.1.0
workflow: standard-agent-adapter-change
acceptance:
  - "queue-generic-agent writes a queued job under jobs/phase6-watch-agent."
  - "run-scheduler --watch executes the queued job and records scheduler metadata."
  - "worker.json, heartbeat.json, and JSONL events.log identify worker phase6-live-watch."
  - "heartbeat.json records stopped status when bounded watch exits."
  - "events.log records worker_started and job_completed."
  - "The scheduler does not mutate state.json."
  - "aggregate-jobs writes jobs/aggregation.json and reports consumed=1 incomplete=0."
  - "Codex indexes agent-job, agent-result, and aggregation evidence in order."
  - "The run reaches completed with verification, review waiver, and handoff evidence."
verification:
  - "python -m unittest tests.test_async_job_artifacts.Phase4ClosureRunTest.test_phase6_watch_run_was_produced_by_watch_scheduler_path -v"
  - "python -m harness.cli validate harness/runs/2026-06-22-phase-6-scheduler-watch-mode"
  - "git diff --check"
review_plan:
  - "Use review-waiver.md scoped to this run record only; do not waive review for harness/cli.py, CI, tests, or scheduler implementation code."
constraints:
  - "External agent must read HARNESS_AGENT_INPUT_FILE."
  - "External agent must write HARNESS_AGENT_OUTPUT_FILE."
  - "External agent stdout must be exactly phase6 scheduler watch agent wrote output."
  - "Scheduler and external agent must not edit state.json."
recovery_strategy: "Remove this new run directory, the targeted test assertion, and durable doc additions if the live watch scheduler smoke cannot be made valid."
residual_risk_owner: codex
---

# Plan

## Goal

Produce a source-controlled Phase 6 run whose async artifacts and scheduler metadata are created by the real local watch scheduler path.

## Files

- `scripts/watch-smoke.py`
- `jobs/phase6-watch-agent/*`
- `jobs/scheduler/worker.json`
- `jobs/scheduler/heartbeat.json`
- `jobs/scheduler/events.log`
- `jobs/scheduler/stop.json`
- `jobs/aggregation.json`
- `verification.md`
- `review-waiver.md`
- `handoff.md`
- `state.json`

## Steps

1. Initialize this run with `harness.cli init-run`.
2. Advance the run through `triaged`, `planned`, and `in_progress`.
3. Fill `task.md`, `triage.md`, and `plan.md`.
4. Add `scripts/watch-smoke.py`.
5. Queue `phase6-watch-agent` through `queue-generic-agent`.
6. Execute the queued job through bounded `run-scheduler --watch`.
7. Exercise `stop-scheduler` after bounded watch execution.
8. Aggregate terminal jobs through `aggregate-jobs`.
9. Index `agent-job`, `agent-result`, and `aggregation` evidence in that order.
10. Advance to `implemented`, write and index verification, review waiver, and handoff evidence.
11. Advance through `verified`, `reviewed`, and `completed`, then validate the run.

## Out of Scope

Multi-worker claim locking, automatic stale-running recovery, cloud queue execution, and cross-run queue execution are not implemented.
