# Claude Review MCP Adapter

This adapter exposes one MCP tool: `claude_review`.

The tool runs synchronously from Codex's perspective. It returns a terminal status and writes raw logs and structured review output.

The adapter must not let Claude Code mutate files or Harness state.

## Contract shape

The adapter writes an MCP envelope JSON to `output_file`. The envelope contains:

- Terminal state: `status`, `completed`, optional `reason`, optional `exit_code`, and `duration_seconds`.
- Audit metadata: `harness_version`, `adapter_version`, `prompt_version`, `reviewer`, `reviewer_model`, `reviewer_model_version`, and `reviewer_cli_version`.
- Artifact paths: `output_file`, `raw_log_file`, and, for successful `passed` or `findings` results, `review_file`.

`reviewer_cli_version` is detected from `claude --version` when the CLI can be executed. v0.2 also records optional `reviewer_provenance` with `schema_version: "0.2.0"`, CLI metadata, all observed model names, deterministic `primary_model`, and controlled `unknowns`.

`adapter_version` remains the adapter wrapper compatibility version. `reviewer_provenance.schema_version` is the provenance contract version and is the field consumers should use to detect v0.2 provenance support.

The compatibility fields remain present. `reviewer_model` mirrors `reviewer_provenance.primary_model` when provenance exists. For multi-model reviews, `primary_model` is selected from complete `modelUsage` entries by largest `inputTokens + outputTokens` total, with alphabetical tie-breaks. If no model has complete usage but model names are present, the first sorted model name is selected. If provenance exists but `primary_model` is `null`, consumers must distinguish that from old artifacts that have no `reviewer_provenance` field.

This v0.2 slice does not normalize token counts into `usage.input_tokens` or `usage.output_tokens`. When normalized token counts are absent, `token_usage` appears in `reviewer_provenance.unknowns` for every v0.2 review output. This is expected and not an error condition.

`raw_usage` preserves the original per-model usage object from Claude output for audit purposes. Treat it as opaque pass-through metadata; consumers must not depend on a stable key set or nested shape.

For v0.1, structured review evidence is included directly in the same envelope instead of a nested evidence object. Successful `passed` and `findings` results must include `summary`, `findings`, `tested`, `not_tested`, and `residual_risks`. A `passed` result may have an empty `findings` array. A `findings` result must include at least one finding with `severity`, `title`, `evidence`, and `recommendation`.

Status-specific requirements:

- `not_available` requires `reason` and `completed: false`.
- `timeout`, `failed`, and `schema_invalid` require `completed: false`.
- `passed` and `findings` require `completed: true`.

Input must include `artifact_dir`, the current run's review artifact directory. `output_file`, `review_file`, and `raw_log_file` must resolve under `artifact_dir`; the wrapper rejects paths outside `artifact_dir` with `not_available`, reason `unsupported_environment`.

## Local check

Run `python -m pip install --require-hashes -r mcp/claude-review/requirements.lock.txt`.

Run `python mcp/claude-review/server.py`.
