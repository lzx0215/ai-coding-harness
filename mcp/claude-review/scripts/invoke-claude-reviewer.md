# invoke-claude-reviewer Contract

## Runtime

The default runtime is Python 3.12. A Windows `.cmd` shim may call the Python script.

## Command

Run `python mcp/claude-review/scripts/invoke-claude-reviewer.py --input <input-json> --output <output-json> --raw-log <raw-log>`.

`--output` writes the MCP envelope JSON. For v0.1, the envelope also includes the structured review fields directly: `summary`, `findings`, `tested`, `not_tested`, and `residual_risks`.

The input JSON must provide every write destination:

- `artifact_dir`: current run's review artifact directory.
- `output_file`: MCP envelope JSON destination. This should match `--output`.
- `review_file`: structured review evidence destination for successful `passed` or `findings` results.
- `raw_log_file`: raw stdout/stderr log destination. This should match `--raw-log`.

`output_file`, `review_file`, and `raw_log_file` must resolve under `artifact_dir` after path normalization. If any requested write destination resolves outside `artifact_dir`, the wrapper must not invoke Claude and must reject the request with status `not_available`, reason `unsupported_environment`, and `completed: false`.

For successful `passed` and `findings` results, the wrapper writes `review_file` under `artifact_dir` and also includes the same structured review fields in the MCP envelope written to `--output`.

## Claude CLI

The wrapper uses:

`claude -p --output-format json --system-prompt "<json-only reviewer prompt>" --json-schema "<review schema>" --permission-mode plan --tools "" --no-session-persistence --max-budget-usd 1`

The review prompt is passed on stdin. Do not pass multi-line review content as a command-line argument on Windows; npm `.cmd` shims may not preserve the full prompt reliably.

## Rules

- Do not allow Claude to edit files.
- Capture stdout and stderr to the raw log.
- Return `not_available` if `claude` is missing or auth fails before model execution.
- Return `timeout` if the process exceeds `timeout_seconds`.
- Return `schema_invalid` if JSON cannot be parsed into the required shape.
