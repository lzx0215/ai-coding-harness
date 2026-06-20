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
| `agent-result` | `harness/runs/<run-id>/jobs/<job-id>/output.json` | Reserved pointer to an agent result payload when that payload is not promoted into an existing canonical review artifact. In this slice it is path-checked only; no payload schema is enforced yet. |
| `aggregation` | `harness/runs/<run-id>/jobs/aggregation.json` | Fan-in summary for async jobs. When indexed, it must validate against `harness/schemas/aggregation.schema.json` and pass CLI semantic checks for job bucket consistency. |

## Aggregation Semantics

Indexed `aggregation` evidence must satisfy these semantic rules in addition to
the JSON schema:

- every job id in `succeeded_jobs`, `failed_jobs`, `timeout_jobs`,
  `cancelled_jobs`, and `incomplete_jobs` must appear in `consumed_jobs`
- every `consumed_jobs` entry must appear in exactly one terminal bucket or in
  `incomplete_jobs`
- a job cannot appear in more than one terminal bucket
- a job cannot be both terminal and incomplete
- duplicate job ids inside any aggregation bucket are invalid

Aggregation recommendations are advisory. Codex remains responsible for any
subsequent state transition.
