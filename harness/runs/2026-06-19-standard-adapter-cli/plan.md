# Plan

## Goal

Execute the adjusted S1-S4 route and leave auditable evidence.

## Steps

1. Run `python mcp/claude-review/server.py` before assuming the server is broken.
2. Add static regression tests for workflow registry, state schema, and review status mapping.
3. Install existing MCP requirements and rerun server startup checks.
4. Add a minimal `harness.cli` module with `validate` and `advance`.
5. Run real Claude review smoke through the wrapper.
6. Fix adapter issues exposed by real Claude smoke runs with regression tests first.
7. Generate selected-file diff artifacts for the Standard run.
8. Run real Claude review against the Standard diff.
9. Run full verification and validate the run state.

## Verification

- `python -m unittest discover -s tests -v`
- `python -m harness.cli validate harness/runs/example-fast-doc-change`
- `python -c "import sys; sys.path.insert(0, r'mcp/claude-review'); import server; print('server_import_ok')"`
- Real wrapper smoke with `invoke-claude-reviewer.py`
- Real Claude review of this run's diff

## Rollback

Revert the adapter, wrapper, CLI, tests, and this run directory together if the integration proves unsuitable.
