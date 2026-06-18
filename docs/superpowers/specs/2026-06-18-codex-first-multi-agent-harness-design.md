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
-> reviewing
-> reviewed
-> completed
```

Exceptional states:

```text
blocked
needs_user_decision
failed_verification
review_blocked
review_failed
review_timeout
review_schema_invalid
external_review_unavailable
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

State transition table:

| From | Event | To | Notes |
| --- | --- | --- | --- |
| `draft` | task accepted | `triaged` | Codex records task track and triage reason. |
| `triaged` | valid workflow selected | `planned` | `current_workflow` must exist in the workflow registry. |
| `planned` | work starts | `in_progress` | Codex may use internal subagents or tools. |
| `in_progress` | implementation or document change produced | `implemented` | Evidence must include changed files or produced artifacts. |
| `implemented` | verification passes or is explicitly waived | `verified` | Waiver requires reason and residual risk. |
| `implemented` | verification fails | `failed_verification` | Codex must fix and rerun verification, or ask the user. |
| `verified` | external review requested | `reviewing` | Codex calls `claude_review` synchronously. |
| `verified` | review waived by workflow or user | `reviewed` | Waiver reason is recorded as evidence. |
| `reviewing` | `claude_review` returns `passed` | `reviewed` | Review evidence is recorded. |
| `reviewing` | `claude_review` returns `findings` with no high or critical findings | `reviewed` | Medium or lower findings are fixed or recorded as residual risk. |
| `reviewing` | `claude_review` returns `findings` with high or critical findings | `review_blocked` | Codex must fix, reverify, and rereview, or request risk acceptance. |
| `reviewing` | `claude_review` returns `failed` | `review_failed` | Process failure, not review findings. Codex may retry once for Standard tasks. |
| `reviewing` | `claude_review` returns `timeout` | `review_timeout` | Timeout is not a pass. Track-specific handling applies. |
| `reviewing` | `claude_review` returns `schema_invalid` | `review_schema_invalid` | Result is not trusted. Codex may retry once after preserving raw logs. |
| `reviewing` | `claude_review` returns `not_available` | `external_review_unavailable` | Reason must be recorded, for example tool missing, auth missing, or input over budget. |
| `failed_verification` | fix applied | `implemented` | Codex reruns verification before proceeding. |
| `review_blocked` | fix applied | `implemented` | Codex must reverify before rereview. |
| `review_failed` | retry starts | `reviewing` | Maximum one retry in v0.1 unless user explicitly overrides. |
| `review_timeout` | retry starts | `reviewing` | Standard may retry once with reduced scope; Strict requires user decision. |
| `review_schema_invalid` | retry starts | `reviewing` | Retry must preserve invalid output and raw log. |
| `external_review_unavailable` | user accepts risk | `risk_accepted` | Standard only by default; Strict requires explicit user decision. |
| `reviewed` | completion criteria met | `completed` | Requires verification evidence, review handling, handoff, and state update. |
| Any non-terminal state | missing permission or critical input | `blocked` | Codex records blocker and requested input. |
| Any non-terminal state | user decision required | `needs_user_decision` | Codex records options and consequences. |
| Any review or verification exception | user accepts residual risk | `risk_accepted` | Must cite the risk and acceptance source. |

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
    external-review-template.json
    verification.md
    handoff.md
  schemas/
    state.schema.json
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
      invoke-claude-reviewer.md
      invoke-claude-reviewer.<runtime>
