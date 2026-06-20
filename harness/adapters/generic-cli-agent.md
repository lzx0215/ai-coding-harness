# Generic CLI Agent Adapter

Generic CLI agents must receive explicit input files and return structured output files.

They must not mutate Harness state directly.

## Local Orchestration

Codex may run a generic CLI agent as a run-local async job:

```powershell
python -m harness.cli run-generic-agent --agent <agent-name> <run-dir> <job-id> -- <command> [args...]
```

The harness creates:

```text
<run-dir>/jobs/<job-id>/
  job.json
  input.json
  output.json
  raw.log
```

The command receives explicit file paths through environment variables:

- `HARNESS_AGENT_INPUT_FILE`
- `HARNESS_AGENT_OUTPUT_FILE`
- `HARNESS_AGENT_RAW_LOG_FILE`
- `HARNESS_RUN_ID`
- `HARNESS_JOB_ID`
- `HARNESS_AGENT`
- `HARNESS_AGENT_ADAPTER`

The command must write `HARNESS_AGENT_OUTPUT_FILE`. The harness captures stdout/stderr in `raw.log`, updates `job.json`, and does not mutate `state.json`.

The command runs with the job directory as its working directory. This reduces accidental writes to the repository root, but it is not a security sandbox: Codex must invoke only trusted commands. `raw.log` stores unredacted stdout/stderr and must be reviewed before being indexed or committed when secrets may be present.

## Result Contract

`output.json` must validate against `harness/schemas/agent-result.schema.json`.

## Evidence Indexing

Codex may index generic async job artifacts using the Phase 4 evidence types
defined in `harness/core/evidence.md`:

- `agent-job` for the job process record
- `agent-result` for an unpromoted result payload
- `aggregation` for a Codex fan-in summary

Use an existing canonical review evidence type instead when the result is promoted into `reviews/`.

Required result fields:

- run_id
- job_id
- agent
- adapter
- status
- summary
- findings
- evidence
- not_tested
- residual_risks
- generated_at

Allowed result statuses:

- passed
- findings
- failed
- timeout
- cancelled
- schema_invalid
- not_available

Codex may index a valid `output.json` as `agent-result` evidence only when it has a matching terminal `agent-job` evidence entry for the same `job_id`.
