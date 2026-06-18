# Codex-first Multi-Agent Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Codex-first Multi-Agent Harness v0.1 scaffold defined in `docs/superpowers/specs/2026-06-18-codex-first-multi-agent-harness-design.md`.

**Architecture:** Keep Harness rules agent-neutral under `harness/core`, keep Codex-specific behavior in `AGENTS.md` and `.codex`, and expose Claude Code review through a controlled MCP adapter under `mcp/claude-review`. The first implementation is mostly rules, schemas, templates, and a testable adapter skeleton; Claude Code remains read-only.

**Tech Stack:** Markdown, JSON Schema, TOML, Python 3.12, Python MCP SDK (`mcp`), Python `unittest`, Claude Code CLI 2.1.160.

---

## Scope Check

This plan covers one cohesive v0.1 scaffold. It intentionally does not build a full CLI, async job system, dashboard, cloud runner, or multi-external-agent runtime.

The only executable adapter in scope is `claude_review`, implemented as a synchronous MCP tool backed by a Python wrapper. Tests use fake Claude runners and do not call the real Claude model.

## File Structure

Create or modify these files:

- Create: `AGENTS.md`
- Modify: `docs/INDEX.md`
- Create: `harness/core/state-authority.md`
- Create: `harness/core/task-triage.md`
- Create: `harness/core/lifecycle.md`
- Create: `harness/core/delegation.md`
- Create: `harness/core/verification.md`
- Create: `harness/core/memory.md`
- Create: `harness/core/safety.md`
- Create: `harness/adapters/codex.md`
- Create: `harness/adapters/claude-code.md`
- Create: `harness/adapters/generic-cli-agent.md`
- Create: `harness/templates/task.md`
- Create: `harness/templates/plan.md`
- Create: `harness/templates/agent-brief.md`
- Create: `harness/templates/agent-result.md`
- Create: `harness/templates/external-review-template.json`
- Create: `harness/templates/verification.md`
- Create: `harness/templates/handoff.md`
- Create: `harness/schemas/state.schema.json`
- Create: `harness/memory/context.md`
- Create: `harness/memory/progress.md`
- Create: `harness/memory/risks.md`
- Create: `harness/memory/decisions.md`
- Create: `harness/runs/example-fast-doc-change/task.md`
- Create: `harness/runs/example-fast-doc-change/triage.md`
- Create: `harness/runs/example-fast-doc-change/verification.md`
- Create: `harness/runs/example-fast-doc-change/handoff.md`
- Create: `harness/runs/example-fast-doc-change/state.json`
- Create: `.codex/config.toml`
- Create: `.codex/agents/planner.toml`
- Create: `.codex/agents/explorer.toml`
- Create: `.codex/agents/implementer.toml`
- Create: `.codex/agents/reviewer.toml`
- Create: `.codex/hooks/README.md`
- Create: `mcp/claude-review/README.md`
- Create: `mcp/claude-review/schema/claude-review-input.schema.json`
- Create: `mcp/claude-review/schema/claude-review-output.schema.json`
- Create: `mcp/claude-review/scripts/invoke-claude-reviewer.md`
- Create: `mcp/claude-review/scripts/invoke-claude-reviewer.py`
- Create: `mcp/claude-review/scripts/invoke-claude-reviewer.cmd`
- Create: `mcp/claude-review/adapter.py`
- Create: `mcp/claude-review/server.py`
- Create: `mcp/claude-review/requirements.txt`
- Create: `tests/test_state_schema.py`
- Create: `tests/test_claude_review_adapter.py`

## Task 1: Repository Entry Points

**Files:**
- Create: `AGENTS.md`
- Modify: `docs/INDEX.md`

- [ ] **Step 1: Create `AGENTS.md`**

Use this exact structure:

```md
# Codex-first Multi-Agent Harness

## Role

Codex is the master orchestrator for this repository.

Harness rules define valid workflows, state transitions, risk handling, verification, memory, and handoff. External agents return evidence only.

## Read Order

1. `harness/core/state-authority.md`
2. `harness/core/task-triage.md`
3. `harness/core/lifecycle.md`
4. `harness/core/delegation.md`
5. `harness/core/verification.md`
6. `harness/core/memory.md`
7. `harness/core/safety.md`
8. Relevant files under `harness/adapters/`
9. Current run under `harness/runs/<run-id>/`, when one exists

## Core Invariants

- Harness defines valid workflows; Codex selects and executes them.
- Codex may update current run state, but external agents must not mutate state.
- Claude Code is a read-only reviewer in v0.1.
- No completion claim is valid without verification evidence.
- Strict workflow deviation requires explicit user confirmation.

## Completion Report

Every completed task must state:

- What changed
- How it was verified
- What was not verified
- Residual risks
- Next step
```

- [ ] **Step 2: Update `docs/INDEX.md`**

Make sure it includes these entries:

