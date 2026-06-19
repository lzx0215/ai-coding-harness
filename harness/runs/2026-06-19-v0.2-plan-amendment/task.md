# Task

## Goal

Apply the implementation-plan sanity-check amendments before v0.2 execution.

## Track

Standard

## Workflow

standard-doc-system-change

## Scope

- Fix the v0.2 implementation plan so explicit `model` / `reviewer_model` metadata remains higher priority than `modelUsage`.
- Preserve `modelUsage` model evidence when explicit metadata is present.
- Add a focused regression test to the plan for explicit-model precedence plus preserved `modelUsage` entries.
- Add the existing scalar fallback regression to the implementation test command.
- Expand the real Claude review input-file creation step from the v0.1.1 working example.
- Record that parsed `cli.version` is informational and `cli.raw_version` remains the audit source for non-numeric versions.
- Verify and commit the amended implementation plan.

## Non-goals

- Implement adapter, schema, or test code.
- Change the approved v0.2 design spec.
- Rewrite completed run histories.
- Run real Claude review for this plan-only amendment.
- Push to a remote repository.

## Acceptance Criteria

- The plan's `build_reviewer_provenance` code path sets `primary_model` from explicit metadata when present.
- The plan preserves additional `modelUsage` models after the explicit metadata model.
- The plan includes a failing-then-passing test for explicit metadata precedence in structured provenance.
- The Task 4 adapter test command includes the existing scalar regression `test_normalize_prefers_explicit_model_metadata_over_model_usage`.
- The Task 6 real review step contains an explicit `claude-review.input.json` generation command.
- This amendment run validates and reaches `completed`.
- The plan amendment is committed after verification.

## Verification Plan

- Validate this run with `python -m harness.cli validate`.
- Run a placeholder scan against the amended plan.
- Run `git diff --check`.
- Run the default unit suite.
- Inspect staged files before commit.

## Risks

- This is a plan-only amendment, so implementation correctness is still proven later by the implementation run.
- The real Claude review step remains optional for this amendment; live external review is planned for the implementation run.
