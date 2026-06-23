# State Authority

## Authority

Harness defines valid states and transitions. Codex executes transitions for the current run. External agents return evidence only.

## Normal States

`draft -> triaged -> planned -> in_progress -> implemented -> verified -> reviewing -> reviewed -> completed`

## Exceptional States

- `blocked`
- `needs_user_decision`
- `failed_verification`
- `review_blocked`
- `review_failed`
- `review_timeout`
- `review_schema_invalid`
- `external_review_unavailable`
- `risk_accepted`

## Transition Rules

- `current_workflow` must be present in the workflow registry.
- `review_failed` means process failure, not blocking findings.
- Blocking findings use `review_blocked`.
- `timeout` and `not_available` are adapter statuses, not completion evidence.
- Historical run records are append-only unless the user explicitly requests correction.
- The base transition table still contains `external_review_unavailable -> risk_accepted`.
  For Strict tracks, `advance` applies an additional policy gate: a direct
  `external_review_unavailable -> risk_accepted` transition is rejected and the
  run must enter `needs_user_decision` first.
- `needs_user_decision` is a state checkpoint for explicit user decision. It is
  not, by itself, proof that risk was accepted; downstream completion still
  requires indexed risk-acceptance evidence when the run reaches `risk_accepted`.

## Review Status Mapping

| Review status | Harness state |
| --- | --- |
| `passed` | `reviewed` |
| `findings` with no `high` or `critical` findings | `reviewed` after triage |
| `findings` with `high` or `critical` findings | `review_blocked` |
| `failed` | `review_failed` |
| `timeout` | `review_timeout` |
| `schema_invalid` | `review_schema_invalid` |
| `not_available` | `external_review_unavailable` |

## Resume

On resume, Codex must read `state.json`, validate it against `harness/schemas/state.schema.json`, verify evidence paths, and continue only from a valid transition.

## Stale Running Jobs

`running` async jobs are current process records, not Harness completion states.
Codex must distinguish active work from orphaned work before recovery:

- Active: the job has a `worker_id`, and `jobs/scheduler/heartbeat.json` has the
  same `worker_id`, `status = running-job`, matching `current_job_id`, and a
  `last_seen_at` inside the chosen heartbeat timeout.
- Recent: no fresh matching heartbeat proves activity, but the job's
  `updated_at` or, when absent, `started_at` is still inside the timeout.
- Stale: no fresh matching heartbeat proves activity, and the job's
  `updated_at` or `started_at` is older than the timeout.
- Invalid: required timestamps are missing or malformed after schema validation.

Recovery is never automatic. A stale `running` job may be requeued or marked
failed only through an explicit operator-confirmed recovery action that writes a
`job-recovery` artifact and a scheduler event before changing the current
`job.json`. Requeue recovery must not overwrite or delete partial `raw.log` or
`output.json`; those artifacts require explicit user correction first.

Multi-worker scheduler execution is guarded by per-job `claim.lock` directories.
A worker owns a queued job only after a prepared directory containing
`owner.json` is atomically renamed to `jobs/<job-id>/claim.lock`. Normal
scheduler polling must not clear existing claim locks. Explicit stale recovery
may remove a stale claim lock only after recovery preconditions pass, the
`job-recovery` artifact and scheduler event are written, and the `job.json`
state change succeeds. If recovery is rejected, including for partial
`raw.log` or `output.json`, the claim lock must remain untouched.

Claim leases are diagnostic and recovery safety inputs. An expired lease does
not authorize ordinary scheduler polling to steal a lock or rewrite a running
job. A fresh matching lease blocks stale recovery because it may represent an
active worker whose run-level scheduler heartbeat was overwritten by another
worker. Claimed job state transitions must compare `worker_id` and
`claim_token` before writing `job.json`.

## Cross-Run Queue Records

Local cross-run queue entries are coordination records, not state authority.
They may reference existing run-local queued jobs, but they do not own the
referenced run's `state.json`, evidence index, review decision, verification, or
handoff.

A cross-run queue worker must claim a queue entry before it attempts to claim
the referenced run-local job. The owning run-local job remains protected by the
normal `jobs/<job-id>/claim.lock` and claim-token contract. Queue entries may
record routing status such as `queued`, `claimed`, `running`, `succeeded`,
`failed`, `timeout`, `cancelled`, or `abandoned`, but those statuses do not
advance the owning Harness run.

Cross-run queue recovery and cleanup are explicit operator actions. Recovery may
requeue or abandon a queue entry with an audit artifact; cleanup records that a
terminal queue entry was handled. Neither action may silently rewrite or delete
owning run-local `job.json`, `raw.log`, or `output.json` artifacts.

Phase 9A queue-entry leases are diagnostic only. The local queue does not
automatically steal or reap expired `claimed` / `running` entries. If a queue
worker dies after claiming the referenced run-local job, the run-local stale-job
recovery contract must make that job safe before the queue entry can be
requeued.
