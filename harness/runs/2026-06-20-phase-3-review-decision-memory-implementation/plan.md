---
run_id: 2026-06-20-phase-3-review-decision-memory-implementation
schema_version: 0.1.0
workflow: standard-code-change
acceptance:
  - "review-decision.schema.json exists and constrains all dispositions"
  - "validate loads and semantically validates indexed review-decision.json"
  - "advance gates review-related targets on review decision"
  - "advance -> completed enforces handoff and memory closure"
  - "check-ready warns on memory files declared without memory_update"
  - "no new Harness state or evidence type"
verification:
  - "python -m unittest discover -s tests"
  - "validate every harness/runs/* directory"
  - "test_state_schema + evidence vocabulary invariant"
review_plan:
  - "Independent review of the advance gate scope and closure frontmatter requirement"
constraints:
  - "validate never fatal-parses Markdown"
  - "historical runs remain valid without review-decision.json"
  - "review is not a substitute for verification"
recovery_strategy: null
residual_risk_owner: null
---

# Plan

## Goal

Implement Phase 3 from the approved plan, one TDD task at a time, committing after each green cycle.

## Files

- harness/schemas/review-decision.schema.json
- harness/cli.py
- harness/readiness.py
- tests/test_phase3_review_decision.py
- tests/test_phase3_closure.py
- tests/test_harness_cli.py
- tests/test_phase2_readiness.py

## Steps

1. Task 1: review-decision schema + tests.
2. Task 2: validate indexed review-decision evidence.
3. Task 3: advance review-decision transition gate.
4. Task 4: advance -> completed handoff and memory closure.
5. Task 5: check-ready soft memory-declaration warning.
6. Task 6: final verification.

## Verification

Full unittest suite plus historical-run validation plus state/evidence invariants.

## Rollback

Revert the five task commits; the schema and validators are additive and no historical run is migrated.
