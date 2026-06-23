# Phase 9 Entry Gate Local Scheduler Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce source-controlled closure evidence that local watch, stale recovery, claim locking, and Phase 8 multi-worker scheduler semantics are stable enough to satisfy the local prerequisites for the Phase 9 Cross-Run / Cloud Queue design.

**Architecture:** Do not implement cross-run queues or cloud queues. Create one Strict closure run that records targeted Phase 7, Phase 7.1, and Phase 8 verification logs, synchronizes durable project memory, and records any remaining CI or review decision explicitly.

**Tech Stack:** Python 3.12 stdlib, `unittest`, existing `harness.cli`, JSON Schema 2020-12, PowerShell on Windows, current source-controlled Harness run lifecycle.

---

## File Structure

- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/`
  - Strict run record proving local scheduler prerequisite stability before any Phase 9 implementation.
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/`
  - Source-controlled targeted command logs for Phase 7, Phase 7.1, Phase 8, full suite, run validation, and whitespace checks.
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification.md`
  - Human-readable verification summary that links each Phase 9 entry gate to fresh evidence.
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/review-waiver.md`
  - Scoped waiver only if this execution changes documentation and run records but no implementation code.
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/handoff.md`
  - Closure report with changed files, verified items, unverified items, residual risks, and memory update metadata.
- Modify: `harness/memory/progress.md`
  - Bring durable memory forward from Phase 6 to Phase 8 plus Phase 9 gated design status.
- Modify: `docs/INDEX.md`
  - Add this implementation plan and, after execution, the closure run reference.
- Do not modify: `harness/cli.py`, schemas, tests, adapters, CI workflow, credentials, cloud resources, or cross-run queue code.

## Scope Boundary

This plan closes local scheduler evidence gaps before Phase 9. It does not start Phase 9A or Phase 9B implementation.

Phase 9A Cross-Run Local Queue remains blocked until this closure run reaches `completed` or records the exact unmet gate. Phase 9B Cloud Queue Adapter remains blocked until Phase 9A is proven and the user approves a provider, account boundary, credential source, cost boundary, and cleanup plan.

## Task 1: Baseline Audit

**Files:**
- Read: `docs/superpowers/specs/2026-06-23-phase-9-cross-run-cloud-queue-design.md`
- Read: `harness/core/run-lifecycle-sop.md`
- Read: `harness/memory/progress.md`
- Read: `docs/INDEX.md`

- [ ] **Step 1: Confirm the working tree starts clean**

Run:

```powershell
git status --short
```

Expected: no output. If there is output, inspect it and stop unless the diff is this plan being executed.

- [ ] **Step 2: Capture the baseline commit**

Run:

```powershell
git log -1 --oneline
git rev-parse HEAD
```

Expected: the first command prints the current closure baseline commit and the second command prints its full SHA. Record both in the execution notes for the closure run.

- [ ] **Step 3: Confirm no Phase 9 implementation exists**

Run:

```powershell
rg -n "cross-run queue|cloud queue|queue adapter|Phase 9A|Phase 9B" harness tests docs --glob "!docs/superpowers/specs/2026-06-23-phase-9-cross-run-cloud-queue-design.md" --glob "!docs/superpowers/plans/2026-06-23-phase-9-entry-gate-local-scheduler-closure-implementation.md"
```

Expected: no implementation code references. Documentation references are acceptable only if they describe Phase 9 as gated future work.

## Task 2: Create The Strict Closure Run

**Files:**
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/state.json`
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/task.md`
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/triage.md`
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/plan.md`

- [ ] **Step 1: Initialize the run**

Run:

```powershell
$RUN_ID = "2026-06-23-phase-9-entry-gate-local-scheduler-closure"
$RUN_DIR = "harness/runs/$RUN_ID"
$BASE_COMMIT = (git rev-parse HEAD).Trim()
python -m harness.cli init-run $RUN_DIR --run-id $RUN_ID --track Strict --workflow strict-risk-change --base-commit $BASE_COMMIT
```

Expected: `state.json`, `task.md`, `triage.md`, and `plan.md` exist under `$RUN_DIR`.

- [ ] **Step 2: Replace `task.md` with the closure task**

Use `apply_patch` to replace `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/task.md` with:

```markdown
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
```

- [ ] **Step 3: Replace `triage.md` with the Strict triage**

Use `apply_patch` to replace `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/triage.md` with:

```markdown
---
run_id: 2026-06-23-phase-9-entry-gate-local-scheduler-closure
schema_version: 0.1.0
track: Strict
workflow: strict-risk-change
review_required: true
strict_triggers:
  - "Phase 9 is a future queue boundary involving permissions, authentication, ownership, recovery, cleanup, and audit."
  - "This closure verifies recovery semantics that must not be weakened before cross-run or cloud scheduling."
