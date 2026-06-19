# Triage

## Track

Standard.

## Workflow

`standard-agent-adapter-change`

## Rationale

The task changes MCP adapter behavior, adapter output schema, harness state schema metadata allowances, dependency locking, and regression tests. It is non-destructive and does not expand external agent permissions, so Strict escalation is not required.

## Review Requirement

Claude Code review is required because the diff touches agent adapter behavior, review metadata, schemas, dependency reproducibility, and audit evidence.

## Non-Goals

- Do not start v0.2 scope.
- Do not rewrite historical run records.
- Do not change Claude Code from read-only reviewer behavior.
- Do not add new workflow IDs.
