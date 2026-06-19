# Phase 1 Local Run Closure Design

## Summary

Phase 1 strengthens the local Harness run loop. The goal is to make run creation, state advancement, verification evidence, review handling, handoff, and memory closure repeatable without changing the Codex-first authority model.

The main design decision is to keep `harness.cli advance` as the only state transition entrypoint. Completion checks are added to `advance <run> completed`, not to a new `close-run` command. This preserves the existing state machine while preventing incomplete or unverifiable runs from entering `completed`.

## Goals

- Keep Codex as the only actor that advances Harness state.
- Preserve the existing state machine and transition authority.
- Add a track-aware completion evidence gate for `completed`.
- Enforce an initial evidence type vocabulary without rewriting historical runs.
- Keep evidence path validation centralized in `validate_evidence_paths`.
- Make risk acceptance explicit through indexed run evidence.
- Keep Phase 1 local and synchronous. Async jobs and multi-agent fan-in belong to Phase 4.

## Non-goals

- Add an async job system.
- Add multi-agent orchestration.
- Add cloud or background execution.
- Rewrite historical run records.
- Replace `state.json` as the run state authority.
- Move review artifacts into a new storage model.
- Add a UI or dashboard.

## Current State

`harness/cli.py` already provides:

- `validate`, which checks state schema validity and indexed evidence paths.
- `advance`, which enforces legal status transitions, validates current and candidate state, and writes state atomically.
- A state machine where only `reviewed -> completed` and `risk_accepted -> completed` are legal completion transitions.

`harness/schemas/state.schema.json` already defines `evidence[]` entries with:

- `type`
- `path`
- optional `description`

The current gap is that completion has no evidence completeness gate. A run can legally transition from `reviewed` to `completed` even if `verification`, review disposition, or `handoff` evidence is missing from `state.json.evidence[]`.

## Considered Approaches

| Approach | Trade-off | Decision |
| --- | --- | --- |
| Add a new `close-run` command | Clear command name, but creates a second completion path beside `advance`. | Rejected. State transition authority should remain single-path. |
| Add completion checks to `advance <run> completed` | Keeps one state entrypoint and only tightens terminal transition behavior. | Chosen. |
| Add a top-level `risk_acceptance` field | Structured, but expands state schema for data that is already evidence-like. | Rejected for Phase 1. |
| Represent risk acceptance as indexed evidence | Small schema surface and consistent with run evidence model. | Chosen. |
| Leave `evidence[].type` as unconstrained free text | Backward-compatible, but completion gate becomes string-convention based and weak. | Rejected. |
| Enforce an initial vocabulary in `validate` | Stronger contract while preserving historical runs by seeding the vocabulary from actual use. | Chosen. |

## Proposed Contract

`advance` remains the only command that changes `state.json.status`.

`validate` must reject:

- Invalid state schema.
- Indexed evidence paths outside the repository.
- Indexed evidence paths that do not exist.
- Indexed evidence types outside the controlled vocabulary.

`advance <run> completed` must run a track-aware completion evidence gate after normal transition validation and before writing the candidate state.

Fast-track completion requires:

- `verification`
- `handoff`

Standard and Strict completion require:

- `verification`
- `handoff`
- one review handling evidence type:
  - `review-evidence`
  - `review`
  - `review-waiver`

Any `risk_accepted -> completed` transition additionally requires:

- `risk-acceptance`

Completion gate checks only evidence types. Path existence and repository-boundary checks remain the responsibility of `validate_evidence_paths`.

## Data Model

Phase 1 does not add a new top-level field for risk acceptance. Risk acceptance is represented as run evidence:

```json
{
  "type": "risk-acceptance",
  "path": "harness/runs/<run-id>/risk-acceptance.md",
  "description": "User accepted residual risk for unavailable review."
}
```

The initial controlled evidence type vocabulary is:

```text
task
triage
plan
design-spec
implementation-plan
diff
changed-files
diff-meta
verification
review-input
review-output
review-evidence
review-raw-log
review
review-waiver
risk-acceptance
handoff
```

This list includes all evidence types currently used by historical runs, including `design-spec` and `implementation-plan`. Historical runs must continue to validate without migration.

Adding a new evidence type requires:

1. Updating the controlled vocabulary constant.
2. Updating validation tests.
3. Documenting the intended evidence meaning.

## Error Handling

If `advance <run> completed` lacks required completion evidence, the command fails before writing state and reports the missing evidence types.

If evidence paths are missing, `validate` reports the existing path errors. The completion gate must not duplicate path-resolution logic.

If review cannot run for a Standard task, Codex must record `review-waiver` or proceed through `external_review_unavailable -> risk_accepted` with `risk-acceptance` evidence before completion.

If a Strict task cannot complete required review, Phase 1 records the state faithfully and stops for user decision. Silent downgrade to residual risk is not allowed.

Intermediate transitions must not trigger the completion gate. For example, `planned -> in_progress` and `implemented -> verified` must not require verification or handoff evidence before those artifacts can reasonably exist.

## Verification Strategy

Unit tests should cover:

- `validate` accepts all existing historical runs.
- `validate` rejects an evidence type outside the controlled vocabulary.
- `advance reviewed -> completed` succeeds for a Fast run with `verification` and `handoff`.
- Fast completion does not require review evidence.
- `advance reviewed -> completed` succeeds for a Standard run with `verification`, `handoff`, and review handling evidence.
- Standard completion fails when `verification` is missing.
- Standard completion fails when `handoff` is missing.
- Standard completion fails when review handling evidence is missing.
- `external_review_unavailable -> risk_accepted -> completed` succeeds only when `risk-acceptance` evidence is indexed.
- `risk_accepted -> completed` fails when `risk-acceptance` evidence is missing.
- Intermediate transitions do not trigger completion evidence checks.
- Evidence path failures remain reported by `validate_evidence_paths`.

Repository-level verification should run:

```powershell
python -m unittest discover -s tests
python -m harness.cli validate harness/runs/example-fast-doc-change
python -m harness.cli validate harness/runs/2026-06-19-v0.2-reviewer-provenance-implementation
```

The implementation plan should expand historical-run validation to all run directories when practical.

## Acceptance Criteria

- `advance` remains the only state transition command.
- `completed` cannot be reached without required track-specific evidence.
- Fast runs can complete without review evidence.
- Standard and Strict runs require verification, handoff, and review handling evidence.
- `risk_accepted` completion requires indexed `risk-acceptance` evidence.
- `validate` rejects unknown evidence types.
- Historical runs continue to validate without editing their evidence records.
- Tests prove intermediate transitions are not blocked by the completion gate.
- Documentation states that evidence type additions require code, tests, and purpose documentation.

## Phase 4 Compatibility Notes

Phase 4 will add async job evidence types such as `agent-job`, `agent-result`, and `aggregation`. Those types must be added to the controlled vocabulary before job artifacts can be indexed in `state.json.evidence[]`.

Phase 1 deliberately does not create `jobs/` or background execution. It only establishes the local evidence and completion contract that Phase 4 can build on.
