# Agent Result

Write this payload to the job `output.json`. It must validate against `harness/schemas/agent-result.schema.json`.

This template may be indexed as `agent-result` only when the result payload is not promoted into a canonical review artifact. Indexed `agent-result` evidence must validate against the schema and match a terminal `agent-job` evidence entry for the same job.

```json
{
  "run_id": "replace-with-run-id",
  "job_id": "replace-with-job-id",
  "agent": "replace-with-agent-name",
  "adapter": "generic-cli-agent",
  "status": "passed",
  "summary": "One concise paragraph describing the result.",
  "findings": [
    {
      "severity": "medium",
      "title": "Finding title",
      "evidence": "Concrete evidence from inspected files or command output.",
      "recommendation": "Specific recommended action.",
      "file": "optional/path.py",
      "line": 1
    }
  ],
  "evidence": [
    {
      "path": "harness/runs/<run-id>/jobs/<job-id>/output.json",
      "description": "Structured agent result."
    }
  ],
  "not_tested": [
    "State anything material the agent did not verify."
  ],
  "residual_risks": [
    "State any remaining risk after this result."
  ],
  "generated_at": "2026-06-20T00:00:00Z"
}
```

Allowed `status` values: `passed`, `findings`, `failed`, `timeout`, `cancelled`, `schema_invalid`, `not_available`.