risk_reasons:
  - "Incorrectly marking Phase 9 entry gates as satisfied could allow unsafe cross-run or cloud queue work to start."
  - "Stale recovery and claim-lock evidence affects scheduler safety assumptions."
  - "Run evidence must remain append-only and Codex-owned."
verification_required:
  - "Run targeted Phase 7 stale detection and recovery tests."
  - "Run targeted Phase 7.1 claim-locking and real crash-smoke tests."
  - "Run targeted Phase 8 claim token, lease, artifact guard, and live multi-worker tests."
  - "Run the full local unit suite."
  - "Validate every source-controlled run."
  - "Run git diff --check."
  - "Record remote CI status or explicit residual-risk decision."
---

# Triage

## Track Decision

Strict. This run does not implement Phase 9, but it gates a future Strict phase that will involve queue ownership, permissions, authentication, recovery, cleanup, and audit. Treating the closure as Strict prevents accidental downgrade of unresolved scheduler safety gaps.

## Workflow

`strict-risk-change`.

## Risk Reasons

- Phase 9 implementation must not start on stale or inconsistent local scheduler evidence.
- Recovery semantics must remain explicit and audited.
- Claim locks, claim tokens, leases, and artifact overwrite guards are safety boundaries for any future cross-run or cloud queue.
- Documentation and memory must not claim a gate is satisfied without fresh verification evidence.

## Review Requirement

Review handling is required before completion. A scoped review waiver is acceptable only if the execution changes run records and documentation without touching runtime code, schemas, adapters, tests, CI, permissions, credentials, or cloud resources. If implementation files change, stop and request independent review.

## Verification Required

- Targeted Phase 7 stale detection and recovery tests.
- Targeted Phase 7.1 claim-locking and crash-smoke tests.
- Targeted Phase 8 claim token, lease, artifact guard, and live multi-worker tests.
- Full unit suite.
- All source-controlled run validation.
- Whitespace check with `git diff --check`.
- Remote CI state or explicit residual-risk decision.

## Out Of Scope

No cross-run queue, cloud queue, provider selection, credential use, destructive cleanup, or historical run rewrite.
```

- [ ] **Step 4: Replace `plan.md` with the run-local execution plan**

Use `apply_patch` to replace `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/plan.md` with:

```markdown
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
```

- [ ] **Step 5: Advance the run to in-progress**

Run:

```powershell
python -m harness.cli advance harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure triaged
python -m harness.cli advance harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure planned
python -m harness.cli advance harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure in_progress
```

Expected: each command exits 0 and the run state becomes `in_progress`.

- [ ] **Step 6: Commit the run skeleton**

Run:

```powershell
git add harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure
git commit -m "docs: open Phase 9 entry gate closure run"
```

Expected: a commit containing only the new closure run skeleton.

## Task 3: Capture Targeted Phase 7, Phase 7.1, And Phase 8 Evidence

**Files:**
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/phase7-stale-recovery.log`
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/phase7-1-claim-crash.log`
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/phase8-multi-worker.log`

- [ ] **Step 1: Create the verification log directory**

Run:

```powershell
New-Item -ItemType Directory -Force harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs
```

Expected: the directory exists.

- [ ] **Step 2: Run Phase 7 stale detection and recovery tests**

Run:

```powershell
python -m unittest `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_detects_old_running_job_without_fresh_matching_heartbeat_as_stale `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_recover_stale_running_job_requires_confirmation_and_requeues_with_audit_artifact `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_recover_stale_running_job_can_mark_failed_with_audit_artifact `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_requeue_recovery_requires_conflicting_artifacts_to_be_corrected_first `
  -v *> harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/phase7-stale-recovery.log
