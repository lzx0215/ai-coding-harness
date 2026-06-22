# Phase 6 Scheduler Background Worker Design

## Summary

Phase 6 turns the Phase 5.2 one-shot local scheduler into an observable run-scoped worker loop. The worker can run in the foreground through `run-scheduler --watch` or be launched as a detached local background process through `start-scheduler`. `stop-scheduler` requests graceful shutdown by writing a scheduler stop artifact.

The scheduler remains below the Harness lifecycle authority boundary. It writes scheduler artifacts and job artifacts only. It never indexes evidence into `state.json`, never advances Harness state, and never treats a job artifact as completion evidence. Codex must still explicitly consume artifacts, index evidence, run validation, and advance state through the existing CLI lifecycle commands.

## Goals

- Add a foreground watch loop with heartbeat, polling interval, bounded test controls, graceful stop handling, and structured scheduler events.
- Add a local detached worker launcher that reuses the same watch-loop implementation.
- Add a stop command that requests shutdown through a run-local artifact.
- Keep `run-scheduler --once` behavior compatible, but change the CLI shape so `--once` and `--watch` are a mutually exclusive required group.
- Keep invalid job handling strict for `--once`, while making watch mode resilient: invalid job records write structured warnings and skip the current polling iteration instead of aborting the whole worker.
- Preserve Phase 5.2 authority boundaries: scheduler artifacts are not evidence until Codex explicitly indexes them, and scheduler execution never mutates `state.json`.

## Non-Goals

- No multi-worker claim locking.
- No stale-running automatic recovery.
- No cloud queue.
- No cross-run queue.
- No automatic evidence indexing.
- No automatic Harness state transition.
- No permission sandbox beyond the current local subprocess behavior.
- No automatic interruption of a running job when a stop request appears.
- No log rotation or long-term scheduler log retention policy.

## Existing Constraints

The current Phase 5.2 scheduler already provides these constraints and extension points:

- `state.json` is the lifecycle authority. Scheduler logic returns artifacts only.
- `queue-generic-agent` creates queued jobs without starting subprocesses.
- `run-scheduler --once` validates the run, loads scheduler jobs, claims queued jobs, and executes them sequentially.
- `aggregate-jobs` writes `jobs/aggregation.json` without mutating `state.json`.
- Agent stdout and stderr are captured in each job's `raw.log`.
- `write_json_atomic` is available and should be used for `worker.json`, `heartbeat.json`, `stop.json`, and job status updates.
- Phase 5.2 does not implement stale-running recovery, multi-worker locking, daemon behavior, or cloud execution. Phase 6 moves watch mode into scope but keeps the other boundaries intact.

## Considered Approaches

| Approach | Trade-off | Decision |
| --- | --- | --- |
| A. Foreground-only bounded watch loop | Easiest to test and sufficient for CI, but does not satisfy the requested background worker mode. | Use as the core implementation and test surface. |
| B. OS service or platform-specific daemon | More production-like, but introduces Windows service, Unix daemon, lifecycle, permissions, and install complexity too early. | Rejected for Phase 6. |
| C. Detached local Python child process using the same watch loop | Provides real background behavior while keeping implementation local, testable, and package-friendly. | Chosen. |

## Proposed CLI Surface

```powershell
harness run-scheduler <run-dir> (--once | --watch) `
  [--poll-interval-seconds 5] `
  [--max-iterations N] `
  [--max-seconds N] `
  [--worker-id <id>]

harness start-scheduler <run-dir> `
  [--poll-interval-seconds 5] `
  [--max-iterations N] `
  [--max-seconds N] `
  [--worker-id <id>]

harness stop-scheduler <run-dir> [--reason <text>]
```

The PowerShell line continuations are for readability only. CI/package-smoke commands should be verified against the current workflow shell and may use single-line equivalents.

`run-scheduler --once` keeps the Phase 5.2 strict behavior: invalid job records fail the command before execution.

`run-scheduler --watch` runs in the current process. It validates startup state, writes scheduler identity and heartbeat artifacts, then loops until a stop condition is reached. If a valid `jobs/scheduler/stop.json` already exists when the worker starts polling, the worker treats it as an active stop request.

