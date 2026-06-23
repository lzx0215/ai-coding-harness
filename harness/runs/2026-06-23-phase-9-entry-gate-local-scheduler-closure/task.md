---
run_id: 2026-06-23-phase-9-entry-gate-local-scheduler-closure
schema_version: 0.1.0
track: Strict
workflow: strict-risk-change
owner: codex
requested_outcome: "Close local scheduler evidence gates required before Phase 9 Cross-Run / Cloud Queue implementation."
scope:
  - "Record source-controlled verification evidence for Phase 7 stale-running detection and explicit recovery."
  - "Record source-controlled verification evidence for Phase 7.1 local claim locking and crash-smoke behavior."
  - "Record source-controlled verification evidence for Phase 8 claim tokens, lease diagnostics, claim-aware writes, artifact guards, and live multi-worker scheduler behavior."
  - "Synchronize docs/INDEX.md and harness/memory/progress.md with the Phase 8 baseline and Phase 9 gated design status."
  - "Record remote CI status or an explicit residual-risk decision if remote CI has not run for the closure baseline."
non_goals:
  - "Implement cross-run queue execution."
  - "Implement cloud queue execution."
  - "Select a cloud provider."
  - "Read, write, or request credentials."
  - "Mutate historical run records outside this new closure run."
  - "Change harness runtime code, schemas, adapters, tests, or CI unless verification exposes a blocking defect."
constraints:
  - "Codex remains the only authority for state transitions."
  - "External workers, schedulers, and tests produce evidence only."
  - "No Phase 9 implementation plan may be written until this closure either completes or records the exact unmet gate."
  - "No destructive cleanup is allowed."
---

# Task

## Goal

Create a Strict source-controlled closure run proving that the local scheduler semantics required by the Phase 9 design are stable: bounded watch mode, stale-running detection and explicit recovery, local claim locking, claim tokens, leases, claim-aware writes, artifact overwrite guards, and live local multi-worker execution.

## Track

Strict.

## Workflow

`strict-risk-change`.

## Acceptance Criteria

- Phase 7 targeted stale detection and recovery tests pass and their logs are stored under `verification-logs/`.
- Phase 7.1 targeted claim-locking and real process-kill crash smoke tests pass and their logs are stored under `verification-logs/`.
- Phase 8 targeted claim token, lease, artifact guard, and live multi-worker smoke tests pass and their logs are stored under `verification-logs/`.
- Full local unit suite passes.
- Every source-controlled run validates.
- `git diff --check` passes.
- `docs/INDEX.md` and `harness/memory/progress.md` agree that Phase 9 is a Strict gated future phase and implementation remains blocked until entry gates are satisfied.
- Review evidence or a scoped review waiver is indexed.
- The run reaches `completed`, or the run stops before completion with the exact unmet gate recorded.

## Out Of Scope

Cross-run queues, cloud queues, cloud credentials, provider selection, remote resource cleanup, and destructive history changes are out of scope.
