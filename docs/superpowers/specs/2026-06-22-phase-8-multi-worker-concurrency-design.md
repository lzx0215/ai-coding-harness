# Phase 8 Multi-Worker Concurrency Design

## Summary

Phase 8 hardens the scheduler for multiple local worker processes running
against the same run directory. Phase 7.1 introduced local `claim.lock`
ownership, so Phase 8 does not replace that primitive. It extends the claim into
a full execution contract: claim lease metadata, claim-aware `job.json`
compare-before-write checks, and artifact write guards that prevent duplicate
execution and `raw.log` / `output.json` overwrite under concurrent workers.

The supported scope is one machine and one local filesystem. Cross-host
distributed scheduling remains out of scope.

## Goals

- Ensure concurrent local scheduler workers execute each queued job at most once.
- Ensure a worker can transition a job from `queued` to `running` only while it
  still owns the matching claim.
- Ensure terminal job writes are accepted only when the running job still
  matches the worker's claim.
- Prevent `raw.log` and `output.json` overwrite under double-start, stale
  worker, or manual artifact interference scenarios.
- Add deterministic concurrent unit tests and a live multi-worker scheduler
  smoke with real scheduler processes.
- Preserve Phase 7 explicit stale recovery: lease expiry is diagnosable, not an
  automatic scheduler takeover.

## Non-Goals

- No cross-machine locking, network filesystem guarantees, cloud queue, or
  database-backed compare-and-swap.
- No automatic recovery, requeue, or fail action during normal scheduler polling.
- No killing of agent subprocesses outside bounded crash/live smoke tests.
- No claim lock evidence indexing. `claim.lock`, lease fields, scheduler
  heartbeat, and scheduler events remain control and diagnostic state.
- No silent historical correction. Recovery must remain explicit and audited.

## Baseline From Phase 7.1

Current claim ownership is:

1. Worker writes `owner.json` inside a unique temp directory.
2. Worker atomically renames that prepared directory to `claim.lock`.
3. Worker reloads `job.json`.
4. Worker executes only if the job is still `queued`.
5. Worker releases `claim.lock` after a terminal job result.

This prevents two workers from claiming the same job at the same instant. It
does not yet fully express lease age, claim identity in `job.json`, or a reusable
compare-before-write helper for every job state transition.

## Claim Owner And Lease Metadata

`claim.lock/owner.json` remains the claim owner record. Phase 8 extends the
schema with stable claim identity and lease timestamps:

```json
{
  "schema_version": 2,
  "run_id": "2026-06-22-example",
  "job_id": "review-001",
  "worker_id": "scheduler-abc123",
  "claim_token": "8f0f2c3e8d1a4e9a8f0f2c3e8d1a4e9a",
  "claimed_at": "2026-06-22T12:00:00Z",
  "lease_started_at": "2026-06-22T12:00:00Z",
  "lease_heartbeat_at": "2026-06-22T12:00:05Z",
  "lease_expires_at": "2026-06-22T12:01:05Z",
  "lock_path": "jobs/review-001/claim.lock"
}
```

`claim_token` is generated per claim attempt and is copied into `job.json` when
the job enters `running`. `worker_id` alone is insufficient because a worker may
restart with the same configured id.

Lease timestamps are diagnostic and recovery inputs. A lease whose
`lease_expires_at` is in the past does not permit ordinary scheduler polling to
steal the lock or execute the job. It only helps stale detection explain why the
claim is stale.

## Job Claim Fields

`job.json` gains optional fields:

```json
{
  "claim_token": "8f0f2c3e8d1a4e9a8f0f2c3e8d1a4e9a",
  "claim_started_at": "2026-06-22T12:00:00Z",
  "claim_updated_at": "2026-06-22T12:00:05Z"
}
```

Rules:

- `queued` jobs normally have `claim_token = null`.
- A worker may set `status = running`, `worker_id`, and claim fields only after
  it owns `claim.lock` and the current job is still `queued`.
- Terminal jobs keep the last claim fields as diagnostic history.
- Requeue recovery clears `worker_id`, `started_at`, `completed_at`,
  `error_reason`, and claim fields.
- Fail recovery keeps claim fields in `previous_job` and records the failed
  recovery action in `new_job`.

## Compare-Before-Write Semantics

Because this harness uses JSON files rather than a database, compare semantics
are implemented by a strict reload-and-verify step immediately before every
claim-sensitive write:

```text
reload owner.json
reload job.json
verify owner.run_id == job.run_id
verify owner.job_id == job.job_id
verify owner.worker_id == active worker_id
verify owner.claim_token == expected claim_token
verify job status is the expected source status
verify job claim_token is null for queued->running
verify job claim_token matches for running->terminal
verify raw.log/output.json preconditions
write job.json atomically
```

This is not a distributed CAS. It is a local, file-backed compare contract while
the worker owns `claim.lock`. Other scheduler workers cannot pass the claim
check. Manual file edits can still invalidate the compare; in that case the
worker must fail fast without overwriting artifacts.

## Artifact Protection

`raw.log` and `output.json` are final job artifacts and must never be overwritten
by a second execution attempt.

Execution rules:

- Before starting the agent command, the worker checks that both artifact paths
  are inside the job directory and do not exist.
- For scheduler-owned claimed execution, the agent writes to a claim-specific
  temporary output path such as `output.<claim_token>.tmp.json`. After the agent
  exits, the harness rechecks claim ownership and publishes that file to
  `output.json` with an exclusive create/rename operation. This is the only way
  to make `output.json` overwrite protection enforceable because the agent
  process itself performs the initial write.
