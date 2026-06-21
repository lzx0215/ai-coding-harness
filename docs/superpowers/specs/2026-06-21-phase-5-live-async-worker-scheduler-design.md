# Phase 5.2 Live Async Worker Scheduler Design

## Summary

Phase 5.2 turns the Phase 4 generic async job substrate into a live local scheduler path. The first slice is a run-scoped, single-process scheduler that can queue generic agent jobs, claim queued jobs, execute them through the existing subprocess adapter, and write a job aggregation artifact.

The scheduler remains below the Harness lifecycle authority boundary. It writes run-local job artifacts only. It never indexes evidence into `state.json`, never advances Harness state, and never treats a job artifact as completion evidence. Codex must still explicitly consume artifacts, index evidence, run validation, and advance state through the existing CLI lifecycle commands.

## Goals

- Split the current `run_generic_agent` flow into explicit queue and execute steps.
- Add a reproducible local scheduler smoke path before introducing daemon, multi-worker, or cloud queue behavior.
- Preserve the existing `run-generic-agent` CLI behavior as create plus execute.
- Use atomic job status updates for the queued to running claim and terminal completion.
- Generate `jobs/aggregation.json` from observed job artifacts without mutating `state.json`.
- Add CI and package-smoke coverage for the new packaged CLI commands.
- Produce a real Phase 5 live scheduler run proving queue, scheduler execution, aggregation, evidence indexing, and handoff.

## Non-Goals

- No daemon, watch loop, background service, cloud queue, or cross-run queue.
- No multi-worker concurrency or distributed locking.
- No automatic evidence indexing.
- No automatic Harness state transition.
- No automatic stale-running recovery.
- No migration of existing Phase 4 run artifacts.
- No permission sandbox beyond the current local subprocess behavior.

## Existing Constraints

The current async job contract already enforces several Phase 5.2 requirements:

- `state.json` is the lifecycle authority. External jobs and scheduler logic return evidence only.
- Indexed `agent-job` evidence must be terminal. Current validation rejects consumed `queued` and `running` jobs with `non-terminal job cannot be consumed`.
- `run_generic_agent` already has a natural split point:
  - after the initial queued `job.json` and `input.json` are written
  - before the job is marked `running` and the subprocess starts
- `jobs/aggregation.json` is already a run-local job artifact. Writing it does not affect state until Codex indexes it as `aggregation` evidence.
- `write_json_atomic` already exists and should be reused for all job status updates.

## Considered Approaches

| Approach | Trade-off | Decision |
| --- | --- | --- |
| A. Run-scoped scheduler with queue, run-once, and aggregate commands | Small, local, reproducible, aligns with the Phase 4 contract. Does not prove daemon or multi-worker behavior. | Chosen. |
| B. Watch-mode scheduler with heartbeat and stale recovery | More realistic for long-running work, but requires lifecycle and recovery semantics that are not yet designed. | Deferred. |
| C. Global queue or cloud worker | Useful later for distributed work, but introduces locks, permissions, cross-run ownership, and recovery complexity. | Rejected for Phase 5.2. |

## Proposed CLI Surface

Phase 5.2 adds three commands and keeps the existing command:

```powershell
harness queue-generic-agent <run-dir> <job-id> --agent <agent-name> [--adapter generic-cli-agent] [--timeout-seconds 1800] -- <command>
harness run-scheduler <run-dir> --once
harness aggregate-jobs <run-dir>
harness run-generic-agent <run-dir> <job-id> --agent <agent-name> [--adapter generic-cli-agent] [--timeout-seconds 1800] -- <command>
```

`run-generic-agent` remains the compatibility command. Internally it becomes:

```text
create_generic_agent_job(...)
execute_generic_agent_job(...)
```

The first scheduler slice only supports `--once`. A watch mode must be designed separately.

## Proposed Internal Functions

### `create_generic_agent_job`

Creates a run-local queued job:

- validates the run
- rejects empty `job_id`, empty `agent`, empty command, invalid timeout, and path traversal
- rejects duplicate job directories
- writes `jobs/<job-id>/job.json` with `status = "queued"`
- writes `jobs/<job-id>/input.json`
- does not start a subprocess
- does not mutate `state.json`
- does not index evidence

### `execute_generic_agent_job`

Executes one existing queued job:

1. Load `job.json` and `input.json`.
2. Reject direct execution when `job.status` is not `queued`.
3. Atomically claim the job by writing `status = "running"` and `started_at`.
4. Run the command from `input.json` with the same environment variables used by the current generic adapter.
5. Write `raw.log`.
6. Validate `output.json` against `agent-result.schema.json` when the subprocess exits successfully.
7. Atomically write terminal `job.json` with `succeeded`, `failed`, `timeout`, or `cancelled`, plus `completed_at` and `error_reason`.

Terminal jobs are never re-executed. This prevents output and raw-log overwrite for an already completed job.

### `scheduler_run_once`

Scans `jobs/*/job.json`, selects jobs with `status = "queued"`, sorts them by `(created_at, job_id)`, and executes the selected jobs sequentially.

The scan is a point-in-time snapshot. Jobs queued during scheduler execution are picked up by a later `run-scheduler --once` invocation.

Non-queued jobs are not claimed:

- terminal jobs are skipped
- `running` jobs are skipped
- invalid job records cause the scheduler command to fail before execution, so the operator sees the corrupt artifact instead of silently ignoring it

### `aggregate_jobs`

Reads all job records under `jobs/*/job.json` and writes `jobs/aggregation.json`.

Aggregation semantics:

