# Phase 7.1 Crash Smoke And Claim Locking Design

## Summary

Phase 7.1 extends stale-running recovery with two missing pieces: a real
end-to-end scheduler crash smoke and multi-worker-safe job claiming. The
scheduler may run in multiple local worker processes, but a queued job must be
claimed by at most one worker. A hard-killed scheduler can still leave a job in
`running`; stale diagnosis and recovery remain explicit operator actions.

## Goals

- Prove a real scheduler process can be killed while an agent job is running.
- Verify the killed worker leaves `job.json.status = running` and a stale
  heartbeat instead of silently marking completion.
- Verify `detect-stale-jobs` classifies that killed job as stale after timeout.
- Add per-job claim locking so concurrent workers cannot double-claim the same
  queued job.
- Keep recovery explicit: stale claim locks may be cleared only by
  `recover-stale-job --confirm`, never by normal scheduler polling.

## Non-Goals

- No cloud queue, distributed lock service, database, or cross-host locking.
- No automatic stale recovery during `run-scheduler --watch` or `--once`.
- No automatic killing of agent subprocesses outside the crash-smoke test.
- No attempt to prove behavior under power loss or filesystem corruption.
- No global scheduler singleton lock; multiple local workers may run.
- `claim.lock` and `owner.json` are internal scheduler control files, not
  evidence artifacts, and must not be indexed as evidence.
- Claim ownership does not provide cooperative mid-execution cancellation. If a
  live worker's lock is deleted by an external process, the already-started
  agent command is not interrupted by claim locking.

## Claim Locking

Each job gets an optional lock directory:

```text
jobs/<job-id>/claim.lock/
  owner.json
```

Workers claim a job by writing `owner.json` inside a unique temporary directory
under the job directory, then atomically renaming that prepared directory to
`claim.lock`. The final rename is the mutual-exclusion boundary: if
`claim.lock` already exists, the worker loses the claim and does not execute the
job. This avoids the unsafe `mkdir claim.lock` then `write owner.json` window.

After the prepared directory is renamed to `claim.lock`, the worker reloads
`job.json` and proceeds only if the job is still `queued`. If the job is no
longer queued, the worker removes the lock it just acquired and treats the job
as skipped. If a worker is killed before the final rename, only an ignored
temporary directory may remain; no valid claim lock exists.

`owner.json` is durable lock metadata shipped atomically with the visible
`claim.lock` directory. Missing or invalid `owner.json` therefore represents
lock metadata corruption or manual interference, not a normal claim race.
Normal scheduler polling must treat that lock as held and must not clear it.
`detect-stale-jobs` reports the owner status as `missing-owner` or
`invalid-owner`. `recover-stale-job --confirm` may clear such a lock only after
the associated job is classified as stale or invalid for explicit recovery.

`owner.json` records:

```json
{
  "schema_version": 1,
  "worker_id": "scheduler-abc123",
  "job_id": "review-001",
  "run_id": "2026-06-22-example",
  "claimed_at": "2026-06-22T12:00:00Z",
  "lock_path": "jobs/review-001/claim.lock"
}
```

`owner.json` has a dedicated `claim-owner.schema.json`. Required fields are
`schema_version`, `worker_id`, `job_id`, `run_id`, `claimed_at`, and
`lock_path`. `pid` is intentionally omitted. If it is ever added later, it must
be diagnostic only and must not be used as an OS-level liveness probe.

Missing or invalid `owner.json` is not evidence corruption and does not make
historical jobs invalid. It is lock metadata corruption for the current job only.
Validation must continue to accept jobs and historical runs where `claim.lock`
is absent.

A worker that cannot create `claim.lock` does not execute the job. It may record
the job as skipped for that polling iteration.

When a claimed job reaches a terminal status, the owning worker removes its
`claim.lock`. If lock cleanup fails, the terminal job remains authoritative and
aggregation still consumes the terminal `job.json`; the stale lock is a
diagnostic warning, not completion evidence.

## Crash And Stale Lock Semantics

If a scheduler process is hard-killed while running a job:

- the job may remain `running`
- `claim.lock` may remain on disk
- scheduler `heartbeat.json` may remain at `running-job`
- the agent subprocess may be terminated by the test harness

Normal scheduler polling must not steal this job or clear the lock. Codex uses
`detect-stale-jobs` to classify the job. If stale, the operator may run
`recover-stale-job --confirm` with either `--action requeue` or `--action fail`.

Recovery must write the `job-recovery` artifact and scheduler event before
changing `job.json`. Recovery lock cleanup has strict ordering:

