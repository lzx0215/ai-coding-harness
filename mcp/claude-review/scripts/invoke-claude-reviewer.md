# invoke-claude-reviewer Contract

## Runtime

The default runtime is Python 3.12. A Windows `.cmd` shim may call the Python script.

## Command

Run `python mcp/claude-review/scripts/invoke-claude-reviewer.py --input <input-json> --output <output-json> --raw-log <raw-log>`.

## Claude CLI

The wrapper uses:

`claude -p --output-format json --permission-mode plan --tools "" --no-session-persistence --max-budget-usd 1 "<review prompt>"`

## Rules

- Do not allow Claude to edit files.
- Capture stdout and stderr to the raw log.
- Return `not_available` if `claude` is missing or auth fails before model execution.
- Return `timeout` if the process exceeds `timeout_seconds`.
- Return `schema_invalid` if JSON cannot be parsed into the required shape.
