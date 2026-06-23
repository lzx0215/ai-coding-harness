# Phase 7.1 Crash Smoke And Claim Locking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic multi-worker claim locking for queued scheduler jobs and a real scheduler process crash smoke that proves stale-running detection after a hard kill.

**Architecture:** Use a prepared temporary directory containing `owner.json`, then atomically rename it to `jobs/<job-id>/claim.lock/` as the local claim primitive. Store diagnostic claim metadata in `claim.lock/owner.json`, but treat the directory as the claim. Scheduler workers must claim before executing and must release only after terminal job completion. Explicit stale recovery may clear stale locks only after recovery preconditions, audit writes, and the `job.json` state change succeed.

**Tech Stack:** Python stdlib (`pathlib`, `json`, `shutil`, `subprocess`, `threading`, `time`, `uuid`), `unittest`, existing harness CLI helpers and schemas.

---

## Contract Decisions

- The prepared-directory rename to `claim.lock` is the atomic claim boundary.
- `owner.json` is present before `claim.lock` becomes visible. Missing or invalid `owner.json` is an explicit lock metadata corruption state, not proof that the lock is free.
- Normal scheduler polling never clears `claim.lock`, including missing-owner locks.
- Recovery lock cleanup happens after audited recovery and successful `job.json` mutation only.
- If recovery is rejected before `job.json` mutation, the lock remains untouched.
- `owner.json` omits `pid`; OS liveness is outside the claim locking contract.
- Crash smoke owns cleanup of scheduler and blocking agent child processes.
- Historical jobs with no `claim.lock` remain valid.

## Tasks

- [x] Update the Phase 7.1 design to incorporate review blockers G1, G2, G3 and testability items T1, T2.

- [x] Add claim owner schema.
  - Create `harness/schemas/claim-owner.schema.json`.
  - Required fields: `schema_version`, `worker_id`, `job_id`, `run_id`, `claimed_at`, `lock_path`.
  - Reject `pid` by omission from the documented schema.
  - Do not add claim owner files to evidence indexing.

- [x] Write red tests for claim helper behavior.
  - `test_try_claim_job_creates_owner_and_blocks_second_worker`
  - `test_try_claim_job_releases_lock_when_reload_finds_non_queued_job`
  - `test_missing_claim_owner_is_reported_without_autoclearing_lock`
  - Expected initial result: tests fail because claim helpers and owner reporting do not exist yet.

- [x] Implement claim helper layer in `harness/cli.py`.
  - Add a small claim result dataclass.
  - Add path helpers for `claim.lock` and `owner.json`.
  - `try_claim_job` writes `owner.json` in a unique temporary directory, then renames that prepared directory to `claim.lock`.
  - If the same process fails before the rename, clean the temporary directory and re-raise.
  - If the reloaded job is not `queued`, release the newly-created lock and return `None`.
  - `release_job_claim` removes only a verified `claim.lock` path below a job directory.

- [x] Integrate claim locking into scheduler execution.
  - `scheduler_run_once` claims before executing each queued generic-agent job.
  - `scheduler_run_watch` uses the same claim path.
  - Direct single-job execution remains available for tests and explicit CLI paths, but scheduler workers do not use unlocked read-then-write execution.
  - Claimed jobs release their lock after terminal completion.

- [x] Write red tests for recovery ordering.
  - `test_requeue_recovery_clears_stale_claim_lock_after_success`
  - `test_requeue_recovery_keeps_claim_lock_when_artifact_conflict_rejects_recovery`
  - Expected initial result: the success case fails before lock cleanup exists; the conflict case protects the G2 invariant.

- [x] Implement stale lock cleanup in recovery.
  - Extend stale detection output with claim lock status: absent, present, missing-owner, invalid-owner.
  - Recovery clears stale lock only after recovery artifact write, scheduler event append, and `job.json` write succeed.
  - If an artifact conflict rejects requeue, do not touch `claim.lock`.
  - If post-success lock cleanup fails, surface a cleanup error with the run/job context.

- [x] Write deterministic multi-worker race tests.
  - Reuse a release-file blocking generic-agent fixture.
  - Start two local worker paths against one queued job.
  - Assert at most one command reaches the blocking agent.
  - Assert the losing worker does not create agent output or mark execution.

- [x] Implement and verify multi-worker scheduler behavior.
  - Ensure both `--once` and `--watch` paths share the same claim helper.
  - Ensure a worker that fails to claim skips the job for that polling iteration.
  - Ensure lock release happens on terminal success and terminal failure.

- [x] Write real crash smoke.
  - Start `python -m harness.cli run-scheduler <run-dir> --watch --poll-interval-seconds 0.1 --worker-id crash-smoke-worker`.
  - Use a blocking agent that waits on a release file.
  - Poll until job is `running`, job `worker_id` matches, `claim.lock/owner.json` exists, and scheduler heartbeat is `running-job`.
  - Kill the scheduler process tree with the existing bounded helper; on Windows this must terminate children with `taskkill /T /F`.
  - Force-clean any surviving blocking agent child before the test exits.
  - Assert stale detection reports the job after a short heartbeat timeout.

- [x] Update docs and index.
  - Add the implementation plan and claim-owner schema to `docs/INDEX.md` where appropriate.
  - Ensure docs say `claim.lock` is internal scheduler state, not evidence.

- [x] Verify.
  - Run targeted tests:
    ```powershell
    python -m unittest tests.test_generic_agent_adapter tests.test_harness_cli tests.test_async_job_artifacts -v
    ```
  - Run the full suite:
    ```powershell
    python -m unittest discover -s tests -v
    ```
  - Validate source-controlled runs:
    ```powershell
    Get-ChildItem -Directory harness\runs | ForEach-Object { python -m harness.cli validate $_.FullName }
    ```
  - Check whitespace:
    ```powershell
    git diff --check
    ```

## Risks

- Windows process-tree termination can leave child processes if the child is not in the scheduler tree. The smoke must detect and clean that explicitly.
- Lock cleanup after successful recovery is not transactionally coupled to `job.json`; a cleanup failure must be visible to the operator.
- Directory locking is local-filesystem coordination, not a distributed lock.
- Timing-sensitive tests must use release files and bounded polling, not sleeps alone.
