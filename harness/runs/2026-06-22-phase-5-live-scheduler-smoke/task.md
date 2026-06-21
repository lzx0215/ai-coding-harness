---
run_id: 2026-06-22-phase-5-live-scheduler-smoke
schema_version: 0.1.0
track: Standard
workflow: standard-agent-adapter-change
owner: codex
requested_outcome: "Prove the real local scheduler path with queue-generic-agent, run-scheduler --once, and aggregate-jobs."
scope:
  - "Create a source-controlled Phase 5.2 live scheduler smoke run."
  - "Queue a generic CLI job through harness.cli queue-generic-agent."
  - "Execute the queued job through harness.cli run-scheduler --once."
  - "Aggregate completed jobs through harness.cli aggregate-jobs."
  - "Index agent-job, agent-result, and aggregation evidence explicitly."
non_goals:
  - "Watch mode."
  - "Multi-worker concurrency."
  - "Cloud queue integration."
  - "Automatic stale-running recovery."
  - "Recovery of orphaned running jobs; orphaned running jobs are skipped, not recovered."
constraints:
  - "The scheduler must not mutate state.json."
  - "aggregate-jobs must write jobs/aggregation.json."
  - "External agent output must be structured JSON."
---

# Task

## Goal

Create a real Phase 5.2 run proving the local live scheduler path: `queue-generic-agent` creates a queued job, `run-scheduler --once` executes it, and `aggregate-jobs` consumes the terminal job into `jobs/aggregation.json`.

## Track

Standard.

## Workflow

`standard-agent-adapter-change`.

## Acceptance Criteria

- `queue-generic-agent` prints `queued generic-agent: 2026-06-22-phase-5-live-scheduler-smoke/phase5-live-scheduler-agent`.
- `run-scheduler --once` prints `scheduler: 2026-06-22-phase-5-live-scheduler-smoke executed=1 skipped=0`.
- `aggregate-jobs` prints `aggregated jobs: 2026-06-22-phase-5-live-scheduler-smoke consumed=1 incomplete=0`.
- `jobs/phase5-live-scheduler-agent/job.json` is terminal and indexed as `agent-job`.
- `jobs/phase5-live-scheduler-agent/output.json` validates and is indexed as `agent-result`.
- `jobs/aggregation.json` records `consumed_jobs` as `["phase5-live-scheduler-agent"]` and `incomplete_jobs` as `[]`.
- `state.json` reaches `completed`.

## Out of Scope

- Watch mode.
- Multi-worker concurrency.
- Cloud queue integration.
- Automatic stale-running recovery.
- Orphaned running job recovery; orphaned running jobs are skipped, not recovered.
