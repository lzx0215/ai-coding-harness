---
run_id: 2026-06-22-phase-5-live-scheduler-smoke
schema_version: 0.1.0
changed:
  - "Created a source-controlled Phase 5.2 live scheduler smoke run."
  - "Queued phase5-live-scheduler-agent through queue-generic-agent."
  - "Executed the queued job through run-scheduler --once."
  - "Aggregated terminal async job evidence through aggregate-jobs."
  - "Indexed agent-job, agent-result, aggregation, verification, review-waiver, and handoff evidence."
verified:
  - "queue-generic-agent printed queued generic-agent: 2026-06-22-phase-5-live-scheduler-smoke/phase5-live-scheduler-agent"
  - "run-scheduler --once printed scheduler: 2026-06-22-phase-5-live-scheduler-smoke executed=1 skipped=0"
  - "aggregate-jobs printed aggregated jobs: 2026-06-22-phase-5-live-scheduler-smoke consumed=1 incomplete=0"
  - "state.json SHA256 was unchanged by run-scheduler --once"
  - "raw.log contains phase5 live scheduler agent wrote output"
not_verified:
  - "Watch mode."
  - "Multi-worker concurrency."
  - "Cloud queue integration."
  - "Automatic stale-running recovery."
  - "Local single-process only."
  - "Orphaned running jobs are skipped, not recovered."
residual_risks:
  - "Watch mode remains unverified."
  - "Multi-worker concurrency remains unverified."
  - "Cloud queue behavior remains unverified."
  - "Automatic stale-running recovery remains unverified."
  - "This run proves local single-process scheduler execution only."
  - "Orphaned running jobs are skipped, not recovered."
next_step: "Use this live scheduler smoke as the Phase 5.2 local scheduler baseline before broadening to watch mode or concurrency."
memory_update: updated
memory_files:
  - "harness/memory/progress.md"
---

# Handoff

## What Changed

Created a live Phase 5.2 run whose async job artifacts were produced by the real `queue-generic-agent` + `run-scheduler --once` + `aggregate-jobs` path.

## Evidence

- `jobs/phase5-live-scheduler-agent/input.json`
- `jobs/phase5-live-scheduler-agent/job.json`
- `jobs/phase5-live-scheduler-agent/output.json`
- `jobs/phase5-live-scheduler-agent/raw.log`
- `jobs/aggregation.json`

`input.json` is retained as historical runtime input from this worktree execution. Its absolute artifact paths document what the scheduler used for this run; they are not a portable replay interface.

## State

completed

## Risks

This run proves local single-process scheduler execution only. Watch mode, multi-worker concurrency, cloud queue behavior, automatic stale-running recovery, and orphaned running job recovery remain unverified. Orphaned running jobs are skipped, not recovered.
