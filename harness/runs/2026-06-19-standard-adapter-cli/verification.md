# Verification

## Commands Run

```powershell
python mcp/claude-review/server.py
python -m unittest tests.test_static_contracts -v
python -m pip install -r mcp/claude-review/requirements.txt
python -c "import sys; sys.path.insert(0, r'mcp/claude-review'); import server; print('server_import_ok')"
python -m unittest tests.test_harness_cli -v
python -m harness.cli validate harness/runs/example-fast-doc-change
python -m unittest discover -s tests -v
python mcp/claude-review/scripts/invoke-claude-reviewer.py --input <temp-input> --output <temp-output> --raw-log <temp-raw-log>
python mcp/claude-review/scripts/invoke-claude-reviewer.py --input harness/runs/2026-06-19-standard-adapter-cli/reviews/claude-review-final.input.json --output harness/runs/2026-06-19-standard-adapter-cli/reviews/claude-review-final.json --raw-log harness/runs/2026-06-19-standard-adapter-cli/reviews/claude-review-final.raw.log
python mcp/claude-review/server.py
python -m harness.cli validate harness/runs/2026-06-19-standard-adapter-cli
python -m harness.cli validate harness/runs/example-fast-doc-change
```

## Results

- Initial server run failed before dependency installation with `ModuleNotFoundError: No module named 'mcp'`.
- After installing `mcp/claude-review/requirements.txt`, direct server execution no longer failed at import and stayed running until the short smoke timeout.
- Server import smoke returned `server_import_ok`.
- Static contract tests passed.
- CLI tests passed.
- Example Fast run validation passed.
- Full unit suite passed with 36 tests.
- Real Claude wrapper smoke produced terminal `findings`, wrote `output_file`, `review_file`, and `raw_log_file`, and reviewed the embedded smoke diff.
- Real Claude review of this Standard diff completed with terminal `findings` and no high or medium findings. Final review evidence is in `harness/runs/2026-06-19-standard-adapter-cli/reviews/claude-review-final.evidence.json`; raw log is in `harness/runs/2026-06-19-standard-adapter-cli/reviews/claude-review-final.raw.log`.
- Final `python mcp/claude-review/server.py` run exited 0 locally after dependency installation.
- `python -m harness.cli validate harness/runs/2026-06-19-standard-adapter-cli` passed.
- `python -m harness.cli validate harness/runs/example-fast-doc-change` passed.

## Not Verified

- No long-lived MCP client session was exercised through Codex's MCP runtime.
- No cloud or CI environment was tested.
- Low/info review findings were not all fixed in this pass.

## Residual Risks

- Claude output can vary across versions and models, so schema-constrained parsing still needs monitoring.
- The local `python -m pip install` changed the current Python environment but did not add a root dependency lockfile.
- `advance_run` still writes directly to `state.json` rather than through an atomic temp-file replace.
- Evidence path validation checks existence but does not yet enforce path confinement.
