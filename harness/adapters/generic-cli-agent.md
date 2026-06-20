# Generic CLI Agent Adapter

Generic CLI agents must receive explicit input files and return structured output files.

They must not mutate Harness state directly.

Codex may index generic async job artifacts using the Phase 4 evidence types
defined in `harness/core/evidence.md`:

- `agent-job` for the job process record
- `agent-result` for an unpromoted result payload
- `aggregation` for a Codex fan-in summary

`agent-result` is intentionally path-checked only in the first Phase 4 slice.
Use an existing canonical review evidence type instead when the result is
promoted into `reviews/`.

Required result fields:

- status
- summary
- findings
- evidence
- not_tested
- residual_risks
