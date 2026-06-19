# Plan

## Goal

Create the v0.2 implementation plan and record the planning checkpoint.

## Files

- `docs/superpowers/plans/2026-06-19-v0.2-reviewer-provenance-implementation.md`
- `docs/INDEX.md`
- `harness/memory/progress.md`
- `harness/runs/2026-06-19-v0.2-implementation-plan/*`

## Steps

1. Read approved v0.2 spec and current adapter/schema/test files.
2. Write the implementation plan with the state-schema-first commit strategy.
3. Index the plan and update progress memory.
4. Validate this planning run.
5. Run default verification.
6. Complete the run.

## Verification

- `python -m harness.cli validate harness/runs/2026-06-19-v0.2-implementation-plan`
- `git diff --check`
- placeholder and forbidden-completion-language scan
- `python -m unittest discover -s tests -v`

## Rollback

Before commit, remove this run, remove the new implementation plan, and revert `docs/INDEX.md` and `harness/memory/progress.md` edits.