```md
## Specs

- `docs/superpowers/specs/2026-06-18-codex-first-multi-agent-harness-design.md` - Codex-first Multi-Agent Harness v0.1 design.

## Plans

- `docs/superpowers/plans/2026-06-18-codex-first-multi-agent-harness-implementation.md` - Implementation plan for the v0.1 scaffold.

## Harness

- `AGENTS.md` - Codex entrypoint and read order.
- `harness/core/` - Agent-neutral Harness rules.
- `harness/adapters/` - Agent-specific adapter rules.
- `harness/templates/` - Copyable task and evidence templates.
- `harness/schemas/` - JSON schemas for machine-checkable artifacts.
- `harness/memory/` - Curated long-term memory.
- `harness/runs/` - Per-task run records and evidence.
```

- [ ] **Step 3: Verify entry points**

Run:

```powershell
Test-Path AGENTS.md
Test-Path docs\INDEX.md
```

Expected:

```text
True
True
```

- [ ] **Step 4: Commit Task 1**

```powershell
git add AGENTS.md docs/INDEX.md
git commit -m "Add harness repository entry points"
```

## Task 2: Core Harness Rules

**Files:**
- Create: `harness/core/state-authority.md`
- Create: `harness/core/task-triage.md`
- Create: `harness/core/lifecycle.md`
- Create: `harness/core/delegation.md`
- Create: `harness/core/verification.md`
- Create: `harness/core/memory.md`
- Create: `harness/core/safety.md`

- [ ] **Step 1: Create `harness/core/state-authority.md`**

Use sections:

```md
# State Authority

## Authority

Harness defines valid states and transitions. Codex executes transitions for the current run. External agents return evidence only.

## Normal States

`draft -> triaged -> planned -> in_progress -> implemented -> verified -> reviewing -> reviewed -> completed`

## Exceptional States

- `blocked`
- `needs_user_decision`
- `failed_verification`
- `review_blocked`
- `review_failed`
- `review_timeout`
- `review_schema_invalid`
- `external_review_unavailable`
- `risk_accepted`

## Transition Rules

- `current_workflow` must be present in the workflow registry.
- `review_failed` means process failure, not blocking findings.
- Blocking findings use `review_blocked`.
- `timeout` and `not_available` are adapter statuses, not completion evidence.
- Historical run records are append-only unless the user explicitly requests correction.

## Resume

On resume, Codex must read `state.json`, validate it against `harness/schemas/state.schema.json`, verify evidence paths, and continue only from a valid transition.
```

- [ ] **Step 2: Create `harness/core/task-triage.md`**

Use sections:

```md
# Task Triage

## Fast

Use for typo, small copy, small formatting, and low-risk edits.

## Standard

Use for normal code changes, multi-file edits, features, refactors, documentation systems, schemas, and non-destructive adapter changes.

## Strict

Use for deletion, security, permissions, auth, secrets, production configuration, database, payments, privacy, destructive changes, irreversible migration, or state/history rewriting.

## Required Escalation

Move to Strict when a task touches credentials, production state, irreversible filesystem operations, external agent permissions, or high-risk workflow rules.
```

- [ ] **Step 3: Create `harness/core/lifecycle.md`**

Include the workflow registry from the design spec:

```md
# Lifecycle

## Lifecycle

`Discover -> Define -> Deliver -> Verify -> Review -> Handoff -> Improve`

## Workflow Registry

| Workflow ID | Track | Applies to | Required stages |
| --- | --- | --- | --- |
| `fast-doc-change` | Fast | Copy, typo, or formatting-only documentation changes. | Discover, Deliver, Verify, Handoff summary. |
| `fast-code-change` | Fast | Very small low-risk code edits with obvious local validation. | Discover, Deliver, Verify, Handoff summary. |
| `standard-doc-system-change` | Standard | Documentation structure, templates, process rules, or harness documents. | Discover, Define, Deliver, Verify, Review optional, Handoff, Improve optional. |
| `standard-code-change` | Standard | Normal code changes, features, bug fixes, refactors, or test changes. | Discover, Define, Deliver, Verify, Review, Handoff, Improve optional. |
| `standard-agent-adapter-change` | Standard | MCP adapter, agent wrapper, schema, or non-destructive integration changes. | Discover, Define, Deliver, Verify, Review, Handoff, Improve optional. |
| `strict-risk-change` | Strict | Auth, security, permissions, secrets, production config, database, payments, or privacy-sensitive changes. | Discover, Define with user confirmation, Deliver, Verify, Review, Handoff, Improve. |
| `strict-destructive-change` | Strict | Deletion, irreversible migration, broad cleanup, or state/history rewriting. | Discover, Define with scope and recovery confirmation, Deliver, Verify, Review, Handoff, Improve. |

## Rule

Codex must not invent a workflow ID. Add new workflow IDs here before using them.
```

- [ ] **Step 4: Create `harness/core/delegation.md`**

Use:

```md
# Delegation

## Codex Subagents

Use Codex subagents for read-heavy exploration, test-failure analysis, large document scans, low-coupling subtasks, and review categorization.

## Claude Code Reviewer

Call Claude Code review when:

- A Standard code change is implemented.
- A Strict task needs independent review.
- The user explicitly asks for cross-checking.
- The diff touches auth, security, permissions, secrets, production config, database, payments, privacy-sensitive code, agent adapters, MCP tools, or state management.
- The diff changes public APIs, workflow rules, state schemas, verification behavior, or completion criteria.
- The diff changes at least 3 files or at least 200 lines.
- Required verification was skipped, partially run, or replaced by manual inspection.

## Input Budget

Default limits:

- `max_input_chars = 120000`
- `max_files = 30`
- `max_diff_lines = 2000`
```

