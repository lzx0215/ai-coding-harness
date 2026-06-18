# Codex-first Multi-Agent Harness v0.1 Design

## Summary

This design defines a Codex-first multi-agent harness.

Codex is the master orchestrator. Harness rules define valid workflows, state transitions, risk handling, verification, memory, and handoff. Claude Code is the first external agent in v0.1 and acts only as a read-only reviewer through an MCP adapter.

## Goals

- Make Codex the primary orchestration agent.
- Make Harness the rule, state, template, audit, and memory layer.
- Use Claude Code as an external read-only reviewer.
- Call Claude Code through an MCP tool, not ad hoc command construction.
- Preserve review, verification, and handoff evidence per run.
- Keep long-term memory curated and separate from raw run logs.
- Leave a clean path for future agent adapters.

## Non-goals

- Build a full harness CLI.
- Build an async job system.
- Run multiple external agents in parallel.
- Let Claude Code write files.
- Let Claude Code mutate Harness state.
- Let Claude Code decide workflow or approve completion.
- Build a dashboard or UI.
- Build cloud orchestration.
- Auto-integrate arbitrary agents.
- Build historical run editing tools.

## Authority Model

Authority is layered.

| Layer | Authority |
| --- | --- |
| User | Final authorization and explicit overrides. |
| Harness Rules | Workflow, state, risk, verification, and memory authority. |
| Codex | Master orchestrator and current-run state executor. |
| Claude Code | External read-only reviewer that returns evidence. |
| MCP Adapter | Tool boundary for invocation, timeout, logging, and schema validation. |
| Hooks | Validation, logging, blocking, or reminders. Hooks do not define workflow. |

Core invariants:

- Harness defines valid workflows.
- Codex selects and executes workflows using Harness rules.
- Codex may update only current run state and allowed memory files.
- External agents must not mutate Harness state.
- Claude review is evidence, not approval.
- No completion claim is valid without verification evidence.
- Historical run records are append-only by default.
- Strict workflow deviation requires user confirmation.

## State Model

Normal states:

```text
draft
-> triaged
-> planned
-> in_progress
-> implemented
-> verified
-> reviewed
-> completed
```

Exceptional states:

```text
blocked
needs_user_decision
failed_verification
failed_review
review_timeout
review_schema_invalid
review_not_available
risk_accepted
```

State rules:

- Codex may update current run state.
- Codex may append memory.
- Codex must not rewrite Harness core rules unless explicitly requested.
- Codex must not rewrite historical run records except explicit correction.
- Claude Code must not mutate state.
- Claude Code must not decide workflow.
- Claude Code must not approve completion.

## Repository Structure

Target v0.1 structure:

```text
AGENTS.md
harness/
  core/
    state-authority.md
    task-triage.md
    lifecycle.md
    delegation.md
    verification.md
    memory.md
    safety.md
  adapters/
    codex.md
    claude-code.md
    generic-cli-agent.md
  templates/
    task.md
    plan.md
    agent-brief.md
    agent-result.md
    review-result.json
    verification.md
    handoff.md
  memory/
    context.md
    progress.md
    risks.md
    decisions.md
  runs/
.codex/
  config.toml
  agents/
  hooks/
mcp/
  claude-review/
    README.md
    schema/
      claude-review-input.schema.json
      claude-review-output.schema.json
    scripts/
      invoke-claude-reviewer.ps1
```

Layer responsibilities:

- `AGENTS.md`: Codex entrypoint, high-priority orchestration rules, and read order.
- `harness/core/*`: Agent-neutral workflow, state, safety, verification, delegation, and memory rules.
- `harness/adapters/*`: Agent-specific implementation notes.
- `harness/templates/*`: Copyable task, review, verification, handoff, and agent result templates.
- `harness/memory/*`: Long-term distilled context, progress, risks, and decisions.
- `harness/runs/<run-id>/*`: Per-task evidence and state.
- `.codex/*`: Codex implementation layer for agents, config, hooks, and MCP registration.
- `mcp/claude-review/*`: Claude Code reviewer adapter.

## Run Record Structure

Each run should have a stable evidence directory:

```text
harness/runs/2026-06-18-001/
  task.md
  triage.md
  plan.md
  agent-briefs/
    claude-reviewer.md
  artifacts/
    diff.patch
    command-output.log
  reviews/
    claude-review.json
    claude-review.raw.log
    codex-review.md
  verification.md
  handoff.md
  state.json
```

Minimal `state.json`:

```json
{
  "run_id": "2026-06-18-001",
  "status": "draft",
  "track": "Standard",
  "current_workflow": "standard-code-change",
  "owner": "codex",
  "external_agents": [
    {
      "name": "claude-code",
      "role": "reviewer",
      "state_access": "none"
    }
  ],
  "evidence": []
}
```

## Lifecycle

General lifecycle:

