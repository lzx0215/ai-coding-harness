# Claude Review MCP Adapter

This adapter exposes one MCP tool: `claude_review`.

The tool runs synchronously from Codex's perspective. It returns a terminal status and writes raw logs and structured review output.

The adapter must not let Claude Code mutate files or Harness state.

## Contract shape

The adapter writes an MCP envelope JSON to `output_file`. The envelope contains:

- Terminal state: `status`, `completed`, optional `reason`, optional `exit_code`, and `duration_seconds`.
- Audit metadata: `harness_version`, `adapter_version`, `prompt_version`, `reviewer`, `reviewer_model`, `reviewer_model_version`, and `reviewer_cli_version`.
- Artifact paths: `output_file`, `raw_log_file`, and, for successful `passed` or `findings` results, `review_file`.

`reviewer_cli_version` is detected from `claude --version` when the CLI can be executed. `reviewer_model` is taken from explicit Claude output metadata or, for current real raw logs, from the first `modelUsage` key. `reviewer_model_version` is nullable because current real raw logs do not expose a distinct model-version field. If a value cannot be proven from CLI output, the adapter records `null` instead of an invented sentinel.

For v0.1, structured review evidence is included directly in the same envelope instead of a nested evidence object. Successful `passed` and `findings` results must include `summary`, `findings`, `tested`, `not_tested`, and `residual_risks`. A `passed` result may have an empty `findings` array. A `findings` result must include at least one finding with `severity`, `title`, `evidence`, and `recommendation`.

Status-specific requirements:

- `not_available` requires `reason` and `completed: false`.
- `timeout`, `failed`, and `schema_invalid` require `completed: false`.
- `passed` and `findings` require `completed: true`.

Input must include `artifact_dir`, the current run's review artifact directory. `output_file`, `review_file`, and `raw_log_file` must resolve under `artifact_dir`; the wrapper rejects paths outside `artifact_dir` with `not_available`, reason `unsupported_environment`.

## Local check

Run `python -m pip install --require-hashes -r mcp/claude-review/requirements.lock.txt`.

Run `python mcp/claude-review/server.py`.