- [ ] **Step 5: Create verification, memory, and safety rules**

Create `harness/core/verification.md`:

```md
# Verification

Verification proves behavior. Review evaluates risk.

Completion requires verification evidence, review handling, handoff, and state update.

Forbidden completion language:

- should work
- looks good
- probably fixed
- Claude found nothing, so it is done

If verification cannot run, record reason, impact, substitute check, residual risk, and whether user decision is needed.
```

Create `harness/core/memory.md`:

```md
# Memory

Run records are detailed. Memory is distilled.

Store only durable context, stable decisions, repeated risks, workflow improvements, user preferences, and agent integration constraints.

Do not store raw logs, transient stack traces, hidden reasoning, or one-run-only review details.
```

Create `harness/core/safety.md`:

```md
# Safety

Strict tasks require scope, non-goals, recovery strategy, verification plan, and residual risk owner before execution.

Stop and ask before destructive operations, secret handling, production changes, auth changes, database changes, payment changes, permission expansion, or state/history rewriting.
```

- [ ] **Step 6: Verify core rule files**

Run:

```powershell
Get-ChildItem harness\core\*.md | Measure-Object
```

Expected:

```text
Count    : 7
```

- [ ] **Step 7: Commit Task 2**

```powershell
git add harness/core
git commit -m "Add core harness rules"
```

## Task 3: Schemas and Templates

**Files:**
- Create: `harness/schemas/state.schema.json`
- Create: `harness/templates/task.md`
- Create: `harness/templates/plan.md`
- Create: `harness/templates/agent-brief.md`
- Create: `harness/templates/agent-result.md`
- Create: `harness/templates/external-review-template.json`
- Create: `harness/templates/verification.md`
- Create: `harness/templates/handoff.md`
- Create: `tests/test_state_schema.py`

- [ ] **Step 1: Create `harness/schemas/state.schema.json`**