- Before writing `raw.log`, the worker rechecks that it still owns the matching
  claim and writes `raw.log` with exclusive-create semantics.
- If `output.json` already existed before the command, execution is rejected
  before agent start.
- If `raw.log` or `output.json` appears unexpectedly while the worker is
  running, the worker marks the job failed only if it still owns the claim and
  can write the terminal state without overwriting either artifact. Otherwise it
  leaves the job running/stale for explicit recovery.

The safe default for ambiguous artifact ownership is to stop and require
operator recovery. Silent artifact replacement is forbidden.

## Lease Refresh

The scheduler's existing job heartbeat thread is extended to refresh the claim
lease while a job runs:

- update `owner.json.lease_heartbeat_at`
- update `owner.json.lease_expires_at`
- optionally mirror `job.json.claim_updated_at` when this can be done without
  violating the compare contract

Lease refresh failures are diagnostic scheduler events. They do not immediately
stop the agent command. If the worker later cannot prove it still owns the
claim, it must not write terminal artifacts or terminal job state.

## Recovery Interaction

Normal scheduler polling never clears or steals `claim.lock`, even if the lease
has expired.

`detect-stale-jobs` includes claim lease data in each job assessment:

- claim status: absent, present, missing-owner, invalid-owner
- claim worker id
- claim token
- lease heartbeat timestamp
- lease expiry timestamp
- lease age seconds
- lease expired boolean

`recover-stale-job --confirm` keeps the Phase 7.1 ordering:

1. classify job as stale
2. validate action and confirmation
3. reject `requeue` if `raw.log` or `output.json` exists
4. write recovery artifact
5. append scheduler event
6. write `job.json`
7. remove stale `claim.lock`

If recovery fails before `job.json` changes, the claim lock remains untouched.

## CLI And API Changes

Internal helpers:

- `new_claim_token() -> str`
- `refresh_claim_lease(claim, lease_seconds, now=None) -> dict`
- `load_and_validate_claim_owner(claim) -> dict`
- `assert_claim_matches_job(job, owner, expected_status, expected_claim_token)`
- `write_job_if_claim_matches(...) -> dict`
- `guard_job_artifact_absent(path, field) -> None`

Schema changes:

- `claim-owner.schema.json` moves to `schema_version = 2` with claim token and
  lease fields.
- `job.schema.json` adds nullable claim fields.

CLI behavior:

- `run-scheduler --once` and `--watch` use the same claim compare helpers.
- `detect-stale-jobs` reports lease details.
- `recover-stale-job` clears claim fields when requeueing.

No new public lifecycle state is introduced.

## Tests

Unit tests:

- direct concurrent `acquire_claim_lock_dir` contention still yields exactly one
  winner
- two workers with the same configured `worker_id` get different claim tokens
- queued-to-running write fails if claim token is missing or mismatched
- running-to-terminal write fails if job claim token differs from owner token
- artifact pre-existence rejects execution before agent start
- unexpected artifact appearance during execution does not overwrite files
- lease refresh updates owner timestamps without changing evidence
- stale detection reports expired lease details
- requeue recovery clears claim fields and removes lock only after successful
  recovery

Live smoke tests:

- Start three real `run-scheduler --watch` worker processes against five queued
  blocking jobs.
- Release the jobs.
- Assert each job has exactly one raw log, one output file, one terminal status,
  and one claim token.
- Assert no job command ran twice by recording append-only side effects in a
  per-job execution marker file.
- Assert workers can exit cleanly through `stop-scheduler` or bounded
  `max-seconds`.

## Implementation Order

Phase 8 must be implemented in this order:

1. **G1: Windows claim-lock retry gate.** Confirm the Phase 7.1 M1 fix is
   present: transient Windows rename failures for `claim.lock` retry with
   bounded backoff, and the race test is not using an over-tight timeout. This
   is a startup prerequisite; Phase 8 must not proceed if this gate regresses.
2. **B2: Lease refresh boundaries.** Define and test lease metadata creation,
   refresh, expiry reporting, and failure handling before adding new state
   transitions. Lease expiry must remain diagnostic and must not authorize
   scheduler steal/recovery.
3. **B1: Conditional job writes.** Add claim-token compare-before-write helpers
   for `queued -> running` and `running -> terminal` transitions. These helpers
   must fail closed on mismatched owner, mismatched token, unexpected status, or
   artifact precondition failure.
4. **Core functionality.** Wire lease and conditional-write helpers through
   `scheduler_run_once`, `scheduler_run_watch`, and generic-agent execution.
   Update schemas, stale detection output, and recovery clearing of claim
   fields.
5. **T1/T2: Concurrency and live smoke.** Add deterministic concurrent unit
   coverage first, then add the live multi-worker smoke using real scheduler
   processes and blocking jobs.

## Acceptance Criteria

- Full unit suite passes on Windows.
- Source-controlled run validation passes.
- `git diff --check` passes.
- Live multi-worker smoke proves no duplicate command execution under at least
  three local scheduler processes.
- No test can overwrite pre-existing `raw.log` or `output.json`.
- Stale lease detection remains explicit; normal scheduler polling does not
  recover or steal stale locks.

## Residual Risks

- File-backed compare semantics protect harness-controlled workers, not
  arbitrary manual edits.
- A worker killed after the agent subprocess produces partial artifacts may
  still require explicit recovery.
- Lease refresh relies on local clock readings; severe clock jumps can affect
  stale classification.
- This design remains intentionally local-filesystem only.
