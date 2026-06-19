# Plan

## Steps

1. Verify the sanity-check feedback against the current adapter semantics and existing tests.
2. Amend `docs/superpowers/plans/2026-06-19-v0.2-reviewer-provenance-implementation.md`.
3. Add a provenance regression test snippet for explicit metadata precedence and preserved `modelUsage` entries.
4. Rewrite the plan's provenance builder snippet so explicit metadata determines `primary_model` when present.
5. Expand the real Claude review input-file creation step from the v0.1.1 review input structure.
6. Add a CLI-version parsing note that keeps `raw_version` authoritative for non-numeric strings.
7. Create this append-only amendment run.
8. Run validation, placeholder scan, whitespace checks, and unit tests.
9. Commit the amended plan and run evidence.

## Commit Strategy

One plan-amendment checkpoint commit after verification.
