---
run_id: 2026-06-20-phase-3-review-decision-memory-implementation
schema_version: 0.1.0
track: Standard
workflow: standard-code-change
owner: codex
requested_outcome: "Implement Phase 3 review-decision artifact, its indexed-evidence validation, the advance review-decision gate, and handoff/memory closure without adding new Harness states or evidence types."
scope:
  - "harness/schemas/review-decision.schema.json"
  - "harness/cli.py review-decision validation and advance gates"
  - "harness/readiness.py soft memory-declaration warning"
  - "tests/test_phase3_review_decision.py, tests/test_phase3_closure.py, and added test_harness_cli.py / test_phase2_readiness.py cases"
non_goals:
  - "No new Harness status"
  - "No new review-decision evidence type"
  - "No migration of historical runs"
  - "No replacement of verification by review"
constraints:
  - "Historical runs must remain valid without review-decision.json"
  - "validate stays the only artifact authority; advance stays the only transition authority"
---

# Task

## Goal

Implement the Phase 3 review decision and memory closure contract defined in `docs/superpowers/specs/2026-06-20-phase-3-review-decision-memory-design.md` as a task-by-task TDD plan executed in `docs/superpowers/plans/2026-06-20-phase-3-review-decision-memory-implementation.md`.

## Track

Standard

## Workflow

standard-code-change

## Scope

- Review decision schema (`review-decision.schema.json`).
- `validate` loading and semantic validation of indexed `review-decision.json`.
- `advance` review-decision transition gate plus missing-decision requirement for triage targets.
- `advance -> completed` handoff and memory closure gate.
- `check-ready` soft memory-declaration warning.

## Non-goals

- No new Harness state.
- No new evidence type.
- No historical-run migration.
- Review is not a substitute for verification.

## Acceptance Criteria

- All Phase 3 plan tasks implemented and committed.
- Full suite green; all historical runs validate.
- No new state or evidence type introduced.

## Verification Plan

Run the full unittest suite and validate every `harness/runs/*` directory.

## Risks

Closure gate requires handoff frontmatter for new runs; pre-existing completion tests were updated to reflect the new contract.
