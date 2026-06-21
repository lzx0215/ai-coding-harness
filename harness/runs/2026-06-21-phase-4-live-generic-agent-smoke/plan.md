---
run_id: 2026-06-21-phase-4-live-generic-agent-smoke
schema_version: 0.1.0
workflow: standard-agent-adapter-change
acceptance:
  - "run-generic-agent produces job/input/output/raw.log under this run."
  - "Codex indexes agent-job, agent-result, and aggregation evidence."
  - "The run reaches completed with verification and handoff evidence."
verification:
  - "python -m harness.cli validate harness/runs/2026-06-21-phase-4-live-generic-agent-smoke"
  - "python -m unittest tests.test_async_job_artifacts.Phase4ClosureRunTest.test_phase4_live_run_was_produced_by_run_generic_agent -v"
review_plan:
  - "Use review-waiver.md for this narrow run-record smoke; do not waive future scheduler or adapter code review."
constraints:
  - "External agent output must be structured JSON."
  - "External agent must not edit state.json."
recovery_strategy: "Remove this new run directory and test if the smoke cannot be made valid."
residual_risk_owner: codex
---

# Plan

## Goal

Produce a source-controlled Phase 4 run whose async artifacts are created by the real `run-generic-agent` CLI path.

## Files

- `scripts/agent-smoke.py`
- `jobs/phase4-live-generic-agent/*`
- `jobs/aggregation.json`
- `verification.md`
- `review-waiver.md`
- `handoff.md`
- `state.json`

## Steps

1. Initialize this run with `harness.cli init-run`.
2. Fill task, triage, and plan evidence.
3. Advance to `in_progress`.
4. Execute `run-generic-agent` with `scripts/agent-smoke.py`.
5. Create `jobs/aggregation.json` from the terminal job.
6. Index `agent-job`, `agent-result`, `aggregation`, `verification`, `review-waiver`, and `handoff`.
7. Advance to `completed`.

## Verification

- Validate the run.
- Run the targeted regression test for this live run.

## Rollback

Remove `harness/runs/2026-06-21-phase-4-live-generic-agent-smoke/` and the targeted test assertion if the run cannot be completed.
