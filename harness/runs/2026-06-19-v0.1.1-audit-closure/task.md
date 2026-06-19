# Task

Close v0.1.1 auditability gaps before starting v0.2.

## User Request

- Detect and record real Claude reviewer identity metadata where available.
- Verify whether `claude --version` exposes a CLI version.
- Inspect real raw review logs for a model name.
- If metadata is unavailable, make the relevant schema fields nullable and document the limitation.
- Regenerate the Claude review adapter lockfile with hashes.
- Add a regression proving hash-locked installation validation passes.
- Run this change through the `standard-agent-adapter-change` workflow and use the harness to review itself.

## Empirical Discovery

- `claude --version` returned `2.1.168 (Claude Code)`.
- Existing raw logs under `harness/runs/2026-06-19-standard-adapter-cli/reviews/` include `modelUsage` keys such as `glm-5.2[1m]`.
- Existing adapter outputs recorded `reviewer_model`, `reviewer_model_version`, and `reviewer_cli_version` as `unknown`.
- Existing `mcp/claude-review/requirements.lock.txt` pins exact versions but does not include package hashes.
