---
run_id: 2026-06-21-phase-4-live-generic-agent-smoke
schema_version: 0.1.0
track: Standard
workflow: standard-agent-adapter-change
review_required: true
strict_triggers: []
risk_reasons:
  - "Touches agent adapter workflow evidence."
verification_required:
  - "Run-local CLI execution must produce real job artifacts."
  - "The completed run must validate."
---

# Triage

## Track Decision

Standard. The task records a real adapter/CLI execution path and evidence lifecycle, but it does not touch secrets, production state, destructive operations, or permissions.

## Workflow

`standard-agent-adapter-change`.

## Risk Reasons

- The run is source-controlled evidence for Phase 4 behavior.
- Incorrect evidence indexing would weaken the Harness audit trail.

## Review Requirement

Review handling is required before completion. A review waiver is acceptable for this narrow run-record smoke because the repository code change is verified separately by tests and CI.

## Verification Required

- Validate this run with `harness.cli`.
- Assert the raw log contains deterministic live agent stdout.
- Run the relevant async artifact regression test.
