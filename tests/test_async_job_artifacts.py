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

    def test_aggregation_schema_rejects_empty_conflict(self):
        aggregation = minimal_aggregation()
        aggregation["conflicts"] = [""]

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
