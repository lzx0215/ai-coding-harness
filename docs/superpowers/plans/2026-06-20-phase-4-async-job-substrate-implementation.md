# Phase 4 Async Job Substrate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the first Phase 4 slice: run-local async job artifacts, explicit job evidence indexing, fan-in aggregation validation, and Standard versus Strict unavailable-review policy.

**Architecture:** Keep `state.json` as the Harness lifecycle authority. Add machine-checkable job and aggregation schemas, extend the CLI evidence vocabulary, and validate consumed job evidence only when Codex indexes artifacts into `state.json.evidence[]`. Do not add a background worker, cloud queue, live scheduler, or migrate existing synchronous `reviews/` artifacts.

**Tech Stack:** Python standard library, `jsonschema`, `unittest`, Harness JSON schemas, Markdown docs.

---

## File Structure

- Create `harness/schemas/job.schema.json`
  - Defines run-local `jobs/<job-id>/job.json`.
  - Separates process status from Harness lifecycle status.
  - Allows `queued`, `running`, `succeeded`, `failed`, `timeout`, and `cancelled`.
- Create `harness/schemas/aggregation.schema.json`
  - Defines `jobs/aggregation.json`.
  - Records consumed, terminal, incomplete, failed, timeout, cancelled jobs, findings, conflicts, recommendation, and residual risks.
- Modify `harness/cli.py`
  - Extend `EVIDENCE_TYPES` with `agent-job`, `agent-result`, and `aggregation`.
  - Add job status constants.
  - Add consumed-job evidence validation.
  - Add aggregation schema validation.
  - Add Strict unavailable-review transition policy.
- Create `tests/test_async_job_artifacts.py`
  - Schema tests for jobs and aggregation.
  - CLI validation tests for consumed job evidence and aggregation evidence.
- Modify `tests/test_harness_cli.py`
  - Update evidence vocabulary test.
  - Add Standard versus Strict unavailable-review transition tests.
- Modify `docs/INDEX.md`
  - Add this Phase 4 implementation plan.

## Task 1: Job And Aggregation Schemas

**Files:**
- Create: `harness/schemas/job.schema.json`
- Create: `harness/schemas/aggregation.schema.json`
- Create: `tests/test_async_job_artifacts.py`

- [ ] **Step 1: Add failing schema tests**

Create `tests/test_async_job_artifacts.py` with:

```python
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
JOB_SCHEMA = ROOT / "harness" / "schemas" / "job.schema.json"
AGGREGATION_SCHEMA = ROOT / "harness" / "schemas" / "aggregation.schema.json"


def load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validation_errors(schema_path: Path, payload: dict) -> list:
    return list(Draft202012Validator(load_schema(schema_path)).iter_errors(payload))


def minimal_job(status: str = "succeeded") -> dict:
    return {
        "job_id": "claude-review-001",
        "run_id": "test-run",
        "agent": "claude-code",
        "adapter": "claude-review",
        "status": status,
        "input_file": "input.json",
        "output_file": "output.json",
        "raw_log_file": "raw.log",
        "created_at": "2026-06-20T00:00:00Z",
        "started_at": "2026-06-20T00:00:01Z",
        "completed_at": "2026-06-20T00:02:00Z",
        "timeout_seconds": 900,
        "error_reason": None,
        "provenance": {
            "agent": "claude-code",
            "adapter_version": "0.1.0",
            "runtime": "local-cli",
        },
    }


def minimal_aggregation() -> dict:
    return {
        "run_id": "test-run",
        "generated_at": "2026-06-20T00:03:00Z",
        "consumed_jobs": ["claude-review-001"],
        "succeeded_jobs": ["claude-review-001"],
        "failed_jobs": [],
        "timeout_jobs": [],
        "cancelled_jobs": [],
        "incomplete_jobs": [],
        "findings": [],
        "conflicts": [],
        "recommended_transition": None,
        "residual_risks": [],
    }


class AsyncJobArtifactSchemaTest(unittest.TestCase):
    def test_job_schema_accepts_allowed_statuses(self):
        for status in ["queued", "running", "succeeded", "failed", "timeout", "cancelled"]:
            with self.subTest(status=status):
                self.assertEqual(validation_errors(JOB_SCHEMA, minimal_job(status)), [])

    def test_job_schema_rejects_unknown_status(self):
        job = minimal_job("waiting")

        errors = validation_errors(JOB_SCHEMA, job)

        self.assertTrue(errors)

    def test_aggregation_schema_accepts_minimal_payload(self):
        self.assertEqual(validation_errors(AGGREGATION_SCHEMA, minimal_aggregation()), [])

    def test_aggregation_schema_rejects_unknown_transition(self):
        aggregation = minimal_aggregation()
        aggregation["recommended_transition"] = "silently_completed"

        errors = validation_errors(AGGREGATION_SCHEMA, aggregation)

        self.assertTrue(errors)

    def test_aggregation_schema_accepts_high_finding_recommending_review_blocked(self):
        aggregation = minimal_aggregation()
        aggregation["recommended_transition"] = "review_blocked"
        aggregation["findings"] = [
            {
                "job_id": "claude-review-001",
                "severity": "high",
                "title": "Blocking defect",
                "evidence": "Review output reported a high severity finding.",
                "recommendation": "Fix and rerun review.",
            }
        ]

        self.assertEqual(validation_errors(AGGREGATION_SCHEMA, aggregation), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run schema tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_async_job_artifacts -v
```

