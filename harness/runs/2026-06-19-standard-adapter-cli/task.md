# Task

## Goal

Execute the adjusted S1-S4 route for the Codex-first harness: verify the MCP server path first, add static state/schema regression tests, repair adapter integration gaps found by real Claude runs, add a minimal state CLI, and record a real Standard run.

## Track

Standard

## Workflow

standard-agent-adapter-change

## Scope

- Claude review adapter invocation and wrapper hardening.
- Minimal Harness CLI with `validate` and `advance`.
- Static contract tests for workflow, state, and review mappings.
- Real Claude review smoke and Standard run evidence.

## Non-goals

- No dashboard.
- No async review job system.
- No additional external agent adapters.
- No historical run rewriting.

## Acceptance Criteria

- `python mcp/claude-review/server.py` is actually run before repair decisions.
- Static contract tests cover schema/workflow/state/review mapping drift.
- CLI validates run state and rejects invalid or non-Codex state advancement.
- Real Claude CLI review produces terminal adapter evidence.
- This Standard run has task, triage, plan, diff artifacts, verification, review, handoff, and state.

## Verification Plan

- Run targeted tests for new static and CLI behavior.
- Run full unit test suite.
- Run MCP server import/start smoke.
- Run real Claude review adapter smoke.
- Run real Claude review against this Standard diff.
- Validate this run with `python -m harness.cli validate`.

## Risks

- Real Claude output may vary; adapter must preserve terminal status and raw logs.
- The Standard run is recorded after some implementation work had already started from the user's route adjustment.