`start-scheduler` validates arguments, clears any stale `jobs/scheduler/stop.json`, then starts a detached Python child process that runs `python -m harness.cli run-scheduler <run-dir> --watch ...`. It returns after launch and prints the worker id. It does not claim that the worker successfully executed jobs; the heartbeat and events artifacts are the observable worker state. The detached launch mechanism is platform-specific and finalized at implementation; the watch loop itself is platform-independent. The detached child must not depend on the caller console staying open: child stdin/stdout/stderr should be redirected away from the caller, and intentional scheduler diagnostics belong in `events.log` and `heartbeat.json`.

`stop-scheduler` writes `jobs/scheduler/stop.json` atomically. The worker observes it between polling iterations or after the current job completes.

## Scheduler Artifact Layout

Phase 6 adds a singleton run-local scheduler directory:

```text
<run-dir>/jobs/scheduler/
  worker.json
  heartbeat.json
  stop.json
  events.log
```

This directory is not evidence by itself. Codex may later decide to index selected scheduler artifacts only if the evidence contract is extended deliberately.

### `worker.json`

`worker.json` is written once at worker startup. It records identity and static configuration:

```json
{
  "worker_id": "scheduler-20260622-abc123",
  "pid": 12345,
  "run_dir": "C:/ai/ai-coding-harness/harness/runs/...",
  "started_at": "2026-06-22T03:00:00Z",
  "poll_interval": 5.0,
  "max_iterations": null,
  "max_seconds": null,
  "cli_version": "0.2.0"
}
```

If a later worker is started for the same run, it writes a new `worker.json`. `worker.json` is a current-worker snapshot, not append-only history. Worker start/stop history is retained in `events.log` through `worker_started`, `worker_stopped`, and failure events. Phase 6 does not add lockfiles or stale-worker takeover semantics, so operators remain responsible for not launching overlapping workers.

### `heartbeat.json`

`heartbeat.json` is overwritten every polling iteration and at worker shutdown. It records volatile state only:

```json
{
  "worker_id": "scheduler-20260622-abc123",
  "last_seen_at": "2026-06-22T03:00:05Z",
  "iteration": 2,
  "status": "running-job",
  "current_job_id": "phase6-job"
}
```

Allowed statuses:

- `starting`
- `idle`
- `running-job`
- `sleeping`
- `warning`
- `stopping`
- `stopped`
- `failed`

Heartbeat is an observation signal only. Phase 6 does not use heartbeat age to recover stale `running` jobs, steal ownership, or mutate existing job artifacts.

### `events.log`

`events.log` is newline-delimited JSON. Each line is one JSON object with this shape:

```json
{"ts":"2026-06-22T03:00:05Z","event":"job_completed","detail":{"worker_id":"scheduler-20260622-abc123","job_id":"phase6-job","status":"succeeded"}}
```

Required fields:

- `ts`: UTC timestamp.
- `event`: stable event name.
- `detail`: JSON object with event-specific structured details.

The scheduler event log is for scheduler lifecycle events only. Agent stdout and stderr remain isolated in each job's `raw.log`; the scheduler must not copy agent output into `events.log`.

Initial event vocabulary:

- `worker_started`
- `heartbeat_written`
- `poll_started`
- `poll_completed`
- `job_started`
- `job_completed`
- `invalid_jobs_observed`
- `stop_requested`
- `stop_observed`
- `max_iterations_reached`
- `max_seconds_reached`
- `worker_stopped`
- `startup_failed`
- `worker_failed`

## Watch Loop Semantics

The watch loop performs these steps:

1. Validate startup state.
2. Write `worker.json`.
3. Write `heartbeat.json` with `status = "starting"`.
4. Append `worker_started` to `events.log`.
5. Repeat until a stop condition:
   - check for `stop.json`
   - write heartbeat for the current iteration
   - scan jobs
   - if invalid job records are present, append `invalid_jobs_observed`, set heartbeat `status = "warning"`, skip this polling iteration, and sleep
   - execute queued jobs sequentially using the existing generic agent execution path
   - after each job completes, check `stop.json` before claiming another job
   - sleep for `poll_interval_seconds`
6. Write final heartbeat with `status = "stopped"` or `status = "failed"`.
7. Append `worker_stopped` or `worker_failed`.

Jobs queued while an iteration is executing are picked up in a later polling iteration.

## Stop Semantics

`stop-scheduler` writes:

```json
{
  "requested_at": "2026-06-22T03:01:00Z",
  "requested_by": "codex",
  "reason": "operator requested shutdown"
}
```

Stop requests are cooperative:

