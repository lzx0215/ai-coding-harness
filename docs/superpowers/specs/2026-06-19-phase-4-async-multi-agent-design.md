# Phase 4 Async Multi-Agent Design

## Summary

Phase 4 adds a run-local async job substrate for multi-agent evidence generation. It builds on Phase 1's local run closure contract: run state remains the Harness lifecycle authority, while async jobs are evidence-producing processes that Codex consumes before advancing state.

The core rule is that external agents and job artifacts never mutate `state.json`. Jobs produce structured outputs, logs, and optional provenance. Codex indexes consumed artifacts into `state.json.evidence[]`, aggregates results, and then advances the run according to Harness rules.

## Goals

- Support async agent execution without giving agents state authority.
- Support fan-out to multiple reviewers or specialized agents.
- Support fan-in aggregation with explicit conflict and severity handling.
- Keep job execution status separate from Harness run status.
- Make job artifacts auditable and recoverable after interruption.
- Preserve current `reviews/claude-review*.json` compatibility.
- Add track-aware policy for Standard versus Strict failure handling.

## Non-goals

- Build a cloud queue or distributed scheduler.
- Let external agents mutate files or Harness state directly.
- Rewrite existing review artifacts into the job model.
- Replace `external_agents[]` or review output schemas in existing runs.
- Add UI, dashboards, or live monitoring.
- Solve arbitrary agent marketplace integration.

## Relationship to Phase 1

Phase 1 must land first because it defines:

- A controlled evidence type vocabulary.
- Track-aware completion evidence gates.
- Explicit risk acceptance evidence.
- `advance` as the only state transition entrypoint.

Phase 4 extends that foundation by adding job artifacts and new evidence types. It does not weaken Phase 1's completion gate. A job result only matters after Codex has consumed it and indexed the relevant artifact as evidence.

## Current State

The repository currently supports synchronous Claude review through `mcp/claude-review/`. Review artifacts live under run-local `reviews/`, and `external_agents[]` records reviewer metadata and terminal review status.

The current state machine already includes review exception states:

- `review_failed`
- `review_timeout`
- `review_schema_invalid`
- `external_review_unavailable`
- `review_blocked`

However, there is no general async job model. There is also no job-level retry history, cancellation record, or fan-in aggregation contract.

## Considered Approaches

| Approach | Trade-off | Decision |
| --- | --- | --- |
| Extend only `reviews/` for every agent | Simple for review-only work, but does not generalize to non-review agents or async process tracking. | Rejected. |
| Add a global `harness/jobs/` queue | Easier to inspect all jobs globally, but weakens run-local auditability and complicates cleanup. | Rejected for Phase 4 first slice. |
| Add run-local `jobs/<job-id>/` | Keeps async evidence with the run, supports recovery, and preserves current review artifacts. | Chosen. |
| Force Claude review through jobs immediately | Unifies implementation, but requires migrating a stable synchronous path. | Rejected. Existing `reviews/` remains compatible. |
| Use job artifacts to directly advance run state | Automation-friendly, but violates Codex-first state authority. | Rejected. Codex must consume job outputs first. |

## Proposed Contract

Each async agent invocation creates a run-local job directory:

```text
harness/runs/<run-id>/
  jobs/
    <job-id>/
      job.json
      input.json
      output.json
      raw.log
```

`job.json` records process state, not Harness lifecycle state.

Allowed job statuses:

```text
queued
running
succeeded
failed
timeout
cancelled
```

Only terminal jobs can be consumed into indexed evidence or aggregation:

```text
succeeded
failed
timeout
cancelled
```

`queued` and `running` jobs may be present on disk, but they cannot be marked consumed, included in aggregation, or used to satisfy review, handoff, or completion gates. A terminal job status alone also does not satisfy completion; completion still requires the Phase 1 evidence gates.

Timestamp semantics:

- `created_at` is required for every job.
- `queued` jobs must not have `started_at` or `completed_at`.
- `running` jobs must have `started_at` and must not have `completed_at`.
- terminal jobs must have both `started_at` and `completed_at`.
- timestamps must be monotonic: `created_at <= started_at <= completed_at` when the fields are present.

Codex must explicitly index consumed job artifacts into `state.json.evidence[]`. The presence of a job directory is never enough.

## Data Model

Minimal `job.json`:

```json
{
  "job_id": "claude-review-001",
  "run_id": "2026-06-19-example",
  "agent": "claude-code",
  "adapter": "claude-review",
  "status": "succeeded",
  "input_file": "input.json",
  "output_file": "output.json",
  "raw_log_file": "raw.log",
  "created_at": "2026-06-19T00:00:00Z",
  "started_at": "2026-06-19T00:00:01Z",
  "completed_at": "2026-06-19T00:02:00Z",
  "timeout_seconds": 900,
  "error_reason": null,
  "provenance": {
    "agent": "claude-code",
    "adapter_version": "0.1.0",
    "runtime": "local-cli"
  }
}
```

`provenance` is optional and generic. It records job-level agent, adapter, runtime, and environment metadata. It does not replace `reviewer_provenance` in Claude review output schema.

Phase 4 extends the Phase 1 evidence type vocabulary with:

```text
agent-job
agent-result
aggregation
```

The type split is:

- `agent-job` indexes `jobs/<job-id>/job.json`, the process record.
- `agent-result` indexes `jobs/<job-id>/output.json`, the agent result payload, when that payload is not also stored as a canonical review artifact.
- `aggregation` indexes a fan-in aggregation artifact under `jobs/`.

