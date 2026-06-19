# Plan

## Deliver

1. Add adapter tests for real CLI version detection and model extraction from `modelUsage`.
2. Add schema tests for nullable unavailable reviewer model metadata.
3. Add a lockfile hash-validation regression using pip `--require-hashes`.
4. Implement reviewer metadata extraction:
   - `reviewer_cli_version` from `claude --version` when the CLI exists.
   - `reviewer_model` from explicit fields or `modelUsage` keys.
   - `reviewer_model_version` remains nullable when no real version field exists.
5. Update JSON schemas and templates to accept null for unavailable reviewer identity fields.
6. Regenerate `mcp/claude-review/requirements.lock.txt` with hashes.
7. Document metadata and lockfile limitations.

## Verify

- Run targeted tests for adapter, schema, and lockfile behavior.
- Run the full unittest suite.
- Validate example and new harness runs with `python -m harness.cli validate`.
- Run `pip install --dry-run --require-hashes` against the lockfile.
- Run `pip check`.
- Run a real Claude review for this Standard adapter change.

## Handoff Criteria

- New run state reaches `completed`.
- Review evidence is recorded.
- Verification evidence names both verified and unverified areas.
- Changes are committed as a focused v0.1.1 audit-closure commit.
