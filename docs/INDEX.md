# Documentation Index

## Entry Point

- `README.md` - Chinese project overview, quick start, and current scaffold status.
- `AGENTS.md` - Codex entrypoint and read order.

## Current Status

- Phase 3 review decision and memory closure plus follow-up provenance hardening are merged into `master`: indexed `review-decision.json` evidence is schema/semantically validated, review-related transitions are gated by Codex decisions where required, and completion requires handoff/memory closure metadata.
- Phase 4 async job substrate is implemented in the source tree: run-local job, agent-result, and aggregation schemas are available; consumed async job evidence and aggregation evidence are validated; Standard and Strict unavailable-review policy is enforced.
- A formal closure run exists at `harness/runs/2026-06-21-phase-4-async-substrate-closure/`; a live `run-generic-agent` smoke run exists at `harness/runs/2026-06-21-phase-4-live-generic-agent-smoke/`.
- Phase 5.2 local scheduler smoke is implemented and exercised by `harness/runs/2026-06-22-phase-5-live-scheduler-smoke/`, covering `queue-generic-agent`, `run-scheduler --once`, and `aggregate-jobs`. Residual risks: local single-process scheduler smoke only; watch mode, multi-worker concurrency, cloud queue, and stale-running recovery are unverified; orphaned running jobs are skipped, not recovered.
- Phase 6 bounded local scheduler watch mode is exercised by `harness/runs/2026-06-22-phase-6-scheduler-watch-mode/`, covering `queue-generic-agent`, bounded `run-scheduler --watch`, scheduler `worker.json` / `heartbeat.json` / JSONL `events.log`, `stop-scheduler`, and `aggregate-jobs`. External Claude review is indexed with no medium/high/critical findings remaining. Residual risks: heartbeat is observational only, stop is cooperative, remote Actions has not run for this branch, and double-claim risk remains without multi-worker claim locking.
- Team-repeatable validation is now defined by `.github/workflows/ci.yml` and `pyproject.toml` with editable tests, non-editable package smoke, packaged console-script run validation, and merge-base scoped whitespace checks.

## Specs

- `docs/superpowers/specs/2026-06-18-codex-first-multi-agent-harness-design.md` - Codex-first Multi-Agent Harness v0.1 design.
- `docs/superpowers/specs/2026-06-19-v0.2-reviewer-provenance-design.md` - v0.2 reviewer provenance and nullable metadata consumer design.
- `docs/superpowers/specs/2026-06-19-phase-1-local-run-closure-design.md` - Phase 1 local run/state closure hardening design.
- `docs/superpowers/specs/2026-06-19-phase-4-async-multi-agent-design.md` - Phase 4 async multi-agent job and aggregation design.
- `docs/superpowers/specs/2026-06-21-phase-5-live-async-worker-scheduler-design.md` - Phase 5.2 live local async scheduler design.
- `docs/superpowers/specs/2026-06-22-phase-6-scheduler-background-worker-design.md` - Phase 6 scheduler watch mode and background worker design.
- `docs/superpowers/specs/2026-06-20-phase-2-run-definition-evidence-design.md` - Phase 2 run definition, frontmatter, and evidence helper design.
- `docs/superpowers/specs/2026-06-20-phase-3-review-decision-memory-design.md` - Phase 3 review decision, handoff, and memory closure design.

## Plans

- `docs/superpowers/plans/2026-06-18-codex-first-multi-agent-harness-implementation.md` - Implementation plan for the v0.1 scaffold.
- `docs/superpowers/plans/2026-06-19-phase-1-local-run-closure-implementation.md` - Implementation plan for Phase 1 local run closure hardening.
- `docs/superpowers/plans/2026-06-20-phase-4-async-job-substrate-implementation.md` - Implementation plan for the first Phase 4 async job substrate slice.
- `docs/superpowers/plans/2026-06-21-phase-5-live-async-worker-scheduler-implementation.md` - Implementation plan for the Phase 5.2 live local scheduler slice.
- `docs/superpowers/plans/2026-06-22-phase-6-scheduler-background-worker-implementation.md` - Implementation plan for the Phase 6 scheduler watch/background-worker slice, including Task 7 live run closure.
- `docs/superpowers/plans/2026-06-19-v0.2-reviewer-provenance-implementation.md` - Implementation plan for v0.2 reviewer provenance and state schema compatibility.
- `docs/superpowers/plans/2026-06-19-v0.2.1-reviewer-provenance-hardening.md` - Follow-up hardening queue for v0.2.1 reviewer provenance cleanup and schema edge cases.
- `docs/superpowers/plans/2026-06-20-phase-2-run-definition-evidence-implementation.md` - Implementation plan for Phase 2 run definition, readiness checks, and evidence helper commands.

## Harness

- `harness/core/` - Agent-neutral Harness rules.
- `harness/core/evidence.md` - Controlled evidence vocabulary and Phase 4 async evidence contract.
- `harness/core/run-lifecycle-sop.md` - SOP for creating runs, advancing state, indexing evidence, and completing handoff before considering a reusable skill.
- `harness/adapters/` - Agent-specific adapter rules.
- `harness/templates/` - Copyable task and evidence templates.
- `harness/schemas/` - JSON schemas for machine-checkable artifacts, including run state, async jobs, agent results, and aggregation.
- `harness/memory/` - Curated long-term memory.
- `harness/runs/` - Per-task run records and evidence.
