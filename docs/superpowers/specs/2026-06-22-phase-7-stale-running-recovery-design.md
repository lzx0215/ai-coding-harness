# Phase 7 Stale Running Detection And Recovery Design

## Summary

Phase 7 adds explicit stale-running diagnostics and operator-confirmed recovery
for async jobs. The scheduler still does not own Harness lifecycle state:
diagnosis and recovery produce job artifacts and scheduler events only. Codex
remains responsible for indexing recovery evidence and advancing `state.json`.

## Goals

- Distinguish active `running` jobs from orphaned `running` jobs left by a
  crashed scheduler.
- Record scheduler ownership on newly claimed jobs with `worker_id` and
  `updated_at`.
- Define stale detection using heartbeat timeout, worker identity, `started_at`,
  and `updated_at`.
- Support explicit recovery by requeueing a stale job or marking it failed.
- Prevent silent history mutation by writing a `job-recovery` artifact and
  scheduler event before changing the current `job.json`.
- Require users to correct partial `raw.log` or `output.json` artifacts before a
  stale job can be requeued.

## Non-Goals

- No automatic stale recovery during scheduler polling.
- No multi-worker compare-and-swap claim locking.
- No process-table or OS-level liveness probe.
- No deletion or automatic renaming of partial job artifacts.
- No automatic evidence indexing or Harness state transition.

## Stale Classification

`detect-stale-jobs` classifies only jobs whose `job.json.status` is `running`.

| Classification | Meaning |
| --- | --- |
| `active` | `heartbeat.json` has the same `worker_id`, `status = running-job`, matching `current_job_id`, and `last_seen_at` inside the configured heartbeat timeout. |
| `recent` | No fresh matching heartbeat proves activity, but job `updated_at` or fallback `started_at` is still inside the timeout. |
| `stale` | No fresh matching heartbeat proves activity, and job `updated_at` or fallback `started_at` is older than the timeout. |
| `invalid` | The running job has unusable timestamp data after schema validation. |

The timeout is an operator-chosen threshold. Phase 7 requires it explicitly on
CLI commands instead of baking in a default that could be wrong for long-running
agents.

## Recovery Semantics

`recover-stale-job` requires:

- a target job currently classified as `stale`
- `--confirm`
- a non-empty `--reason`
- `--action requeue` or `--action fail`

For `requeue`, `raw.log` and `output.json` must not exist. If they do exist,
the command stops with an artifact-correction error. The user must inspect and
move, delete, or otherwise correct those partial artifacts explicitly before
retrying recovery.

For `fail`, the current job becomes terminal `failed`, keeps its original
`worker_id`, and receives an error reason prefixed with
`stale running recovery`.

Every recovery writes:

```text
jobs/<job-id>/recovery/<timestamp>-<action>.json
jobs/scheduler/events.log
```

The recovery artifact includes previous and new job snapshots, stale assessment,
actor, timestamp, reason, action, heartbeat timeout, and artifact correction
confirmation. This preserves the audit trail even though `job.json` remains the
current process record.

## CLI Surface

```powershell
harness detect-stale-jobs <run-dir> --heartbeat-timeout-seconds 300

harness recover-stale-job <run-dir> <job-id> `
  --action requeue `
  --reason "scheduler crashed during review" `
  --heartbeat-timeout-seconds 300 `
  --confirm

harness recover-stale-job <run-dir> <job-id> `
  --action fail `
  --reason "partial output cannot be safely retried" `
  --heartbeat-timeout-seconds 300 `
  --confirm
```

## Validation

- Unit tests cover active heartbeat classification, stale timeout
  classification, explicit confirmation, requeue recovery artifact creation,
  artifact-conflict refusal, and failed recovery.
- Schema tests cover `worker_id`, `updated_at`, and `job-recovery`.
- Existing historical runs remain valid because new job fields are optional.

## Residual Risks

- A long-running job can be misclassified if its worker stops refreshing
  `heartbeat.json`; recovery remains manual and confirm-gated to reduce damage.
- Multi-worker double-claim protection is still not implemented.
- Phase 7 does not inspect OS process tables, so worker identity is artifact
  based.
- Users remain responsible for deciding how to preserve or discard partial
  artifacts before requeueing.
