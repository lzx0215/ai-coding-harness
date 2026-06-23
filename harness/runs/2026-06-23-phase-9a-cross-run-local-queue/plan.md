---
run_id: 2026-06-23-phase-9a-cross-run-local-queue
schema_version: 0.1.0
workflow: strict-risk-change
acceptance:
  - "Local cross-run queue entries can be created for existing queued run-local jobs."
  - "Authorized local workers claim queue entries and execute referenced jobs through existing job claims."
  - "Recovery and cleanup write explicit queue audit artifacts."
  - "Queue records do not mutate or advance owning run state."
verification:
  - "python -m unittest tests.test_cross_run_queue -v"
  - "python -m unittest discover -s tests -v"
  - "all source-controlled run validation"
  - "git diff --check"
  - "remote GitHub Actions CI"
review_plan:
  - "Run Claude Code review if the adapter is available."
  - "If unavailable, record strict review-risk handling before completion."
constraints:
  - "No cloud queue/provider behavior in Phase 9A."
  - "No automatic evidence indexing from queue workers."
  - "No destructive cleanup of run-local job artifacts."
recovery_strategy: "Use confirmed queue recovery to requeue or abandon non-terminal/failed entries; use existing stale-job recovery for owning run-local jobs."
residual_risk_owner: codex
---

# Plan

## Goal

Execute `docs/superpowers/plans/2026-06-23-phase-9a-cross-run-local-queue-implementation.md` and close Phase 9A with source-controlled evidence.

## Files

- `harness/cli.py`
- `harness/schemas/cross-run-queue-entry.schema.json`
- `harness/schemas/cross-run-queue-event.schema.json`
- `tests/test_cross_run_queue.py`
- `tests/test_static_contracts.py`
- `harness/core/state-authority.md`
- `harness/core/evidence.md`
- `docs/INDEX.md`
- `harness/memory/progress.md`
- `harness/runs/2026-06-23-phase-9a-cross-run-local-queue/`

## Steps

1. Add schemas and static contracts.
2. Add queue entry creation for existing queued jobs.
3. Add queue authorization, entry claims, and local one-shot execution through existing job claims.
4. Add CLI commands.
5. Add explicit recovery and cleanup audit helpers.
6. Capture a live smoke with two owning runs and one local cross-run queue.
7. Update durable docs and memory.
8. Run local verification, external review handling, push, and confirm remote CI.

## Verification

- Focused cross-run queue tests.
- Full unit suite.
- Source-controlled run validation.
- Live smoke evidence under `live-smoke/`.
- Review handling evidence.
- Remote CI.

## Rollback

Revert the Phase 9A commits on the feature branch. The change is additive and does not migrate existing run state. Source-controlled queue schemas, tests, and docs can be reverted without mutating historical run records.