Expected: fails because `job.schema.json` and `aggregation.schema.json` do not exist.

- [ ] **Step 3: Create `job.schema.json`**

Create `harness/schemas/job.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Harness Async Job",
  "type": "object",
  "required": [
    "job_id",
    "run_id",
    "agent",
    "adapter",
    "status",
    "input_file",
    "output_file",
    "raw_log_file",
    "created_at",
    "timeout_seconds"
  ],
  "properties": {
    "job_id": { "type": "string", "minLength": 1 },
    "run_id": { "type": "string", "minLength": 1 },
    "agent": { "type": "string", "minLength": 1 },
    "adapter": { "type": "string", "minLength": 1 },
    "status": {
      "type": "string",
      "enum": ["queued", "running", "succeeded", "failed", "timeout", "cancelled"]
    },
    "input_file": { "type": "string", "minLength": 1 },
    "output_file": { "type": "string", "minLength": 1 },
    "raw_log_file": { "type": "string", "minLength": 1 },
    "created_at": {
      "type": "string",
      "minLength": 1,
      "format": "date-time",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:Z|[+-]\\d{2}:\\d{2})$"
    },
    "started_at": {
      "type": ["string", "null"],
      "minLength": 1,
      "format": "date-time",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:Z|[+-]\\d{2}:\\d{2})$"
    },
    "completed_at": {
      "type": ["string", "null"],
      "minLength": 1,
      "format": "date-time",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:Z|[+-]\\d{2}:\\d{2})$"
    },
    "timeout_seconds": { "type": "integer", "minimum": 1 },
    "error_reason": { "type": ["string", "null"], "minLength": 1 },
    "provenance": {
      "type": "object",
      "properties": {
        "agent": { "type": "string", "minLength": 1 },
        "adapter_version": { "type": "string", "minLength": 1 },
        "runtime": { "type": "string", "minLength": 1 }
      },
      "additionalProperties": true
    }
  },
  "additionalProperties": false
}
```

- [ ] **Step 4: Create `aggregation.schema.json`**

Create `harness/schemas/aggregation.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Harness Async Job Aggregation",
  "type": "object",
  "required": [
    "run_id",
    "generated_at",
    "consumed_jobs",
    "succeeded_jobs",
    "failed_jobs",
    "timeout_jobs",
    "cancelled_jobs",
    "incomplete_jobs",
    "findings",
    "conflicts",
    "recommended_transition",
    "residual_risks"
  ],
  "properties": {
    "run_id": { "type": "string", "minLength": 1 },
    "generated_at": {
      "type": "string",
      "minLength": 1,
      "format": "date-time",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:Z|[+-]\\d{2}:\\d{2})$"
    },
    "consumed_jobs": { "$ref": "#/$defs/job_id_list" },
    "succeeded_jobs": { "$ref": "#/$defs/job_id_list" },
    "failed_jobs": { "$ref": "#/$defs/job_id_list" },
    "timeout_jobs": { "$ref": "#/$defs/job_id_list" },
    "cancelled_jobs": { "$ref": "#/$defs/job_id_list" },
    "incomplete_jobs": { "$ref": "#/$defs/job_id_list" },
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["job_id", "severity", "title", "evidence", "recommendation"],
        "properties": {
          "job_id": { "type": "string", "minLength": 1 },
          "severity": {
            "type": "string",
            "enum": ["info", "low", "medium", "high", "critical"]
          },
          "title": { "type": "string", "minLength": 1 },
          "evidence": { "type": "string", "minLength": 1 },
          "recommendation": { "type": "string", "minLength": 1 }
        },
        "additionalProperties": false
      }
    },
    "conflicts": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 }
    },
    "recommended_transition": {
      "type": ["string", "null"],
      "enum": [null, "reviewed", "review_blocked", "review_failed", "review_timeout", "review_schema_invalid", "external_review_unavailable", "needs_user_decision"]
    },
    "residual_risks": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 }
    }
  },
  "$defs": {
    "job_id_list": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 }
    }
  },
  "additionalProperties": false
}
```

