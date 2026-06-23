---
run_id: 2026-06-23-phase-9-entry-gate-local-scheduler-closure
schema_version: 0.1.0
workflow: strict-risk-change
acceptance:
  - "Phase 7 targeted stale detection and recovery tests pass."
  - "Phase 7.1 targeted claim-locking and crash-smoke tests pass."
  - "Phase 8 targeted claim token, lease, artifact guard, and live multi-worker tests pass."
  - "Full unit suite passes."
  - "Every source-controlled run validates."
  - "git diff --check passes."
  - "Remote CI status is known or the missing remote CI run is recorded as residual risk with user decision."
  - "The run reaches completed with verification, review handling, and handoff evidence."
verification:
  - "python -m unittest discover -s tests -v"
  - "Get-ChildItem -Directory harness\\runs | ForEach-Object { python -m harness.cli validate $_.FullName }"
  - "git diff --check"
review_plan:
  - "Use a scoped review waiver only if no runtime code, schemas, adapters, tests, CI, permissions, credentials, or cloud resources changed."
  - "If runtime code changes, request independent review before advancing to reviewed."
constraints:
  - "Do not implement cross-run queues."
  - "Do not implement cloud queues."
  - "Do not touch credentials or remote resources."
  - "Do not rewrite historical runs."
recovery_strategy: "If any gate fails, leave this run before completed and record the failed gate in verification.md and handoff.md; do not mark Phase 9 implementation as ready."
residual_risk_owner: codex
---

# Plan

## Goal

Create source-controlled closure evidence for the local scheduler prerequisites named in the Phase 9 Cross-Run / Cloud Queue design.

## Files

- `verification-logs/phase7-stale-recovery.log`
- `verification-logs/phase7-1-claim-crash.log`
- `verification-logs/phase8-multi-worker.log`
- `verification-logs/full-suite.log`
- `verification-logs/run-validation.log`
- `verification-logs/diff-check.log`
- `verification.md`
- `review-waiver.md`
- `handoff.md`
- `state.json`

## Steps

1. Advance this run to `triaged`, `planned`, and `in_progress`.
2. Run targeted Phase 7 stale detection and recovery tests; save the log.
3. Run targeted Phase 7.1 claim-locking and crash-smoke tests; save the log.
4. Run targeted Phase 8 claim token, lease, artifact guard, and live multi-worker tests; save the log.
5. Run the full local unit suite; save the log.
6. Validate every source-controlled run; save the log.
7. Run `git diff --check`; save the log.
8. Update durable docs and memory.
9. Write `verification.md` with exact command outcomes.
10. Index the Phase 9 design spec, this implementation plan, verification logs, verification summary, review handling, and handoff evidence.
11. Advance through `implemented`, `verified`, `reviewed`, and `completed` only if the evidence supports each transition.

## Out Of Scope

Cross-run queue execution, cloud queue execution, provider selection, credentials, remote resources, destructive cleanup, and historical run rewrites are not implemented.
