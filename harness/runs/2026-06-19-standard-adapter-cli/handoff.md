# Handoff

## What Changed

- Added `harness.cli` with `validate` and `advance`.
- Added static contract tests for workflow registry, state status enum, and review status mapping.
- Hardened Claude review adapter execution:
  - uses the resolved Claude executable path,
  - reads wrapper input with `utf-8-sig`,
  - passes review prompts on stdin,
  - constrains Claude output with `--system-prompt` and `--json-schema`,
  - keeps `--permission-mode plan` and `--tools ""`,
  - handles `structured_output` from real Claude CLI output.
- Recorded this Standard run with selected-file diff, verification, real Claude review, and state evidence.

## Evidence

- `harness/runs/2026-06-19-standard-adapter-cli/artifacts/diff.patch`
- `harness/runs/2026-06-19-standard-adapter-cli/artifacts/diff.meta.json`
- `harness/runs/2026-06-19-standard-adapter-cli/verification.md`
- `harness/runs/2026-06-19-standard-adapter-cli/reviews/claude-review-final.json`
- `harness/runs/2026-06-19-standard-adapter-cli/reviews/claude-review-final.evidence.json`
- `harness/runs/2026-06-19-standard-adapter-cli/reviews/claude-review-final.raw.log`

## State

completed

## Risks

- Real Codex MCP client runtime was not exercised.
- No CI or clean-machine dependency install was tested.
- Low/info review findings remain for future hardening.

## Next Step

S5 should focus on hardening before adding more adapters: atomic `state.json` writes, evidence path confinement, root dependency locking, and optional CLI entrypoint tests.