- [ ] **Step 5: Run schema tests again**

Run:

```powershell
python -m unittest tests.test_async_job_artifacts -v
```

Expected: all schema tests pass.

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
git add harness/schemas/job.schema.json harness/schemas/aggregation.schema.json tests/test_async_job_artifacts.py
git commit -m "feat(harness): add async job artifact schemas"
```

## Task 2: Evidence Vocabulary And Consumed Job Validation

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_harness_cli.py`
- Modify: `tests/test_async_job_artifacts.py`

- [ ] **Step 1: Add failing tests for Phase 4 evidence types**

In `tests/test_harness_cli.py`, update `test_evidence_type_vocabulary_matches_phase_1_contract` into `test_evidence_type_vocabulary_matches_phase_4_contract` and add the three Phase 4 types:

```python
"agent-job",
"agent-result",
"aggregation",
```

Expected full vocabulary is the existing 17 Phase 1 types plus those three Phase 4 types.

- [ ] **Step 2: Add failing tests for consumed job evidence**

Append these helpers to `tests/test_async_job_artifacts.py`:

```python
from harness import cli


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def minimal_state(status: str = "verified") -> dict:
    return {
        "run_id": "test-run",
        "harness_version": "0.2.0",
        "state_schema_version": "0.2.0",
        "status": status,
        "track": "Standard",
        "current_workflow": "standard-code-change",
        "owner": "codex",
        "base_commit": "HEAD",
        "created_at": "2026-06-20T00:00:00Z",
        "updated_at": "2026-06-20T00:00:00Z",
        "external_agents": [
            {
                "name": "claude-code",
                "role": "reviewer",
                "state_access": "none",
                "status": "not_requested",
            }
        ],
        "evidence": [],
    }
```

Add tests:

```python
class AsyncJobEvidenceValidationTest(unittest.TestCase):
    def test_validate_accepts_terminal_agent_job_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            write_json(job_file, minimal_job("succeeded"))
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "agent-job",
                    "path": str(job_file.relative_to(ROOT)),
                }
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.errors, [])

    def test_validate_rejects_non_terminal_agent_job_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            write_json(job_file, minimal_job("running"))
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "agent-job",
                    "path": str(job_file.relative_to(ROOT)),
                }
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("non-terminal job cannot be consumed" in error for error in result.errors),
            result.errors,
        )

    def test_succeeded_job_directory_is_not_auto_indexed_as_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            write_json(job_file, minimal_job("succeeded"))
            state = minimal_state()
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.errors, [])

    def test_validate_rejects_invalid_agent_job_schema(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            job = minimal_job("succeeded")
            job["status"] = "done"
            write_json(job_file, job)
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "agent-job",
                    "path": str(job_file.relative_to(ROOT)),
                }
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("job schema error" in error for error in result.errors),
            result.errors,
        )
```

