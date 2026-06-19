# Plan

## Goal

Close the second spec-review amendments and checkpoint the v0.2 design baseline.

## Files

- `docs/superpowers/specs/2026-06-19-v0.2-reviewer-provenance-design.md`
- `harness/runs/2026-06-19-v0.2-spec-amendment/*`

## Steps

1. Revise the spec for incomplete usage, unknown invariants, migration ordering, strict unknown validation, and deferred CLI semver.
2. Record this amendment run.
3. Validate the run and execute default verification.
4. Stage only v0.2 design checkpoint files.
5. Commit the checkpoint.

## Verification

- `python -m harness.cli validate harness/runs/2026-06-19-v0.2-spec-amendment`
- `git diff --check`
- placeholder and forbidden-completion-language scan
- `python -m unittest discover -s tests -v`

## Rollback

Before commit, remove the amendment run and revert the latest spec edits. After commit, revert the checkpoint commit if the design baseline is rejected.
