# Documentation Index

## Entry Point

- `README.md` - Chinese project overview, quick start, and current scaffold status.
- `AGENTS.md` - Codex entrypoint and read order.

## Specs

- `docs/superpowers/specs/2026-06-18-codex-first-multi-agent-harness-design.md` - Codex-first Multi-Agent Harness v0.1 design.
- `docs/superpowers/specs/2026-06-19-v0.2-reviewer-provenance-design.md` - v0.2 reviewer provenance and nullable metadata consumer design.
- `docs/superpowers/specs/2026-06-19-phase-1-local-run-closure-design.md` - Phase 1 local run/state closure hardening design.
- `docs/superpowers/specs/2026-06-19-phase-4-async-multi-agent-design.md` - Phase 4 async multi-agent job and aggregation design.
- `docs/superpowers/specs/2026-06-20-phase-2-run-definition-evidence-design.md` - Phase 2 run definition, frontmatter, and evidence helper design.
- `docs/superpowers/specs/2026-06-20-phase-3-review-decision-memory-design.md` - Phase 3 review decision, handoff, and memory closure design.

## Plans

- `docs/superpowers/plans/2026-06-18-codex-first-multi-agent-harness-implementation.md` - Implementation plan for the v0.1 scaffold.
- `docs/superpowers/plans/2026-06-19-phase-1-local-run-closure-implementation.md` - Implementation plan for Phase 1 local run closure hardening.
- `docs/superpowers/plans/2026-06-20-phase-4-async-job-substrate-implementation.md` - Implementation plan for the first Phase 4 async job substrate slice.
- `docs/superpowers/plans/2026-06-19-v0.2-reviewer-provenance-implementation.md` - Implementation plan for v0.2 reviewer provenance and state schema compatibility.
- `docs/superpowers/plans/2026-06-19-v0.2.1-reviewer-provenance-hardening.md` - Follow-up hardening queue for v0.2.1 reviewer provenance cleanup and schema edge cases.
- `docs/superpowers/plans/2026-06-20-phase-2-run-definition-evidence-implementation.md` - Implementation plan for Phase 2 run definition, readiness checks, and evidence helper commands.

## Harness

- `harness/core/` - Agent-neutral Harness rules.
- `harness/adapters/` - Agent-specific adapter rules.
- `harness/templates/` - Copyable task and evidence templates.
- `harness/schemas/` - JSON schemas for machine-checkable artifacts, including run state, async jobs, agent results, and aggregation.
- `harness/memory/` - Curated long-term memory.
- `harness/runs/` - Per-task run records and evidence.
