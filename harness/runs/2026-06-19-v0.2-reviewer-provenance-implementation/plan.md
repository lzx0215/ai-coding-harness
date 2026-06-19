# Plan

## Goal

Complete the v0.2 reviewer provenance implementation evidence run.

## Steps

1. Create and validate a v0.2 implementation run.
2. Advance the run to `in_progress`.
3. Generate implementation diff artifacts from `master` to the current branch.
4. Run final verification: unit tests, known run validation, `pip check`, and MCP server import.
5. Run a real Claude review through the adapter.
6. Inspect and record review status and provenance fields.
7. Write verification, review, and handoff evidence.
8. Advance the run through `completed` only if verification and review disposition allow it.

## Review Gate

Do not merge this branch to `master` automatically after Task 6. The real review output is the first end-to-end provenance proof and must be reviewed before any merge decision.

## Rollback

Before committing evidence, remove `harness/runs/2026-06-19-v0.2-reviewer-provenance-implementation/` and revert any evidence-only progress/index edits.
