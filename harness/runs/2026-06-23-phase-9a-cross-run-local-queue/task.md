---
run_id: 2026-06-23-phase-9a-cross-run-local-queue
schema_version: 0.1.0
track: Strict
workflow: strict-risk-change
owner: codex
requested_outcome: "Implement Phase 9A local filesystem cross-run queue"
scope:
  - Add durable local cross-run queue entry and event schemas.
  - Queue existing run-local generic-agent jobs by reference.
  - Authorize and claim queue entries before claiming the owning run-local job.
  - Execute referenced jobs through existing Phase 8 claim-token logic.
  - Record explicit queue recovery and cleanup audit artifacts.
non_goals:
  - Cloud queue adapters.
  - Provider selection or credentials.
  - Automatic evidence indexing or run state advancement from queue workers.
  - Destructive cleanup of run-local terminal artifacts.
constraints:
  - Cross-run queue records are coordination artifacts, not state authority.
  - External agents remain evidence producers only.
  - Completion requires local verification, source-controlled smoke evidence, and review handling.
---

# Task

## Goal

Implement the first Phase 9 slice: a local filesystem cross-run queue that can route existing queued generic-agent jobs across multiple Harness runs while preserving each owning run's state authority and terminal job artifacts.

## Track

Strict.

## Workflow

`strict-risk-change`, because this slice crosses run ownership boundaries and introduces a new coordination surface that can affect more than one run.

## Scope

- Add `cross-run-queue-entry` and `cross-run-queue-event` JSON schemas.
- Add CLI/runtime helpers to create queue entries for existing queued run-local jobs.
- Add queue-entry authorization, atomic local claim locks, and one-shot worker execution.
- Delegate job execution to existing `try_claim_job` and `execute_claimed_generic_agent_job`.
- Add explicit recovery and cleanup audit helpers for queue entries.
- Add public CLI entrypoints for queue creation and one-shot local queue execution.
- Capture a source-controlled live smoke with two owning runs and one local queue.

## Non-goals

- Cloud queues, object stores, network shares, provider-specific permissions, and credentials.
- Queue-driven updates to `state.json`.
- Automatic evidence indexing from queue files.
- Deleting or compacting terminal run-local `job.json`, `raw.log`, or `output.json`.

## Acceptance Criteria

- Queue entries validate against source-controlled schemas.
- Queue creation rejects missing or non-queued referenced jobs.
- Unauthorized workers cannot claim entries.
- Authorized workers execute referenced jobs exactly once through the run-local claim path.
- Queue recovery requires explicit confirmation and writes an audit artifact.
- Queue cleanup writes an audit record without deleting owning run artifacts.
- CLI commands cover queue creation and one-shot queue execution.
- All existing source-controlled runs validate after changes.

## Verification Plan

- Focused `tests.test_cross_run_queue`.
- Static contract tests.
- Full `unittest discover`.
- Source-controlled live smoke artifacts under this run.
- `git diff --check`.
- Remote GitHub Actions CI for the pushed branch.

## Risks

- Local atomic directory claims are not proof for cross-machine filesystems or cloud queues.
- Queue records are control/audit artifacts only; Codex still owns evidence indexing and state advancement.
- Cloud-provider security, cost, cleanup, and audit semantics remain unimplemented.
