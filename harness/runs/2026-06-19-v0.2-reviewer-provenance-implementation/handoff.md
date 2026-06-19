# Handoff

## What Changed

- State schema compatibility now allows `harness_version` and `state_schema_version` values `0.1.0` or `0.2.0`.
- Claude review output schema now accepts optional `reviewer_provenance`.
- Claude review adapter now emits structured reviewer provenance while preserving scalar compatibility fields.
- Adapter provenance handles deterministic primary model selection, metadata CLI version fallback, explicit model overlap with `modelUsage`, and controlled `unknowns`.
- Documentation and templates now describe the v0.2 provenance contract.
- This run records the first real `0.2.0` Harness state record.

## How It Was Verified

- `python -m unittest discover -s tests -v` -> `68 tests`, `OK (skipped=1)`.
- `python -m harness.cli validate` passed for five historical run records.
- `python -m pip check` -> `No broken requirements found.`
- MCP server import -> `server_import_ok`.
- Optional live hash validation with `HARNESS_RUN_PIP_HASH_CHECK=1` -> `OK`.
- Diff artifacts are UTF-8 without BOM/NUL bytes and `git apply --check --reverse diff.patch` passed.
- Real Claude review through the adapter completed with `status: findings`, no `high` or `critical` findings.
- Final review output included `reviewer_provenance.schema_version: 0.2.0`, `primary_model: glm-5.2[1m]`, and `unknowns: ["model_version", "token_usage"]`.

## What Was Not Verified

- Merge to `master`.
- Push or PR creation.
- Behavior of downstream provenance consumers outside this repository.
- Future token usage normalization.

## Residual Risks

- `reviewer_model` semantics changed for multi-model reviews to mirror deterministic `primary_model`; this is documented but should be considered before merge.
- Output schema can be hardened further for non-empty model converse invariants.
- Some helper edge cases remain follow-up test candidates.
- `token_usage` remains an expected unknown in v0.2 because token normalization is deferred.

## Next Step

Inspect the final real Claude review result before deciding whether to merge `codex/v0.2-state-schema-compat` into `master`.
