---
run_id: 2026-06-22-phase-6-scheduler-watch-mode
schema_version: 0.1.0
track: Standard
workflow: standard-agent-adapter-change
review_required: true
strict_triggers: []
risk_reasons:
  - "Records live scheduler watch evidence for an agent adapter workflow."
  - "Incorrect async evidence indexing would weaken the Harness audit trail."
  - "Scheduler metadata is observational and must not replace Codex-owned state transitions."
verification_required:
  - "Run-local queue plus watch scheduler execution must produce real job artifacts."
  - "The scheduler must write worker.json, heartbeat.json, and JSONL events.log."
  - "The scheduler must not mutate state.json."
  - "aggregate-jobs must write jobs/aggregation.json."
  - "The completed run must validate."
---

# Triage

## Track Decision

Standard. This task creates run-record artifacts, durable docs, and a focused regression test for bounded local scheduler watch mode. It does not touch secrets, production state, destructive operations, auth, permissions, database, payments, or privacy-sensitive code.

## Workflow

`standard-agent-adapter-change`.

## Risk Reasons

- The run is source-controlled evidence for Phase 6 scheduler watch behavior.
- Scheduler evidence is only valid if Codex explicitly indexes the consumed async artifacts.
- `state.json` authority remains with Codex lifecycle commands; scheduler and external agent output must not mutate it.
- `worker.json`, `heartbeat.json`, and `events.log` are observational runtime metadata, not state authority.

## Review Requirement

Review handling is required before completion. A review waiver may be used only for the run record artifacts created by this smoke run and must not waive review for `harness/cli.py`, CI, tests, or scheduler implementation code.

## Verification Required

- Prove `queue-generic-agent`, `run-scheduler --watch`, `stop-scheduler`, and `aggregate-jobs` stdout.
- Validate this run with `harness.cli`.
- Run the targeted Phase 6 watch scheduler regression test.
- Confirm scheduler metadata exists and records `phase6-live-watch`.
- Confirm `aggregation.json` records one consumed job and zero incomplete jobs.

## Out of Scope

Multi-worker claim locking, automatic stale-running recovery, cloud queue execution, and cross-run queue execution are not implemented.
