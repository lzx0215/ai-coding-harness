# Triage

## Track

Standard

## Workflow

standard-agent-adapter-change

## Reason

The work changes an MCP adapter wrapper, adapter subprocess invocation, parser behavior, state validation CLI, and tests. It is not destructive and does not touch secrets, auth configuration, production systems, databases, or permissions, so Strict is not required.

## Review Requirement

Claude Code review is required because the diff touches MCP adapter behavior, state management, review output parsing, and completion evidence.