1. Load and classify the running job as stale.
2. Validate explicit operator confirmation and requested action.
3. For `requeue`, reject if partial `raw.log` or `output.json` exists.
4. Write the `job-recovery` artifact.
5. Append the scheduler recovery event.
6. Write the new `job.json` state.
7. Remove the stale `claim.lock` only after the `job.json` state change
   succeeds.

If any step before the `job.json` state change fails, the recovery is rejected,
the job stays in its previous state, and `claim.lock` must remain untouched. This
includes the artifact-conflict rejection for `requeue`. Removing a lock before a
successful recovery state change is forbidden because it can create an unlocked
stale `running` job that another worker may double-execute.

If lock cleanup fails after a successful `job.json` state change, the recovery
must report that cleanup failure. The changed `job.json` and appended recovery
evidence remain the source of truth; the stale lock is then an operator-visible
cleanup problem.

## Real Kill Smoke

The smoke test creates a temporary run, queues one blocking generic-agent job,
and starts a real scheduler child process:

```powershell
python -m harness.cli run-scheduler <run-dir> --watch `
  --poll-interval-seconds 0.1 `
  --worker-id crash-smoke-worker
```

The agent script waits on a release file. The test polls until:

- `jobs/<job-id>/job.json` is `running`
- `worker_id` is `crash-smoke-worker`
- `jobs/<job-id>/claim.lock/owner.json` exists
- `jobs/scheduler/heartbeat.json` reports `running-job`

Then the test terminates the scheduler process tree using the same bounded
process-tree helper used by the harness CLI. On Windows the helper must use
`taskkill /T /F` for the scheduler process tree; on POSIX it may terminate the
process group. The smoke test is responsible for cleaning up any blocking agent
child process it created. If an agent child survives scheduler termination, the
test must force-clean that child before returning and fail with a clear cleanup
error instead of leaking a process.

After the heartbeat timeout window, `detect-stale-jobs` must report the job in
`stale_jobs`.

The smoke must use bounded waits and deterministic temporary files. It should be
part of the normal unit suite only if it is stable on Windows and CI. If it is
too timing-sensitive, keep it behind an explicit environment gate and document
that gate in verification.

## CLI And API Changes

Internal helpers:

- `try_claim_job(run_dir, job_id, worker_id, root) -> claim | None`
- `release_job_claim(claim) -> None`
- `execute_claimed_generic_agent_job(...)`
- `read_claim_owner(lock_dir) -> owner | missing | invalid`

Scheduler paths:

- `scheduler_run_once` and `scheduler_run_watch` both claim before executing.
- `execute_generic_agent_job` remains available for direct single-job execution
  but scheduler code no longer relies on an unlocked read-then-write claim.
- `recover_stale_running_job` clears a stale lock only after stale
  classification, explicit confirmation, artifact-conflict checks, audited
  recovery writes, and successful `job.json` state change.

No new Harness lifecycle state is introduced.

## Tests

- Two concurrent workers racing the same queued job execute it at most once.
  This must reuse the release-file blocking agent fixture so both workers race a
  still-queued job deterministically instead of relying on timing.
- A worker that loses `claim.lock` does not run the agent command.
- `run-scheduler --once` uses claim locking.
- `run-scheduler --watch` uses claim locking.
- A killed real scheduler process leaves a running job detectable as stale.
- Stale recovery requeue clears stale `claim.lock` and leaves corrected artifacts
  untouched.
- Stale recovery requeue that is rejected for partial `raw.log` or `output.json`
  leaves `claim.lock` untouched.
- Active or recent jobs cannot have locks cleared by recovery.
- Existing aggregation and evidence validation continue to accept historical
  jobs without lock metadata.
- Missing or invalid `owner.json` is reported by stale detection and never
  auto-cleared by scheduler polling.

## Acceptance Criteria

- No test can cause the same queued job command to execute twice under two local
  workers.
- Concurrent workers observe at most one successful `claim.lock` acquisition.
- Scheduler crash smoke proves stale-running detection after real process kill.
- Scheduler polling never clears stale locks or recovers stale jobs
  automatically.
- Recovery remains append-audited through `job-recovery` and scheduler events.
- Full unit tests, source-controlled run validation, and `git diff --check`
  pass.

## Residual Risks

- Local filesystem directory creation is the locking primitive; this is not a
  distributed lock for network filesystems.
- A hard kill can leave lock directories behind until explicit recovery.
- Process-tree termination behavior differs by platform; the smoke must account
  for Windows behavior and avoid unbounded waits.
- Multi-worker fairness is not guaranteed; the contract is at-most-once claim,
  not balanced scheduling.