`agent-result` payloads must validate against `harness/schemas/agent-result.schema.json` and include `run_id`, `job_id`, `agent`, `adapter`, `status`, `summary`, `findings`, `evidence`, `not_tested`, `residual_risks`, and `generated_at`. Codex must cross-check `run_id` against `state.json` and `job_id` against a matching terminal `agent-job` evidence entry before treating the result as consumed evidence.

Example indexed job evidence:

```json
{
  "type": "agent-job",
  "path": "harness/runs/<run-id>/jobs/<job-id>/job.json",
  "description": "Terminal async agent job consumed by Codex."
}
```

Example indexed agent result evidence:

```json
{
  "type": "agent-result",
  "path": "harness/runs/<run-id>/jobs/<job-id>/output.json",
  "description": "Structured async agent result consumed by Codex."
}
```

Example aggregation evidence:

```json
{
  "type": "aggregation",
  "path": "harness/runs/<run-id>/jobs/aggregation.json",
  "description": "Codex aggregation of async agent job results."
}
```

Existing `reviews/claude-review*.json` artifacts remain valid and are not migrated. Future async Claude review may produce both:

- a job record under `jobs/<job-id>/` for process tracking
- a review artifact under `reviews/` for review result semantics

For async Claude review, `job.provenance` is the process/runtime audit source, while `reviewer_provenance` in the review output remains the reviewer identity and model source of truth. Codex should index `job.json` as `agent-job`; if the output is promoted to `reviews/`, Codex should index the review artifact with the existing `review-*` evidence types instead of duplicating the same payload as `agent-result`.

## Fan-out / Fan-in

Fan-out is allowed only when Codex can define:

- input scope per job
- agent role and adapter
- timeout and retry policy
- expected output schema
- evidence destination
- whether the job is required or optional

Fan-in produces an aggregation artifact. The aggregation must list:

- consumed jobs
- succeeded jobs
- failed jobs
- timeout jobs
- cancelled jobs
- incomplete jobs that were not consumed
- findings, grouped by severity
- conflicts or disagreements between agents
- recommended Harness state transition, if any
- residual risks

Aggregation can recommend `review_blocked` when high or critical findings exist, but it must not mutate `state.json`. Codex consumes the aggregation and then calls `advance` if a state transition is warranted.

Aggregation cross-checking treats `consumed_jobs` as the set of terminal jobs consumed by Codex. Terminal buckets must be subsets of `consumed_jobs` and must match the corresponding `job.json.status`. `incomplete_jobs` records non-terminal or missing jobs observed during fan-in and must not be listed in `consumed_jobs`.

## Error Handling

Job failure and run failure are separate.

A job can fail, timeout, or be cancelled without immediately changing run state. Codex decides whether the job result is retryable, ignorable, risk-acceptable, or blocking.

Retries happen at the job layer before Codex advances the run to `external_review_unavailable`. Once the run enters `external_review_unavailable`, the current state machine only allows:

```text
external_review_unavailable -> risk_accepted
```

Phase 4 does not add `external_review_unavailable -> reviewing` in the first slice.

Track-aware policy:

| Track | Required reviewer unavailable | Allowed handling |
| --- | --- | --- |
| Fast | Usually no required reviewer | Record skipped or unavailable evidence if review was attempted. |
| Standard | May enter risk acceptance flow | Requires `risk-acceptance` evidence before completion. |
| Strict | Must stop for user decision | Use `needs_user_decision` unless the user explicitly approves a Strict risk acceptance path. |

No completion claim can rely on a `queued` or `running` job.

## Verification Strategy

Unit tests should cover:

- `job.json` schema accepts all allowed job statuses.
- `job.json` schema rejects unknown job statuses.
- Non-terminal jobs cannot be indexed as consumed job evidence or satisfy completion gates.
- A `succeeded` job does not automatically appear in `state.json.evidence[]`.
- Consumed jobs must be explicitly indexed as `agent-job` evidence.
- Aggregation artifacts list consumed, failed, timeout, cancelled, and incomplete jobs.
- Writing an aggregation artifact does not change `state.json.status`.
- Codex consumption of aggregation can support a subsequent `reviewing -> review_blocked` transition when high or critical findings exist.
- Standard reviewer unavailable can proceed only through risk acceptance evidence.
- Strict required reviewer unavailable enters `needs_user_decision` rather than silent risk acceptance.
- Existing `reviews/claude-review*.json` artifacts remain valid without migration.

Integration verification should include:

```powershell
python -m unittest discover -s tests
python -m harness.cli validate harness/runs/2026-06-19-v0.2-reviewer-provenance-implementation
```

If a real async adapter is available, run one local job smoke and record the job, output, raw log, aggregation, and state evidence indexing.

## Acceptance Criteria

- Async jobs are stored under the owning run.
- Job status is separate from Harness run status.
- External agents cannot mutate `state.json`.
- Codex explicitly indexes consumed job artifacts into `state.json.evidence[]`.
- Non-terminal jobs cannot satisfy completion gates.
- Aggregation records partial success, failed jobs, incomplete jobs, conflicts, findings, and residual risks.
- Aggregation artifacts do not directly mutate state.
- Standard and Strict tracks have distinct unavailable-reviewer handling.
- Existing synchronous Claude review artifacts continue to work unchanged.
- Phase 4 evidence type additions are added to the controlled vocabulary before use.

## Deferred Work

- Cloud queue integration.
- Background worker supervision.
- Cross-run job dashboards.
- Automatic branch or worktree creation per job.
- Historical migration of synchronous reviews into job records.
- Arbitrary third-party agent plugin discovery.
- New state machine edge `external_review_unavailable -> reviewing`.
