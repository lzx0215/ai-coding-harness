# Phase 3 Review Decision and Memory Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Phase 3 review decision artifact, its indexing validation, the review-related `advance` gate, and handoff/memory closure checks without adding any new Harness state, any new evidence type, or any historical-run migration.

**Spec:** `docs/superpowers/specs/2026-06-20-phase-3-review-decision-memory-design.md` is the authority for behavior. This plan is the task-by-task implementation of that spec.

**Architecture:** Keep every Phase 3 rule inside the existing authority boundaries. `validate` stays the only evidence/artifact authority and gains review-decision semantic validation. `advance` stays the only transition authority and gains two new gates: a review-decision transition gate and a handoff/memory closure gate that fires only on `-> completed`. No Phase 3 rule lives in `check-ready` fatal logic; the soft memory-declaration disagreement remains a `check-ready` warning. `validate` still does not fatal-parse Markdown frontmatter, so historical completed runs remain valid.

**Tech Stack:** Python standard library, `unittest`, existing `jsonschema` validation, existing `harness.cli` state helpers, existing `harness.readiness` frontmatter parser.

---

## Scope

Implement Phase 3 only.

In scope:

- `harness/schemas/review-decision.schema.json` for the `review-decision.json` artifact.
- `validate` loads and validates indexed `review-decision.json` (indexed as `review-evidence`) against the schema plus semantic rules.
- `advance` rejects review-related target states that conflict with an indexed `review-decision.json.recommended_status`.
- `advance -> completed` handoff closure gate over the Phase 2 handoff frontmatter fields.
- Memory closure rules: `memory_update`/`memory_files` consistency with hard failures and one soft warning.
- Tests proving historical runs keep validating and that no new state or evidence type is introduced.

Out of scope (explicit non-goals from the spec):

- No new Harness status. Review disposition is a field, not a state.
- No new `review-decision` evidence type. The artifact is indexed as `review-evidence`.
- No migration of historical runs. Historical runs without `review-decision.json` stay valid.
- No replacement of verification by review. `verification` evidence is still required for completion.
- No change to reviewer output schemas or Phase 4 job aggregation.

## Authority Boundaries (Phase 3-specific)

Phase 3 follows the Phase 2 authority contract exactly:

- `validate` gains review-decision schema + semantic checks. It is still the only artifact authority.
- `advance` gains the review-decision transition gate (next to `validate_transition_policy`) and the handoff/memory closure gate (next to `validate_completion_evidence`). It is still the only transition authority.
- `check-ready` gains only the soft memory-declaration disagreement warning. It is still predictive and non-mutating.
- `validate` never fatal-parses Markdown. The only place handoff frontmatter is fatal is the `advance -> completed` closure gate. This preserves "historical runs remain valid."

## Detection Rule for the Review Decision Artifact

An indexed `review-evidence` entry is `{type, path, description}`. There is no sub-type field, so an artifact is treated as a `review-decision.json` **iff the resolved path's basename is `review-decision.json`**. This matches the canonical path the spec defines (`harness/runs/<run-id>/reviews/review-decision.json`) and leaves every other `review-evidence` artifact (raw review outputs, logs) untouched. Historical runs index no such path, so the new checks never fire on them.

## File Structure

- Create `harness/schemas/review-decision.schema.json`
  - JSON Schema (draft 2020-12) for the review decision artifact.
  - Encodes disposition enum, `recommended_status` enum, and `disposition -> recommended_status` consistency via `allOf if/then`.

- Modify `harness/cli.py`
  - Add `REVIEW_DECISION_SCHEMA` constant and review-decision helpers.
  - Add `validate_review_decision_evidence(...)` called from `validate_state`.
  - Add `validate_review_decision_transition(...)` called from `advance_run`.
  - Add `validate_handoff_closure(...)` called from `advance_run` on `-> completed`.
  - Register the soft memory-disagreement path for `check-ready` via `readiness`.

- Modify `harness/readiness.py`
  - Add the soft `memory_update`/`memory_files` disagreement warning to `validate_document_frontmatter` for `handoff.md`. (Warning only, never fatal.)

- Create `tests/test_phase3_review_decision.py`
  - Schema tests: dispositions, `recommended_status`, `blocked`/`process-failed` consistency, override rule inputs.

- Modify `tests/test_harness_cli.py`
  - `validate` loads and accepts/rejects indexed `review-decision.json`.
  - `advance` enforces the review-decision transition gate.
  - `advance -> completed` enforces handoff and memory closure.
  - Vocabulary invariant still holds (no new evidence type).

- Create `tests/test_phase3_closure.py`
  - Handoff closure field requirements and memory consistency for the completion gate, plus the `check-ready` soft warning.

---

### Task 1: Add the Review Decision Schema

**Files:**
- Create: `harness/schemas/review-decision.schema.json`
- Create: `tests/test_phase3_review_decision.py`

- [ ] **Step 1: Write failing schema tests**

Create `tests/test_phase3_review_decision.py`:

