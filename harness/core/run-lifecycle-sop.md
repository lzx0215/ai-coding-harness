# Run Lifecycle SOP

## Purpose

Use this SOP when a task needs a source-controlled Harness run record. The run is evidence; it does not replace verification.

## When To Use

- The task changes Harness rules, state, schemas, adapters, CI, package behavior, or long-lived project documentation.
- The task needs explicit audit evidence beyond a final chat summary.
- The task exercises async jobs, external reviewers, risk acceptance, or handoff closure.

Do not create a run for trivial typo fixes unless the user explicitly asks.

## Steps

1. Create the run:

```powershell
python -m harness.cli init-run harness/runs/<run-id> --run-id <run-id> --track <Fast|Standard|Strict> --workflow <workflow-id> --base-commit <commit>
```

2. Fill `task.md`, `triage.md`, and `plan.md` with concrete scope, non-goals, verification, review handling, and residual risks.

3. Advance state only through the CLI:

```powershell
python -m harness.cli advance harness/runs/<run-id> triaged
python -m harness.cli advance harness/runs/<run-id> planned
python -m harness.cli advance harness/runs/<run-id> in_progress
```

4. Produce artifacts. For a generic async agent, run:

```powershell
python -m harness.cli run-generic-agent --agent <agent-name> --timeout-seconds <seconds> harness/runs/<run-id> <job-id> -- <command>
```

5. Index consumed evidence explicitly. Index terminal `agent-job` before `agent-result` or `aggregation`:

```powershell
python -m harness.cli index-evidence harness/runs/<run-id> agent-job jobs/<job-id>/job.json --description "Terminal async job consumed by Codex."
python -m harness.cli index-evidence harness/runs/<run-id> agent-result jobs/<job-id>/output.json --description "Structured async agent result consumed by Codex."
python -m harness.cli index-evidence harness/runs/<run-id> aggregation jobs/aggregation.json --description "Codex fan-in aggregation."
```

6. Advance to `implemented`, run verification, then write and index `verification.md`:

```powershell
python -m harness.cli advance harness/runs/<run-id> implemented
python -m harness.cli validate harness/runs/<run-id>
python -m harness.cli index-evidence harness/runs/<run-id> verification verification.md --description "Verification record."
```

7. Handle review. Index a real review artifact when available. Use `review-waiver.md` only when the waiver is explicitly scoped and residual risk is recorded:

```powershell
python -m harness.cli index-evidence harness/runs/<run-id> review-waiver review-waiver.md --description "Scoped review waiver."
```

8. Write `handoff.md` with frontmatter closure fields. If long-term memory changed, set `memory_update` and list `memory_files`.

9. Index handoff and complete:

```powershell
python -m harness.cli index-evidence harness/runs/<run-id> handoff handoff.md --description "Completion handoff."
python -m harness.cli advance harness/runs/<run-id> verified
python -m harness.cli advance harness/runs/<run-id> reviewed
python -m harness.cli advance harness/runs/<run-id> completed
```

10. Final validation:

```powershell
python -m harness.cli validate harness/runs/<run-id>
```

## Skill Escalation Rule

Keep this as an SOP until the workflow is reused at least twice or the user explicitly asks for a reusable Codex skill. A skill should encode stable repeated behavior, not one-off project cleanup.