if ($LASTEXITCODE -ne 0) {
  Get-Content harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/phase7-stale-recovery.log
  exit $LASTEXITCODE
}
```

Expected: the log contains `Ran 4 tests` and `OK`.

- [ ] **Step 3: Run Phase 7.1 claim-locking and crash-smoke tests**

Run:

```powershell
python -m unittest `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_acquire_claim_lock_retries_transient_windows_access_denied `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_try_claim_job_creates_owner_and_blocks_second_worker `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_run_once_two_workers_execute_same_queued_job_at_most_once `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_real_scheduler_process_kill_leaves_claimed_running_job_detectable_as_stale `
  -v *> harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/phase7-1-claim-crash.log
if ($LASTEXITCODE -ne 0) {
  Get-Content harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/phase7-1-claim-crash.log
  exit $LASTEXITCODE
}
```

Expected: the log contains `Ran 4 tests` and `OK`.

- [ ] **Step 4: Run Phase 8 claim token, lease, artifact guard, and live multi-worker tests**

Run:

```powershell
python -m unittest `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_concurrent_claims_same_worker_id_get_one_token `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_job_heartbeat_refreshes_claim_lease `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_execute_claimed_job_records_claim_token_on_running_job `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_claimed_execution_does_not_overwrite_raw_log_created_during_run `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_claimed_execution_does_not_overwrite_output_created_during_run `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_live_multi_worker_watch_processes_execute_jobs_once `
  -v *> harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/phase8-multi-worker.log
if ($LASTEXITCODE -ne 0) {
  Get-Content harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/phase8-multi-worker.log
  exit $LASTEXITCODE
}
```

Expected: the log contains `Ran 6 tests` and `OK`.

- [ ] **Step 5: Commit targeted evidence logs**

Run:

```powershell
git add harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs
git commit -m "test: record Phase 9 entry gate targeted evidence"
```

Expected: a commit containing the three targeted verification logs.

## Task 4: Run Full Local Verification

**Files:**
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/full-suite.log`
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/run-validation.log`
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/diff-check.log`

- [ ] **Step 1: Run the full unit suite**

Run:

```powershell
python -m unittest discover -s tests -v *> harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/full-suite.log
if ($LASTEXITCODE -ne 0) {
  Get-Content harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/full-suite.log
  exit $LASTEXITCODE
}
```

Expected: the log ends with `OK` and records the current test count.

- [ ] **Step 2: Validate every source-controlled run**

Run:

```powershell
$validationFailed = $false
Get-ChildItem -Directory harness/runs | ForEach-Object {
  python -m harness.cli validate $_.FullName
  if ($LASTEXITCODE -ne 0) {
    $script:validationFailed = $true
  }
} *> harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/run-validation.log
if ($validationFailed) {
  Get-Content harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/run-validation.log
  exit 1
}
```

Expected: every line begins with `valid:`.

- [ ] **Step 3: Run whitespace validation**

Run:

```powershell
git diff --check *> harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/diff-check.log
if ($LASTEXITCODE -ne 0) {
  Get-Content harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification-logs/diff-check.log
  exit $LASTEXITCODE
}
```

Expected: exit code 0. Line-ending warnings from Git are acceptable only if there are no whitespace error lines.

- [ ] **Step 4: Advance to implemented**

Run:

```powershell
python -m harness.cli advance harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure implemented
```

Expected: state becomes `implemented`.

- [ ] **Step 5: Commit full verification logs**

Run:

```powershell
git add harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure
git commit -m "test: record Phase 9 entry gate full verification"
```

Expected: a commit containing full-suite, run-validation, diff-check logs, and the state transition to `implemented`.

## Task 5: Synchronize Durable Docs And Memory

**Files:**
- Modify: `docs/INDEX.md`
- Modify: `harness/memory/progress.md`

- [ ] **Step 1: Update `docs/INDEX.md` current status**

Use `apply_patch` to add a current-status bullet after the Phase 8 bullet:

```markdown
- Phase 9 Cross-Run / Cloud Queue is defined as a Strict gated future phase in `docs/superpowers/specs/2026-06-23-phase-9-cross-run-cloud-queue-design.md`; implementation must not begin until local watch, stale recovery, claim locking, Phase 8 multi-worker semantics, memory/docs synchronization, source-controlled run validation, full local tests, and remote CI status or accepted residual risk are recorded.
```

Also add this plan under `## Plans`:

```markdown
- `docs/superpowers/plans/2026-06-23-phase-9-entry-gate-local-scheduler-closure-implementation.md` - Implementation plan for closing local scheduler evidence gates before Phase 9 queue work.
```

- [ ] **Step 2: Update `harness/memory/progress.md`**

Use `apply_patch` to add a durable memory section after the Phase 6 paragraph:

