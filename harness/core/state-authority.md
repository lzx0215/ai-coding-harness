# State Authority

## Authority

Harness defines valid states and transitions. Codex executes transitions for the current run. External agents return evidence only.

## Normal States

`draft -> triaged -> planned -> in_progress -> implemented -> verified -> reviewing -> reviewed -> completed`

## Exceptional States

- `blocked`
- `needs_user_decision`
- `failed_verification`
- `review_blocked`
- `review_failed`
- `review_timeout`
- `review_schema_invalid`
- `external_review_unavailable`
- `risk_accepted`

## Transition Rules

- `current_workflow` must be present in the workflow registry.
- `review_failed` means process failure, not blocking findings.
- Blocking findings use `review_blocked`.
- `timeout` and `not_available` are adapter statuses, not completion evidence.
- Historical run records are append-only unless the user explicitly requests correction.

## Resume

On resume, Codex must read `state.json`, validate it against `harness/schemas/state.schema.json`, verify evidence paths, and continue only from a valid transition.
