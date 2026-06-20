# Phase 3 Review Decision and Memory Closure Design

## Summary

Phase 3 defines how Codex records review handling, closure decisions, handoff content, and long-term memory updates without adding new Harness states.

The main design decision is to represent review handling as a `review-decision.json` artifact with a `disposition` field. A disposition is not a Harness state. It is an evidence-backed decision record that maps to existing Harness states, transitions, and evidence types.

## Goals

- Define a structured review decision artifact.
- Keep review disposition separate from `state.json.status`.
- Reuse existing Harness states and evidence types where possible.
- Make waiver, unavailable review, blocking findings, and risk acceptance auditable.
- Define handoff closure semantics using the Phase 2 Markdown frontmatter format.
- Define memory closure rules that keep long-term memory distilled.
- Avoid forward dependencies from Phase 2 planning to Phase 3 disposition enums.

## Non-goals

- Add new Harness states.
- Replace Phase 1 completion gates.
- Replace reviewer output schemas.
- Replace Phase 4 job aggregation.
- Store raw review logs in memory.
- Force historical run migration.
- Treat review as a substitute for verification.

## Relationship to Other Phases

Phase 1 defines the state machine, completion evidence gates, review waiver evidence, risk acceptance evidence, and the rule that `advance` is the only state transition entrypoint.

Phase 2 defines the Markdown frontmatter format for human-authored run artifacts. Phase 3 uses that format for handoff closure but does not require Phase 2 plans to reference Phase 3 review disposition values.

Phase 4 separates async job status from Harness run status. Phase 3 follows the same pattern by separating review disposition from Harness run status.

## Current State

Harness already has review-related states:

- `reviewing`
- `reviewed`
- `review_blocked`
- `review_failed`
- `review_timeout`
- `review_schema_invalid`
- `external_review_unavailable`
- `risk_accepted`

Harness already has review and risk evidence types:

- `review-output`
- `review-evidence`
- `review-raw-log`
- `review`
- `review-waiver`
- `risk-acceptance`
- `handoff`

The current gap is that Codex's review triage decision is not a first-class artifact. Review outputs can exist, but the run may not have a compact machine-checkable record explaining how the output was mapped to a Harness transition, waiver, blocked state, or risk acceptance path.

## Considered Approaches

| Approach | Trade-off | Decision |
| --- | --- | --- |
| Add new Harness states for review decision outcomes | Direct but duplicates existing exceptional states and makes the state machine harder to maintain. | Rejected. |
| Store review decision only in free-form handoff text | Readable, but hard to validate and hard to resume from. | Rejected. |
| Add `review-decision.json` with a disposition field that maps to existing states | Structured, auditable, and preserves the state authority boundary. | Chosen. |
| Add a new `review-decision` evidence type immediately | More explicit, but expands the evidence vocabulary before implementation proves it is necessary. | Deferred. |
| Index `review-decision.json` as `review-evidence` | Reuses existing vocabulary and keeps Phase 3 focused. | Chosen for the first slice. |

## Review Disposition Boundary

Review disposition is a field inside `review-decision.json`. It is not a Harness state and must not be used as a replacement for `state.json.status`.

Allowed disposition values:

```text
passed
findings-triaged
waived
unavailable
risk-accepted
blocked
```

Disposition-to-Harness mapping:

| Disposition | Harness expression |
| --- | --- |
| `passed` | Review evidence supports `reviewed`. |
| `findings-triaged` | Review findings were triaged; target state is `reviewed` when no unresolved high or critical findings remain, otherwise `review_blocked`. |
| `waived` | `verified -> reviewed` plus indexed `review-waiver` evidence. |
| `unavailable` | Adapter `not_available` mapped to `external_review_unavailable`. |
| `risk-accepted` | `risk_accepted` plus indexed `risk-acceptance` evidence. |
| `blocked` | `review_blocked`. |

The disposition record may recommend a target Harness state, but it must not mutate state. Codex still advances the run through `advance` if a transition is warranted.

`unavailable` must not collapse all review process failures into one category. Existing adapter statuses still map to their existing Harness states: `failed -> review_failed`, `timeout -> review_timeout`, and `schema_invalid -> review_schema_invalid`. Codex may later make a decision from those states, but it must not relabel them as reviewer unavailability unless the adapter status is actually `not_available`.

## Review Decision Contract

`review-decision.json` is a new structured artifact. It should be indexed as `review-evidence` unless a later phase deliberately adds a dedicated evidence type to the controlled vocabulary.

Minimal shape:

```json
{
  "schema_version": "0.1.0",
  "run_id": "2026-06-20-example",
  "generated_at": "2026-06-20T00:00:00Z",
  "disposition": "findings-triaged",
  "recommended_status": "reviewed",
  "decision_owner": "codex",
  "source_evidence": [
    {
      "type": "review-output",
      "path": "harness/runs/2026-06-20-example/reviews/claude-review.json"
    }
  ],
  "severity_counts": {
    "critical": 0,
    "high": 0,
    "medium": 1,
    "low": 0,
    "info": 0
  },
  "resolved_findings": [],
  "accepted_risks": [],
  "not_tested": [],
  "residual_risks": [],
  "notes": "Medium finding triaged as non-blocking."
}
```

Required fields:

- `schema_version`
- `run_id`
- `generated_at`
- `disposition`
- `recommended_status`
- `decision_owner`
- `source_evidence`
- `severity_counts`
- `resolved_findings`
- `accepted_risks`
- `not_tested`
- `residual_risks`

Rules:

- `recommended_status` must be one of the existing Harness states.
- `disposition` must be one of the Phase 3 disposition values.
- `source_evidence[]` paths must point to indexed or indexable review artifacts.
- `risk-accepted` disposition requires corresponding user risk acceptance evidence before completion.
- `waived` disposition requires `review-waiver` evidence.
- `blocked` disposition must recommend `review_blocked`.
- A decision record cannot override a high or critical finding without either resolved finding evidence or explicit risk acceptance.

## Review Handling Flow

Normal passed review:

```text
implemented
-> verified
-> reviewing
-> reviewed
-> completed
```

Codex records:

- verification evidence
- review output evidence
- review decision evidence
- handoff evidence

Review with non-blocking findings:

```text
reviewing -> reviewed
```

Allowed only when the decision record explains why findings are non-blocking or how they were resolved.

Review with high or critical unresolved findings:

```text
reviewing -> review_blocked
```

The run must not move to `reviewed` until the finding is fixed, reverified, and retriaged, unless the user explicitly accepts risk through the existing risk acceptance path.

Review waived:

```text
verified -> reviewed
```

Requires:

- `review-waiver` evidence
- `review-decision.json` with `disposition = "waived"`

Reviewer unavailable:

```text
reviewing -> external_review_unavailable
```

Standard tasks may continue only through risk acceptance when allowed by Phase 1 policy. Strict tasks stop for user decision unless the user explicitly approves a risk acceptance path.

## Handoff Closure Semantics

Phase 3 uses the Phase 2 handoff frontmatter contract and defines when it is complete enough for closure.

Required handoff fields before completion:

```yaml
changed:
  - "What changed."
verified:
  - "Verification evidence summary."
not_verified:
  - "What was not verified."
residual_risks:
  - "Remaining risk."
next_step: "Concrete next step."
memory_update: none
memory_files: []
```

Rules:

- `changed` must summarize the actual diff or documentation change.
- `verified` must cite verification evidence, not merely repeat the plan.
- `not_verified` must be present even when empty.
- `residual_risks` must be present even when empty.
- `next_step` must be actionable.
- Handoff evidence does not replace verification, review, waiver, or risk acceptance evidence.

## Memory Closure Rules

Long-term memory remains distilled, not exhaustive.

Memory updates are appropriate for:

- Stable project context.
- Confirmed architecture or workflow decisions.
- Repeated risks.
- Durable user preferences.
- Agent integration constraints.
- Current phase and next-step summaries that help future sessions resume.

Memory updates are not appropriate for:

- Raw logs.
- One-off command output.
- Transient stack traces.
- Hidden reasoning.
- Repetitive review details.
- Information useful only to the current run.

`handoff.md` records the memory decision:

```yaml
memory_update: updated
memory_files:
  - harness/memory/progress.md
```

If no durable memory update is needed:

```yaml
memory_update: none
memory_files: []
```

If memory should be updated later:

```yaml
memory_update: deferred
memory_files: []
```

Phase 3 does not add a new memory evidence type in the first slice. Memory file changes are audited through the normal diff and handoff evidence.

## Error Handling

If `review-decision.json` is missing when review handling is required, Codex must not claim review closure.

If `review-decision.json` has an unknown disposition, validation must reject the artifact once the schema is implemented.

If the decision recommends a Harness state that is inconsistent with the disposition, validation must reject the artifact once semantic validation is implemented.

If review output and review decision disagree, Codex must treat the run as needing user decision or review triage. It must not silently choose the more favorable outcome.

If memory update is marked `updated` but `memory_files` is empty, closure checks should warn or fail according to the implemented warning/error policy.

## Verification Strategy

Unit tests should cover:

- `review-decision.json` schema accepts all allowed dispositions.
- The schema rejects unknown dispositions.
- The schema rejects unknown `recommended_status` values.
- `blocked` disposition requires `recommended_status = "review_blocked"`.
- `risk-accepted` disposition requires non-empty accepted risk or risk acceptance reference.
- `waived` disposition requires a waiver reference.
- Review disposition values are not added to the Harness state schema.
- Historical runs continue to validate without `review-decision.json`.
- Handoff frontmatter missing in historical runs is warning-level, not error-level.
- Handoff closure checks require changed, verified, not verified, residual risks, and next step for new runs.

Repository-level verification should run:

```powershell
python -m unittest discover -s tests -v
python -m harness.cli validate harness/runs/example-fast-doc-change
```

## Acceptance Criteria

- Phase 3 adds no new Harness status.
- Review disposition is documented as a decision field, not state.
- Disposition values map to existing Harness states and evidence.
- `review-decision.json` has a JSON schema contract.
- `review-decision.json` is indexed as `review-evidence` in the first slice.
- Review waiver and risk acceptance reuse existing Phase 1 evidence contracts.
- High or critical unresolved findings cannot be silently treated as reviewed.
- Handoff closure fields are defined.
- Memory closure rules distinguish durable memory from run-local detail.
- Historical runs remain valid without migration.
