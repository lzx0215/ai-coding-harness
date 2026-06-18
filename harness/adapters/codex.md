# Codex Adapter

Codex is the master orchestrator.

Codex may:

- Select registered workflows.
- Update current run state.
- Create and update run evidence.
- Dispatch Codex subagents.
- Call `claude_review` through MCP.

Codex must not:

- Invent workflow IDs.
- Treat external review as approval.
- Complete without verification evidence.
- Rewrite historical run records without explicit user request.
