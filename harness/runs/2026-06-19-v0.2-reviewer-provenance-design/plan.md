# Plan

## Goal

Start v0.2 with an auditable design record for reviewer provenance and nullable metadata consumers.

## Files

- `docs/superpowers/specs/2026-06-19-v0.2-reviewer-provenance-design.md`
- `docs/INDEX.md`
- `harness/memory/progress.md`
- `harness/runs/2026-06-19-v0.2-reviewer-provenance-design/task.md`
- `harness/runs/2026-06-19-v0.2-reviewer-provenance-design/triage.md`
- `harness/runs/2026-06-19-v0.2-reviewer-provenance-design/plan.md`
- `harness/runs/2026-06-19-v0.2-reviewer-provenance-design/state.json`

## Steps

1. Create the v0.2 design spec.
2. Create the run task, triage, and plan records.
3. Update documentation index and progress memory.
4. Create a valid draft `state.json`.
5. Advance the run through `triaged` to `planned`.
6. Validate the run.
7. Stop for user spec review before implementation planning.

## Verification

- `python -m harness.cli validate harness/runs/2026-06-19-v0.2-reviewer-provenance-design`
- `git diff --check`
- `git status --short`

## Rollback

Remove the v0.2 spec, this run directory, and the corresponding `docs/INDEX.md` and `harness/memory/progress.md` updates before implementation starts.
