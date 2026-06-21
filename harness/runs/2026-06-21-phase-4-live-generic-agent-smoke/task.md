---
run_id: 2026-06-21-phase-4-live-generic-agent-smoke
schema_version: 0.1.0
track: Standard
workflow: standard-agent-adapter-change
owner: codex
requested_outcome: "Prove Phase 4 with a run produced by the real run-generic-agent CLI path."
scope:
  - "Create a source-controlled Phase 4 run record."
  - "Launch a generic CLI agent through harness.cli run-generic-agent."
  - "Index the terminal job, agent result, aggregation, verification, review handling, and handoff evidence."
non_goals:
  - "Do not implement a scheduler or background worker."
  - "Do not rewrite historical run records."
constraints:
  - "External agents must not mutate state.json."
  - "Codex remains responsible for evidence indexing and state transitions."
---

# Task

## Goal

Create a real Phase 4 run proving that `run-generic-agent` can produce a terminal job artifact, structured agent result, and raw log that Codex consumes as evidence.

## Track

Standard.

## Workflow

`standard-agent-adapter-change`.

## Scope

- Initialize the run with the Harness CLI.
- Execute `run-generic-agent` with a deterministic local smoke agent script.
- Create a Codex aggregation artifact from the terminal job.
- Index evidence and advance the run through completion.

## Non-goals

- Scheduler implementation.
- Cloud queue integration.
- Historical migration of earlier Phase 4 closure records.

## Acceptance Criteria

- `jobs/phase4-live-generic-agent/job.json` exists and is terminal.
- `jobs/phase4-live-generic-agent/output.json` validates as `agent-result`.
- `jobs/phase4-live-generic-agent/raw.log` contains `phase4 live generic agent wrote output`.
- `jobs/aggregation.json` is indexed as `aggregation`.
- `state.json` reaches `completed`.

## Verification Plan

- `python -m harness.cli validate harness/runs/2026-06-21-phase-4-live-generic-agent-smoke`
- `python -m unittest tests.test_async_job_artifacts.Phase4ClosureRunTest.test_phase4_live_run_was_produced_by_run_generic_agent -v`

## Risks

- This proves the local generic-agent CLI path, not a scheduler.
- The smoke agent is deterministic and local; it is not an independent reviewer.
