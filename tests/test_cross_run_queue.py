import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
ENTRY_SCHEMA = ROOT / "harness" / "schemas" / "cross-run-queue-entry.schema.json"
EVENT_SCHEMA = ROOT / "harness" / "schemas" / "cross-run-queue-event.schema.json"


def load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def valid_entry() -> dict:
    return {
        "schema_version": "0.1.0",
        "queue_id": "phase9a-local",
        "entry_id": "entry-one",
        "run_id": "run-one",
        "run_dir": "harness/runs/run-one",
        "job_id": "job-one",
        "agent": "generic-test-agent",
        "adapter": "generic-cli-agent",
        "creator": "codex",
        "allowed_worker_id": None,
        "allowed_worker_groups": ["local"],
        "status": "queued",
        "created_at": "2026-06-23T00:00:00Z",
        "updated_at": "2026-06-23T00:00:00Z",
        "claim_owner": None,
        "claim_token": None,
        "claim_started_at": None,
        "claim_updated_at": None,
        "lease_expires_at": None,
        "terminal_job_status": None,
        "recovery": [],
        "cleanup": [],
    }


class CrossRunQueueSchemaTest(unittest.TestCase):
    def test_cross_run_queue_entry_schema_accepts_minimal_queued_entry(self):
        Draft202012Validator(load_schema(ENTRY_SCHEMA)).validate(valid_entry())

    def test_cross_run_queue_entry_schema_rejects_path_traversal_run_dir(self):
        entry = valid_entry()
        entry["run_dir"] = "../outside"

        errors = list(Draft202012Validator(load_schema(ENTRY_SCHEMA)).iter_errors(entry))

        self.assertTrue(errors)

    def test_cross_run_queue_entry_schema_rejects_unknown_status(self):
        entry = valid_entry()
        entry["status"] = "invented"

        errors = list(Draft202012Validator(load_schema(ENTRY_SCHEMA)).iter_errors(entry))

        self.assertTrue(errors)

    def test_cross_run_queue_event_schema_accepts_minimal_event(self):
        event = {
            "schema_version": "0.1.0",
            "queue_id": "phase9a-local",
            "entry_id": "entry-one",
            "event": "entry_created",
            "actor": "codex",
            "created_at": "2026-06-23T00:00:00Z",
            "details": {},
        }

        Draft202012Validator(load_schema(EVENT_SCHEMA)).validate(event)


if __name__ == "__main__":
    unittest.main()
