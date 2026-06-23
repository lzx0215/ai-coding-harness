---
run_id: 2026-06-23-phase-9a-cross-run-local-queue
schema_version: 0.1.0
changed: []
changed:
  - "Implemented Phase 9A local filesystem cross-run queue schemas and CLI entrypoints."
  - "Added queue entry creation for existing queued run-local generic-agent jobs."
  - "Added worker authorization, queue claim locking, one-shot local queue execution, and terminal status preservation."
  - "Added explicit queue recovery and cleanup audit helpers without deleting owning run-local artifacts."
  - "Updated state/evidence/docs/memory contracts to keep queue records as control/audit artifacts, not run state authority."
  - "Added regression coverage for claim/load/execution exception paths that must not strand queue claim locks."
  - "Captured a live smoke with two owning runs and one local cross-run queue."
verified:
  - "python -m unittest tests.test_cross_run_queue -v -> 21 tests OK."
  - "python -m unittest tests.test_static_contracts -v -> 18 tests OK, 1 skipped."
  - "python -m unittest discover -s tests -v -> 336 tests OK, 1 skipped."
  - "git diff --check -> exit 0, line-ending warnings only."
  - "All top-level source-controlled harness/runs directories validated successfully."
  - "live-smoke/command-log.md shows two queued owning jobs executed through one local cross-run queue with executed=2 skipped=0."
  - "Live smoke assertions confirmed both owning state.json files were byte-identical before and after queue execution."
  - "Final real Claude Code review returned findings with info severity only; review-decision.json records findings-triaged -> reviewed."
not_verified:
  - "Cloud queue adapters, provider credentials, object stores, network shares, and cross-machine filesystems."
  - "Automatic queue lease reaping or lock stealing."
  - "Automatic evidence indexing or state advancement from queue workers."
  - "Destructive cleanup or compaction of owning run-local terminal artifacts."
  - "Non-OSError non-HarnessCliError exception variants from try_claim_job."
  - "Failure of release_cross_run_queue_claim itself while handling an earlier queue-worker exception."
  - "Remote GitHub Actions for this branch at the time this handoff was written."
residual_risks:
  - "Phase 9A claim locking is local-filesystem only and is not proof for networked or cloud-backed queues."
  - "Queue entries are control/audit artifacts only; Codex must still index owning run evidence and advance state explicitly."
  - "If terminal queue marking fails, the queue claim lock is released but the entry state may require explicit operator recovery."
  - "Run-local stale job recovery remains the authority when a cross-run worker dies after claiming an owning run-local job."
  - "Queue cleanup is audit-only and does not delete run-local job.json, raw.log, or output.json artifacts."
next_step: "Push the Phase 9A branch, confirm remote GitHub Actions, then merge or start Phase 9B only after explicit provider, credential, cost, cleanup, and audit approval."
memory_update: updated
memory_files:
  - "harness/memory/progress.md"
---

# Handoff

## What Changed

Implemented Phase 9A as an additive local cross-run queue slice. Queue entries reference existing queued run-local generic-agent jobs; workers claim queue entries before claiming the owning run-local job; job execution still flows through the existing Phase 8 run-local claim-token path.

Recovery and cleanup are explicit audit actions. Queue files are documented as control/audit records, not completion evidence or state authority.

## Evidence

- `verification-cross-run-queue.log`
- `verification-static-contracts.log`
- `verification-full-suite.log`
- `verification-diff-check.log`
- `verification-run-validation.log`
- `live-smoke/command-log.md`
- `reviews/phase9a-code-review-claim-coverage-followup/claude-review.json`
- `reviews/phase9a-code-review-claim-coverage-followup/claude-review.evidence.json`
- `reviews/phase9a-code-review-claim-coverage-followup/review-decision.json`

## State

completed

## Risks

Phase 9A is local-filesystem only. It does not implement cloud providers, network-share safety, credential boundaries, provider cleanup, automatic queue lease reaping, or queue-driven state advancement.

The final external review returned three informational notes and no medium, high, or critical findings. The notes are preserved in `review-decision.json`.

## Next Step

Push the branch and confirm remote GitHub Actions. Do not start Phase 9B cloud queue work until provider, credential, cost, cleanup, and audit boundaries are explicitly approved.