- terminal jobs are listed in `consumed_jobs`
- terminal jobs are also listed in exactly one terminal bucket: `succeeded_jobs`, `failed_jobs`, `timeout_jobs`, or `cancelled_jobs`
- non-terminal observed jobs are listed in `incomplete_jobs`
- `incomplete_jobs` are not listed in `consumed_jobs`, matching the current CLI validator behavior
- valid terminal `output.json` files contribute findings to the aggregation
- missing or invalid result payloads are recorded as residual risks rather than inventing findings
- aggregation recommendations remain advisory
- writing aggregation does not mutate `state.json`

## Claim And Crash Semantics

The queued to running claim is an atomic write to `job.json`. This gives the scheduler a clear ownership marker without introducing locks.

Crash cases are intentionally limited in Phase 5.2:

- crash before claim: job remains `queued`; a later `run-scheduler --once` can execute it
- crash after claim but before terminal completion: job remains `running`
- crash after terminal write: job remains terminal and will not be re-executed

Phase 5.2 does not distinguish active `running` jobs from orphaned `running` jobs left by a crashed scheduler. Both are skipped by later scheduler runs and reported through aggregation as incomplete when `aggregate-jobs` is run.

Manual recovery is out of scope for the scheduler. Codex can choose to create a new job, record a risk, or apply a deliberate artifact correction when explicitly authorized.

## Data Flow

Queue:

```text
Codex/CLI -> queue-generic-agent -> jobs/<job-id>/job.json queued
                                 -> jobs/<job-id>/input.json
```

Run:

```text
Codex/CLI -> run-scheduler --once -> claim queued job as running
                                  -> subprocess agent command
                                  -> jobs/<job-id>/raw.log
                                  -> jobs/<job-id>/output.json
                                  -> jobs/<job-id>/job.json terminal
```

Aggregate:

```text
Codex/CLI -> aggregate-jobs -> jobs/aggregation.json
```

Consume:

```text
Codex -> index-evidence agent-job
      -> index-evidence agent-result
      -> index-evidence aggregation
      -> validate
      -> advance state when Harness rules allow
```

## Error Handling

- Creating an existing job id fails.
- Direct execution of a terminal or running job fails.
- Scheduler execution skips non-queued jobs and never retries terminal jobs.
- Timeout and subprocess failure produce terminal job records, matching current `run_generic_agent` behavior.
- A successful subprocess with missing or invalid `output.json` marks the job `failed`.
- `aggregate-jobs` should still produce an aggregation when some jobs are non-terminal, listing those jobs under `incomplete_jobs`.
- `aggregate-jobs` should fail if a job record cannot be parsed or does not validate against the job schema.

## Tests

Unit tests should cover:

- `create_generic_agent_job` writes queued `job.json` and `input.json` without mutating `state.json`.
- `execute_generic_agent_job` can execute a queued job created by a prior independent call.
- `execute_generic_agent_job` rejects terminal jobs and running jobs.
- `run_generic_agent` remains compatible and still creates terminal job, result, and raw log artifacts.
- `scheduler_run_once` executes queued jobs in deterministic order.
- `scheduler_run_once` skips `running` and terminal jobs without claiming them.
- A crash-like `running` job is not consumed as evidence and appears in aggregation `incomplete_jobs`.
- `aggregate_jobs` classifies terminal and non-terminal jobs according to current validator semantics.
- `aggregate_jobs` does not mutate `state.json`.
- CLI parser exposes `queue-generic-agent`, `run-scheduler`, and `aggregate-jobs`.
- Packaged CLI smoke invokes the new commands from outside the repository.
- Static CI contract tests assert `.github/workflows/ci.yml` includes smoke coverage for the new commands.

Full verification should include:

```powershell
python -m unittest discover -s tests
Get-ChildItem -Directory harness/runs | ForEach-Object { python -m harness.cli validate $_.FullName }
git diff --check
```

The packaged smoke job should also validate all historical runs after non-editable install, preserving the Phase 4 package-root regression coverage.

## Live Phase 5 Run

Implementation must produce a source-controlled run:

```text
harness/runs/2026-06-21-phase-5-live-scheduler-smoke/
```

The run should prove:

- the run was created through `init-run`
- a queued job was created through `queue-generic-agent`
- the job was executed through `run-scheduler --once`
- `aggregate-jobs` produced `jobs/aggregation.json`
- Codex explicitly indexed `agent-job`, `agent-result`, `aggregation`, `verification`, review evidence or review waiver, and `handoff`
- the run completed through normal Harness state transitions

The handoff must explicitly record:

- claim writes are atomic through `write_json_atomic`
- the run proves local single-process scheduler behavior only
- watch mode, multi-worker concurrency, cloud queue, and stale-running recovery were not verified
- orphaned `running` jobs are skipped, not automatically recovered

## Acceptance Criteria

- `run-generic-agent` remains backward compatible.
- Queued jobs are not indexed automatically and cannot satisfy consumed evidence gates.
- `queue-generic-agent` can create a queued job without starting it.
- `run-scheduler --once` can claim and execute queued jobs.
- Scheduler execution never mutates `state.json`.
- Direct execution rejects non-queued jobs, including terminal jobs.
- Terminal jobs are not re-run and raw logs are not overwritten.
- `aggregate-jobs` records terminal jobs as consumed and non-terminal jobs as incomplete.
- `aggregate-jobs` writes `jobs/aggregation.json` without indexing evidence.
- CI covers the new commands in both editable tests and non-editable package smoke.
- A live Phase 5 scheduler smoke run exists and validates.

## Residual Risks

- Phase 5.2 does not prove multi-worker safety.
- Phase 5.2 does not prove daemon/watch behavior.
- Phase 5.2 does not detect whether a `running` job is active or orphaned.
- Manual intervention is required after a scheduler crash that leaves a job `running`.
- Local subprocess execution inherits the same permission and environment risks as the existing generic adapter.
