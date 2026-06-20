# Phase 2 Run Definition and Evidence Design

## Summary

Phase 2 makes run definition, triage, planning, and human-readable run artifacts more structured without changing the Harness authority model.

The main design decision is to use YAML frontmatter for human-authored Markdown artifacts and keep `validate` and `advance` as the only authorities for evidence validity and state transitions. Helper commands may reduce manual work, but they must not decide what evidence counts or create a second state gate outside `advance`.

## Goals

- Define a stable Markdown frontmatter contract for `task.md`, `triage.md`, `plan.md`, and `handoff.md`.
- Preserve readable run records for humans.
- Keep historical run records valid without migration.
- Add convenience command designs for run initialization, evidence indexing, and readiness checks.
- Keep `validate` as the evidence type, path, and artifact validation authority.
- Keep `advance` as the only Harness state transition authority.
- Avoid any forward dependency from Phase 2 plan fields to Phase 3 review disposition values.

## Non-goals

- Add async jobs or multi-agent fan-in. Those belong to Phase 4.
- Add a new Harness status.
- Replace Markdown run records with JSON.
- Make missing frontmatter an error for historical runs.
- Enforce review decision semantics before Phase 3 defines them.
- Let helper commands bypass `validate` or `advance`.

## Relationship to Other Phases

Phase 1 already defines:

- The evidence type vocabulary.
- Evidence path validation.
- Completion evidence gates.
- `advance` as the only state transition entrypoint.

Phase 2 builds on that foundation by adding structure around the documents that explain the run. It does not weaken or duplicate Phase 1 validation.

Phase 3 will define review decision and memory closure. Phase 2 plan acceptance fields therefore stay free text. They must not reference Phase 3 disposition enums.

Phase 4 handles async jobs and agent result aggregation. Phase 2 helper commands must not create job status semantics or consume async job artifacts.

## Current State

The repository already has templates for:

- `task.md`
- `plan.md`
- `verification.md`
- `handoff.md`
- `agent-brief.md`
- `agent-result.md`
- `risk-acceptance.md`

Run state already records `evidence[]` entries with `type`, `path`, and optional `description`.

The current gap is that task definition, triage rationale, plan acceptance criteria, and handoff content are mostly free-form. That is readable, but hard to check consistently before work begins or before a run is closed.

## Considered Approaches

| Approach | Trade-off | Decision |
| --- | --- | --- |
| Convert all task, plan, triage, and handoff documents to JSON | Strong machine validation, but poor human readability and unnecessary churn for existing run records. | Rejected. |
| Keep all documents as unconstrained Markdown | Maximum readability, but weak repeatability and hard to check across runs. | Rejected. |
| Use YAML frontmatter for machine fields and Markdown bodies for human context | Preserves readability while allowing predictable checks. | Chosen. |
| Add new hard gates through a `check-ready` command | Convenient, but creates a second transition authority outside `advance`. | Rejected. |
| Add hard stage gates inside `advance` if needed | Preserves the state authority boundary. | Chosen as the only allowed hard-gate path. |

## Authority Boundaries

Phase 2 helper commands are convenience commands only. They do not replace `validate` or `advance` as Harness authorities.

`validate` remains the only authority for:

- Evidence type vocabulary.
- Evidence path existence and repository containment.
- Artifact-level schema validation.
- Historical run compatibility validation.

`advance` remains the only authority for:

- Legal state transitions.
- Actor checks.
- Transition policy.
- Completion gates.
- Any future hard stage gate.

`index-evidence` may append evidence entries to `state.json.evidence[]`, but the entry is not valid until `harness.cli validate` accepts its type, path, and artifact-level contract. It must not implement its own definition of "valid evidence."

`check-ready` is predictive guidance only. It may report missing task, triage, plan, handoff, or frontmatter fields before a user attempts a transition, but it is not a state gate and must not update `state.json`.

If Phase 2 or a later phase adds a hard gate for transitions such as `draft -> triaged` or `triaged -> planned`, the gate must be implemented inside `advance` as a `validate_stage_gate`-style check beside `validate_completion_evidence`. A helper command cannot be the gate.

## Markdown Frontmatter Contract

Human-authored run documents use this shape:

```markdown
---
run_id: 2026-06-20-example
schema_version: 0.1.0
---

# Human-readable title

Human-authored body.
```

The frontmatter is for stable machine-readable fields. The Markdown body remains the audit-friendly human record.

Missing frontmatter in historical run records is a validation warning, not an error. Missing frontmatter in newly generated templates should be avoided, but Phase 2 does not rewrite historical runs.

### `task.md`

Recommended frontmatter:

```yaml
run_id: 2026-06-20-example
schema_version: 0.1.0
track: Standard
workflow: standard-code-change
owner: codex
requested_outcome: "Implement the requested behavior with tests."
scope:
  - "Files or subsystems in scope."
non_goals:
  - "Explicitly excluded work."
constraints:
  - "Known constraints."
```

Rules:

- `track` must match the selected Harness track.
- `workflow` must be a registered workflow ID before it is used in `state.json`.
- `non_goals` is required for Strict tasks and recommended for Standard tasks.
- `requested_outcome` must be descriptive text, not a completion claim.

### `triage.md`

Recommended frontmatter:

```yaml
run_id: 2026-06-20-example
schema_version: 0.1.0
track: Standard
workflow: standard-code-change
review_required: true
strict_triggers: []
risk_reasons:
  - "Touches state management."
verification_required:
  - "unit tests"
  - "targeted CLI smoke"
```

Rules:

- `track` and `workflow` must align with `state.json`.
- `strict_triggers` records why a task was or was not escalated.
- `review_required` is advisory for planning. Review handling is still governed by Phase 1 completion evidence and Phase 3 review decision rules.

### `plan.md`

Recommended frontmatter:

```yaml
run_id: 2026-06-20-example
schema_version: 0.1.0
workflow: standard-code-change
acceptance:
  - "Observable acceptance criterion written in free text."
verification:
  - "Command or manual check expected before completion."
review_plan:
  - "Reviewer or waiver expectation in free text."
constraints:
  - "Implementation constraint."
recovery_strategy: null
residual_risk_owner: null
```

Rules:

- `acceptance` is free text in Phase 2.
- `acceptance` must not reference Phase 3 review disposition enums.
- `verification` is the planned verification, not proof that verification ran.
- Strict tasks require `recovery_strategy` and `residual_risk_owner` before implementation.

### `handoff.md`

Phase 2 defines the frontmatter syntax for handoff, but Phase 3 defines the closure semantics.

Recommended frontmatter:

```yaml
run_id: 2026-06-20-example
schema_version: 0.1.0
changed:
  - "What changed."
verified:
  - "Verification evidence summary."
not_verified:
  - "What was not verified."
residual_risks:
  - "Remaining risk."
next_step: "Concrete next step."
memory_update: none
memory_files: []
```

Rules:

- `verified` summarizes verification evidence; it does not replace the `verification` evidence type.
- `memory_update` may be `none`, `updated`, or `deferred`.
- Phase 3 decides how handoff content is checked before completion.

## Helper Command Designs

### `init-run`

Purpose: create a run directory and initial run artifacts from templates.

Allowed behavior:

- Create `state.json` in `draft` state for a new run.
- Create `task.md`, `triage.md`, `plan.md`, and `handoff.md` placeholders with frontmatter.
- Create initial evidence entries only when the referenced files exist.
- Run `validate` after creation and report its result.

Forbidden behavior:

- Advance an existing run.
- Mark a run as planned, verified, reviewed, or completed.
- Invent workflow IDs.
- Treat template presence as completion evidence.

### `index-evidence`

Purpose: reduce manual JSON editing when adding evidence entries.

Allowed behavior:

- Build a candidate `state.json` with a new `evidence[]` entry.
- Delegate legality checks to the same validation logic used by `validate`.
- Atomically write the candidate only when the validation result allows it.
- Report validation errors without redefining evidence rules.

Forbidden behavior:

- Define its own evidence vocabulary.
- Skip path containment checks.
- Treat a path as valid because it matches a naming convention.
- Mark an artifact consumed if its artifact-level contract fails validation.

### `check-ready`

Purpose: give predictive guidance before a user attempts a transition.

Allowed behavior:

- Read `state.json` and known run artifacts.
- Report missing or inconsistent frontmatter fields.
- Report likely blockers for `draft -> triaged`, `triaged -> planned`, or closure readiness.
- Return non-zero when readiness warnings are present, if useful for automation.

Forbidden behavior:

- Mutate `state.json`.
- Create evidence.
- Advance state.
- Act as a hard transition gate.

## Warning Model

Phase 2 introduces the concept of validation warnings for advisory document structure checks.

Warnings may include:

- Missing frontmatter on historical Markdown artifacts.
- Missing optional fields.
- Planned verification that has not run yet.
- Handoff fields not yet filled while a run is still in progress.

Errors remain reserved for invalid state schema, invalid evidence types, unsafe or missing evidence paths, artifact schema failures, illegal transitions, and completion gate failures.

## Verification Strategy

Unit tests should cover:

- Existing historical runs continue to validate.
- Missing frontmatter in historical Markdown artifacts produces warnings, not errors.
- Generated templates include recommended frontmatter.
- `index-evidence` delegates to validation and rejects unknown evidence types.
- `index-evidence` delegates to validation and rejects unsafe or missing paths.
- `check-ready` does not mutate `state.json`.
- `check-ready` reports missing task, triage, or plan frontmatter as predictive findings.
- `init-run` creates a draft run that passes `validate`.
- No helper command can advance state.

If a hard stage gate is introduced in Phase 2 implementation, additional tests must prove:

- The gate is called from `advance`.
- The gate does not run from `check-ready`.
- Intermediate transitions without the required document evidence fail before writing state.
- Historical completed runs are not rewritten.

Repository-level verification should run:

```powershell
python -m unittest discover -s tests -v
python -m harness.cli validate harness/runs/example-fast-doc-change
```

## Acceptance Criteria

- Markdown run artifacts have a documented frontmatter contract.
- Historical runs remain valid without migration.
- Missing historical frontmatter is warning-level, not error-level.
- `validate` remains the authority for evidence validity.
- `advance` remains the authority for state transitions.
- `index-evidence` does not define evidence validity.
- `check-ready` is explicitly predictive and non-mutating.
- Phase 2 plan acceptance fields do not depend on Phase 3 disposition enums.
- Any future hard stage gate is implemented inside `advance`, not as a helper-command side effect.