```python
import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "harness" / "schemas" / "review-decision.schema.json"


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate(payload: dict) -> list:
    return list(Draft202012Validator(load_schema()).iter_errors(payload))


def minimal_decision() -> dict:
    return {
        "schema_version": "0.1.0",
        "run_id": "2026-06-20-example",
        "generated_at": "2026-06-20T00:00:00Z",
        "disposition": "findings-triaged",
        "recommended_status": "reviewed",
        "decision_owner": "codex",
        "source_evidence": [
            {
                "type": "review-output",
                "path": "harness/runs/2026-06-20-example/reviews/claude-review.json",
            }
        ],
        "severity_counts": {
            "critical": 0,
            "high": 0,
            "medium": 1,
            "low": 0,
            "info": 0,
        },
        "resolved_findings": [],
        "accepted_risks": [],
        "not_tested": [],
        "residual_risks": [],
        "notes": "Medium finding triaged as non-blocking.",
    }


class ReviewDecisionSchemaTest(unittest.TestCase):
    def test_schema_accepts_every_allowed_disposition(self):
        for disposition, recommended_status in [
            ("passed", "reviewed"),
            ("findings-triaged", "reviewed"),
            ("waived", "reviewed"),
            ("unavailable", "external_review_unavailable"),
            ("process-failed", "review_failed"),
            ("process-failed", "review_timeout"),
            ("process-failed", "review_schema_invalid"),
            ("risk-accepted", "risk_accepted"),
            ("blocked", "review_blocked"),
        ]:
            with self.subTest(disposition=disposition, recommended_status=recommended_status):
                payload = minimal_decision()
                payload["disposition"] = disposition
                payload["recommended_status"] = recommended_status

                self.assertEqual(validate(payload), [])

    def test_schema_rejects_unknown_disposition(self):
        payload = minimal_decision()
        payload["disposition"] = "approved"

        self.assertTrue(validate(payload))

    def test_schema_rejects_unknown_recommended_status(self):
        payload = minimal_decision()
        payload["recommended_status"] = "completed"

        self.assertTrue(validate(payload))

    def test_schema_requires_blocked_disposition_to_recommend_review_blocked(self):
        payload = minimal_decision()
        payload["disposition"] = "blocked"
        payload["recommended_status"] = "reviewed"

        self.assertTrue(validate(payload))

    def test_schema_requires_reviewed_dispositions_to_recommend_reviewed(self):
        for disposition in ["passed", "findings-triaged", "waived"]:
            with self.subTest(disposition=disposition):
                payload = minimal_decision()
                payload["disposition"] = disposition
                payload["recommended_status"] = "review_blocked"

                self.assertTrue(validate(payload))

    def test_schema_requires_unavailable_disposition_to_recommend_unavailable_state(self):
        payload = minimal_decision()
        payload["disposition"] = "unavailable"
        payload["recommended_status"] = "reviewed"

        self.assertTrue(validate(payload))

    def test_schema_requires_risk_accepted_disposition_to_recommend_risk_accepted_state(self):
        payload = minimal_decision()
        payload["disposition"] = "risk-accepted"
        payload["recommended_status"] = "reviewed"

        self.assertTrue(validate(payload))

    def test_schema_requires_process_failed_to_recommend_process_failure_state(self):
        for recommended_status in ["reviewed", "review_blocked", "external_review_unavailable"]:
            with self.subTest(recommended_status=recommended_status):
                payload = minimal_decision()
                payload["disposition"] = "process-failed"
                payload["recommended_status"] = recommended_status

                self.assertTrue(validate(payload))

    def test_schema_requires_all_documented_fields(self):
        required_fields = [
            "schema_version",
            "run_id",
            "generated_at",
            "disposition",
            "recommended_status",
            "decision_owner",
            "source_evidence",
            "severity_counts",
            "resolved_findings",
            "accepted_risks",
            "not_tested",
            "residual_risks",
        ]
        for field in required_fields:
            with self.subTest(field=field):
                payload = copy.deepcopy(minimal_decision())
                del payload[field]

                self.assertTrue(validate(payload))

    def test_schema_severity_counts_requires_all_severities(self):
        payload = minimal_decision()
        payload["severity_counts"] = {"critical": 0, "high": 0}

        self.assertTrue(validate(payload))

    def test_schema_allows_optional_notes(self):
        payload = minimal_decision()
        payload["notes"] = "Free text decision notes."

        self.assertEqual(validate(payload), [])

    def test_schema_rejects_unknown_top_level_property(self):
        payload = minimal_decision()
        payload["unexpected_field"] = "no"

        self.assertTrue(validate(payload))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run schema tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_phase3_review_decision -v
```

Expected: ERROR/FAIL because `harness/schemas/review-decision.schema.json` does not exist.

- [ ] **Step 3: Create the review decision schema**

