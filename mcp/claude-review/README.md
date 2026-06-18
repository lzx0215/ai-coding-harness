# Claude Review MCP Adapter

This adapter exposes one MCP tool: `claude_review`.

The tool runs synchronously from Codex's perspective. It returns a terminal status and writes raw logs and structured review output.

The adapter must not let Claude Code mutate files or Harness state.

## Local check

Run `python -m pip install -r mcp/claude-review/requirements.txt`.

Run `python mcp/claude-review/server.py`.