- [ ] **Step 3: Run new tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_evidence_type_vocabulary_matches_phase_4_contract tests.test_async_job_artifacts.AsyncJobEvidenceValidationTest -v
```

Expected: fails because Phase 4 evidence types and job evidence validation do not exist.

- [ ] **Step 4: Extend CLI constants**

In `harness/cli.py`, update `EVIDENCE_TYPES` with:

```python
"agent-job",
"agent-result",
"aggregation",
```

Add after `COMPLETION_REQUIRED_EVIDENCE_TYPES`:

```python
JOB_SCHEMA = ROOT / "harness" / "schemas" / "job.schema.json"
AGGREGATION_SCHEMA = ROOT / "harness" / "schemas" / "aggregation.schema.json"
JOB_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "timeout", "cancelled"})
TERMINAL_JOB_STATUSES = frozenset({"succeeded", "failed", "timeout", "cancelled"})
```

- [ ] **Step 5: Add JSON artifact loading and schema validation helpers**

Add after `validate_evidence_paths`:

```python
def first_existing_evidence_path(
    raw_path: str,
    *,
    root: Path,
    run_dir: Path,
) -> Path | None:
    for candidate in evidence_path_candidates(raw_path, root=root, run_dir=run_dir):
        if candidate.exists():
            return candidate
    return None


def format_schema_errors(prefix: str, errors: Iterable[Any]) -> list[str]:
    formatted: list[str] = []
    for error in sorted(errors, key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.path) or "<root>"
        formatted.append(f"{prefix} schema error at {location}: {error.message}")
    return formatted


def validate_json_artifact(path: Path, schema_path: Path, prefix: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        payload = load_json(path)
    except UnicodeDecodeError as exc:
        return None, [f"{prefix} invalid encoding: {exc}"]
    except json.JSONDecodeError as exc:
        return None, [f"{prefix} invalid JSON: {exc}"]
    except OSError as exc:
        return None, [f"{prefix} cannot read file: {exc}"]

    schema = load_json(schema_path)
    errors = format_schema_errors(prefix, Draft202012Validator(schema).iter_errors(payload))
    if errors:
        return None, errors
    return payload, []
```

- [ ] **Step 6: Add consumed job evidence validation**

Add after `validate_evidence_types`:

```python
def validate_job_evidence(
    state: dict[str, Any],
    *,
    root: Path,
    run_dir: Path,
) -> list[str]:
    errors: list[str] = []
    for index, evidence in evidence_items(state):
        evidence_type = evidence.get("type")
        if evidence_type != "agent-job":
            continue

        raw_path = evidence.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue

        job_path = first_existing_evidence_path(raw_path, root=root, run_dir=run_dir)
        if job_path is None:
            continue

        job, job_errors = validate_json_artifact(job_path, JOB_SCHEMA, "job")
        errors.extend(f"evidence[{index}]: {error}" for error in job_errors)
        if job is None:
            continue

        status = job.get("status")
        if status not in TERMINAL_JOB_STATUSES:
            errors.append(
                f"non-terminal job cannot be consumed at evidence[{index}]: {status}",
            )

    return errors
```

Update `validate_state`:

```python
    errors.extend(validate_evidence_types(state))
    errors.extend(validate_evidence_paths(state, root=root, run_dir=run_dir))
    errors.extend(validate_job_evidence(state, root=root, run_dir=run_dir))
    errors.extend(validate_aggregation_evidence(state, root=root, run_dir=run_dir))
```

`validate_aggregation_evidence` is added in Task 3. Until Task 3 lands, add only `validate_job_evidence`.

- [ ] **Step 7: Run consumed job tests again**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_evidence_type_vocabulary_matches_phase_4_contract tests.test_async_job_artifacts.AsyncJobEvidenceValidationTest -v
```

Expected: all listed tests pass after Task 2 implementation.

- [ ] **Step 8: Commit Task 2**

Run:

```powershell
git add harness/cli.py tests/test_harness_cli.py tests/test_async_job_artifacts.py
git commit -m "feat(harness): validate consumed async job evidence"
```

## Task 3: Aggregation Evidence Validation

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_async_job_artifacts.py`

- [ ] **Step 1: Add failing aggregation evidence tests**

Add to `AsyncJobEvidenceValidationTest`:

```python
    def test_validate_accepts_aggregation_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            aggregation_file = run_dir / "jobs" / "aggregation.json"
            write_json(aggregation_file, minimal_aggregation())
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "aggregation",
                    "path": str(aggregation_file.relative_to(ROOT)),
                }
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.errors, [])

    def test_validate_rejects_invalid_aggregation_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            aggregation_file = run_dir / "jobs" / "aggregation.json"
            aggregation = minimal_aggregation()
            aggregation["recommended_transition"] = "completed"
            write_json(aggregation_file, aggregation)
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "aggregation",
                    "path": str(aggregation_file.relative_to(ROOT)),
                }
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("aggregation schema error" in error for error in result.errors),
            result.errors,
        )