Create `harness/schemas/review-decision.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Harness Review Decision Artifact",
  "type": "object",
  "required": [
    "schema_version",
    "run_id",
    "generated_at",
    "disposition",
    "recommended_status",
    "decision_owner",
    "source_evidence",
    "severity_counts",
    "resolved_findings",
    "accepted_risks",
    "not_tested",
    "residual_risks"
  ],
  "properties": {
    "schema_version": { "type": "string", "enum": ["0.1.0"] },
    "run_id": { "type": "string", "minLength": 1 },
    "generated_at": {
      "type": "string",
      "minLength": 1,
      "format": "date-time",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:Z|[+-]\\d{2}:\\d{2})$"
    },
    "disposition": {
      "type": "string",
      "enum": [
        "passed",
        "findings-triaged",
        "waived",
        "unavailable",
        "process-failed",
        "risk-accepted",
        "blocked"
      ]
    },
    "recommended_status": {
      "type": "string",
      "enum": [
        "reviewed",
        "review_blocked",
        "review_failed",
        "review_timeout",
        "review_schema_invalid",
        "external_review_unavailable",
        "risk_accepted"
      ]
    },
    "decision_owner": { "type": "string", "minLength": 1 },
    "source_evidence": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type", "path"],
        "properties": {
          "type": { "type": "string", "minLength": 1 },
          "path": { "type": "string", "minLength": 1 }
        },
        "additionalProperties": false
      }
    },
    "severity_counts": {
      "type": "object",
      "required": ["critical", "high", "medium", "low", "info"],
      "properties": {
        "critical": { "type": "integer", "minimum": 0 },
        "high": { "type": "integer", "minimum": 0 },
        "medium": { "type": "integer", "minimum": 0 },
        "low": { "type": "integer", "minimum": 0 },
        "info": { "type": "integer", "minimum": 0 }
      },
      "additionalProperties": false
    },
    "resolved_findings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["title", "evidence"],
        "properties": {
          "title": { "type": "string", "minLength": 1 },
          "evidence": { "type": "string", "minLength": 1 },
          "severity": {
            "type": "string",
            "enum": ["info", "low", "medium", "high", "critical"]
          }
        },
        "additionalProperties": false
      }
    },
    "accepted_risks": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["risk", "evidence"],
        "properties": {
          "risk": { "type": "string", "minLength": 1 },
          "evidence": { "type": "string", "minLength": 1 }
        },
        "additionalProperties": false
      }
    },
    "not_tested": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 }
    },
    "residual_risks": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 }
    },
    "notes": { "type": "string", "minLength": 1 }
  },
  "allOf": [
    {
      "if": {
        "properties": {
          "disposition": { "enum": ["passed", "findings-triaged", "waived"] }
        },
        "required": ["disposition"]
      },
      "then": {
        "properties": { "recommended_status": { "const": "reviewed" } },
        "required": ["recommended_status"]
      }
    },
    {
      "if": {
        "properties": { "disposition": { "const": "unavailable" } },
        "required": ["disposition"]
      },
      "then": {
        "properties": {
          "recommended_status": { "const": "external_review_unavailable" }
        },
        "required": ["recommended_status"]
      }
    },
    {
      "if": {
        "properties": { "disposition": { "const": "risk-accepted" } },
        "required": ["disposition"]
      },
      "then": {
        "properties": { "recommended_status": { "const": "risk_accepted" } },
        "required": ["recommended_status"]
      }
    },
    {
      "if": {
        "properties": { "disposition": { "const": "blocked" } },
        "required": ["disposition"]
      },
      "then": {
        "properties": { "recommended_status": { "const": "review_blocked" } },
        "required": ["recommended_status"]
      }
    },
    {
      "if": {
        "properties": { "disposition": { "const": "process-failed" } },
        "required": ["disposition"]
      },
      "then": {
        "properties": {
          "recommended_status": {
            "enum": ["review_failed", "review_timeout", "review_schema_invalid"]
          }
        },
        "required": ["recommended_status"]
      }
    }
  ],
  "additionalProperties": false
}
```

Rationale: `disposition -> recommended_status` consistency for every disposition is encoded as `allOf if/then`, mirroring how `state.schema.json` ties workflows to tracks. Cross-evidence rules (waived/risk-accepted evidence, high/critical override, and `source_evidence` indexability) cannot be expressed in schema and are enforced by the semantic validator in Task 2.

- [ ] **Step 4: Run schema tests to verify they pass**

Run:

```powershell
python -m unittest tests.test_phase3_review_decision -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```powershell
git add harness/schemas/review-decision.schema.json tests/test_phase3_review_decision.py
git commit -m "feat: add phase 3 review decision schema"
```

---

### Task 2: Validate Indexed Review Decision Evidence

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_harness_cli.py`

- [ ] **Step 1: Add failing validation tests**

Add these tests inside `HarnessCliTest` in `tests/test_harness_cli.py`:

```python
    def test_validate_accepts_indexed_review_decision_as_review_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            # Make the referenced source_evidence path indexable (it exists).
            (reviews_dir / "claude-review.json").write_text(
                json.dumps({"status": "passed"}),
                encoding="utf-8",
            )
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "passed",
                        "recommended_status": "reviewed",
                        "decision_owner": "codex",
                        "source_evidence": [
                            {"type": "review-output", "path": "reviews/claude-review.json"}
                        ],
                        "severity_counts": {
                            "critical": 0,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": [],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.errors, [], result.errors)

    def test_validate_rejects_indexed_review_decision_with_unknown_disposition(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "approved",
                        "recommended_status": "reviewed",
                        "decision_owner": "codex",
                        "source_evidence": [],
                        "severity_counts": {
                            "critical": 0,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": [],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("review-decision" in error and "schema error" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_review_decision_run_id_mismatch(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "another-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "passed",
                        "recommended_status": "reviewed",
                        "decision_owner": "codex",
                        "source_evidence": [],
                        "severity_counts": {
                            "critical": 0,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": [],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("does not match state run_id" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_high_finding_reviewed_without_resolution(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "findings-triaged",
                        "recommended_status": "reviewed",
                        "decision_owner": "codex",
                        "source_evidence": [],
                        "severity_counts": {
                            "critical": 0,
                            "high": 1,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": [],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("high or critical finding" in error for error in result.errors),
            result.errors,
        )

    def test_validate_allows_high_finding_blocked_decision(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "blocked",
                        "recommended_status": "review_blocked",
                        "decision_owner": "codex",
                        "source_evidence": [],
                        "severity_counts": {
                            "critical": 1,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": ["Critical finding blocks review."],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.errors, [], result.errors)

    def test_validate_allows_high_finding_reviewed_with_risk_acceptance(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "risk-accepted",
                        "recommended_status": "risk_accepted",
                        "decision_owner": "codex",
                        "source_evidence": [],
                        "severity_counts": {
                            "critical": 0,
                            "high": 1,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [
                            {"risk": "High finding accepted.", "evidence": "risk-acceptance.md"}
                        ],
                        "not_tested": [],
                        "residual_risks": ["High finding accepted as risk."],
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "risk-acceptance.md").write_text("# Risk Acceptance\n", encoding="utf-8")
            state = minimal_state(status="external_review_unavailable")
            state["track"] = "Standard"
            state["current_workflow"] = "standard-code-change"
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                },
                {
                    "type": "risk-acceptance",
                    "path": "risk-acceptance.md",
                    "description": "Risk acceptance evidence.",
                },
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.errors, [], result.errors)

    def test_validate_rejects_waived_decision_without_review_waiver_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "waived",
                        "recommended_status": "reviewed",
                        "decision_owner": "codex",
                        "source_evidence": [],
                        "severity_counts": {
                            "critical": 0,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": [],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("review-waiver" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_review_decision_with_non_indexable_source_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "passed",
                        "recommended_status": "reviewed",
                        "decision_owner": "codex",
                        "source_evidence": [
                            {
                                "type": "review-output",
                                "path": "reviews/never-created.json",
                            }
                        ],
                        "severity_counts": {
                            "critical": 0,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": [],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any(
                "source_evidence" in error and "does not exist" in error
                for error in result.errors
            ),
            result.errors,
        )
```