Use this schema:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Harness Run State",
  "type": "object",
  "required": [
    "run_id",
    "harness_version",
    "state_schema_version",
    "status",
    "track",
    "current_workflow",
    "owner",
    "base_commit",
    "created_at",
    "updated_at",
    "external_agents",
    "evidence"
  ],
  "properties": {
    "run_id": { "type": "string", "minLength": 1 },
    "harness_version": { "type": "string", "pattern": "^0\\.1\\.0$" },
    "state_schema_version": { "type": "string", "pattern": "^0\\.1\\.0$" },
    "status": {
      "type": "string",
      "enum": [
        "draft",
        "triaged",
        "planned",
        "in_progress",
        "implemented",
        "verified",
        "reviewing",
        "reviewed",
        "completed",
        "blocked",
        "needs_user_decision",
        "failed_verification",
        "review_blocked",
        "review_failed",
        "review_timeout",
        "review_schema_invalid",
        "external_review_unavailable",
        "risk_accepted"
      ]
    },
    "track": { "type": "string", "enum": ["Fast", "Standard", "Strict"] },
    "current_workflow": {
      "type": "string",
      "enum": [
        "fast-doc-change",
        "fast-code-change",
        "standard-doc-system-change",
        "standard-code-change",
        "standard-agent-adapter-change",
        "strict-risk-change",
        "strict-destructive-change"
      ]
    },
    "owner": { "type": "string", "enum": ["codex"] },
    "base_commit": { "type": "string", "minLength": 1 },
    "created_at": { "type": "string", "minLength": 1 },
    "updated_at": { "type": "string", "minLength": 1 },
    "external_agents": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "role", "state_access", "status"],
        "properties": {
          "name": { "type": "string" },
          "role": { "type": "string" },
          "adapter": { "type": "string" },
          "adapter_version": { "type": "string" },
          "tool": { "type": "string" },
          "model": { "type": "string" },
          "model_version": { "type": "string" },
          "cli_version": { "type": "string" },
          "prompt_version": { "type": "string" },
          "state_access": { "type": "string", "enum": ["none"] },
          "status": {
            "type": "string",
            "enum": [
              "not_requested",
              "requested",
              "running",
              "passed",
              "findings",
              "failed",
              "timeout",
              "schema_invalid",
              "not_available"
            ]
          }
        },
        "additionalProperties": false
      }
    },
    "evidence": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type", "path"],
        "properties": {
          "type": { "type": "string" },
          "path": { "type": "string" },
          "description": { "type": "string" }
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

- [ ] **Step 2: Create template files**

Create `harness/templates/task.md`:

```md
# Task

## Goal

## Track

## Workflow

## Scope

## Non-goals

## Acceptance Criteria

## Verification Plan

## Risks
```

Create `harness/templates/plan.md`:

```md
# Plan

## Goal

## Files

## Steps

## Verification

## Rollback
```

Create `harness/templates/agent-brief.md`:

```md
# Agent Brief

## Role

## Inputs

## Scope

## Forbidden Actions

## Expected Output
```

Create `harness/templates/agent-result.md`:

```md
# Agent Result

## Agent

## Status

## Summary

## Evidence

## Findings

## Residual Risks
```

Create `harness/templates/verification.md`:

```md
# Verification

## Commands Run

## Results

## Not Verified

## Residual Risks
```

Create `harness/templates/handoff.md`:

```md
# Handoff

## What Changed

## Evidence

## State

## Risks

## Next Step
```

Create `harness/templates/external-review-template.json`:

```json
{
  "status": "passed",
  "run_id": "example-run",
  "harness_version": "0.1.0",
  "adapter_version": "0.1.0",
  "prompt_version": "0.1.0",
  "reviewer": "external-agent",
  "reviewer_model": "unknown",
  "reviewer_model_version": "unknown",
  "reviewer_cli_version": "unknown",
  "summary": "",
  "findings": [],
  "tested": [],
  "not_tested": [],
  "residual_risks": [],
  "raw_log_file": ""
}
```

- [ ] **Step 3: Write state schema test**

Create `tests/test_state_schema.py`:

```python
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StateSchemaTest(unittest.TestCase):
    def test_schema_has_required_statuses(self):
        schema = json.loads((ROOT / "harness/schemas/state.schema.json").read_text())
        statuses = schema["properties"]["status"]["enum"]
        self.assertIn("review_blocked", statuses)
        self.assertIn("review_failed", statuses)
        self.assertIn("external_review_unavailable", statuses)

    def test_schema_has_registered_workflows(self):
        schema = json.loads((ROOT / "harness/schemas/state.schema.json").read_text())
        workflows = schema["properties"]["current_workflow"]["enum"]
        self.assertEqual(
            workflows,
            [
                "fast-doc-change",
                "fast-code-change",
                "standard-doc-system-change",
                "standard-code-change",
                "standard-agent-adapter-change",
                "strict-risk-change",
                "strict-destructive-change",
            ],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run schema tests**

Run:

```powershell
python -m unittest tests.test_state_schema -v
```

Expected:

```text
test_schema_has_registered_workflows ... ok
test_schema_has_required_statuses ... ok
```

- [ ] **Step 5: Commit Task 3**

```powershell
git add harness/templates harness/schemas tests/test_state_schema.py
git commit -m "Add harness schemas and templates"
```

## Task 4: Memory and Example Run

**Files:**
- Create: `harness/memory/context.md`
- Create: `harness/memory/progress.md`
- Create: `harness/memory/risks.md`
- Create: `harness/memory/decisions.md`
- Create: `harness/runs/example-fast-doc-change/task.md`
- Create: `harness/runs/example-fast-doc-change/triage.md`
- Create: `harness/runs/example-fast-doc-change/verification.md`
- Create: `harness/runs/example-fast-doc-change/handoff.md`
- Create: `harness/runs/example-fast-doc-change/state.json`

- [ ] **Step 1: Create memory files**

Use these initial contents:

```md
# Context

This repository contains a Codex-first Multi-Agent Harness. Codex is the master orchestrator. Harness rules define workflow authority. Claude Code is v0.1's external read-only reviewer.
```

```md
# Progress

## Current Phase

Design approved. Implementation plan in progress.

## Next Step

Build the v0.1 scaffold from the approved implementation plan.
```

```md
# Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| External reviewer mutates state | Breaks audit boundary | Claude Code is read-only and returns evidence only. |
| Review timeout treated as pass | False completion | `timeout` maps to `review_timeout`, never `reviewed`. |
| Rules become too heavy | Agent overhead | `AGENTS.md` stays lean; details live in `harness/core`. |
```

```md
# Decisions

| Date | Decision | Rationale |
| --- | --- | --- |
| 2026-06-18 | Codex-first orchestration | Codex is the main execution surface; Harness supplies durable rules. |
| 2026-06-18 | Claude Code reviewer is read-only | Reduces risk while enabling independent review evidence. |
| 2026-06-18 | `claude_review` is synchronous in v0.1 | Avoids async job-state complexity. |
```

- [ ] **Step 2: Create example Fast run**

Create `harness/runs/example-fast-doc-change/task.md`:

```md
# Task

## Goal

Demonstrate a completed Fast documentation run.

## Track

Fast

## Workflow

fast-doc-change

## Scope

Documentation-only example.

## Non-goals

- No code changes
- No external reviewer

## Acceptance Criteria

- Run record has task, triage, verification, handoff, and state files.

## Verification Plan

Check that required files exist.

## Risks

No material runtime risk.
```

Create `harness/runs/example-fast-doc-change/triage.md`:

```md
# Triage

## Track

Fast

## Reason

This is a documentation-only example run with no code, no destructive action, and no external reviewer requirement.
```

Create `harness/runs/example-fast-doc-change/verification.md`:

```md
# Verification

## Commands Run

`Test-Path harness\runs\example-fast-doc-change\state.json`

## Results

Expected result is `True`.

## Not Verified

Claude Code review was not requested because Fast documentation changes do not require external review by default.

## Residual Risks

No material residual risk for this example run.
```

Create `harness/runs/example-fast-doc-change/handoff.md`:

```md
# Handoff

## What Changed

Created an example Fast documentation run record.

## Evidence

- `task.md`
- `triage.md`
- `verification.md`
- `state.json`

## State

completed

## Risks

No material residual risk.

## Next Step

Use this example as a shape reference for future Fast documentation runs.
```

Use `harness/runs/example-fast-doc-change/state.json`:

```json
{
  "run_id": "example-fast-doc-change",
  "harness_version": "0.1.0",
  "state_schema_version": "0.1.0",
  "status": "completed",
  "track": "Fast",
  "current_workflow": "fast-doc-change",
  "owner": "codex",
  "base_commit": "example",
  "created_at": "2026-06-18T00:00:00Z",
  "updated_at": "2026-06-18T00:00:00Z",
  "external_agents": [
    {
      "name": "claude-code",
      "role": "reviewer",
      "state_access": "none",
      "status": "not_requested"
    }
  ],
  "evidence": [
    {
      "type": "verification",
      "path": "harness/runs/example-fast-doc-change/verification.md",
      "description": "Fast documentation run verification example."
    },
    {
      "type": "handoff",
      "path": "harness/runs/example-fast-doc-change/handoff.md",
      "description": "Fast documentation run handoff example."
    }
  ]
}
```

- [ ] **Step 3: Verify example run files**

Run:

```powershell
Test-Path harness\runs\example-fast-doc-change\state.json
Test-Path harness\memory\decisions.md
```

Expected:

```text
True
True
```

- [ ] **Step 4: Commit Task 4**

```powershell
git add harness/memory harness/runs/example-fast-doc-change
git commit -m "Add harness memory and example run"
```

## Task 5: Codex Configuration and Custom Agents

**Files:**
- Create: `.codex/config.toml`
- Create: `.codex/agents/planner.toml`
- Create: `.codex/agents/explorer.toml`
- Create: `.codex/agents/implementer.toml`
- Create: `.codex/agents/reviewer.toml`
- Create: `.codex/hooks/README.md`
- Create: `harness/adapters/codex.md`
- Create: `harness/adapters/generic-cli-agent.md`

- [ ] **Step 1: Create `.codex/config.toml`**

Use conservative config:

```toml
[agents]
max_threads = 4
max_depth = 1
job_max_runtime_seconds = 1800

[mcp_servers.claude_review]
command = "python"
args = ["mcp/claude-review/server.py"]
startup_timeout_sec = 20
tool_timeout_sec = 960
enabled = true
required = false
```

- [ ] **Step 2: Create custom agent TOML files**

Create `.codex/agents/planner.toml`:

```toml
name = "planner"
description = "Creates focused implementation plans from approved Harness specs."
developer_instructions = """
Plan like an owner.
Use Harness workflow and state rules.
Do not implement code.
Return concise steps, files, verification, risks, and commit boundaries.
"""
model_reasoning_effort = "medium"
```

Create `.codex/agents/explorer.toml`:

```toml
name = "explorer"
description = "Performs read-heavy repository exploration without mutating files."
developer_instructions = """
Explore like an auditor.
Read relevant files and summarize findings with paths.
Do not modify files.
Return concise context, risks, and suggested next files to inspect.
"""
model_reasoning_effort = "medium"
```

Create `.codex/agents/implementer.toml`:

```toml
name = "implementer"
description = "Implements scoped changes from an approved Harness plan."
developer_instructions = """
Implement only the assigned task.
Follow the active Harness plan and verification rules.
Do not broaden scope.
Return changed files, commands run, results, and residual risks.
"""
model_reasoning_effort = "medium"
```

Create `.codex/agents/reviewer.toml`:

```toml
name = "reviewer"
description = "Reviews changes for correctness, regressions, security, and test gaps."
developer_instructions = """
Review like an owner.
Prioritize correctness, security, regressions, and missing verification.
Do not refactor or modify files.
Return findings with severity, evidence, file paths, and recommendations.
"""
model_reasoning_effort = "high"
```

- [ ] **Step 3: Create Codex and generic adapter docs**

Create `harness/adapters/codex.md`:

```md
# Codex Adapter

Codex is the master orchestrator.

Codex may:

- Select registered workflows.
- Update current run state.
- Create and update run evidence.
- Dispatch Codex subagents.
- Call `claude_review` through MCP.

Codex must not:

- Invent workflow IDs.
- Treat external review as approval.
- Complete without verification evidence.
- Rewrite historical run records without explicit user request.
```

Create `harness/adapters/generic-cli-agent.md`:

```md
# Generic CLI Agent Adapter

Generic CLI agents must receive explicit input files and return structured output files.

They must not mutate Harness state directly.

Required result fields:

- status
- summary
- findings
- evidence
- not_tested
- residual_risks
```

- [ ] **Step 4: Create hooks README**

Use:

```md
# Codex Hooks

Hooks are not required for v0.1 correctness.

Future hooks may validate state transitions, scan for secrets, or write lifecycle logs. Hooks must not define Harness workflow authority.
```

- [ ] **Step 5: Verify Codex config files**

Run:

```powershell
Test-Path .codex\config.toml
Get-ChildItem .codex\agents\*.toml | Measure-Object
```

Expected:

```text
True
Count    : 4
```

- [ ] **Step 6: Commit Task 5**

```powershell
git add .codex harness/adapters/codex.md harness/adapters/generic-cli-agent.md
git commit -m "Add Codex adapter configuration"
```

## Task 6: Claude Code Adapter Contracts

**Files:**
- Create: `harness/adapters/claude-code.md`
- Create: `mcp/claude-review/README.md`
- Create: `mcp/claude-review/schema/claude-review-input.schema.json`
- Create: `mcp/claude-review/schema/claude-review-output.schema.json`
- Create: `mcp/claude-review/scripts/invoke-claude-reviewer.md`
- Create: `mcp/claude-review/requirements.txt`

- [ ] **Step 1: Create `harness/adapters/claude-code.md`**

Use:

```md
# Claude Code Adapter

Claude Code v0.1 is a read-only external reviewer.

## Invocation

Codex calls Claude only through MCP tool `claude_review`.

## Forbidden

- No file mutation
- No Harness state mutation
- No workflow decisions
- No completion approval

## Terminal Status Mapping

| MCP status | Harness state effect |
| --- | --- |
| `passed` | `reviewed` |
| `findings` with no high or critical findings | `reviewed` after triage |
| `findings` with high or critical findings | `review_blocked` |
| `failed` | `review_failed` |
| `timeout` | `review_timeout` |
| `schema_invalid` | `review_schema_invalid` |
| `not_available` | `external_review_unavailable` |

## Timeout

Timeout is not a pass. Standard tasks may retry once with reduced scope. Strict tasks require user decision.
```

- [ ] **Step 2: Create MCP README and requirements**

`mcp/claude-review/requirements.txt`:

```text
mcp==1.28.0
```

`mcp/claude-review/README.md`:

```md
# Claude Review MCP Adapter

This adapter exposes one MCP tool: `claude_review`.

The tool runs synchronously from Codex's perspective. It returns a terminal status and writes raw logs and structured review output.

The adapter must not let Claude Code mutate files or Harness state.

## Local check

Run `python -m pip install -r mcp/claude-review/requirements.txt`.

Run `python mcp/claude-review/server.py`.
```

- [ ] **Step 3: Create input and output schemas**

Create `mcp/claude-review/schema/claude-review-input.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Claude Review Input",
  "type": "object",
  "required": [
    "run_id",
    "task_file",
    "plan_file",
    "diff_file",
    "diff_meta_file",
    "changed_files_file",
    "verification_file",
    "review_scope",
    "output_file",
    "timeout_seconds",
    "max_input_chars",
    "max_files",
    "max_diff_lines"
  ],
  "properties": {
    "run_id": { "type": "string", "minLength": 1 },
    "harness_version": { "type": "string" },
    "prompt_version": { "type": "string" },
    "task_file": { "type": "string", "minLength": 1 },
    "plan_file": { "type": "string", "minLength": 1 },
    "diff_file": { "type": "string", "minLength": 1 },
    "diff_meta_file": { "type": "string", "minLength": 1 },
    "changed_files_file": { "type": "string", "minLength": 1 },
    "verification_file": { "type": "string", "minLength": 1 },
    "review_scope": {
      "type": "array",
      "items": { "type": "string" },
      "minItems": 1
    },
    "output_file": { "type": "string", "minLength": 1 },
    "timeout_seconds": { "type": "integer", "minimum": 1 },
    "max_input_chars": { "type": "integer", "minimum": 1 },
    "max_files": { "type": "integer", "minimum": 1 },
    "max_diff_lines": { "type": "integer", "minimum": 1 }
  },
  "additionalProperties": false
}
```

Create `mcp/claude-review/schema/claude-review-output.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Claude Review Output",
  "type": "object",
  "required": [
    "status",
    "run_id",
    "completed",
    "output_file",
    "raw_log_file",
    "duration_seconds"
  ],
  "properties": {
    "status": {
      "type": "string",
      "enum": [
        "passed",
        "findings",
        "failed",
        "timeout",
        "schema_invalid",
        "not_available"
      ]
    },
    "reason": {
      "type": "string",
      "enum": [
        "tool_missing",
        "auth_missing",
        "input_over_budget",
        "no_review_target",
        "unsupported_environment",
        "wrapper_failed_to_start"
      ]
    },
    "run_id": { "type": "string", "minLength": 1 },
    "completed": { "type": "boolean" },
    "output_file": { "type": "string", "minLength": 1 },
    "raw_log_file": { "type": "string", "minLength": 1 },
    "exit_code": { "type": ["integer", "null"] },
    "duration_seconds": { "type": "number", "minimum": 0 }
  },
  "additionalProperties": false
}
```

- [ ] **Step 4: Create wrapper contract**

Create `mcp/claude-review/scripts/invoke-claude-reviewer.md`:

```md
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
```

- [ ] **Step 5: Verify contract files**

Run:

```powershell
Test-Path mcp\claude-review\README.md
Test-Path mcp\claude-review\schema\claude-review-input.schema.json
Test-Path mcp\claude-review\schema\claude-review-output.schema.json
Test-Path mcp\claude-review\scripts\invoke-claude-reviewer.md
```

Expected:

```text
True
True
True
True
```

- [ ] **Step 6: Commit Task 6**

```powershell
git add harness/adapters/claude-code.md mcp/claude-review
git commit -m "Add Claude Code review adapter contract"
```

## Task 7: Claude Review Adapter Implementation

**Files:**
- Create: `mcp/claude-review/adapter.py`
- Create: `mcp/claude-review/server.py`
- Create: `mcp/claude-review/scripts/invoke-claude-reviewer.py`
- Create: `mcp/claude-review/scripts/invoke-claude-reviewer.cmd`
- Create: `tests/test_claude_review_adapter.py`

- [ ] **Step 1: Create `mcp/claude-review/adapter.py`**

Implement pure functions first:

```python
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


