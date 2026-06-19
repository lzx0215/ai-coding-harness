# Task

## Goal

Apply the second spec-review amendments before v0.2 implementation planning and create a checkpoint commit.

## Track

Standard

## Workflow

standard-doc-system-change

## Scope

- Clarify `primary_model` incomplete-usage handling.
- Add `model_name` / `primary_model` unknown invariants.
- Reorder the migration plan so state schema compatibility lands before v0.2 output emission.
- Require schema failure for out-of-vocabulary `unknowns`.
- Turn CLI semver from an open question into a deferred decision.
- Verify and commit the design checkpoint.

## Non-goals

- Implement adapter, schema, or test code.
- Rewrite the completed `2026-06-19-v0.2-reviewer-provenance-design` run state.
- Run real Claude review for this design-only amendment.
- Push to a remote repository.

## Acceptance Criteria

- The v0.2 spec contains no unresolved question section.
- The migration plan explicitly prevents half-migrated output/state schema behavior.
- The amendment run validates and reaches `completed`.
- The design checkpoint is committed after verification.

## Verification Plan

- Validate this run with `python -m harness.cli validate`.
- Run `git diff --check`.
- Run placeholder and forbidden-completion-language scans.
- Run the default unit suite.
- Inspect staged files before commit.

## Risks

- Creating a new amendment run adds ceremony, but avoids mutating a completed run's state history.
- The commit will include all uncommitted v0.2 design checkpoint files, so staging must stay scoped.