- [ ] **Step 2: Run validation tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_validate_accepts_indexed_review_decision_as_review_evidence tests.test_harness_cli.HarnessCliTest.test_validate_rejects_indexed_review_decision_with_unknown_disposition tests.test_harness_cli.HarnessCliTest.test_validate_rejects_review_decision_run_id_mismatch tests.test_harness_cli.HarnessCliTest.test_validate_rejects_high_finding_reviewed_without_resolution tests.test_harness_cli.HarnessCliTest.test_validate_allows_high_finding_blocked_decision tests.test_harness_cli.HarnessCliTest.test_validate_allows_high_finding_reviewed_with_risk_acceptance tests.test_harness_cli.HarnessCliTest.test_validate_rejects_waived_decision_without_review_waiver_evidence tests.test_harness_cli.HarnessCliTest.test_validate_rejects_review_decision_with_non_indexable_source_evidence -v
```

Expected: FAIL because review-decision evidence is not validated yet.

- [ ] **Step 3: Add the schema constant and detection helper**

In `harness/cli.py`, add near the other schema constants:

```python
REVIEW_DECISION_SCHEMA = ROOT / "harness" / "schemas" / "review-decision.schema.json"
REVIEW_DECISION_FILENAME = "review-decision.json"
REVIEW_DECISION_TARGETS = frozenset(
    {
        "reviewed",
        "review_blocked",
        "review_failed",
        "review_timeout",
        "review_schema_invalid",
        "external_review_unavailable",
        "risk_accepted",
    }
)
# Targets where Codex's triaged decision must be recorded as a
# review-decision.json. These are the states that represent Codex's review
# disposition (review passed/triaged), not adapter-reported outcomes, reviewer
# unavailability, or the user-driven risk acceptance path. `reviewed` and
# `review_blocked` require a decision record; the remaining review-related
# states reuse their own evidence contracts (process-failure states,
# external_review_unavailable) or the Phase 1 risk-acceptance path.
REVIEW_DECISION_REQUIRED_TARGETS = frozenset({"reviewed", "review_blocked"})
# Evidence types that signal a review actually happened. When any of these are
# indexed and a run advances to a REVIEW_DECISION_REQUIRED_TARGETS state, an
# indexed review-decision.json is required. Absence of all of these (e.g. a Fast
# run, or a pre-review run) means no decision is required, which keeps
# historical runs valid without migration.
REVIEW_SIGNAL_EVIDENCE_TYPES = frozenset(
    {
        "review-input",
        "review-output",
        "review-evidence",
        "review-raw-log",
        "review",
    }
)
```

- [ ] **Step 4: Add the loader and validator**

Add after `validate_aggregation_against_jobs` (keep evidence helpers grouped):

```python
def load_indexed_review_decision(
    state: dict[str, Any],
    *,
    root: Path,
    run_dir: Path,
) -> tuple[dict[str, Any] | None, int, list[str]]:
    """Return (decision_payload_or_None, evidence_index, errors) for the indexed
    review-decision.json. Detection is by basename == review-decision.json among
    review-evidence entries, matching the canonical path in the Phase 3 spec."""
    errors: list[str] = []
    state_run_id = state.get("run_id")
    for index, evidence in evidence_items(state):
        if evidence.get("type") != "review-evidence":
            continue
        raw_path = evidence.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue

        candidate_path = first_existing_evidence_path(raw_path, root=root, run_dir=run_dir)
        if candidate_path is None:
            continue
        if candidate_path.name != REVIEW_DECISION_FILENAME:
            continue

        decision, decision_errors = validate_json_artifact(
            candidate_path,
            REVIEW_DECISION_SCHEMA,
            "review-decision",
        )
        errors.extend(f"evidence[{index}]: {error}" for error in decision_errors)
        if decision is None:
            return None, index, errors

        if isinstance(state_run_id, str) and decision.get("run_id") != state_run_id:
            errors.append(
                f"evidence[{index}]: review-decision run_id {decision.get('run_id')} "
                f"does not match state run_id {state_run_id}",
            )

        return decision, index, errors

    return None, -1, errors


def validate_review_decision_evidence(
    state: dict[str, Any],
    *,
    root: Path,
    run_dir: Path,
) -> list[str]:
    errors: list[str] = []
    decision, index, load_errors = load_indexed_review_decision(
        state,
        root=root,
        run_dir=run_dir,
    )
    errors.extend(load_errors)
    if decision is None:
        return errors

    errors.extend(
        validate_review_decision_semantics(
            decision,
            state,
            index=index,
            root=root,
            run_dir=run_dir,
        )
    )
    return errors


