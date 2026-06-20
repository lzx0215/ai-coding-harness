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
