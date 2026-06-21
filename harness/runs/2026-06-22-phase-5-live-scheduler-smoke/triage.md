---
run_id: 2026-06-22-phase-5-live-scheduler-smoke
schema_version: 0.1.0
track: Standard
workflow: standard-agent-adapter-change
review_required: true
strict_triggers: []
risk_reasons:
  - "Records live scheduler evidence for an agent adapter workflow."
  - "Incorrect async evidence indexing would weaken the Harness audit trail."
verification_required:
  - "Run-local queue + scheduler execution must produce real job artifacts."
  - "The scheduler must not mutate state.json."
  - "aggregate-jobs must write jobs/aggregation.json."
  - "The completed run must validate."
---

# Triage

## Track Decision

Standard. This task creates run-record artifacts, docs, and a focused regression test for the local scheduler path. It does not touch secrets, production state, destructive operations, auth, permissions, database, payments, or privacy-sensitive code.

## Workflow

`standard-agent-adapter-change`.

## Risk Reasons

- The run is source-controlled evidence for Phase 5.2 scheduler behavior.
- Scheduler evidence is only valid if Codex explicitly indexes the consumed async artifacts.
- `state.json` authority remains with Codex lifecycle commands; scheduler and external agent output must not mutate it.

## Review Requirement

Review handling is required before completion. A review waiver may be used only for the run record artifacts created by this smoke run and must not waive review for `harness/cli.py`, CI, tests, or scheduler implementation code.

## Verification Required

- Prove `queue-generic-agent`, `run-scheduler --once`, and `aggregate-jobs` stdout.
- Validate this run with `harness.cli`.
- Run the targeted Phase 5 live scheduler regression test.
- Confirm `aggregation.json` records one consumed job and zero incomplete jobs.

## Out of Scope

Watch mode, multi-worker concurrency, cloud queue integration, automatic stale-running recovery, and orphaned running job recovery are out of scope. Orphaned running jobs are skipped, not recovered.