```markdown
Phase 7 stale-running detection and explicit recovery is implemented in source. Scheduler-claimed jobs record worker identity and timestamps; stale detection classifies active, recent, stale, and invalid running jobs using scheduler heartbeat and job timestamps; recovery requires explicit confirmation, writes `job-recovery` audit artifacts, and preserves partial artifacts unless the operator confirms correction. Phase 7.1 local claim locking adds `claim.lock/owner.json` and a real scheduler process-kill crash smoke.

Phase 8 multi-worker concurrency hardening is implemented in source. It adds claim tokens, claim lease diagnostics, claim-aware job writes, guarded raw/output artifact publishing, recovery safeguards for fresh matching leases, and a live multi-worker scheduler smoke for local filesystem workers.

Phase 9 Cross-Run / Cloud Queue is defined as a Strict gated future phase. It must start with a local cross-run queue slice only after the local scheduler entry gates are recorded; cloud queue adapters remain later work requiring explicit provider, credential, cost, cleanup, and audit approval.
```

Replace the old `## Next Step` content with:

```markdown
## Next Step

Close the Phase 9 entry gates with `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure` before writing any Phase 9A implementation plan. If remote CI is not run for the closure baseline, record that as residual risk with explicit user decision before treating the Phase 9 implementation gate as satisfied.
```

- [ ] **Step 3: Commit docs and memory synchronization**

Run:

```powershell
git add docs/INDEX.md harness/memory/progress.md docs/superpowers/plans/2026-06-23-phase-9-entry-gate-local-scheduler-closure-implementation.md
git commit -m "docs: plan Phase 9 entry gate closure"
```

Expected: a commit containing the plan, documentation index update, and memory synchronization.

## Task 6: Write And Index Verification Evidence

**Files:**
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification.md`

- [ ] **Step 1: Write `verification.md`**

Use `apply_patch` to create `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/verification.md` with the observed command results. Use this structure and replace command result lines with exact counts from the logs:

```markdown
# Verification

## Targeted Phase 7

- Command log: `verification-logs/phase7-stale-recovery.log`
- Result: passed
- Evidence: stale-running detection, explicit requeue recovery, explicit fail recovery, and artifact-conflict recovery rejection were exercised.

## Targeted Phase 7.1

- Command log: `verification-logs/phase7-1-claim-crash.log`
- Result: passed
- Evidence: transient claim-lock retry, claim owner creation, concurrent single-job execution guard, and real scheduler process-kill stale detection were exercised.

## Targeted Phase 8

- Command log: `verification-logs/phase8-multi-worker.log`
- Result: passed
- Evidence: same-worker claim token contention, lease refresh, running job claim token recording, raw/output overwrite guards, and live multi-worker watch execution were exercised.

## Full Suite

- Command log: `verification-logs/full-suite.log`
- Result: passed

## Source-Controlled Run Validation

- Command log: `verification-logs/run-validation.log`
- Result: passed

## Whitespace

- Command log: `verification-logs/diff-check.log`
- Result: passed

## Remote CI

- Result: not run for this closure baseline unless a later CI status artifact is added.
- Impact: Phase 9 implementation remains blocked until remote CI is known or the missing run is accepted as residual risk by the user.

## Not Verified