```text
Discover -> Define -> Deliver -> Verify -> Review -> Handoff -> Improve
```

Task tracks:

| Track | Applies to | Default workflow |
| --- | --- | --- |
| Fast | Typos, small copy changes, small formatting changes, low-risk edits. | Execute directly, lightly verify, record what was not verified. |
| Standard | Normal code changes, multi-file edits, features, refactors, documentation systems. | Define target and acceptance, plan, implement, verify, review, handoff. |
| Strict | Deletion, security, permissions, auth, secrets, production, database, payments, irreversible operations. | Confirm scope, non-goals, recovery strategy, verification plan, and residual risk before execution. |

Codex responsibilities:

1. Read `AGENTS.md` and relevant `harness/core` rules.
2. Triage task track.
3. Create or update the current run.
4. Select a valid Harness workflow.
5. Decide whether to use subagents or external agents.
6. Collect evidence.
7. Update current run state.
8. Report next steps or completion status.

Codex must not:

- Skip Strict confirmation.
- Claim completion without verification evidence.
- Let external agents mutate state.
- Deviate from workflow without recording the reason.
- Treat templates as completion evidence.

## Claude Code Reviewer

Claude Code v0.1 role:

- Read-only reviewer.
- No file mutation.
- No state mutation.
- No workflow decision.
- No completion approval.

Claude reviewer is called when:

- A Standard code change is implemented.
- A Strict task needs independent review before or after execution.
- Codex is uncertain about implementation risk.
- The user explicitly asks for cross-checking.

Claude reviewer is normally not called for:

- Pure Fast copy changes.
- Tasks without a diff or clear review target.
- Low-risk tasks where the user requests fast handling.

Claude reviewer receives:

- `task.md`
- `plan.md`
- `diff.patch` or changed file list
- `verification.md`
- review scope
- output schema

Claude reviewer returns only:

- findings
- severity
- evidence
- recommendations
- tested / not tested
- residual risks

## MCP Tool Contract: `claude_review`

Codex must call Claude Code through a stable MCP tool:

```text
Codex
  -> MCP tool: claude_review
    -> wrapper script
      -> Claude Code CLI
        -> structured review output
    -> schema validation
  -> Codex reads review result
  -> Codex updates current run state
```

Example input:

```json
{
  "run_id": "2026-06-18-001",
  "task_file": "harness/runs/2026-06-18-001/task.md",
  "plan_file": "harness/runs/2026-06-18-001/plan.md",
  "diff_file": "harness/runs/2026-06-18-001/artifacts/diff.patch",
  "verification_file": "harness/runs/2026-06-18-001/verification.md",
  "review_scope": [
    "correctness",
    "security",
    "regression",
    "test_gaps",
    "maintainability"
  ],
  "output_file": "harness/runs/2026-06-18-001/reviews/claude-review.json",
  "timeout_seconds": 900
}
```

Terminal statuses:

```text
passed
findings
failed
timeout
schema_invalid
not_available
```

Example successful output:

```json
{
  "status": "findings",
  "run_id": "2026-06-18-001",
  "completed": true,
  "output_file": "harness/runs/2026-06-18-001/reviews/claude-review.json",
  "raw_log_file": "harness/runs/2026-06-18-001/reviews/claude-review.raw.log",
  "exit_code": 0,
  "duration_seconds": 187
}
```

Example review result file:

```json
{
  "status": "findings",
  "run_id": "2026-06-18-001",
  "reviewer": "claude-code",
  "summary": "One medium issue found.",
  "findings": [
    {
      "severity": "medium",
      "file": "src/example.ts",
      "line": 42,
      "issue": "Input validation happens after an early return.",
      "evidence": "The changed branch returns before validation runs.",
      "recommendation": "Move validation before the early return."
    }
  ],
  "tested": [],
  "not_tested": [
    "Did not run the test suite independently."
  ],
  "residual_risks": [],
  "raw_log_file": "harness/runs/2026-06-18-001/reviews/claude-review.raw.log"
}
```

Allowed severity:

```text
critical
high
medium
low
info
```

## Synchronous Review Completion

v0.1 uses synchronous review execution from Codex's perspective.

Codex does not poll. Codex calls `claude_review` once and waits for a terminal status. The MCP adapter may poll the Claude Code process internally, stream logs, enforce timeouts, and terminate the process if needed.

Codex considers Claude review complete only when:

1. `claude_review` returns a terminal status.
2. `raw_log_file` is written.
3. `output_file` is written or the adapter explains why it could not be written.
4. For `passed` or `findings`, `output_file` passes schema validation.
5. Codex records the result as current run evidence.

Future async shape, not in v0.1:

```text
claude_review_start -> job_id
claude_review_status -> running/completed/timeout
claude_review_result -> result
claude_review_cancel -> cancelled
```

## Timeout Handling

A Claude Code timeout is not a pass.

When `claude_review` returns `timeout`, Codex must:

