import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from harness import cli


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


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def minimal_state(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "harness_version": "0.2.0",
        "state_schema_version": "0.2.0",
        "status": "verified",
        "track": "Standard",
        "current_workflow": "standard-agent-adapter-change",
        "owner": "codex",
        "base_commit": "HEAD",
        "created_at": "2026-06-23T00:00:00Z",
        "updated_at": "2026-06-23T00:00:00Z",
        "external_agents": [],
        "evidence": [],
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


class CrossRunQueueCreationTest(unittest.TestCase):
    def test_create_cross_run_queue_entry_references_existing_queued_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            run_dir = base / "harness" / "runs" / "run-a"
            queue_dir = base / "queue"
            write_json(run_dir / "state.json", minimal_state("run-a"))
            cli.create_generic_agent_job(
                run_dir,
                "job-a",
                agent="generic-test-agent",
                command=["python", "-c", "print('ok')"],
                root=base,
            )

            entry = cli.create_cross_run_queue_entry(
                queue_dir,
                "entry-a",
                run_dir=run_dir,
                job_id="job-a",
                creator="codex",
                allowed_worker_id=None,
                allowed_worker_groups=["local"],
                root=base,
            )

            saved = json.loads(
                (queue_dir / "entries" / "entry-a" / "entry.json").read_text(
                    encoding="utf-8",
                )
            )
            self.assertEqual(entry["entry_id"], "entry-a")
            self.assertEqual(saved["run_id"], "run-a")
            self.assertEqual(saved["job_id"], "job-a")
            self.assertEqual(saved["status"], "queued")
            self.assertEqual(saved["allowed_worker_groups"], ["local"])

    def test_create_cross_run_queue_entry_rejects_missing_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            run_dir = base / "harness" / "runs" / "run-a"
            queue_dir = base / "queue"
            write_json(run_dir / "state.json", minimal_state("run-a"))

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.create_cross_run_queue_entry(
                    queue_dir,
                    "entry-a",
                    run_dir=run_dir,
                    job_id="missing",
                    creator="codex",
                    allowed_worker_id=None,
                    allowed_worker_groups=["local"],
                    root=base,
                )

            self.assertIn("referenced job does not exist", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
