---
run_id: 2026-06-23-phase-9a-cross-run-local-queue
schema_version: 0.1.0
track: Strict
workflow: strict-risk-change
review_required: true
strict_triggers:
  - "Cross-run coordination"
  - "Async job ownership boundary"
  - "Claim and recovery behavior"
risk_reasons:
  - "A queue worker can affect jobs owned by multiple run directories."
  - "Incorrect claim behavior could execute or mark a referenced job more than once."
  - "Queue cleanup and recovery must not rewrite owning run history silently."
verification_required:
  - "Focused queue tests"
  - "Full local unit suite"
  - "All source-controlled run validation"
  - "Live local smoke"
  - "External review or recorded review-risk handling"
  - "Remote CI"
---

# Triage

## Track Decision

Strict. The change introduces a cross-run coordination surface and must preserve the invariant that run-local `state.json` remains the authority for each owning run.

## Workflow

`strict-risk-change`.

## Risk Reasons

- Queue entries reference jobs owned by other run directories.
- Worker authorization and atomic claims must prevent duplicate execution.
- Recovery and cleanup are operator decisions and must leave durable audit records.
- Queue records must not become implicit evidence or state-transition authority.

## Review Requirement

External review is required because this touches runtime queue/claim behavior. If the reviewer is unavailable, the run must record that process outcome and enter the appropriate strict decision path rather than claiming normal completion.

## Verification Required

- Unit tests for schema, creation, authorization, execution, CLI, recovery, and cleanup.
- Full local test suite.
- Live source-controlled smoke using two owning runs and one local cross-run queue.
- Validation of every source-controlled run.
- Whitespace check and remote CI.