- Cross-run queue execution.
- Cloud queue execution.
- Cloud provider permissions, authentication, credentials, cost controls, and cleanup.
- Remote CI for this closure baseline if no CI status artifact is added.
```

- [ ] **Step 2: Index design, plan, logs, and verification summary**

Run:

```powershell
$RUN_DIR = "harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure"
python -m harness.cli index-evidence $RUN_DIR design-spec docs/superpowers/specs/2026-06-23-phase-9-cross-run-cloud-queue-design.md --description "Approved Phase 9 Strict gated design."
python -m harness.cli index-evidence $RUN_DIR implementation-plan docs/superpowers/plans/2026-06-23-phase-9-entry-gate-local-scheduler-closure-implementation.md --description "Implementation plan for local scheduler entry-gate closure."
python -m harness.cli index-evidence $RUN_DIR verification verification-logs/phase7-stale-recovery.log --description "Targeted Phase 7 stale detection and recovery verification log."
python -m harness.cli index-evidence $RUN_DIR verification verification-logs/phase7-1-claim-crash.log --description "Targeted Phase 7.1 claim-lock and crash-smoke verification log."
python -m harness.cli index-evidence $RUN_DIR verification verification-logs/phase8-multi-worker.log --description "Targeted Phase 8 multi-worker verification log."
python -m harness.cli index-evidence $RUN_DIR verification verification-logs/full-suite.log --description "Full local unit suite verification log."
python -m harness.cli index-evidence $RUN_DIR verification verification-logs/run-validation.log --description "All source-controlled runs validation log."
python -m harness.cli index-evidence $RUN_DIR verification verification-logs/diff-check.log --description "Whitespace validation log."
python -m harness.cli index-evidence $RUN_DIR verification verification.md --description "Verification summary for Phase 9 entry-gate local scheduler closure."
```

Expected: each command exits 0 and `state.json.evidence[]` includes the indexed paths.

- [ ] **Step 3: Commit indexed verification evidence**

Run:

```powershell
git add harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure
git commit -m "docs: index Phase 9 entry gate verification"
```

Expected: a commit containing `verification.md` and updated `state.json`.

## Task 7: Review Handling And Handoff

**Files:**
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/review-waiver.md`
- Create: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/handoff.md`

- [ ] **Step 1: Confirm whether runtime code changed**

Run:

```powershell
git diff --name-only HEAD~4..HEAD
```

Expected: changed paths are limited to docs, memory, and the closure run. If `harness/cli.py`, `harness/schemas/`, `tests/`, `.github/workflows/`, adapters, or credential-related files appear, stop and request independent review instead of writing a waiver.

- [ ] **Step 2: Write a scoped review waiver if no runtime code changed**

Use `apply_patch` to create `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/review-waiver.md`:

```markdown
# Review Waiver

## Scope

This waiver applies only to documentation, durable memory, and the source-controlled closure run artifacts created for `2026-06-23-phase-9-entry-gate-local-scheduler-closure`.

## Reason

No runtime code, schemas, adapters, tests, CI workflow, credentials, permissions, cloud resources, or queue implementation files changed during this closure. The work records verification evidence for already-implemented local scheduler semantics and keeps Phase 9 implementation blocked.

## Not Waived

- Any future Phase 9A Cross-Run Local Queue implementation.
- Any future Phase 9B Cloud Queue Adapter implementation.
- Any runtime change to `harness/cli.py`, schemas, adapters, tests, CI, permissions, credentials, cloud resources, or queue cleanup behavior.

## Residual Risk

Remote CI for this closure baseline is not proven by this waiver. Phase 9 implementation remains blocked until remote CI is known or the user explicitly accepts missing remote CI as residual risk.
```

- [ ] **Step 3: Write `handoff.md`**

Use `apply_patch` to create `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/handoff.md`:

```markdown
---
run_id: 2026-06-23-phase-9-entry-gate-local-scheduler-closure
schema_version: 0.1.0
changed:
  - "Created a Strict source-controlled closure run for Phase 9 local scheduler entry gates."
  - "Recorded targeted Phase 7 stale detection and recovery verification logs."
  - "Recorded targeted Phase 7.1 claim-locking and crash-smoke verification logs."
  - "Recorded targeted Phase 8 claim token, lease, artifact guard, and live multi-worker verification logs."
  - "Recorded full local suite, source-controlled run validation, and whitespace verification logs."
  - "Updated docs/INDEX.md and harness/memory/progress.md with Phase 8 baseline and Phase 9 gated status."
verified:
  - "Phase 7 targeted tests passed."
  - "Phase 7.1 targeted tests passed."
  - "Phase 8 targeted tests passed."
  - "Full local unit suite passed."
  - "All source-controlled runs validated."
  - "git diff --check passed."
not_verified:
  - "Phase 9A cross-run queue execution."
  - "Phase 9B cloud queue execution."
  - "Cloud provider permissions, authentication, credentials, cost controls, and cleanup."
  - "Remote CI for this closure baseline unless a CI status artifact is added."
residual_risks:
  - "Remote CI may still need to run or be explicitly accepted as residual risk before Phase 9 implementation starts."
  - "This run proves local scheduler semantics only; it does not prove cross-run or cloud queue behavior."
next_step: "Do not write a Phase 9A implementation plan until the remaining Phase 9 entry gates are explicitly satisfied or the user accepts documented residual risk."
memory_update: updated
memory_files:
  - "harness/memory/progress.md"
---

# Handoff

## What Changed

Created a Strict closure run that records local scheduler evidence required before Phase 9 Cross-Run / Cloud Queue implementation can be considered.