def validate_review_decision_semantics(
    decision: dict[str, Any],
    state: dict[str, Any],
    *,
    index: int,
    root: Path,
    run_dir: Path,
) -> list[str]:
    errors: list[str] = []
    severity = decision.get("severity_counts", {}) if isinstance(
        decision.get("severity_counts"), dict
    ) else {}
    high_or_critical = (severity.get("high", 0) or 0) > 0 or (
        severity.get("critical", 0) or 0
    ) > 0

    indexed_paths = {
        evidence.get("path")
        for _index, evidence in evidence_items(state)
        if isinstance(evidence.get("path"), str) and evidence.get("path").strip()
    }
    evidence_types = {
        evidence.get("type")
        for _index, evidence in evidence_items(state)
        if isinstance(evidence.get("type"), str)
    }

    recommended_status = decision.get("recommended_status")
    disposition = decision.get("disposition")

    if high_or_critical and recommended_status == "reviewed":
        if not decision.get("resolved_findings") and not decision.get("accepted_risks"):
            errors.append(
                f"evidence[{index}]: review-decision cannot override a high or critical "
                "finding without resolved_findings or accepted_risks",
            )

    if disposition == "waived" and "review-waiver" not in evidence_types:
        errors.append(
            f"evidence[{index}]: waived review-decision requires indexed review-waiver evidence",
        )

    if disposition == "risk-accepted" and "risk-acceptance" not in evidence_types:
        errors.append(
            f"evidence[{index}]: risk-accepted review-decision requires indexed "
            "risk-acceptance evidence",
        )

    source_evidence = decision.get("source_evidence")
    if isinstance(source_evidence, list):
        for position, entry in enumerate(source_evidence):
            if not isinstance(entry, dict):
                continue
            raw_path = entry.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            if raw_path in indexed_paths:
                continue
            # Not indexed, so it must at least be indexable: the artifact must
            # exist within the repository or the run directory.
            candidate = first_existing_evidence_path(raw_path, root=root, run_dir=run_dir)
            if candidate is None:
                errors.append(
                    f"evidence[{index}]: review-decision source_evidence[{position}] "
                    f"path {raw_path} is not indexed and does not exist",
                )

    return errors
```

- [ ] **Step 5: Wire the validator into `validate_state`**

In `validate_state`, after the `validate_aggregation_evidence(...)` call, add:

```python
    errors.extend(
        validate_review_decision_evidence(
            state,
            root=root,
            run_dir=run_dir,
        )
    )
```

- [ ] **Step 6: Run validation tests to verify they pass**

Run the same command as Step 2.

Expected: PASS.

- [ ] **Step 7: Confirm historical runs still validate**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_validate_accepts_all_existing_run_directories -v
```

Expected: PASS. Historical runs index no `review-decision.json`, so the new check is a no-op for them.

- [ ] **Step 8: Commit Task 2**

```powershell
git add harness/cli.py tests/test_harness_cli.py
git commit -m "feat: validate indexed review decision evidence"
```

---