TERMINAL_STATUSES = {
    "passed",
    "findings",
    "failed",
    "timeout",
    "schema_invalid",
    "not_available",
}


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def check_budget(payload: dict[str, Any]) -> str | None:
    diff_file = Path(payload["diff_file"])
    changed_files_file = Path(payload["changed_files_file"])
    max_diff_lines = int(payload.get("max_diff_lines", 2000))
    max_files = int(payload.get("max_files", 30))
    max_input_chars = int(payload.get("max_input_chars", 120000))

    files_count = count_lines(changed_files_file)
    diff_text = diff_file.read_text(encoding="utf-8", errors="replace") if diff_file.exists() else ""

    if files_count > max_files:
        return "input_over_budget"
    if len(diff_text.splitlines()) > max_diff_lines:
        return "input_over_budget"
    if len(diff_text) > max_input_chars:
        return "input_over_budget"
    return None


def not_available(payload: dict[str, Any], reason: str, started: float) -> dict[str, Any]:
    return {
        "status": "not_available",
        "reason": reason,
        "run_id": payload["run_id"],
        "completed": False,
        "output_file": payload["output_file"],
        "raw_log_file": raw_log_path(payload),
        "exit_code": None,
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def raw_log_path(payload: dict[str, Any]) -> str:
    output = Path(payload["output_file"])
    return str(output.with_suffix(".raw.log"))


def validate_review_result(result: dict[str, Any]) -> bool:
    required = {
        "status",
        "run_id",
        "reviewer",
        "summary",
        "findings",
        "tested",
        "not_tested",
        "residual_risks",
        "raw_log_file",
    }
    return required.issubset(result.keys()) and result["status"] in {"passed", "findings"}


def run_claude_review(payload: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    output_file = Path(payload["output_file"])
    output_file.parent.mkdir(parents=True, exist_ok=True)
    raw_log = Path(raw_log_path(payload))

    budget_reason = check_budget(payload)
    if budget_reason:
        result = not_available(payload, budget_reason, started)
        raw_log.write_text("Review input exceeded configured budget.\\n", encoding="utf-8")
        output_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    if shutil.which("claude") is None:
        result = not_available(payload, "tool_missing", started)
        raw_log.write_text("Claude CLI was not found on PATH.\\n", encoding="utf-8")
        output_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    prompt = build_review_prompt(payload)
    command = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--permission-mode",
        "plan",
        "--tools",
        "",
        "--no-session-persistence",
        "--max-budget-usd",
        "1",
        prompt,
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=int(payload.get("timeout_seconds", 900)),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raw_log.write_text((exc.stdout or "") + (exc.stderr or ""), encoding="utf-8")
        return {
            "status": "timeout",
            "run_id": payload["run_id"],
            "completed": False,
            "output_file": str(output_file),
            "raw_log_file": str(raw_log),
            "exit_code": None,
            "duration_seconds": round(time.monotonic() - started, 3),
        }

    raw_log.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        return {
            "status": "failed",
            "run_id": payload["run_id"],
            "completed": False,
            "output_file": str(output_file),
            "raw_log_file": str(raw_log),
            "exit_code": completed.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
        }

    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "status": "schema_invalid",
            "run_id": payload["run_id"],
            "completed": False,
            "output_file": str(output_file),
            "raw_log_file": str(raw_log),
            "exit_code": completed.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
        }

    review = normalize_claude_json(parsed, payload, str(raw_log))
    if not validate_review_result(review):
        return {
            "status": "schema_invalid",
            "run_id": payload["run_id"],
            "completed": False,
            "output_file": str(output_file),
            "raw_log_file": str(raw_log),
            "exit_code": completed.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
        }

    output_file.write_text(json.dumps(review, indent=2), encoding="utf-8")
    return {
        "status": review["status"],
        "run_id": payload["run_id"],
        "completed": True,
        "output_file": str(output_file),
        "raw_log_file": str(raw_log),
        "exit_code": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def build_review_prompt(payload: dict[str, Any]) -> str:
    return (
        "You are Claude Code acting as a read-only reviewer. "
        "Do not modify files. Return only JSON matching the required review shape. "
        f"Review task={payload['task_file']} plan={payload['plan_file']} "
        f"diff={payload['diff_file']} verification={payload['verification_file']}."
    )


def normalize_claude_json(parsed: dict[str, Any], payload: dict[str, Any], raw_log: str) -> dict[str, Any]:
    content = parsed.get("result") or parsed.get("content") or parsed
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            content = {"summary": content, "findings": []}
    findings = content.get("findings", [])
    return {
        "status": "findings" if findings else "passed",
        "run_id": payload["run_id"],
        "harness_version": payload.get("harness_version", "0.1.0"),
        "adapter_version": "0.1.0",
        "prompt_version": payload.get("prompt_version", "0.1.0"),
        "reviewer": "claude-code",
        "reviewer_model": "unknown",
        "reviewer_model_version": "unknown",
        "reviewer_cli_version": "unknown",
        "summary": content.get("summary", ""),
        "findings": findings,
        "tested": content.get("tested", []),
        "not_tested": content.get("not_tested", []),
        "residual_risks": content.get("residual_risks", []),
        "raw_log_file": raw_log,
    }
```

- [ ] **Step 2: Create MCP server**

Create `mcp/claude-review/server.py`:

```python
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from adapter import run_claude_review


mcp = FastMCP("claude-review")


@mcp.tool()
def claude_review(payload: dict) -> dict:
    """Run a synchronous read-only Claude Code review."""
    return run_claude_review(payload)


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 3: Create wrapper script and cmd shim**

`mcp/claude-review/scripts/invoke-claude-reviewer.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapter import run_claude_review


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--raw-log", required=True)
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    payload["output_file"] = args.output
    result = run_claude_review(payload)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`mcp/claude-review/scripts/invoke-claude-reviewer.cmd`:

```cmd
@echo off
python "%~dp0invoke-claude-reviewer.py" %*
```

- [ ] **Step 4: Write adapter unit tests**

Create `tests/test_claude_review_adapter.py`:

```python
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "mcp/claude-review/adapter.py"
spec = importlib.util.spec_from_file_location("claude_review_adapter", ADAPTER_PATH)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class ClaudeReviewAdapterTest(unittest.TestCase):
    def make_payload(self, tmp: Path) -> dict:
        diff = tmp / "diff.patch"
        changed = tmp / "changed-files.txt"
        diff.write_text("diff --git a/a.md b/a.md\\n+hello\\n", encoding="utf-8")
        changed.write_text("a.md\\n", encoding="utf-8")
        return {
            "run_id": "test-run",
            "harness_version": "0.1.0",
            "prompt_version": "0.1.0",
            "task_file": "task.md",
            "plan_file": "plan.md",
            "diff_file": str(diff),
            "diff_meta_file": str(tmp / "diff.meta.json"),
            "changed_files_file": str(changed),
            "verification_file": "verification.md",
            "review_scope": ["correctness"],
            "output_file": str(tmp / "claude-review.json"),
            "timeout_seconds": 1,
            "max_input_chars": 120000,
            "max_files": 30,
            "max_diff_lines": 2000,
        }

    def test_budget_passes_for_small_diff(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            self.assertIsNone(adapter.check_budget(payload))

    def test_budget_blocks_large_diff(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            Path(payload["diff_file"]).write_text("x\\n" * 2001, encoding="utf-8")
            self.assertEqual(adapter.check_budget(payload), "input_over_budget")

    def test_validate_review_result_requires_core_fields(self):
        self.assertFalse(adapter.validate_review_result({"status": "passed"}))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: Run adapter tests**

Run:

```powershell
python -m unittest tests.test_claude_review_adapter -v
```

Expected:

```text
test_budget_blocks_large_diff ... ok
test_budget_passes_for_small_diff ... ok
test_validate_review_result_requires_core_fields ... ok
```

- [ ] **Step 6: Commit Task 7**

```powershell
git add mcp/claude-review/adapter.py mcp/claude-review/server.py mcp/claude-review/scripts tests/test_claude_review_adapter.py
git commit -m "Add Claude review adapter implementation"
```

## Task 8: Final Verification

**Files:**
- Modify only if verification exposes mismatches.

- [ ] **Step 1: Run all Python unit tests**

```powershell
python -m unittest discover -s tests -v
```

Expected:

```text
OK
```

- [ ] **Step 2: Run stale-name scan**

```powershell
rg -n "failed_review|review_not_available|review-result\\.json|invoke-claude-reviewer\\.ps1|Codex is uncertain" .
```

Expected:

```text
No matches.
```

- [ ] **Step 3: Validate required files exist**

```powershell
Test-Path AGENTS.md
Test-Path harness\schemas\state.schema.json
Test-Path .codex\config.toml
Test-Path mcp\claude-review\server.py
Test-Path harness\runs\example-fast-doc-change\state.json
```

Expected:

```text
True
True
True
True
True
```

- [ ] **Step 4: Check Git state**

```powershell
git status --short
```

Expected: either no output, or only intentional files staged before the final commit.

- [ ] **Step 5: Final commit**

If there are verification-only fixes:

```powershell
git add .
git commit -m "Complete harness v0.1 scaffold"
```

If no verification-only fixes were needed, no extra commit is required after Task 7.

## Implementation Notes

- Do not call the real Claude model during tests.
- Do not add async job state in v0.1.
- Do not let Claude Code modify files.
- Keep `AGENTS.md` lean; do not move detailed rules into it.
- If `mcp==1.28.0` cannot install, stop and ask whether to switch to Node MCP SDK.
- If Claude CLI output shape differs from `normalize_claude_json`, update tests before updating parser behavior.
