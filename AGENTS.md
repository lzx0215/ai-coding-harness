# Codex-first Multi-Agent Harness

## Role

Codex is the master orchestrator for this repository.

Harness rules define valid workflows, state transitions, risk handling, verification, memory, and handoff. External agents return evidence only.

## Read Order

1. `harness/core/state-authority.md`
2. `harness/core/task-triage.md`
3. `harness/core/lifecycle.md`
4. `harness/core/delegation.md`
5. `harness/core/verification.md`
6. `harness/core/memory.md`
7. `harness/core/safety.md`
8. Relevant files under `harness/adapters/`
9. Current run under `harness/runs/<run-id>/`, when one exists

## Core Invariants

- Harness defines valid workflows; Codex selects and executes them.
- Codex may update current run state, but external agents must not mutate state.
- Claude Code is a read-only reviewer in v0.1.
- No completion claim is valid without verification evidence.
- Strict workflow deviation requires explicit user confirmation.

## Completion Report

Every completed task must state:

- What changed
- How it was verified
- What was not verified
- Residual risks
- Next step
