# Verification

## Commands Run

```powershell
claude --version
python -m pip install pip-tools
python -m piptools compile --generate-hashes --output-file mcp/claude-review/requirements.lock.txt mcp/claude-review/requirements.txt
python -m unittest tests.test_claude_review_adapter.ClaudeReviewAdapterTest.test_normalize_extracts_model_from_model_usage tests.test_claude_review_adapter.ClaudeReviewAdapterTest.test_run_records_detected_cli_version_and_model_usage_metadata tests.test_state_schema.StateSchemaTest.test_schema_rejects_empty_nested_identity_and_evidence_strings tests.test_static_contracts.StaticContractsTest.test_claude_review_output_schema_allows_nullable_identity_metadata tests.test_static_contracts.StaticContractsTest.test_claude_review_adapter_dependencies_are_locked tests.test_static_contracts.StaticContractsTest.test_claude_review_adapter_lockfile_hash_validation_passes -v
python -m unittest discover -s tests -v
python -m harness.cli validate harness/runs/example-fast-doc-change
python -m harness.cli validate harness/runs/2026-06-19-standard-adapter-cli
python -m harness.cli validate harness/runs/2026-06-19-v0.1.1-audit-closure
python -m pip check
$env:HARNESS_RUN_PIP_HASH_CHECK='1'; python -m unittest tests.test_static_contracts.StaticContractsTest.test_claude_review_adapter_lockfile_hash_validation_passes -v
python server.py
```

## Results

- `claude --version` returned `2.1.168 (Claude Code)`.
- Targeted metadata/schema/hash-lock regressions passed: 6 tests, OK.
- Full unittest suite passed after initial implementation: 50 tests, OK.
- Full unittest suite passed after review fixes and additional metadata edge-case coverage: 53 tests, OK.
- Full unittest suite passed after live-pip test gating and CLI precedence fixes: 54 tests, OK with 1 intentionally skipped integration test.
- Harness CLI validation passed for `example-fast-doc-change`, `2026-06-19-standard-adapter-cli`, and this run.
- `python -m pip check` returned `No broken requirements found.`
- Hash-locked install dry-run is covered by an opt-in unittest gated by `HARNESS_RUN_PIP_HASH_CHECK=1`.
- With `HARNESS_RUN_PIP_HASH_CHECK=1`, `test_claude_review_adapter_lockfile_hash_validation_passes` passed and pip resolved all candidates from the lockfile with `--require-hashes --ignore-installed`.
- `python server.py` from `mcp/claude-review` exited 0.
- Import smoke with `mcp/claude-review` on `sys.path` returned `server_import_ok`.
- First real Claude review returned `findings` with one medium issue: the generated lockfile had dropped the `pywin32` Windows environment marker.
- The `pywin32==312 ; platform_system == "Windows"` marker was restored while preserving hashes, and the static dependency contract was tightened to require the marker.
- Lockfile tests and explicit pip hash dry-run passed again after marker restoration.
- Additional metadata edge-case tests now cover CLI version unavailable outputs, explicit model precedence over `modelUsage`, and non-dict `modelUsage`.
- Second real Claude review returned `findings` with one medium issue: the live pip hash test was non-hermetic in the default unit suite.
- The live pip hash test was gated behind `HARNESS_RUN_PIP_HASH_CHECK=1`, while static lockfile hash checks remain in the default suite.
- The hash integration test no longer uses `--no-deps`, so pip can validate dependency closure from the lockfile during the opt-in run.
- `reviewer_cli_version` precedence was changed so the freshly detected `claude --version` value wins over any future JSON metadata field, with a regression test.
- Existing subprocess-run error-path tests were updated to use explicit version-detection side effects and assert `reviewer_cli_version`.
- Final real Claude review returned only low/info findings and no high/critical findings.
- Final review findings were triaged as non-blocking and recorded in `review.md`.

## Expected Failing Regression Before Fix

Before implementation, the targeted regression run failed on:

- `reviewer_model` remaining `unknown` instead of `glm-5.2[1m]`.
- real run metadata returning `schema_invalid` because `claude --version` was not separated from review execution.
- state schema requiring `model`, `model_version`, and `cli_version` to be non-null strings.
- adapter output schema requiring non-null reviewer identity fields.
- static lockfile check finding missing `--hash=sha256:` entries.

## Not Verified

- Cross-platform install behavior for the generated lockfile. The `pywin32` marker is present, but install was only executed on the current Windows/Python 3.12 environment.
- Long-lived MCP client registration through Codex's MCP runtime.
- A clean virtual environment install without using pip's existing cache.
- Non-Windows execution of the opt-in pip hash integration test.
- Structural validation of future `claude --version` output formats beyond the current first-line output.
- Multi-model `modelUsage` aggregation.

## Residual Risks

- Current raw Claude logs expose a model name through `modelUsage`, but do not expose a distinct model version; `reviewer_model_version` remains `null` until the CLI provides a verifiable field.
- The opt-in lockfile hash integration uses real pip and depends on network or pip cache availability.
- Installing `pip-tools` changed the local Python environment for tooling only; project runtime dependencies remain locked in `mcp/claude-review/requirements.lock.txt`.
- `reviewer_cli_version` records the raw first non-empty version line; future version comparison should use a separate parsed field.
- `modelUsage` fallback records the first model key; richer multi-model provenance is deferred to v0.2.
