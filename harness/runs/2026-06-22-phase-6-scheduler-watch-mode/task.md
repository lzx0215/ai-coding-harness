---
run_id: 2026-06-22-phase-6-scheduler-watch-mode
schema_version: 0.1.0
track: Standard
workflow: standard-agent-adapter-change
owner: codex
requested_outcome: "Prove bounded local scheduler watch mode with source-controlled run evidence."
scope:
  - "Create a source-controlled Phase 6 live scheduler watch run."
  - "Queue a generic CLI job through harness.cli queue-generic-agent."
  - "Execute the queued job through harness.cli run-scheduler --watch."
  - "Exercise harness.cli stop-scheduler after bounded watch execution."
  - "Aggregate completed jobs through harness.cli aggregate-jobs."
  - "Index agent-job, agent-result, and aggregation evidence explicitly."
non_goals:
  - "Multi-worker claim locking."
  - "Automatic stale-running recovery."
  - "Cloud queue execution."
  - "Cross-run queue execution."
constraints:
  - "The scheduler must write worker.json, heartbeat.json, and JSONL events.log."
  - "The scheduler must not mutate state.json."
  - "Codex indexes consumed evidence and advances state."
  - "External agent output must be structured JSON."
---

# Task

## Goal

Create a real Phase 6 run proving bounded local scheduler watch mode: `queue-generic-agent` creates a queued job, `run-scheduler --watch` executes it, scheduler metadata is written under `jobs/scheduler/`, `stop-scheduler` records a cooperative stop request, and `aggregate-jobs` consumes the terminal job into `jobs/aggregation.json`.

## Track

Standard.

## Workflow

`standard-agent-adapter-change`.

## Acceptance Criteria

- `queue-generic-agent` prints `queued generic-agent: 2026-06-22-phase-6-scheduler-watch-mode/phase6-watch-agent`.
- `run-scheduler --watch --poll-interval-seconds 0.1 --max-iterations 3 --worker-id phase6-live-watch` runs the queued job.
- Scheduler writes `jobs/scheduler/worker.json`, `jobs/scheduler/heartbeat.json`, and JSONL `jobs/scheduler/events.log`.
- `worker.json` and `heartbeat.json` identify `phase6-live-watch`.
- `heartbeat.json` ends with status `stopped`.
- `events.log` includes `worker_started` and `job_completed`.
- Scheduler and external agent execution do not mutate `state.json`; Codex lifecycle and evidence-indexing commands own state changes.
- `jobs/phase6-watch-agent/job.json` is terminal and indexed as `agent-job`.
- `jobs/phase6-watch-agent/output.json` validates and is indexed as `agent-result`.
- `jobs/aggregation.json` records `consumed_jobs` as `["phase6-watch-agent"]` and `incomplete_jobs` as `[]`.
- `state.json` reaches `completed`.

## Out of Scope

Multi-worker claim locking, automatic stale-running recovery, cloud queue execution, and cross-run queue execution are not implemented by this run.