```

- [ ] **Step 2: Run aggregation tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_async_job_artifacts.AsyncJobEvidenceValidationTest.test_validate_accepts_aggregation_evidence tests.test_async_job_artifacts.AsyncJobEvidenceValidationTest.test_validate_rejects_invalid_aggregation_evidence -v
```

Expected: fails because `aggregation` validation is not implemented yet.

- [ ] **Step 3: Add aggregation evidence validation**

Add after `validate_job_evidence`:

```python
def validate_aggregation_evidence(
    state: dict[str, Any],
    *,
    root: Path,
    run_dir: Path,
) -> list[str]:
    errors: list[str] = []
    for index, evidence in evidence_items(state):
        if evidence.get("type") != "aggregation":
            continue

        raw_path = evidence.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue

        aggregation_path = first_existing_evidence_path(raw_path, root=root, run_dir=run_dir)
        if aggregation_path is None:
            continue

        _aggregation, aggregation_errors = validate_json_artifact(
            aggregation_path,
            AGGREGATION_SCHEMA,
            "aggregation",
        )
        errors.extend(f"evidence[{index}]: {error}" for error in aggregation_errors)

    return errors
```

Update `validate_state` after job validation:

```python
    errors.extend(validate_aggregation_evidence(state, root=root, run_dir=run_dir))
```

- [ ] **Step 4: Run aggregation tests again**

Run:

```powershell
python -m unittest tests.test_async_job_artifacts.AsyncJobEvidenceValidationTest.test_validate_accepts_aggregation_evidence tests.test_async_job_artifacts.AsyncJobEvidenceValidationTest.test_validate_rejects_invalid_aggregation_evidence -v
```

Expected: both pass.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add harness/cli.py tests/test_async_job_artifacts.py
git commit -m "feat(harness): validate aggregation evidence"
```

## Task 4: Track-Aware Unavailable Review Policy

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_harness_cli.py`

- [ ] **Step 1: Add failing tests for Standard and Strict policy**

Add these tests to `HarnessCliTest`:

```python
    def test_advance_allows_standard_unavailable_review_to_risk_accepted(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="external_review_unavailable")
            state["track"] = "Standard"
            state["current_workflow"] = "standard-code-change"
            write_state(run_dir, state)

            advanced = cli.advance_run(run_dir, "risk_accepted", actor="codex", root=ROOT)

        self.assertEqual(advanced["status"], "risk_accepted")

    def test_advance_rejects_strict_unavailable_review_to_risk_accepted(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="external_review_unavailable")
            state["track"] = "Strict"
            state["current_workflow"] = "strict-risk-change"
            write_state(run_dir, state)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "risk_accepted", actor="codex", root=ROOT)

        self.assertIn(
            "strict unavailable review requires needs_user_decision",
            str(raised.exception),
        )

    def test_advance_allows_strict_unavailable_review_to_needs_user_decision(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="external_review_unavailable")
            state["track"] = "Strict"
            state["current_workflow"] = "strict-risk-change"
            write_state(run_dir, state)

            advanced = cli.advance_run(
                run_dir,
                "needs_user_decision",
                actor="codex",
                root=ROOT,
            )

        self.assertEqual(advanced["status"], "needs_user_decision")
```

- [ ] **Step 2: Run policy tests and verify one fails**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_advance_allows_standard_unavailable_review_to_risk_accepted tests.test_harness_cli.HarnessCliTest.test_advance_rejects_strict_unavailable_review_to_risk_accepted tests.test_harness_cli.HarnessCliTest.test_advance_allows_strict_unavailable_review_to_needs_user_decision -v
```

Expected: Strict `external_review_unavailable -> risk_accepted` currently succeeds, so the rejection test fails.

- [ ] **Step 3: Add transition policy validation**

Add after `validate_completion_evidence`:

```python
def validate_transition_policy(
    state: dict[str, Any],
    next_status: str,
) -> list[str]:
    if (
        state.get("status") == "external_review_unavailable"
        and state.get("track") == "Strict"
        and next_status == "risk_accepted"
    ):
        return [
            "strict unavailable review requires needs_user_decision before risk acceptance",
        ]
    return []