## Evidence

- `verification-logs/phase7-stale-recovery.log`
- `verification-logs/phase7-1-claim-crash.log`
- `verification-logs/phase8-multi-worker.log`
- `verification-logs/full-suite.log`
- `verification-logs/run-validation.log`
- `verification-logs/diff-check.log`
- `verification.md`
- `review-waiver.md`

## State

The run may reach `completed` only after verification, review handling, and handoff evidence are indexed and validation passes.

## Risks

This closure proves local scheduler prerequisites only. Cross-run queue execution, cloud queue execution, provider permissions, credentials, costs, and cleanup remain unverified and out of scope.

## Next Step

Keep Phase 9 implementation blocked until all entry gates in the Phase 9 design are satisfied.
```

- [ ] **Step 4: Index review waiver and handoff**

Run:

```powershell
$RUN_DIR = "harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure"
python -m harness.cli index-evidence $RUN_DIR review-waiver review-waiver.md --description "Scoped review waiver for documentation and run-evidence-only closure."
python -m harness.cli index-evidence $RUN_DIR handoff handoff.md --description "Completion handoff for Phase 9 entry-gate local scheduler closure."
```

Expected: both commands exit 0.

- [ ] **Step 5: Complete the run**

Run:

```powershell
$RUN_DIR = "harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure"
python -m harness.cli advance $RUN_DIR verified
python -m harness.cli advance $RUN_DIR reviewed
python -m harness.cli advance $RUN_DIR completed
python -m harness.cli validate $RUN_DIR
```

Expected: final validation prints `valid: harness\runs\2026-06-23-phase-9-entry-gate-local-scheduler-closure`.

- [ ] **Step 6: Commit closure handoff**

Run:

```powershell
git add harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure
git commit -m "docs: complete Phase 9 entry gate closure run"
```

Expected: a commit containing review waiver, handoff, final `state.json`, and completion evidence.

## Task 8: Final Verification Before Phase 9 Planning

**Files:**
- Read: `docs/superpowers/specs/2026-06-23-phase-9-cross-run-cloud-queue-design.md`
- Read: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/state.json`
- Read: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure/handoff.md`

- [ ] **Step 1: Re-run final validation commands**

Run:

```powershell
python -m unittest discover -s tests -v
Get-ChildItem -Directory harness\runs | ForEach-Object { python -m harness.cli validate $_.FullName }
git diff --check
```

Expected: unit tests pass, every source-controlled run validates, and whitespace check exits 0.

- [ ] **Step 2: Check Phase 9 entry gates against the spec**

Verify manually against `docs/superpowers/specs/2026-06-23-phase-9-cross-run-cloud-queue-design.md`:

```text
Gate 1 Phase 6 watch evidence: satisfied by harness/runs/2026-06-22-phase-6-scheduler-watch-mode.
Gate 2 Phase 7 stale recovery evidence: satisfied by the closure run targeted Phase 7 log.
Gate 3 Phase 7.1 claim locking crash evidence: satisfied by the closure run targeted Phase 7.1 log.
Gate 4 Phase 8 multi-worker evidence: satisfied by the closure run targeted Phase 8 log.
Gate 5 docs and memory synchronization: satisfied if docs/INDEX.md and harness/memory/progress.md agree.
Gate 6 source-controlled run validation: satisfied if run-validation.log and final command pass.
Gate 7 full local test suite: satisfied if full-suite.log and final command pass.
Gate 8 remote CI status: satisfied only if remote CI is known, or explicitly recorded as accepted residual risk.
```

- [ ] **Step 3: Stop before Phase 9A if remote CI remains unresolved**

If Gate 8 is unresolved, do not write a Phase 9A implementation plan. Ask the user whether to push and wait for CI or record missing remote CI as residual risk.

- [ ] **Step 4: Final commit status check**

Run:

```powershell
git status --short
git log --oneline -5
```

Expected: no uncommitted files remain, and the latest commits show the closure run sequence.

## Residual Risks To Report

- This closure does not implement or verify cross-run queue execution.
- This closure does not implement or verify cloud queue execution.
- Remote CI may remain unresolved until the branch is pushed or the user accepts local-only verification as residual risk.
- The closure run uses targeted test logs as source-controlled evidence; it does not create a separate historical Phase 7 or Phase 8 live run directory.
- Any future provider-backed queue work still requires explicit provider, credential, permission, cost, cleanup, and audit approval.
