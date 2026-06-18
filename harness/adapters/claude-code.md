# Claude Code Adapter

Claude Code v0.1 is a read-only external reviewer.

## Invocation

Codex calls Claude only through MCP tool `claude_review`.

## Forbidden

- No file mutation
- No Harness state mutation
- No workflow decisions
- No completion approval

## Terminal Status Mapping

| MCP status | Harness state effect |
| --- | --- |
| `passed` | `reviewed` |
| `findings` with no high or critical findings | `reviewed` after triage |
| `findings` with high or critical findings | `review_blocked` |
| `failed` | `review_failed` |
| `timeout` | `review_timeout` |
| `schema_invalid` | `review_schema_invalid` |
| `not_available` | `external_review_unavailable` |

## Timeout

Timeout is not a pass. Standard tasks may retry once with reduced scope. Strict tasks require user decision.
