# Evidence Contract

## Authority Boundary

Evidence is an input to Codex decisions. Evidence files and external agent outputs
never mutate `state.json` directly.

Codex must explicitly index consumed artifacts in `state.json.evidence[]` before
they can satisfy validation, review, handoff, or risk-acceptance gates.

## Controlled Types

The current controlled evidence vocabulary is implemented in `harness/cli.py`.
Adding a new type requires updating:

- `EVIDENCE_TYPES`
- tests that pin the vocabulary
- this contract or a more specific adapter contract

## Phase 4 Async Evidence

Phase 4 adds three async-agent evidence types:

| Type | Intended path | Contract |
| --- | --- | --- |
| `agent-job` | `harness/runs/<run-id>/jobs/<job-id>/job.json` | Process record for an async job. When indexed, it must validate against `harness/schemas/job.schema.json` and have a terminal status: `succeeded`, `failed`, `timeout`, or `cancelled`. |
| `agent-result` | `harness/runs/<run-id>/jobs/<job-id>/output.json` | Reserved pointer to an agent result payload when that payload is not promoted into an existing canonical review artifact. When indexed, it must validate against `harness/schemas/agent-result.schema.json`, match `state.run_id`, and match a terminal `agent-job` evidence entry for the same `job_id`. |
| `aggregation` | `harness/runs/<run-id>/jobs/aggregation.json` | Fan-in summary for async jobs. When indexed, it must validate against `harness/schemas/aggregation.schema.json` and pass CLI semantic checks for job bucket consistency. |
| `job-recovery` | `harness/runs/<run-id>/jobs/<job-id>/recovery/<timestamp>-<action>.json` | Explicit stale-running recovery audit artifact. When indexed, it must validate against `harness/schemas/job-recovery.schema.json` and match `state.run_id`. Recovery artifacts do not prove job success or completion; they only justify an operator-confirmed current-status correction. |

## Aggregation Semantics

Indexed `aggregation` evidence must satisfy these semantic rules in addition to
the JSON schema:

- every job id in `succeeded_jobs`, `failed_jobs`, `timeout_jobs`,
  and `cancelled_jobs` must appear in `consumed_jobs`
- every `consumed_jobs` entry must appear in exactly one terminal bucket
- non-terminal observed jobs belong in `incomplete_jobs` only; they must not
  appear in `consumed_jobs`
- a job cannot appear in more than one terminal bucket
- a job cannot be both terminal and incomplete
- duplicate job ids inside any aggregation bucket are invalid

Aggregation recommendations are advisory. Codex remains responsible for any
subsequent state transition.

## Stale-Running Recovery Evidence

`job-recovery` evidence exists to prevent silent history rewrites. A recovery
artifact must record the stale assessment, previous job snapshot, new job
snapshot, action (`requeue` or `fail`), explicit reason, actor, timestamp, and
whether artifact correction was confirmed.

The scheduler must not automatically index `job-recovery` evidence or advance
`state.json`. Codex may index the recovery artifact only after deciding to
consume it as part of the run record.

## Scheduler Control Files

`jobs/<job-id>/claim.lock/owner.json`, scheduler `worker.json`,
`heartbeat.json`, `stop.json`, and `events.log` are scheduler control or
diagnostic files, not evidence. They must not be auto-indexed into
`state.json.evidence[]`. Historical runs where `claim.lock` is absent remain
valid.

Claim tokens and lease timestamps are control metadata, not evidence. They must
not be auto-indexed.

## Cross-Run Queue Control Files

Phase 9A local cross-run queue files are control and audit artifacts, not
completion evidence. This includes queue manifests, `events.log`,
`entries/<entry-id>/entry.json`, `entries/<entry-id>/claim.lock/owner.json`,
`entries/<entry-id>/recovery/*.json`, and
`entries/<entry-id>/cleanup/*.json`.

Queue entries may help Codex decide what happened, but they must not be
auto-indexed into any owning run's `state.json.evidence[]`. Terminal run-local
`agent-job`, `agent-result`, and `aggregation` artifacts remain under the owning
run and must still be explicitly indexed by Codex when consumed.