- `start-scheduler` removes a pre-existing `stop.json` before spawning the child, treating it as a stale one-shot signal from a previous worker session.
- `run-scheduler --watch` does not remove `stop.json` at worker startup. If a stop request is present before the first polling iteration, the worker observes it and exits cleanly.
- If the worker is sleeping or between jobs, it exits before claiming another job.
- If the worker is executing a job, it waits for the current job to reach a terminal state, writes job artifacts, observes `stop.json`, and exits without claiming a later queued job.
- Stop requests do not kill subprocesses.
- Stop requests do not mark jobs cancelled.
- Stop requests do not mutate `state.json`.

## Startup Failure Definition

Startup failure is a scheduler command failure before the worker has entered its polling loop. Examples:

- invalid CLI arguments
- missing run directory
- invalid or unreadable `state.json`
- failure to validate the run before startup
- failure to create or write `jobs/scheduler/worker.json`
- invalid polling configuration

Startup failure is not a job failure. It must not mark any job `failed`, `timeout`, or `cancelled`. If the scheduler directory can be written, startup failure may append a `startup_failed` event and write heartbeat `status = "failed"`.

Job failure only applies after a queued job has been claimed and the generic agent execution path produces a terminal job status.

## Invalid Job Handling

`run-scheduler --once` remains strict and fails on invalid job records before any job is claimed.

`run-scheduler --watch` is resilient:

- invalid job records do not terminate the worker
- the worker appends an `invalid_jobs_observed` JSONL event with paths and validation errors
- the worker sets heartbeat `status = "warning"`
- the worker skips the current polling iteration without claiming otherwise valid queued jobs
- the next polling iteration retries from disk

This prevents a long-running worker from dying because a partially written or manually edited job artifact appears, while still making the problem visible and avoiding mixed execution under a corrupt job set.

The all-or-nothing skip is intentional. When any corrupt job record exists, watch mode does not partially execute other queued jobs in the same run. Operators must fix or remove the invalid job artifact before normal watch execution resumes.

## Claim And Concurrency Semantics

Phase 6 inherits the Phase 5.2 claim model: queued jobs are claimed by atomically rewriting `job.json` from `queued` to `running`. This is not a compare-and-swap lock and does not make multiple workers safe.

Phase 6 explicitly does not introduce:

- lockfiles
- stale heartbeat takeover
- process liveness checks that reclassify jobs
- double-claim prevention beyond the current sequential single-worker discipline

If two workers are launched against the same run, double-claim risk remains. That risk must be recorded in the implementation handoff and progress memory.

## Data Flow

Foreground watch:

```text
operator -> run-scheduler --watch
         -> jobs/scheduler/worker.json
         -> jobs/scheduler/heartbeat.json
         -> jobs/scheduler/events.log
         -> jobs/<job-id>/job.json running
         -> agent subprocess
         -> jobs/<job-id>/raw.log
         -> jobs/<job-id>/output.json
         -> jobs/<job-id>/job.json terminal
```

Background worker:

```text
operator -> start-scheduler
         -> detached python -m harness.cli run-scheduler --watch
         -> same scheduler and job artifacts as foreground watch
```

Stop:

```text
operator -> stop-scheduler
         -> jobs/scheduler/stop.json
         -> worker observes stop between jobs or after current job
         -> heartbeat.json stopped
         -> events.log worker_stopped
```

Consume:

```text
Codex -> aggregate-jobs
      -> index-evidence agent-job
      -> index-evidence agent-result
      -> index-evidence aggregation
      -> validate
      -> advance state when Harness rules allow
```

## Error Handling

- Invalid CLI arguments exit non-zero and do not create job artifacts.
- Startup validation failure exits non-zero and does not mark jobs failed.
- Failure to write scheduler artifacts exits non-zero before job execution.
- Invalid job records in `--once` fail the command before execution.
- Invalid job records in `--watch` produce structured warning events and skip the current iteration.
- Generic agent subprocess failure, missing output, invalid output, and timeout keep using the existing terminal job status rules.
- `stop.json` parse errors are treated like invalid scheduler control artifacts: append a structured warning and continue running until a valid stop request is present or another stop condition is reached.

## Tests

Unit and integration tests should cover:

- CLI parser requires exactly one of `--once` or `--watch`.
- Existing package smoke and CI continue to use `run-scheduler --once`.
- `run-scheduler --watch --poll-interval-seconds 0.1 --max-iterations 3` runs a real queued job, writes `worker.json`, `heartbeat.json`, and JSONL `events.log`, then exits without mutating `state.json`.
- A watch loop that receives `stop.json` exits gracefully and leaves terminal job artifacts consumable by `aggregate-jobs`.
- A worker that receives `stop.json` while a job is executing waits for that job to finish, writes terminal job artifacts, and exits without claiming a later queued job.
- Watch mode records invalid job records as `invalid_jobs_observed`, skips the polling iteration, and keeps the worker alive.
- Foreground watch and detached background worker share the same watch-loop implementation.
- `start-scheduler` launches the expected child command without claiming that jobs completed.
- `stop-scheduler` writes `jobs/scheduler/stop.json` atomically and does not mutate `state.json`.
- `events.log` is valid newline-delimited JSON with `ts`, `event`, and object-shaped `detail` on every line.
- `worker.json` contains static identity/configuration fields and `heartbeat.json` contains only volatile fields.
- `aggregate-jobs` correctly classifies terminal and incomplete jobs after watch execution.
- Scheduler artifacts are not automatically indexed as evidence.
- Scheduler execution never advances Harness state.

Full verification should include:

```powershell
python -m unittest discover -s tests
Get-ChildItem -Directory harness/runs | ForEach-Object { python -m harness.cli validate $_.FullName }
git diff --check
```

Package smoke should add a bounded foreground watch invocation so CI proves the packaged console script can execute watch mode from outside the repository. Detached background launch should be covered by unit tests and, if stable on Windows and GitHub-hosted runners, an optional local smoke.

Before implementation reuses the verification commands above, validate them against the current GitHub Actions shell and local Windows shell. If the current workflow shell is not PowerShell, use the equivalent shell-native loop for validating every source-controlled run.

## Live Phase 6 Run

Implementation should produce a source-controlled run:

```text
harness/runs/2026-06-22-phase-6-scheduler-watch-mode/
```

The run should prove:

- the run was created through `init-run`
- a queued job was created through `queue-generic-agent`
- the job was executed through bounded `run-scheduler --watch`
- scheduler artifacts were written under `jobs/scheduler/`
- `events.log` is structured JSONL
- `stop-scheduler` was exercised or an equivalent `stop.json` was written by the CLI
- `aggregate-jobs` produced `jobs/aggregation.json`
- Codex explicitly indexed `agent-job`, `agent-result`, `aggregation`, `verification`, review evidence or review waiver, and `handoff`
- the run completed through normal Harness state transitions

The handoff must explicitly record:

- watch mode is local and run-scoped
- heartbeat is observational only
- stop requests are cooperative and do not interrupt running jobs
- invalid job records in watch mode are warnings, not worker-fatal errors
- no multi-worker locking or stale-running recovery was implemented
- scheduler artifacts are not evidence unless Codex indexes them through an evidence type

## Acceptance Criteria

- `run-scheduler` requires exactly one of `--once` or `--watch`.
- `run-scheduler --once` remains backward compatible and strict on invalid job records.
- `run-scheduler --watch` writes worker identity, heartbeat, and JSONL event artifacts.
- `start-scheduler` launches a detached worker that uses the same watch implementation.
- `stop-scheduler` writes a stop request artifact without mutating `state.json`.
- Watch mode respects poll interval and bounded stop controls.
- Watch mode exits on valid `stop.json`, `max_iterations`, or `max_seconds`.
- Stop requests do not interrupt an already running job.
- Watch mode does not abort permanently on invalid job records.
- `events.log` contains scheduler events only, not agent stdout or stderr.
- `worker.json` stores stable identity/configuration and `heartbeat.json` stores volatile runtime state.
- Scheduler and stop commands never index evidence and never advance `state.json`.
- Double-claim risk is unchanged and documented; no lockfile is introduced.
- CI and package smoke are updated for the mutually exclusive `--once` / `--watch` CLI shape.
- A live Phase 6 scheduler watch run exists and validates.

## Residual Risks

- Multiple workers on the same run remain unsafe.
- A crashed worker can still leave a job `running`; Phase 6 observes but does not recover it.
- Detached background process behavior may vary by OS shell and terminal environment.
- `events.log` can grow without rotation.
- Local subprocess execution inherits the same permission and environment risks as the existing generic adapter.
- Stop requests are cooperative and may be delayed by long-running jobs.