```

Layer responsibilities:

- `AGENTS.md`: Lean Codex entrypoint with read order, authority summary, and 3-5 core invariants. Detailed rules live in `harness/core/*`.
- `harness/core/*`: Agent-neutral workflow, state, safety, verification, delegation, and memory rules.
- `harness/adapters/*`: Agent-specific implementation notes.
- `harness/templates/*`: Copyable task, review, verification, handoff, and agent result templates.
- `harness/schemas/*`: Machine-checkable schemas for state and structured artifacts.
- `harness/memory/*`: Long-term distilled context, progress, risks, and decisions.
- `harness/runs/<run-id>/*`: Per-task evidence and state.
- `.codex/*`: Codex implementation layer for agents, config, hooks, and MCP registration.
- `mcp/claude-review/*`: Claude Code reviewer adapter.

Wrapper runtime rule:

- The design must not assume a fixed wrapper language.
- `invoke-claude-reviewer.md` defines the wrapper contract.
- `invoke-claude-reviewer.<runtime>` is selected during implementation planning, for example `.ps1`, `.py`, `.mjs`, or a Windows `.cmd` shim that calls a chosen runtime explicitly.
- The MCP adapter should invoke the wrapper through an explicit command array rather than relying on the ambient shell.

Naming rules:

- Template names are generic, for example `external-review-template.json`.
- Run artifact names are agent-specific, for example `reviews/claude-review.json`.
- MCP terminal statuses describe adapter call results, for example `not_available`.
- Harness states describe workflow position, for example `external_review_unavailable`.
- `review_failed` means review process failure. Blocking findings use `review_blocked`.

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
    diff.meta.json
    changed-files.txt
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
  "harness_version": "0.1.0",
  "state_schema_version": "0.1.0",
  "status": "draft",
  "track": "Standard",
  "current_workflow": "standard-code-change",
  "owner": "codex",
  "base_commit": "HEAD",
  "created_at": "2026-06-18T00:00:00Z",
  "updated_at": "2026-06-18T00:00:00Z",
  "external_agents": [
    {
      "name": "claude-code",
      "role": "reviewer",
      "adapter": "claude-review",
      "adapter_version": "0.1.0",
      "tool": "claude_review",
      "model": "unknown",
      "model_version": "unknown",
      "cli_version": "unknown",
      "prompt_version": "0.1.0",
      "state_access": "none",
      "status": "not_requested"
    }
  ],
  "evidence": []
}
```

## Diff Artifact Source

`diff.patch` must have a recorded source. Codex must not pass an unexplained patch to an external reviewer.

For Git repositories, v0.1 uses this default:

1. Record `base_commit` before implementation starts.
2. After implementation, run `git add -N .` so new files appear in the diff without staging content.
3. Generate `artifacts/diff.patch` from the working tree relative to `base_commit`.
4. Generate `artifacts/changed-files.txt` from changed tracked and intent-to-add files.
5. Write `artifacts/diff.meta.json`.

Minimal `diff.meta.json`:

```json
{
  "diff_schema_version": "0.1.0",
  "source": "git-working-tree",
  "base_commit": "b2c0ed2",
  "head_commit": "b2c0ed2",
  "includes_uncommitted_changes": true,
  "includes_untracked_intent_to_add": true,
  "command": "git diff --binary b2c0ed2 --",
  "changed_files_file": "harness/runs/2026-06-18-001/artifacts/changed-files.txt",
  "generated_at": "2026-06-18T00:00:00Z"
}
```

If a task is not in a Git repository, Codex must either initialize Git with user approval or record `source: changed-files-without-git` and include enough file snapshots for review. Strict tasks require Git-backed diff evidence unless the user explicitly accepts a weaker audit trail.

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

## Workflow Registry

Harness v0.1 allows only registered workflow IDs in `state.json.current_workflow`.

| Workflow ID | Track | Applies to | Required stages |
| --- | --- | --- | --- |
| `fast-doc-change` | Fast | Copy, typo, or formatting-only documentation changes. | Discover, Deliver, Verify, Handoff summary. |
| `fast-code-change` | Fast | Very small low-risk code edits with obvious local validation. | Discover, Deliver, Verify, Handoff summary. |
| `standard-doc-system-change` | Standard | Documentation structure, templates, process rules, or harness documents. | Discover, Define, Deliver, Verify, Review optional, Handoff, Improve optional. |
| `standard-code-change` | Standard | Normal code changes, features, bug fixes, refactors, or test changes. | Discover, Define, Deliver, Verify, Review, Handoff, Improve optional. |
| `standard-agent-adapter-change` | Standard | MCP adapter, agent wrapper, schema, or non-destructive integration changes. | Discover, Define, Deliver, Verify, Review, Handoff, Improve optional. |
| `strict-risk-change` | Strict | Auth, security, permissions, secrets, production config, database, payments, or privacy-sensitive changes. | Discover, Define with user confirmation, Deliver, Verify, Review, Handoff, Improve. |
| `strict-destructive-change` | Strict | Deletion, irreversible migration, broad cleanup, or state/history rewriting. | Discover, Define with scope and recovery confirmation, Deliver, Verify, Review, Handoff, Improve. |

Rules:

- Codex must not invent a new `current_workflow` ID inside `state.json`.
- A new workflow ID must be added to `harness/core/lifecycle.md` before use.
- Workflow deviations must be recorded in the current run.
- Strict workflow deviations require user confirmation.

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
- The user explicitly asks for cross-checking.
- The diff touches auth, security, permissions, secrets, production config, database, payments, privacy-sensitive code, agent adapters, MCP tools, or state management.
- The diff changes public APIs, workflow rules, state schemas, verification behavior, or completion criteria.
- The diff exceeds objective thresholds: at least 3 files, at least 200 changed lines, or any generated migration/config with operational risk.
- Required verification was skipped, partially run, or replaced by manual inspection.

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
  "harness_version": "0.1.0",
  "prompt_version": "0.1.0",
  "task_file": "harness/runs/2026-06-18-001/task.md",
  "plan_file": "harness/runs/2026-06-18-001/plan.md",
  "diff_file": "harness/runs/2026-06-18-001/artifacts/diff.patch",
  "diff_meta_file": "harness/runs/2026-06-18-001/artifacts/diff.meta.json",
  "changed_files_file": "harness/runs/2026-06-18-001/artifacts/changed-files.txt",
  "verification_file": "harness/runs/2026-06-18-001/verification.md",
  "review_scope": [
    "correctness",
    "security",
    "regression",
    "test_gaps",
    "maintainability"
  ],
  "output_file": "harness/runs/2026-06-18-001/reviews/claude-review.json",
  "timeout_seconds": 900,
  "max_input_chars": 120000,
  "max_files": 30,
  "max_diff_lines": 2000
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

`not_available` requires a reason:

```text
tool_missing
auth_missing
input_over_budget
no_review_target
unsupported_environment
wrapper_failed_to_start
```

Example successful output:

```json
{
  "status": "findings",
  "run_id": "2026-06-18-001",
  "harness_version": "0.1.0",
  "adapter_version": "0.1.0",
  "prompt_version": "0.1.0",
  "completed": true,
  "output_file": "harness/runs/2026-06-18-001/reviews/claude-review.json",
  "raw_log_file": "harness/runs/2026-06-18-001/reviews/claude-review.raw.log",
  "exit_code": 0,
  "duration_seconds": 187,
  "reviewer": {
    "name": "claude-code",
    "model": "unknown",
    "model_version": "unknown",
    "cli_version": "unknown"
  }
}
```

Example review result file:

```json
{
  "status": "findings",
  "run_id": "2026-06-18-001",
  "harness_version": "0.1.0",
  "adapter_version": "0.1.0",
  "prompt_version": "0.1.0",
  "reviewer": "claude-code",
  "reviewer_model": "unknown",
  "reviewer_model_version": "unknown",
  "reviewer_cli_version": "unknown",
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

## Review Input Budget

The adapter enforces review input limits before calling Claude Code.

Default v0.1 limits:

| Limit | Default |
| --- | --- |
| `max_input_chars` | `120000` |
| `max_files` | `30` |
| `max_diff_lines` | `2000` |

If input exceeds budget, the adapter returns:

```json
{
  "status": "not_available",
  "reason": "input_over_budget",
  "completed": false,
  "output_file": "harness/runs/2026-06-18-001/reviews/claude-review.json",
  "raw_log_file": "harness/runs/2026-06-18-001/reviews/claude-review.raw.log"
}
```

Codex may then split the review scope, reduce files, summarize the diff with explicit lossiness, or request user decision. Strict tasks must not silently continue after `input_over_budget`.

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

## Resume Protocol

Codex must be able to resume from `state.json` without guessing.

On resume, Codex must:

1. Read `state.json`.
2. Validate it against `harness/schemas/state.schema.json`.
3. Check that every evidence path listed in state exists or is explicitly marked missing.
4. Inspect the latest non-terminal state.
5. Continue only from a valid transition in the state transition table.

Resume rules:

| Current state | Resume behavior |
| --- | --- |
| `draft` or `triaged` | Re-read task and select or confirm workflow. |
| `planned` | Confirm plan still matches current files before implementation. |
| `in_progress` | Inspect working tree and evidence; do not assume implementation completed. |
| `implemented` | Run or rerun verification before review. |
| `failed_verification` | Fix or request decision, then rerun verification. |
| `verified` | Start review if required; otherwise record review waiver and proceed. |
| `reviewing` | Treat as interrupted unless a terminal `claude_review` artifact exists. Do not assume Claude finished. |
| `review_blocked` | Fix high or critical findings, or request risk acceptance. |
| `review_failed`, `review_timeout`, `review_schema_invalid`, `external_review_unavailable` | Apply the track-specific failure rule; do not proceed silently. |
| `reviewed` | Check handoff and completion criteria. |
| `risk_accepted` | Confirm acceptance evidence exists before handoff or completion. |
| `completed` | No-op unless the user explicitly asks to reopen or audit. |

If `state.json` is missing or schema-invalid, Codex must enter `blocked` and ask whether to reconstruct state from run artifacts.

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

- `state.json` can represent run id, harness version, schema version, status, workflow, track, evidence, and external agent status.
- `state.json` validates against `harness/schemas/state.schema.json`.
- External agent results are evidence, not state authority.
- Historical records are append-only by default.

Claude review layer:

- `claude_review` returns one terminal status.
- Every invocation writes a raw log when possible.
- `passed` and `findings` outputs are schema-validated.
- `timeout` is handled as incomplete review, not pass.
- `not_available` includes a reason such as `tool_missing`, `auth_missing`, or `input_over_budget`.
- Review output records harness, adapter, prompt, model, model version, and CLI version when available.

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
- `AGENTS.md` remains lean: read order, authority summary, and core invariants only.

## MVP Deliverables

v0.1 should produce:

- `AGENTS.md`
- `harness/core/*.md`
- `harness/adapters/codex.md`
- `harness/adapters/claude-code.md`
- `harness/adapters/generic-cli-agent.md`
- `harness/templates/*`
- `harness/memory/*.md`
- `harness/schemas/state.schema.json`
- `.codex/config.toml`
- `.codex/agents/*.toml`
- `.codex/hooks/README.md` or `.codex/hooks/.gitkeep`
- `mcp/claude-review/README.md`
- `mcp/claude-review/schema/*.json`
- `mcp/claude-review/scripts/invoke-claude-reviewer.md`
- one selected `mcp/claude-review/scripts/invoke-claude-reviewer.<runtime>` implementation skeleton
- example Fast-track run record under `harness/runs/example-fast-doc-change/`

## Open Questions for Implementation Planning

- Exact Claude Code CLI command and flags to use on this machine.
- Whether Claude Code can reliably emit JSON matching the required schema.
- Whether the MCP adapter should be implemented in Python or Node.
- Which wrapper runtime to use on Windows, including whether a `.cmd` shim is needed for environments that launch commands through `cmd.exe`.
- Whether Codex hooks should enforce state transitions in v0.1 or remain documented only.
- Which objective review thresholds should be configurable in `harness/core/delegation.md` versus hardcoded defaults.
