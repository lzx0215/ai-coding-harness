# Handoff

## What Changed

- Claude review adapter now records real reviewer identity where available:
  - CLI version from `claude --version`.
  - model name from explicit metadata or `modelUsage`.
  - unavailable model version as `null`.
- Adapter output schema, run state schema, and external review template now allow nullable reviewer identity fields where values cannot be proven.
- `requirements.lock.txt` was regenerated with `--generate-hashes`.
- The `pywin32` Windows environment marker was restored while preserving hashes.
- Lockfile tests now include default static hash checks plus an opt-in live pip hash validation test gated by `HARNESS_RUN_PIP_HASH_CHECK=1`.
- Documentation now instructs hash-locked install and documents nullable/unverifiable reviewer metadata.
- This v0.1.1 work was recorded as a `standard-agent-adapter-change` run with task, triage, plan, diff, verification, review, and handoff evidence.

## Verified

- Targeted metadata/schema/hash-lock regressions passed.
- Full default unittest suite passed: 54 tests, 1 intentionally skipped live-pip integration.
- Opt-in hash integration passed with `HARNESS_RUN_PIP_HASH_CHECK=1`.
- `python -m harness.cli validate` passed for:
  - `harness/runs/example-fast-doc-change`
  - `harness/runs/2026-06-19-standard-adapter-cli`
  - `harness/runs/2026-06-19-v0.1.1-audit-closure`
- `python -m pip check` reported no broken requirements.
- `python server.py` from `mcp/claude-review` exited 0.
- MCP server import smoke returned `server_import_ok`.
- Three real Claude reviews ran through the adapter and captured:
  - `reviewer_model`: `glm-5.2[1m]`
  - `reviewer_model_version`: `null`
  - `reviewer_cli_version`: `2.1.168 (Claude Code)`

## Not Verified

- Cross-platform install outside the current Windows/Python 3.12 environment.
- Clean virtual environment install without pip cache.
- Long-lived MCP client registration through Codex's MCP runtime.
- Multi-model `modelUsage` aggregation semantics.
- Downstream consumers outside this diff that may assume reviewer metadata fields are non-null strings.

## Residual Risks

- `reviewer_model_version` remains `null` until Claude CLI output exposes a distinct verifiable model-version field.
- The opt-in hash validation depends on pip network/cache availability and is skipped by default.
- `reviewer_cli_version` records the raw first non-empty CLI version line; future version gating should parse into a separate field.
- `modelUsage` fallback records the first key; multi-model logs may need a richer metadata shape in v0.2.

## Next Step

v0.1.1 closes the two auditability gaps requested here. v0.2 can start after this commit, with the first v0.2 design item focused on downstream nullable metadata consumers and multi-model reviewer provenance.
