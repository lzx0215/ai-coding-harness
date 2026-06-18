from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from adapter import run_claude_review


mcp = FastMCP("claude-review")


@mcp.tool()
def claude_review(payload: dict) -> dict:
    """Run a synchronous read-only Claude Code review."""
    return run_claude_review(payload)


if __name__ == "__main__":
    mcp.run()
