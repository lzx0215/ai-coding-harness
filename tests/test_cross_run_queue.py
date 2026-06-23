import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


def successful_agent_command() -> list[str]:
    script = (
        "import json, os; "
        "from pathlib import Path; "
        "payload = {"
        "'run_id': os.environ['HARNESS_RUN_ID'], "
        "'job_id': os.environ['HARNESS_JOB_ID'], "
        "'agent': os.environ['HARNESS_AGENT'], "
        "'adapter': os.environ['HARNESS_AGENT_ADAPTER'], "
        "'status': 'passed', "
        "'summary': 'cross-run queue smoke passed', "
        "'findings': [], "
        "'evidence': [], "
        "'not_tested': [], "
        "'residual_risks': [], "
        "'generated_at': '2026-06-23T00:00:00Z'"
        "}; "
        "Path(os.environ['HARNESS_AGENT_OUTPUT_FILE']).write_text("
        "json.dumps(payload, indent=2) + '\\n', encoding='utf-8'"
        ")"
    )
    return [sys.executable, "-c", script]


def build_queued_entry_fixture(
    base: Path,
    *,
    allowed_groups: list[str],
    allowed_worker_id: str | None = None,
) -> tuple[Path, Path]:
    run_dir = base / "harness" / "runs" / "run-a"
    queue_dir = base / "queue"
    write_json(run_dir / "state.json", minimal_state("run-a"))
    cli.create_generic_agent_job(
        run_dir,
        "job-a",
        agent="generic-test-agent",
        command=successful_agent_command(),
        root=base,
    )
    cli.create_cross_run_queue_entry(
        queue_dir,
        "entry-a",
        run_dir=run_dir,
        job_id="job-a",
        creator="codex",
        allowed_worker_id=allowed_worker_id,
        allowed_worker_groups=allowed_groups,
        root=base,
    )
    return run_dir, queue_dir


def build_run_with_queued_job(base: Path) -> tuple[Path, Path]:
    run_dir = base / "harness" / "runs" / "run-a"
    queue_dir = base / "queue"
    write_json(run_dir / "state.json", minimal_state("run-a"))
    cli.create_generic_agent_job(
        run_dir,
        "job-a",
        agent="generic-test-agent",
        command=successful_agent_command(),
        root=base,
    )
    return run_dir, queue_dir


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


