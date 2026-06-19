# Triage

## Track

Standard

## Workflow

standard-doc-system-change

## Reason

The task changes Harness documentation, design records, run metadata, and durable progress memory. It does not modify secrets, auth, permissions, production systems, databases, payments, or destructive state/history, so Strict is not required.

## Review Requirement

No external review is required for this design-only startup step. A later implementation that changes schemas, adapter behavior, state management, or completion criteria should request Claude Code review under `harness/core/delegation.md`.
