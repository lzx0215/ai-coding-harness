# Verification

## Diff Artifacts

- Command: `git diff --binary master..HEAD --`
- Result: exit 0.
- Scope: implementation commits from `master` merge-base `1dcf556` to branch head `753e2b7`.
- Changed files file: `harness/runs/2026-06-19-v0.2-reviewer-provenance-implementation/artifacts/changed-files.txt`
- Diff metadata file: `harness/runs/2026-06-19-v0.2-reviewer-provenance-implementation/artifacts/diff-meta.json`
- Note: Task 6 run evidence files are intentionally excluded from the review diff so the external review target is the implementation, not the evidence wrapper.

### Artifact Encoding Check

- Command: regenerate `diff.patch` with `git diff --binary --output=<diff.patch> master..HEAD --`.
- Command: write `changed-files.txt` and `diff-meta.json` with `.NET UTF8Encoding(false)`.
- Result: exit 0.
- Byte checks:
  - `diff.patch`: first bytes `64696666`, NUL count `0`, strict UTF-8 decode OK.
  - `changed-files.txt`: first bytes `52454144`, NUL count `0`, strict UTF-8 decode OK.
  - `diff-meta.json`: first bytes `7b0d0a20`, NUL count `0`, strict UTF-8 decode OK.
- Command: `git apply --check --reverse harness/runs/2026-06-19-v0.2-reviewer-provenance-implementation/artifacts/diff.patch`
- Result: exit 0.

## Required Checks

### Unit Tests

- Command: `python -m unittest discover -s tests -v`
- Result: exit 0.
- Summary: `Ran 68 tests in 1.341s`, `OK (skipped=1)`.
- Default skipped test: `test_claude_review_adapter_lockfile_hash_validation_passes`, because live hash validation requires `HARNESS_RUN_PIP_HASH_CHECK=1`.

### Historical Run Validation

- Command: `python -m harness.cli validate harness/runs/example-fast-doc-change`
- Result: exit 0, `valid: harness\runs\example-fast-doc-change`.

- Command: `python -m harness.cli validate harness/runs/2026-06-19-standard-adapter-cli`
- Result: exit 0, `valid: harness\runs\2026-06-19-standard-adapter-cli`.

- Command: `python -m harness.cli validate harness/runs/2026-06-19-v0.1.1-audit-closure`
- Result: exit 0, `valid: harness\runs\2026-06-19-v0.1.1-audit-closure`.

- Command: `python -m harness.cli validate harness/runs/2026-06-19-v0.2-reviewer-provenance-design`
- Result: exit 0, `valid: harness\runs\2026-06-19-v0.2-reviewer-provenance-design`.

- Command: `python -m harness.cli validate harness/runs/2026-06-19-v0.2-spec-amendment`
- Result: exit 0, `valid: harness\runs\2026-06-19-v0.2-spec-amendment`.

### Package Health

- Command: `python -m pip check`
- Result: exit 0, `No broken requirements found.`

### MCP Server Import

- Command: `python -c "import sys; sys.path.insert(0, r'mcp/claude-review'); import server; print('server_import_ok')"`
- Result: exit 0, `server_import_ok`.

## Optional Checks

### Live Pip Hash Validation

- Command: `$env:HARNESS_RUN_PIP_HASH_CHECK='1'; python -m unittest tests.test_static_contracts.StaticContractsTest.test_claude_review_adapter_lockfile_hash_validation_passes -v`
- Result: exit 0.
- Summary: `Ran 1 test in 22.315s`, `OK`.

## Not Verified

- Branch merge to `master` was not performed.
- Push or pull request creation was not performed.
- Review disposition is recorded separately in `review.md`.

## Residual Risks

- Real Claude review is recorded separately in `review.md` after this verification evidence is used as review input.
- Reviewer provenance token counts are intentionally not normalized in this v0.2 slice; `token_usage` is expected in `reviewer_provenance.unknowns`.
