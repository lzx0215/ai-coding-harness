# Delegation

## Codex Subagents

Use Codex subagents for read-heavy exploration, test-failure analysis, large document scans, low-coupling subtasks, and review categorization.

## Claude Code Reviewer

Call Claude Code review when:

- A Standard code change is implemented.
- A Strict task needs independent review.
- The user explicitly asks for cross-checking.
- The diff touches auth, security, permissions, secrets, production config, database, payments, privacy-sensitive code, agent adapters, MCP tools, or state management.
- The diff changes public APIs, workflow rules, state schemas, verification behavior, or completion criteria.
- The diff changes at least 3 files or at least 200 lines.
- Required verification was skipped, partially run, or replaced by manual inspection.

## Input Budget

Default limits:

- `max_input_chars = 120000`
- `max_files = 30`
- `max_diff_lines = 2000`