1. Set current run state to `review_timeout`.
2. Record `raw_log_file`, `duration_seconds`, and `timeout_seconds`.
3. Record that Claude review did not complete.
4. Avoid claiming Claude review passed.
5. Branch by task track.

Track behavior:

| Track | Codex behavior |
| --- | --- |
| Fast | Usually should not call Claude. If timeout happens, record incomplete review and continue only with explicit disclosure. |
| Standard | Retry once with reduced scope. If retry times out, request user decision or record residual risk if allowed. |
| Strict | Do not continue by default. Ask the user to extend timeout, reduce scope, switch reviewer, or stop. |

Retry limit:

```text
max_review_retries = 1
```

Reduced retry scope:

```text
correctness
security
blocking regressions only
```

## Verification

Codex must answer before completion:

- What changed.
- How it was verified.
- Verification result.
- What was not verified.
- Residual risks.
- Next step.

Code tasks should prefer real verification commands:

- tests
- lint
- typecheck
- build
- targeted smoke test
- manual inspection

If verification cannot run, Codex must record:

- reason
- impact
- substitute check
- residual risk
- whether a user decision is needed

Forbidden completion language:

- "should work"
- "looks good"
- "probably fixed"
- "Claude found nothing, so it is done"

Allowed completion language cites evidence:

- "Ran `npm test`; exit code 0."
- "Ran `pytest`; 42 passed."
- "Did not run e2e because the project has no e2e configuration."
- "Claude review returned no findings, but this is review evidence and does not replace tests."

## Review and Completion

Verification proves behavior. Review evaluates risk. Both are evidence. Neither alone proves completion.

Completion requires:

1. Required workflow steps are done.
2. Verification evidence exists.
3. Claude review terminal status exists or review was explicitly waived.
4. High or critical findings are fixed or the user accepted risk.
5. Handoff is written.
6. `state.json` is updated.

`risk_accepted` is allowed when:

- The user explicitly accepts residual risk.
- External review is unavailable but a Standard task may continue.
- Some verification cannot run and impact is explained.

`blocked` is used when:

- Permissions are missing.
- Critical input is missing.
- External review is unavailable and required.
- Strict risk is not confirmed.

## Memory

Long-term memory stores only durable, cross-task information:

- stable project context
- stable decisions
- repeated risks
- long-term workflow improvements
- user preferences
- agent integration constraints

Long-term memory must not store:

- one-off command output
- raw logs
- transient stack traces
- hidden reasoning
- repetitive review details
- information useful only to the current run

Memory files:

- `harness/memory/context.md`: durable context.
- `harness/memory/progress.md`: current project phase and next steps.
- `harness/memory/risks.md`: open risks and mitigations.
- `harness/memory/decisions.md`: confirmed architecture and workflow decisions.

Rule:

```text
Run records are detailed; memory is distilled.
```

## Acceptance Criteria

Rules layer:

- `AGENTS.md` tells a new Codex session that Codex is the orchestrator.
- `AGENTS.md` tells Codex that Harness is the workflow authority.
- `AGENTS.md` tells Codex that Claude Code is read-only reviewer.
- Core rules define Fast, Standard, and Strict.
- Core rules define when Codex must stop and ask the user.

State layer:

- `state.json` can represent run id, status, workflow, track, evidence, and external agent status.
- External agent results are evidence, not state authority.
- Historical records are append-only by default.

Claude review layer:

- `claude_review` returns one terminal status.
- Every invocation writes a raw log when possible.
- `passed` and `findings` outputs are schema-validated.
- `timeout` is handled as incomplete review, not pass.

Completion layer:

- Codex does not declare `completed` without verification evidence.
- Codex does not declare `completed` with unresolved high or critical findings unless the user accepted risk.
- Codex does not continue a Strict task past timeout or review failure without user decision.
- Codex records unverified items and residual risks.

Documentation layer:

- Each long-term rule file has one clear responsibility.
- Each template is copyable.
- Each run has complete evidence paths.
- Raw logs stay in run records, not memory.

## MVP Deliverables

v0.1 should produce:

- `AGENTS.md`
- `harness/core/*.md`
- `harness/adapters/codex.md`
- `harness/adapters/claude-code.md`
- `harness/adapters/generic-cli-agent.md`
- `harness/templates/*.md`
- `harness/memory/*.md`
- `mcp/claude-review/README.md`
- `mcp/claude-review/schema/*.json`
- `mcp/claude-review/scripts/invoke-claude-reviewer.ps1` documented script stub

## Open Questions for Implementation Planning

- Exact Claude Code CLI command and flags to use on this machine.
- Whether Claude Code can reliably emit JSON matching the required schema.
- Whether the MCP adapter should be implemented in Python or Node.
- Whether Codex hooks should enforce state transitions in v0.1 or remain documented only.
- Whether `AGENTS.md` should include full core rules or only read order and authority summary.