```

In `advance_run`, after the `can_transition` check and before `validate_completion_evidence`, add:

```python
    policy_errors = validate_transition_policy(state, next_status)
    if policy_errors:
        raise HarnessCliError(format_errors(policy_errors))
```

- [ ] **Step 4: Run policy tests again**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_advance_allows_standard_unavailable_review_to_risk_accepted tests.test_harness_cli.HarnessCliTest.test_advance_rejects_strict_unavailable_review_to_risk_accepted tests.test_harness_cli.HarnessCliTest.test_advance_allows_strict_unavailable_review_to_needs_user_decision -v
```

Expected: all pass.

- [ ] **Step 5: Commit Task 4**

Run:

```powershell
git add harness/cli.py tests/test_harness_cli.py
git commit -m "feat(harness): enforce strict unavailable review policy"
```

## Task 5: Full Verification And Review

**Files:**
- No new source files.
- Verify all files from Tasks 1-4.

- [ ] **Step 1: Run full unit suite**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: exit 0, all tests pass, with the known env-gated pip hash test skipped unless `HARNESS_RUN_PIP_HASH_CHECK=1` is set.

- [ ] **Step 2: Validate all historical run directories**

Run:

```powershell
Get-ChildItem -Directory harness/runs | ForEach-Object { python -m harness.cli validate $_.FullName }
```

Expected: exit 0 and every existing run prints `valid:`.

- [ ] **Step 3: Run diff hygiene**

Run:

```powershell
git diff --check
```

Expected: exit 0. Windows line-ending warnings are acceptable if no whitespace errors are reported.

- [ ] **Step 4: Inspect final diff**

Run:

```powershell
git diff --stat
git status --short --branch
```

Expected changed files:

```text
harness/cli.py
harness/schemas/job.schema.json
harness/schemas/aggregation.schema.json
tests/test_async_job_artifacts.py
tests/test_harness_cli.py
```

- [ ] **Step 5: Run external review when available**

This diff touches state management, workflow rules, evidence validation, and schemas, so `harness/core/delegation.md` requires Claude Code review when available.

Use the existing `mcp/claude-review/scripts/invoke-claude-reviewer.py` wrapper with a review input that includes:

- task summary
- this implementation plan
- `git diff <base>..HEAD`
- changed file list
- verification output

Expected acceptable terminal review statuses:

- `passed`
- `findings` with no `high` or `critical` findings after triage

If the adapter is unavailable, record this as not verified and residual risk. Do not claim external review passed without an artifact.

- [ ] **Step 6: Leave verification artifacts temporary unless a run record is added**

This first Phase 4 implementation slice does not create a source-controlled Harness run record by default. Keep Claude review input/output artifacts in a temp directory and report the temp artifact paths in the final handoff.

If the user explicitly asks to create a source-controlled implementation run record, add that run under `harness/runs/<run-id>/` in a separate docs commit after the runtime commits are complete.

## Acceptance Checklist

- [ ] `job.schema.json` accepts all allowed job statuses and rejects unknown statuses.
- [ ] `aggregation.schema.json` accepts minimal fan-in payloads and rejects unknown recommended transitions.
- [ ] `EVIDENCE_TYPES` includes `agent-job`, `agent-result`, and `aggregation`.
- [ ] Historical run validation remains green.
- [ ] A terminal `agent-job` can be explicitly indexed as evidence.
- [ ] A non-terminal `agent-job` cannot be consumed as evidence.
- [ ] A succeeded job directory is not auto-indexed into `state.json.evidence[]`.
- [ ] Aggregation evidence validates against the aggregation schema.
- [ ] Writing or indexing aggregation evidence does not mutate `state.json.status`.
- [ ] Standard unavailable review can enter risk acceptance.
- [ ] Strict unavailable review goes to `needs_user_decision` instead of silent risk acceptance.
- [ ] Existing synchronous `reviews/claude-review*.json` artifacts remain valid without migration.

## Outcome

As of 2026-06-21, the Phase 4 async job substrate described by this plan is implemented in the source tree and covered by the default test suite. The implementation includes run-local `job`, `agent-result`, and `aggregation` schemas, explicit async evidence validation, consumed job duplicate/status checks, aggregation cross-checking, and Standard versus Strict unavailable-review policy.

The plan checkboxes intentionally remain unchanged as historical planning text. No source-controlled Phase 4 implementation run record has been created.
