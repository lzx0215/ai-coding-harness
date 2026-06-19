# Task

## Goal

Enter v0.2 by defining the reviewer provenance and downstream nullable metadata consumer design.

## Track

Standard

## Workflow

standard-doc-system-change

## Scope

- Create a v0.2 design spec for reviewer provenance.
- Record this v0.2 startup run without rewriting completed v0.1.1 records.
- Update documentation index and durable progress memory.
- Stop at the spec review gate before writing an implementation plan.

## Non-goals

- Implement adapter, schema, or test changes in this step.
- Change auth, permissions, secrets, production configuration, or external agent permissions.
- Mark `harness_version` or `state_schema_version` as `0.2.0` before a schema migration is designed and implemented.
- Rewrite any completed historical run.

## Acceptance Criteria

- A v0.2 design spec exists and is indexed.
- A current run exists with a valid `state.json`.
- The run is advanced only through valid transitions.
- The next step is explicit user review of the written spec.

## Verification Plan

- Validate this run with `python -m harness.cli validate`.
- Check git diff to confirm only v0.2 startup artifacts and index/progress files changed.

## Risks

- The current state schema only permits `0.1.0`, so this startup run must use the current schema version while designing v0.2.
- If implementation starts before spec review, the workflow would skip the agreed design gate.
