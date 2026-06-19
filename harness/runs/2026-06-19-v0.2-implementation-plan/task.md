# Task

## Goal

Write the v0.2 reviewer provenance implementation plan from the approved spec.

## Track

Standard

## Workflow

standard-doc-system-change

## Scope

- Create a file-level implementation plan.
- Decide implementation commit granularity before code changes.
- Update documentation index and progress memory.
- Record this planning run with validation evidence.

## Non-goals

- Implement schema, adapter, or test changes.
- Run real Claude review.
- Push commits to a remote.
- Reopen completed v0.2 design runs.

## Acceptance Criteria

- Plan exists under `docs/superpowers/plans/`.
- Plan states that state schema compatibility lands before v0.2 provenance output emission.
- Plan includes direct test assertions for incomplete usage, unknown invariants, controlled unknown validation, and v0.1.1 fixture compatibility.
- This planning run validates and reaches `completed`.

## Verification Plan

- Validate this run with `python -m harness.cli validate`.
- Run `git diff --check`.
- Scan the plan for placeholder and forbidden completion wording.
- Run default unit tests.

## Risks

- The plan is intentionally detailed; execution agents must still verify current files before each edit.
- Commit hashes inside future implementation run records must use the actual execution-time values.
