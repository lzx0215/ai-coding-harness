---
run_id: 2026-06-22-phase-6-scheduler-watch-mode
schema_version: 0.1.0
waiver_scope: "Run-record-only live scheduler watch smoke artifacts."
waiver_reason: "No runtime implementation changed; this run documents an already-implemented bounded watch scheduler path."
not_waived:
  - "harness/cli.py runtime implementation changes."
  - "State schema changes."
  - "Evidence validation changes."
  - "CI or packaging changes."
  - "tests/test_async_job_artifacts.py."
  - "README.md."
  - "docs/INDEX.md."
  - "harness/memory/progress.md."
residual_risks:
  - "Heartbeat is observational only."
  - "Stop requests are cooperative and do not interrupt running jobs."
  - "Double-claim risk remains if multiple workers are launched against the same run."
owner: codex
---

# Review Waiver

## Decision

External review is waived only for run-record artifacts under `harness/runs/2026-06-22-phase-6-scheduler-watch-mode/`. The task does not change scheduler runtime implementation, schemas, or adapter execution behavior.

## Scope

This waiver covers only:

- `harness/runs/2026-06-22-phase-6-scheduler-watch-mode/`

## Not Waived

Runtime scheduler changes, state schema changes, evidence validation behavior, CI changes, packaging changes, durable documentation updates, and tests still require normal review handling.

Spec and quality review on the implementation branch cover the related non-run-record files:

- `tests/test_async_job_artifacts.py`
- `README.md`
- `docs/INDEX.md`
- `harness/memory/progress.md`

## Residual Risks

Heartbeat metadata is observational only. Stop requests are cooperative and do not interrupt running jobs. Double-claim risk remains if multiple workers are launched against the same run.