### Task 3: Enforce the Review Decision Transition Gate in `advance`

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_harness_cli.py`

- [ ] **Step 1: Add failing transition-gate tests**

Add these tests inside `HarnessCliTest`:

```python
    def test_advance_allows_review_target_matching_recommended_status(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "passed",
                        "recommended_status": "reviewed",
                        "decision_owner": "codex",
                        "source_evidence": [],
                        "severity_counts": {
                            "critical": 0,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": [],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            advanced = cli.advance_run(run_dir, "reviewed", actor="codex", root=ROOT)

        self.assertEqual(advanced["status"], "reviewed")

    def test_advance_rejects_review_target_conflicting_with_recommended_status(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "blocked",
                        "recommended_status": "review_blocked",
                        "decision_owner": "codex",
                        "source_evidence": [],
                        "severity_counts": {
                            "critical": 1,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": ["Critical finding blocks review."],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)
            before = (run_dir / "state.json").read_text(encoding="utf-8")

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "reviewed", actor="codex", root=ROOT)
            after = (run_dir / "state.json").read_text(encoding="utf-8")

        self.assertIn("recommended_status", str(raised.exception))
        self.assertEqual(before, after)

    def test_advance_ignores_review_decision_gate_for_non_review_target(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="draft")
            write_state(run_dir, state)

            advanced = cli.advance_run(run_dir, "triaged", actor="codex", root=ROOT)

        self.assertEqual(advanced["status"], "triaged")

    def test_advance_requires_decision_when_advancing_review_outcome_with_review_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            (run_dir / "review-output.md").write_text("# Review Output\n", encoding="utf-8")
            state = minimal_state(status="reviewing")
            state["track"] = "Standard"
            state["current_workflow"] = "standard-code-change"
            state["evidence"] = [
                {
                    "type": "review-output",
                    "path": "review-output.md",
                    "description": "Reviewer output without a decision.",
                }
            ]
            write_state(run_dir, state)
            before = (run_dir / "state.json").read_text(encoding="utf-8")

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "reviewed", actor="codex", root=ROOT)
            after = (run_dir / "state.json").read_text(encoding="utf-8")

        self.assertIn("review-decision", str(raised.exception))
        self.assertIn("required", str(raised.exception))
        self.assertEqual(before, after)

    def test_advance_allows_review_outcome_without_review_evidence(self):
        # A run that has not indexed any review evidence (e.g. a Fast run that
        # bypasses review, or a pre-review run) is not required to carry a
        # review decision. This keeps historical runs valid.
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="verified")
            state["track"] = "Fast"
            state["current_workflow"] = "fast-doc-change"
            write_state(run_dir, state)

            advanced = cli.advance_run(run_dir, "reviewed", actor="codex", root=ROOT)

        self.assertEqual(advanced["status"], "reviewed")
```

- [ ] **Step 2: Run transition-gate tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_advance_allows_review_target_matching_recommended_status tests.test_harness_cli.HarnessCliTest.test_advance_rejects_review_target_conflicting_with_recommended_status tests.test_harness_cli.HarnessCliTest.test_advance_ignores_review_decision_gate_for_non_review_target tests.test_harness_cli.HarnessCliTest.test_advance_requires_decision_when_advancing_review_outcome_with_review_evidence tests.test_harness_cli.HarnessCliTest.test_advance_allows_review_outcome_without_review_evidence -v
```

Expected: FAIL because the gate is not implemented.

- [ ] **Step 3: Add the transition gate**

Add after `validate_transition_policy` in `harness/cli.py`:

```python
def validate_review_decision_transition(
    state: dict[str, Any],
    next_status: str,
    *,
    root: Path,
    run_dir: Path,
) -> list[str]:
    if next_status not in REVIEW_DECISION_TARGETS:
        return []

    decision, _index, load_errors = load_indexed_review_decision(
        state,
        root=root,
        run_dir=run_dir,
    )
    if load_errors:
        return load_errors
    if decision is None:
        # No indexed decision. It is only required for the triage-disposition
        # targets (reviewed, review_blocked), where Codex's review decision
        # must be recorded. The other review-related targets are adapter
        # outcomes (process-failure states, external_review_unavailable) or
        # the user-driven risk-acceptance path, which reuse their own Phase 1
        # evidence contracts and do not need a decision record. This keeps
        # historical runs valid without migration.
        if next_status not in REVIEW_DECISION_REQUIRED_TARGETS:
            return []
        evidence_types = {
            evidence.get("type")
            for _index, evidence in evidence_items(state)
            if isinstance(evidence.get("type"), str)
        }
        if evidence_types & REVIEW_SIGNAL_EVIDENCE_TYPES:
            return [
                "review-decision is required to advance to a review outcome state "
                "when review evidence is indexed",
            ]
        return []

    recommended_status = decision.get("recommended_status")
    if recommended_status != next_status:
        return [
            f"advance target {next_status} does not match review-decision "
            f"recommended_status {recommended_status}",
        ]
    return []
```

- [ ] **Step 4: Call the gate from `advance_run`**

In `advance_run`, after the `validate_transition_policy(...)` block and before `validate_completion_evidence(...)`, add:

```python
    review_decision_errors = validate_review_decision_transition(
        state,
        next_status,
        root=root,
        run_dir=resolved_run_dir,
    )
    if review_decision_errors:
        raise HarnessCliError(format_errors(review_decision_errors))
```

- [ ] **Step 5: Run transition-gate tests to verify they pass**

Run the same command as Step 2.

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```powershell
git add harness/cli.py tests/test_harness_cli.py
git commit -m "feat: gate review-related advance targets on review decision"
```

---

### Task 4: Enforce Handoff and Memory Closure on `advance -> completed`

**Files:**
- Modify: `harness/cli.py`
- Create: `tests/test_phase3_closure.py`

- [ ] **Step 1: Write failing closure tests**

Create `tests/test_phase3_closure.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from harness import cli


ROOT = Path(__file__).resolve().parents[1]


def minimal_state(status: str = "reviewed") -> dict:
    return {
        "run_id": "phase3-test",
        "harness_version": "0.1.0",
        "state_schema_version": "0.1.0",
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


def write_state(run_dir: Path, state: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "state.json").write_text(
        json.dumps(state, indent=2) + "\n",
        encoding="utf-8",
    )


def complete_evidence(run_dir: Path) -> list[dict]:
    return [
        {
            "type": "verification",
            "path": "verification.md",
            "description": "Verification evidence.",
        },
        {
            "type": "handoff",
            "path": "handoff.md",
            "description": "Handoff evidence.",
        },
        {
            "type": "review",
            "path": "review.md",
            "description": "Review evidence.",
        },
    ]


def write_artifacts(run_dir: Path, *, handoff_text: str) -> None:
    (run_dir / "verification.md").write_text("# Verification\n", encoding="utf-8")
    (run_dir / "review.md").write_text("# Review\n", encoding="utf-8")
    (run_dir / "handoff.md").write_text(handoff_text, encoding="utf-8")


def complete_handoff(memory_update: str = "none", memory_files: list[str] | None = None) -> str:
    memory_files = memory_files if memory_files is not None else []
    if memory_files:
        # Block sequence: `memory_files:` then an indented item per entry.
        memory_files_line = "memory_files:\n" + "\n".join(
            f'  - "{entry}"' for entry in memory_files
        )
    else:
        memory_files_line = "memory_files: []"
    return f"""---
run_id: phase3-test
schema_version: 0.1.0
changed:
  - "Added review decision schema and gates."
verified:
  - "Unit tests cover schema and gates."
not_verified: []
residual_risks: []
next_step: "Merge to master."
memory_update: {memory_update}
{memory_files_line}
---

# Handoff
"""


class HandoffClosureTest(unittest.TestCase):
    def test_advance_to_completed_requires_handoff_closure_fields(self):
        required = ("changed", "verified", "not_verified", "residual_risks", "next_step")
        for missing in required:
            with tempfile.TemporaryDirectory(dir=ROOT) as raw:
                run_dir = Path(raw)
                state = minimal_state(status="reviewed")
                state["evidence"] = complete_evidence(run_dir)
                write_state(run_dir, state)
                full = complete_handoff()
                # Strip one field line to force its absence.
                marker = f"{missing}:"
                stripped = "\n".join(
                    line for line in full.splitlines() if not line.lstrip().startswith(marker)
                )
                write_artifacts(run_dir, handoff_text=stripped)

                with self.subTest(missing=missing):
                    with self.assertRaises(cli.HarnessCliError) as raised:
                        cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

            self.assertIn(f"handoff frontmatter missing field: {missing}", str(raised.exception))

    def test_advance_to_completed_fails_when_memory_update_lacks_files(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="reviewed")
            state["evidence"] = complete_evidence(run_dir)
            write_state(run_dir, state)
            write_artifacts(run_dir, handoff_text=complete_handoff(memory_update="updated"))

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertIn("memory_update is updated but memory_files is empty", str(raised.exception))

    def test_advance_to_completed_fails_when_listed_memory_file_missing(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="reviewed")
            state["evidence"] = complete_evidence(run_dir)
            write_state(run_dir, state)
            write_artifacts(
                run_dir,
                handoff_text=complete_handoff(
                    memory_update="updated",
                    memory_files=["harness/memory/does-not-exist.md"],
                ),
            )

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertIn("memory file does not exist", str(raised.exception))

    def test_advance_to_completed_allows_consistent_handoff(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="reviewed")
            state["evidence"] = complete_evidence(run_dir)
            write_state(run_dir, state)
            (run_dir / "verification.md").write_text("# Verification\n", encoding="utf-8")
            (run_dir / "review.md").write_text("# Review\n", encoding="utf-8")
            (run_dir / "handoff.md").write_text(
                complete_handoff(memory_update="none"),
                encoding="utf-8",
            )

            advanced = cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertEqual(advanced["status"], "completed")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run closure tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_phase3_closure -v
```

Expected: FAIL because the closure gate is not implemented.

- [ ] **Step 3: Add the closure gate**

In `harness/cli.py`, add an import near the top (next to `from harness import readiness`):

```python
from harness import readiness
```

(Already present from Phase 2. No change needed if already imported.)

Add after `validate_completion_evidence`:

```python
HANDOFF_REQUIRED_CLOSURE_FIELDS = (
    "changed",
    "verified",
    "not_verified",
    "residual_risks",
    "next_step",
    "memory_update",
    "memory_files",
)


def validate_handoff_closure(
    state: dict[str, Any],
    next_status: str,
    *,
    root: Path,
    run_dir: Path,
) -> list[str]:
    if next_status != "completed":
        return []

    handoff_path = first_indexed_evidence_path(state, "handoff", root=root, run_dir=run_dir)
    if handoff_path is None:
        return []

    try:
        text = handoff_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return [f"cannot read handoff artifact: {exc}"]

    result = readiness.parse_frontmatter(text)
    errors: list[str] = []
    for field_name in HANDOFF_REQUIRED_CLOSURE_FIELDS:
        if field_name not in result.data:
            errors.append(f"handoff frontmatter missing field: {field_name}")

    if result.data and errors:
        return errors
    if not result.data and errors:
        return errors

    memory_update = result.data.get("memory_update")
    memory_files = result.data.get("memory_files")
    if not isinstance(memory_files, list):
        memory_files = []

    if memory_update == "updated" and not memory_files:
        errors.append("handoff memory_update is updated but memory_files is empty")

    for raw_file in memory_files:
        if not isinstance(raw_file, str) or not raw_file.strip():
            errors.append("handoff memory_files contains an empty entry")
            continue
        candidate = first_existing_evidence_path(raw_file, root=root, run_dir=run_dir)
        if candidate is None:
            errors.append(f"handoff memory file does not exist: {raw_file}")

    return errors


def first_indexed_evidence_path(
    state: dict[str, Any],
    evidence_type: str,
    *,
    root: Path,
    run_dir: Path,
) -> Path | None:
    for _index, evidence in evidence_items(state):
        if evidence.get("type") != evidence_type:
            continue
        raw_path = evidence.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        candidate = first_existing_evidence_path(raw_path, root=root, run_dir=run_dir)
        if candidate is not None:
            return candidate
    return None
```

Rationale: the gate resolves the indexed `handoff` artifact (the completion gate already requires `handoff` evidence to exist), reuses the Phase 2 frontmatter parser, and only fatal-checks closure fields at the `-> completed` transition. `validate` never calls this, so historical completed runs are not re-gated.

- [ ] **Step 4: Call the closure gate from `advance_run`**

In `advance_run`, after the `validate_completion_evidence(...)` block and before building `candidate`, add:

```python
    handoff_errors = validate_handoff_closure(
        state,
        next_status,
        root=root,
        run_dir=resolved_run_dir,
    )
    if handoff_errors:
        raise HarnessCliError(format_errors(handoff_errors))
```

- [ ] **Step 5: Run closure tests to verify they pass**

Run:

```powershell
python -m unittest tests.test_phase3_closure -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```powershell
git add harness/cli.py tests/test_phase3_closure.py
git commit -m "feat: gate completion on handoff and memory closure"
```

---

### Task 5: Add the Soft Memory-Declaration Warning to `check-ready`

**Files:**
- Modify: `harness/readiness.py`
- Modify: `tests/test_phase2_readiness.py`

- [ ] **Step 1: Add a failing readiness test**

Append this test class to `tests/test_phase2_readiness.py`:

```python
class Phase3MemoryReadinessTest(unittest.TestCase):
    def test_check_ready_warns_when_memory_files_present_without_update(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state()
            write_state(run_dir, state)
            (run_dir / "task.md").write_text(
                """---
run_id: phase2-test
schema_version: 0.1.0
track: Standard
workflow: standard-doc-system-change
owner: codex
requested_outcome: "Document behavior."
scope: []
non_goals: []
constraints: []
---

# Task
""",
                encoding="utf-8",
            )
            (run_dir / "triage.md").write_text(
                """---
run_id: phase2-test
schema_version: 0.1.0
track: Standard
workflow: standard-doc-system-change
review_required: true
strict_triggers: []
risk_reasons: []
verification_required: []
---

# Triage
""",
                encoding="utf-8",
            )
            (run_dir / "plan.md").write_text(
                """---
run_id: phase2-test
schema_version: 0.1.0
workflow: standard-doc-system-change
acceptance: []
verification: []
review_plan: []
constraints: []
---

# Plan
""",
                encoding="utf-8",
            )
            (run_dir / "handoff.md").write_text(
                """---
run_id: phase2-test
schema_version: 0.1.0
changed: []
verified: []
not_verified: []
residual_risks: []
next_step: "Review memory declaration."
memory_update: none
memory_files:
  - "harness/memory/progress.md"
---

# Handoff
""",
                encoding="utf-8",
            )

            report = readiness.check_run_readiness(run_dir, state)

        self.assertTrue(
            any(
                "handoff.md frontmatter memory_files declared without memory_update" in warning
                for warning in report.warnings
            ),
            report.warnings,
        )
```

- [ ] **Step 2: Run the readiness test to verify it fails**

Run:

```powershell
python -m unittest tests.test_phase2_readiness.Phase3MemoryReadinessTest -v
```

Expected: FAIL because the soft warning is not emitted.

- [ ] **Step 3: Add the soft warning**

In `harness/readiness.py`, inside `validate_document_frontmatter`, after the existing `workflow` mismatch block and before `return warnings`, add:

```python
    if document_name == "handoff.md":
        memory_update = data.get("memory_update")
        memory_files = data.get("memory_files")
        if (
            memory_update in {None, "none", "deferred"}
            and isinstance(memory_files, list)
            and memory_files
        ):
            warnings.append(
                "handoff.md frontmatter memory_files declared without memory_update",
            )
```

Rationale: this is advisory only. The hard memory failures (`updated` with empty files, or a listed file that does not exist) are enforced by the `advance -> completed` closure gate in Task 4, not here.

- [ ] **Step 4: Run the readiness test to verify it passes**

Run:

```powershell
python -m unittest tests.test_phase2_readiness.Phase3MemoryReadinessTest -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```powershell
git add harness/readiness.py tests/test_phase2_readiness.py
git commit -m "feat: warn on memory files declared without memory_update"
```

---

### Task 6: Final Verification

**Files:**
- None.

- [ ] **Step 1: Run the full test suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass, with the existing opt-in pip hash validation test skipped unless `HARNESS_RUN_PIP_HASH_CHECK=1` is set. The count increases relative to the Phase 2 baseline (176 passed / 1 skipped) by the new Phase 3 tests, with no pre-existing test removed or weakened.

- [ ] **Step 2: Validate all historical runs**

Run:

```powershell
python -m harness.cli validate harness/runs/example-fast-doc-change
python -m harness.cli validate harness/runs/2026-06-19-standard-adapter-cli
python -m harness.cli validate harness/runs/2026-06-19-v0.1.1-audit-closure
python -m harness.cli validate harness/runs/2026-06-19-v0.2-implementation-plan
python -m harness.cli validate harness/runs/2026-06-19-v0.2-plan-amendment
python -m harness.cli validate harness/runs/2026-06-19-v0.2-reviewer-provenance-design
python -m harness.cli validate harness/runs/2026-06-19-v0.2-reviewer-provenance-implementation
python -m harness.cli validate harness/runs/2026-06-19-v0.2-spec-amendment
```

Expected: every command prints `valid: <run-dir>` and exits 0. This proves historical runs validate without a `review-decision.json` and without migrated handoff frontmatter.

- [ ] **Step 3: Confirm no new state and no new evidence type were introduced**

Run:

```powershell
python -m unittest tests.test_state_schema.StateSchemaTest.test_schema_has_required_statuses tests.test_harness_cli.HarnessCliTest.test_evidence_type_vocabulary_matches_phase_4_contract -v
```

Expected: PASS. The status enum and evidence vocabulary are unchanged; review dispositions live only inside `review-decision.json`, not in `state.schema.json`.

- [ ] **Step 4: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected: exit 0.

- [ ] **Step 5: Confirm the implementation branch is clean after committed task work**

Run:

```powershell
git status --short
```

Expected: no output after all task commits are created.

---

## Self-Review Checklist

- Phase 3 adds no new Harness status. Review disposition is a decision field, not a state.
- Phase 3 adds no new evidence type. `review-decision.json` is indexed as `review-evidence`.
- `review-decision.schema.json` exists and pins disposition and `recommended_status` enums plus full `disposition -> recommended_status` consistency for all seven dispositions.
- Indexed `review-decision.json` is validated for schema, run_id match, high/critical override, waived/risk-accepted cross-evidence requirements, and `source_evidence[]` indexability (indexed or existing artifact).
- `advance` rejects review-related targets that differ from an indexed decision's `recommended_status`, before writing `state.json`.
- `advance` requires an indexed `review-decision.json` when advancing to a triage-disposition target (`reviewed` or `review_blocked`) and review evidence is present. Other review-related targets (`risk_accepted`, `external_review_unavailable`, process-failure states) reuse their own Phase 1 evidence contracts and are not gated on a missing decision; a run with no review evidence (including historical runs) is not required to carry a decision.
- `advance -> completed` requires handoff closure fields and enforces memory-update/memory-files consistency.
- `validate` never fatal-parses Markdown frontmatter; only the `-> completed` closure gate does, so historical completed runs stay valid.
- `check-ready` adds only the soft memory-declaration disagreement warning and remains non-mutating.
- Historical runs without `review-decision.json` or migrated handoff frontmatter continue to validate.
- Full test suite and historical-run validation are required before completion.

## Residual Risks and Mitigations

- **Name-based detection** of `review-decision.json` (basename) could miss a decision stored under another filename. Mitigation: the spec defines one canonical path; detection matches it. A run that hides a decision under another name simply is not gated, which is the safe direction (no false rejection).
- **Closure gate reads frontmatter at completion only.** A run that reaches `completed` through a future code path that bypasses `advance_run` would skip the gate. Mitigation: `advance_run` is the only documented transition writer and is actor-locked to `codex`; no helper command advances state.
- **`risk_accepted` is treated as a review-decision target.** A decision recommending `risk_accepted` will gate any conflicting review-outcome advance. This matches the spec disposition table; it is intentional, not a bug.

## Next Step

After this plan is implemented and verified, update `harness/memory/progress.md` to record Phase 3 completion and the next focus (e.g., documenting the review-decision authoring flow for Codex, or Phase 4 follow-ups).
