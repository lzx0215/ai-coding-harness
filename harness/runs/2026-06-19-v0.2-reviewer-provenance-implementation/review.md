# Review

## Review Command

```powershell
python mcp/claude-review/scripts/invoke-claude-reviewer.py --input <absolute claude-review.input.json> --output <absolute claude-review.json> --raw-log <absolute claude-review.raw.log>
```

## Initial Invocation Note

The first invocation used relative `--output` and `--raw-log` paths while `claude-review.input.json` contained absolute paths. The wrapper correctly rejected the mismatch with `status: not_available`, `reason: unsupported_environment`. The review was retried with matching absolute paths.

## Review Iterations

1. First real review returned `findings` with a medium finding that the generated diff artifacts were UTF-16/BOM encoded by PowerShell redirection.
   - Disposition: fixed by regenerating `diff.patch` via `git diff --binary --output=<path>` and writing `changed-files.txt` / `diff-meta.json` with UTF-8 without BOM.
   - Verification: strict UTF-8 decode OK, NUL count `0`, and `git apply --check --reverse diff.patch` exit 0.

2. Second real review returned `findings` with a medium auditability concern that `adapter_version` remains `0.1.0` while `reviewer_provenance.schema_version` is `0.2.0`.
   - Disposition: fixed with commit `37e0f12 docs(review): clarify provenance versioning`.
   - The README now states that `adapter_version` is the adapter wrapper compatibility version and `reviewer_provenance.schema_version` is the provenance contract version.

3. Third real review returned two medium findings:
   - `reviewer_cli_version` metadata fallback was not passed into `reviewer_provenance.cli`.
   - Explicit model overlap with `modelUsage` dropped the primary model's `raw_usage`.
   - Disposition: fixed with commit `753e2b7 fix(review): align provenance metadata`.
   - Regression tests were added first and observed failing before the fix:
     - `test_normalize_uses_metadata_cli_version_in_reviewer_provenance`
     - `test_normalize_preserves_raw_usage_when_explicit_model_overlaps_model_usage`

4. Final real review returned `findings` with no `high` or `critical` findings.
   - Harness disposition: `reviewed` after triage, per `harness/core/state-authority.md`.

## Final Review Summary

- Status: `findings`
- Completed: `true`
- Exit code: `0`
- Reviewer: `claude-code`
- Reviewer model: `glm-5.2[1m]`
- Reviewer model version: `null`
- Reviewer CLI version: `2.1.168 (Claude Code)`
- Review duration: `237.078` seconds

## Final Reviewer Provenance

- `reviewer_provenance.schema_version`: `0.2.0`
- `reviewer_provenance.primary_model`: `glm-5.2[1m]`
- `reviewer_provenance.unknowns`: `model_version`, `token_usage`
- `reviewer_provenance.cli.raw_version`: `2.1.168 (Claude Code)`
- `reviewer_provenance.cli.version`: `2.1.168`

## Final Findings Disposition

### Medium: reviewer_model selection semantics changed for multi-model reviews

Disposition: accepted as intentional v0.2 behavior, non-blocking.

Rationale:

- The approved v0.2 design requires `reviewer_model` to mirror `reviewer_provenance.primary_model`.
- The primary model is selected deterministically from usage totals when complete usage exists.
- `mcp/claude-review/README.md` now documents the selection rule and the dual-versioning contract.
- No high or critical issue is present.

Residual risk:

- Consumers comparing multi-model v0.1 and v0.2 artifacts may observe different `reviewer_model` values. This is documented and must be considered before merge.

### Low: `_reviewer_model` may now be dead code

Disposition: follow-up candidate, non-blocking.

Rationale:

- It is not a correctness issue for v0.2 provenance emission.
- Removing it is cleanup and can be handled after merge-gate review.

### Low: output schema does not enforce converse invariants for non-empty models

Disposition: follow-up candidate, non-blocking.

Rationale:

- Adapter-produced envelopes maintain the invariant.
- This is a schema-hardening improvement for external/schema-only producers.

### Low: `parse_cli_version` rejects pre-release and prefixed version strings

Disposition: accepted as documented behavior, non-blocking.

Rationale:

- `cli.raw_version` remains the audit source of truth.
- `cli.version` is informational and may be `null`.

### Low: helper functions lack direct unit test coverage for edge cases

Disposition: follow-up candidate, non-blocking.

Rationale:

- The main provenance behaviors and the two medium review regressions are covered.
- Edge coverage can be expanded in a later hardening slice.

### Info Findings

Disposition: documented, non-blocking.

## Not Verified By Review

- Merge to `master`.
- Push or pull request creation.
- Production or downstream consumer behavior outside this repository.

## Review Gate

Do not merge this branch automatically. The final real review should be inspected before merge because it is the first end-to-end provenance proof for the v0.2 contract.
