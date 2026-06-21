---
run_id: 2026-06-21-phase-4-async-substrate-closure
schema_version: 0.1.0
track: Standard
workflow: standard-code-change
---

# Plan

1. Add a terminal async job record with matching input, output, and raw log artifacts.
2. Add an aggregation artifact that consumes the terminal job and classifies it as succeeded.
3. Index `agent-job`, `agent-result`, and `aggregation` evidence in `state.json`.
4. Validate this run and all historical runs.
5. Update memory after verification.
