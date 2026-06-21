# Decisions

| Date | Decision | Rationale |
| --- | --- | --- |
| 2026-06-18 | Codex-first orchestration | Codex is the main execution surface; Harness supplies durable rules. |
| 2026-06-18 | Claude Code reviewer is read-only | Reduces risk while enabling independent review evidence. |
| 2026-06-18 | `claude_review` is synchronous in v0.1 | Avoids async job-state complexity. |
| 2026-06-21 | Run lifecycle becomes SOP before skill | Creating runs, advancing state, indexing evidence, and completing handoff is repeatable enough for `harness/core/run-lifecycle-sop.md`; convert it to a Codex skill only after at least two real reuses or explicit user request. |