class CrossRunQueueExecutionTest(unittest.TestCase):
    def test_worker_id_must_be_authorized_to_claim_queue_entry(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            _, queue_dir = build_queued_entry_fixture(
                base,
                allowed_groups=[],
                allowed_worker_id="worker-a",
            )

            unauthorized = cli.try_claim_cross_run_queue_entry(
                queue_dir,
                "entry-a",
                worker_id="worker-b",
                worker_groups=[],
                root=base,
            )
            authorized = cli.try_claim_cross_run_queue_entry(
                queue_dir,
                "entry-a",
                worker_id="worker-a",
                worker_groups=[],
                root=base,
            )

            self.assertIsNone(unauthorized)
            self.assertIsNotNone(authorized)
            self.assertEqual(authorized["claim_owner"], "worker-a")

    def test_worker_group_must_be_authorized_to_claim_queue_entry(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            _, queue_dir = build_queued_entry_fixture(base, allowed_groups=["local"])

            claimed = cli.try_claim_cross_run_queue_entry(
                queue_dir,
                "entry-a",
                worker_id="worker-a",
                worker_groups=["remote"],
                root=base,
            )

            entry = json.loads(
                (queue_dir / "entries" / "entry-a" / "entry.json").read_text(
                    encoding="utf-8",
                )
            )
            self.assertIsNone(claimed)
            self.assertEqual(entry["status"], "queued")
            self.assertFalse((queue_dir / "entries" / "entry-a" / "claim.lock").exists())

    def test_cross_run_queue_run_once_executes_authorized_entry_once(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            run_dir, queue_dir = build_queued_entry_fixture(base, allowed_groups=["local"])
            before_state = (run_dir / "state.json").read_text(encoding="utf-8")

            summary = cli.cross_run_queue_run_once(
                queue_dir,
                worker_id="worker-a",
                worker_groups=["local"],
                root=base,
            )
            second_summary = cli.cross_run_queue_run_once(
                queue_dir,
                worker_id="worker-b",
                worker_groups=["local"],
                root=base,
            )

            job = json.loads((run_dir / "jobs" / "job-a" / "job.json").read_text(encoding="utf-8"))
            entry = json.loads(
                (queue_dir / "entries" / "entry-a" / "entry.json").read_text(
                    encoding="utf-8",
                )
            )
            self.assertEqual(summary["executed_entries"], ["entry-a"])
            self.assertEqual(summary["skipped_entries"], [])
            self.assertEqual(second_summary["executed_entries"], [])
            self.assertEqual(second_summary["skipped_entries"], ["entry-a"])
            self.assertEqual(job["status"], "succeeded")
            self.assertEqual(entry["status"], "succeeded")
            self.assertEqual(entry["terminal_job_status"], "succeeded")
            self.assertTrue((run_dir / "jobs" / "job-a" / "output.json").exists())
            self.assertEqual((run_dir / "state.json").read_text(encoding="utf-8"), before_state)

    def test_cross_run_queue_run_once_mirrors_already_terminal_referenced_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            run_dir, queue_dir = build_queued_entry_fixture(base, allowed_groups=["local"])
            scheduler_summary = cli.scheduler_run_once(
                run_dir,
                worker_id="run-local-worker",
                root=base,
            )

            summary = cli.cross_run_queue_run_once(
                queue_dir,
                worker_id="worker-a",
                worker_groups=["local"],
                root=base,
            )

            entry = json.loads(
                (queue_dir / "entries" / "entry-a" / "entry.json").read_text(
                    encoding="utf-8",
                )
            )
            self.assertEqual(scheduler_summary["executed_jobs"], ["job-a"])
            self.assertEqual(summary["executed_entries"], [])
            self.assertEqual(summary["skipped_entries"], ["entry-a"])
            self.assertEqual(entry["status"], "succeeded")
            self.assertEqual(entry["terminal_job_status"], "succeeded")

    def test_cross_run_queue_run_once_preserves_cancelled_referenced_job_status(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            run_dir, queue_dir = build_queued_entry_fixture(base, allowed_groups=["local"])
            job_path = run_dir / "jobs" / "job-a" / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            completed_at = "2026-06-23T00:00:01Z"
            job["status"] = "cancelled"
            job["completed_at"] = completed_at
            job["updated_at"] = completed_at
            write_json(job_path, job)

            summary = cli.cross_run_queue_run_once(
                queue_dir,
                worker_id="worker-a",
                worker_groups=["local"],
                root=base,
            )

            entry = json.loads(
                (queue_dir / "entries" / "entry-a" / "entry.json").read_text(
                    encoding="utf-8",
                )
            )
            self.assertEqual(summary["executed_entries"], [])
            self.assertEqual(summary["skipped_entries"], ["entry-a"])
            self.assertEqual(entry["status"], "cancelled")
            self.assertEqual(entry["terminal_job_status"], "cancelled")

    def test_cross_run_queue_run_once_marks_invalid_referenced_job_failed_without_stranding_lock(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            _, queue_dir = build_queued_entry_fixture(base, allowed_groups=["local"])
            run_dir = base / "harness" / "runs" / "run-a"
            (run_dir / "jobs" / "job-a" / "job.json").write_text("{", encoding="utf-8")

            summary = cli.cross_run_queue_run_once(
                queue_dir,
                worker_id="worker-a",
                worker_groups=["local"],
                root=base,
            )

            entry_dir = queue_dir / "entries" / "entry-a"
            entry = json.loads((entry_dir / "entry.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["executed_entries"], [])
            self.assertEqual(summary["skipped_entries"], ["entry-a"])
            self.assertEqual(entry["status"], "failed")
            self.assertIsNone(entry["terminal_job_status"])
            self.assertFalse((entry_dir / "claim.lock").exists())

    def test_cross_run_queue_run_once_marks_unloadable_referenced_job_failed_without_stranding_lock(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            _, queue_dir = build_queued_entry_fixture(base, allowed_groups=["local"])

            with (
                mock.patch.object(cli, "try_claim_job", return_value=None),
                mock.patch.object(cli, "load_job_payload", side_effect=OSError("disk unavailable")),
            ):
                summary = cli.cross_run_queue_run_once(
                    queue_dir,
                    worker_id="worker-a",
                    worker_groups=["local"],
                    root=base,
                )

            entry_dir = queue_dir / "entries" / "entry-a"
            entry = json.loads((entry_dir / "entry.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["executed_entries"], [])
            self.assertEqual(summary["skipped_entries"], ["entry-a"])
            self.assertEqual(entry["status"], "failed")
            self.assertIsNone(entry["terminal_job_status"])
            self.assertFalse((entry_dir / "claim.lock").exists())

    def test_cross_run_queue_run_once_releases_queue_claim_after_unexpected_execution_error(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            _, queue_dir = build_queued_entry_fixture(base, allowed_groups=["local"])

            with mock.patch.object(
                cli,
                "execute_claimed_generic_agent_job",
                side_effect=RuntimeError("agent executor crashed"),
            ):
                summary = cli.cross_run_queue_run_once(
                    queue_dir,
                    worker_id="worker-a",
                    worker_groups=["local"],
                    root=base,
                )

            entry_dir = queue_dir / "entries" / "entry-a"
            entry = json.loads((entry_dir / "entry.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["executed_entries"], [])
            self.assertEqual(summary["skipped_entries"], ["entry-a"])
            self.assertEqual(entry["status"], "failed")
            self.assertIsNone(entry["terminal_job_status"])
            self.assertFalse((entry_dir / "claim.lock").exists())


class CrossRunQueueCliTest(unittest.TestCase):
    def test_module_entrypoint_creates_and_runs_cross_run_queue_entry(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            run_dir, queue_dir = build_run_with_queued_job(base)
            entry_path = queue_dir / "entries" / "entry-b" / "entry.json"

            create_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "queue-cross-run-job",
                    str(queue_dir),
                    "entry-b",
                    "--run-dir",
                    str(run_dir),
                    "--job-id",
                    "job-a",
                    "--creator",
                    "codex",
                    "--worker-group",
                    "local",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            run_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "run-cross-run-queue",
                    str(queue_dir),
                    "--once",
                    "--worker-id",
                    "worker-a",
                    "--worker-group",
                    "local",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(create_result.returncode, 0, create_result.stderr + create_result.stdout)
            self.assertTrue(entry_path.exists())
            self.assertEqual(run_result.returncode, 0, run_result.stderr + run_result.stdout)
            self.assertIn("cross-run queue: executed=1", run_result.stdout)


class CrossRunQueueRecoveryCleanupTest(unittest.TestCase):
    def test_recover_claimed_cross_run_entry_requires_confirmation(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            _, queue_dir = build_queued_entry_fixture(base, allowed_groups=["local"])
            claimed = cli.try_claim_cross_run_queue_entry(
                queue_dir,
                "entry-a",
                worker_id="worker-a",
                worker_groups=["local"],
                root=base,
            )
            self.assertIsNotNone(claimed)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.recover_cross_run_queue_entry(
                    queue_dir,
                    "entry-a",
                    action="requeue",
                    reason="stale worker",
                    confirm=False,
                    actor="codex",
                    root=base,
                )

            self.assertIn("requires --confirm", str(raised.exception))

    def test_recover_requeue_requires_referenced_job_to_be_queued(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            run_dir, queue_dir = build_queued_entry_fixture(base, allowed_groups=["local"])
            claimed = cli.try_claim_cross_run_queue_entry(
                queue_dir,
                "entry-a",
                worker_id="worker-a",
                worker_groups=["local"],
                root=base,
            )
            self.assertIsNotNone(claimed)
            job_claim = cli.try_claim_job(
                run_dir,
                "job-a",
                worker_id="worker-a",
                root=base,
            )
            self.assertIsNotNone(job_claim)
            cli.mark_claimed_job_running(job_claim, started_at=cli.utc_now())

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.recover_cross_run_queue_entry(
                    queue_dir,
                    "entry-a",
                    action="requeue",
                    reason="stale worker",
                    confirm=True,
                    actor="codex",
                    root=base,
                )

            self.assertIn("recover the run-local job first", str(raised.exception))

    def test_recover_abandon_records_audit_and_clears_claim(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            _, queue_dir = build_queued_entry_fixture(base, allowed_groups=["local"])
            claimed = cli.try_claim_cross_run_queue_entry(
                queue_dir,
                "entry-a",
                worker_id="worker-a",
                worker_groups=["local"],
                root=base,
            )
            self.assertIsNotNone(claimed)

            result = cli.recover_cross_run_queue_entry(
                queue_dir,
                "entry-a",
                action="abandon",
                reason="operator abandoned stale route",
                confirm=True,
                actor="codex",
                root=base,
            )

            self.assertEqual(result["entry"]["status"], "abandoned")
            self.assertIsNone(result["entry"]["claim_owner"])
            self.assertTrue(result["recovery_path"].exists())
            self.assertFalse((queue_dir / "entries" / "entry-a" / "claim.lock").exists())

    def test_cleanup_terminal_entry_does_not_delete_run_local_artifacts(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            run_dir, queue_dir = build_queued_entry_fixture(base, allowed_groups=["local"])
            cli.cross_run_queue_run_once(
                queue_dir,
                worker_id="worker-a",
                worker_groups=["local"],
                root=base,
            )

            result = cli.cleanup_cross_run_queue_entry(
                queue_dir,
                "entry-a",
                confirm=True,
                actor="codex",
                root=base,
            )

            self.assertTrue(result["cleanup_record"].endswith("-cleanup.json"))
            self.assertTrue((run_dir / "jobs" / "job-a" / "job.json").exists())
            self.assertTrue((run_dir / "jobs" / "job-a" / "output.json").exists())


if __name__ == "__main__":
    unittest.main()
