import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import textwrap
import time
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness import cli


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def minimal_state() -> dict:
    return {
        "run_id": "test-run",
        "harness_version": "0.2.0",
        "state_schema_version": "0.2.0",
        "status": "verified",
        "track": "Standard",
        "current_workflow": "standard-agent-adapter-change",
        "owner": "codex",
        "base_commit": "HEAD",
        "created_at": "2026-06-20T00:00:00Z",
        "updated_at": "2026-06-20T00:00:00Z",
        "external_agents": [
            {
                "name": "generic-test-agent",
                "role": "reviewer",
                "adapter": "generic-cli-agent",
                "state_access": "none",
                "status": "not_requested",
            }
        ],
        "evidence": [],
    }


def write_agent_script(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def temporary_run_directory():
    return tempfile.TemporaryDirectory(
        dir=ROOT,
        ignore_cleanup_errors=os.name == "nt",
    )


def mark_job_running(
    run_dir: Path,
    job_id: str,
    *,
    worker_id: str = "worker-dead",
    created_at: str = "2026-06-22T00:00:00Z",
    started_at: str = "2026-06-22T00:00:00Z",
    updated_at: str = "2026-06-22T00:01:00Z",
) -> dict:
    job_path = run_dir / "jobs" / job_id / "job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job["status"] = "running"
    job["created_at"] = created_at
    job["started_at"] = started_at
    job["updated_at"] = updated_at
    job["worker_id"] = worker_id
    write_json(job_path, job)
    return job


def write_claim_owner(
    run_dir: Path,
    job_id: str,
    *,
    worker_id: str = "worker-dead",
    claimed_at: str = "2026-06-22T00:00:30Z",
    claim_token: str = "f" * 32,
) -> Path:
    lock_dir = run_dir / "jobs" / job_id / "claim.lock"
    lock_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        lock_dir / "owner.json",
        cli.build_claim_owner(
            run_id="test-run",
            job_id=job_id,
            worker_id=worker_id,
            claim_token=claim_token,
            claimed_at=cli.resolve_datetime(claimed_at, "claimed_at"),
        ),
    )
    return lock_dir


def terminate_pid_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


class GenericCliAgentOrchestrationTest(unittest.TestCase):
    def test_load_json_retries_transient_permission_error(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            payload_path = Path(raw) / "payload.json"
            write_json(payload_path, {"ok": True})
            original_read_text = Path.read_text
            attempts: list[Path] = []

            def flaky_read_text(path: Path, *args, **kwargs) -> str:
                if path == payload_path and not attempts:
                    attempts.append(path)
                    raise PermissionError("transient access denied")
                return original_read_text(path, *args, **kwargs)

            with mock.patch.object(Path, "read_text", flaky_read_text):
                loaded = cli.load_json(payload_path)

        self.assertEqual(loaded, {"ok": True})
        self.assertEqual(attempts, [payload_path])

    def test_create_generic_agent_job_writes_queued_artifacts_without_mutating_state(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            original_state = minimal_state()
            write_json(run_dir / "state.json", original_state)

            job = cli.create_generic_agent_job(
                run_dir,
                "generic-queued",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('not executed')"],
                timeout_seconds=30,
                root=ROOT,
            )
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            saved_job = json.loads(
                (run_dir / "jobs" / "generic-queued" / "job.json").read_text(
                    encoding="utf-8",
                )
            )
            input_payload = json.loads(
                (run_dir / "jobs" / "generic-queued" / "input.json").read_text(
                    encoding="utf-8",
                )
            )
            raw_log_exists = (
                run_dir / "jobs" / "generic-queued" / "raw.log"
            ).exists()

        self.assertEqual(job["status"], "queued")
        self.assertEqual(saved_job["status"], "queued")
        self.assertIsNone(saved_job["started_at"])
        self.assertIsNone(saved_job["completed_at"])
        self.assertEqual(input_payload["command"], [sys.executable, "-c", "print('not executed')"])
        self.assertFalse(raw_log_exists)
        self.assertEqual(saved_state, original_state)

    def test_create_generic_agent_job_rejects_empty_adapter_before_job_dir_created(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.create_generic_agent_job(
                    run_dir,
                    "generic-empty-adapter",
                    agent="generic-test-agent",
                    adapter="",
                    command=[sys.executable, "-c", "print('unused')"],
                    timeout_seconds=30,
                    root=ROOT,
                )

            job_dir_exists = (run_dir / "jobs" / "generic-empty-adapter").exists()

        self.assertIn("adapter must be non-empty", str(raised.exception))
        self.assertFalse(job_dir_exists)

    def test_create_generic_agent_job_rejects_malformed_command_before_job_dir_created(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.create_generic_agent_job(
                    run_dir,
                    "generic-bad-command",
                    agent="generic-test-agent",
                    command=[123],
                    timeout_seconds=30,
                    root=ROOT,
                )

            job_dir_exists = (run_dir / "jobs" / "generic-bad-command").exists()

        self.assertIn("command must be a non-empty list of strings", str(raised.exception))
        self.assertFalse(job_dir_exists)

    def test_create_generic_agent_job_rejects_forward_slash_job_id_before_directory_created(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.create_generic_agent_job(
                    run_dir,
                    "nested/job",
                    agent="generic-test-agent",
                    command=[sys.executable, "-c", "print('unused')"],
                    timeout_seconds=30,
                    root=ROOT,
                )

            jobs_dir_exists = (run_dir / "jobs").exists()

        self.assertIn("job_id must be a single safe path segment", str(raised.exception))
        self.assertFalse(jobs_dir_exists)

    def test_create_generic_agent_job_rejects_backslash_job_id_before_directory_created(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.create_generic_agent_job(
                    run_dir,
                    "nested\\job",
                    agent="generic-test-agent",
                    command=[sys.executable, "-c", "print('unused')"],
                    timeout_seconds=30,
                    root=ROOT,
                )

            jobs_dir_exists = (run_dir / "jobs").exists()

        self.assertIn("job_id must be a single safe path segment", str(raised.exception))
        self.assertFalse(jobs_dir_exists)

    def test_create_generic_agent_job_cleans_job_dir_when_input_write_fails(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            original_write_json_file = cli.write_json_file

            def flaky_write_json_file(path: Path, payload: dict) -> None:
                if path.name == "input.json":
                    raise OSError("injected input write failure")
                original_write_json_file(path, payload)

            with mock.patch("harness.cli.write_json_file", side_effect=flaky_write_json_file):
                with self.assertRaises(OSError):
                    cli.create_generic_agent_job(
                        run_dir,
                        "generic-write-failure",
                        agent="generic-test-agent",
                        command=[sys.executable, "-c", "print('unused')"],
                        timeout_seconds=30,
                        root=ROOT,
                    )

            job_dir_exists = (run_dir / "jobs" / "generic-write-failure").exists()
            job_json_exists = (
                run_dir / "jobs" / "generic-write-failure" / "job.json"
            ).exists()

        self.assertFalse(job_dir_exists)
        self.assertFalse(job_json_exists)

    def test_create_generic_agent_job_rejects_non_string_identifiers(self):
        cases = (
            ("job_id", 123),
            ("agent", 123),
            ("adapter", 123),
        )
        for field, value in cases:
            with self.subTest(field=field):
                with temporary_run_directory() as raw:
                    run_dir = Path(raw)
                    write_json(run_dir / "state.json", minimal_state())
                    kwargs = {
                        "job_id": "generic-non-string",
                        "agent": "generic-test-agent",
                        "adapter": "generic-cli-agent",
                    }
                    kwargs[field] = value

                    with self.assertRaises(cli.HarnessCliError) as raised:
                        cli.create_generic_agent_job(
                            run_dir,
                            kwargs["job_id"],
                            agent=kwargs["agent"],
                            adapter=kwargs["adapter"],
                            command=[sys.executable, "-c", "print('unused')"],
                            timeout_seconds=30,
                            root=ROOT,
                        )

                    jobs_dir_exists = (run_dir / "jobs").exists()

                self.assertIn(f"{field} must be a string", str(raised.exception))
                self.assertFalse(jobs_dir_exists)

    def test_execute_generic_agent_job_consumes_preexisting_queued_job(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            original_state = minimal_state()
            write_json(run_dir / "state.json", original_state)
            agent_script = run_dir / "queued_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Queued agent completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                print("queued agent wrote output")
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "generic-queued",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=30,
                root=ROOT,
            )

            job = cli.execute_generic_agent_job(
                run_dir,
                "generic-queued",
                root=ROOT,
            )
            raw_log = (run_dir / "jobs" / "generic-queued" / "raw.log").read_text(
                encoding="utf-8",
            )
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(job["status"], "succeeded")
        self.assertIn("queued agent wrote output", raw_log)
        self.assertEqual(saved_state, original_state)

    def test_execute_generic_agent_job_marks_failed_on_runtime_raw_log_conflict(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "direct_raw_conflict_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                Path(os.environ["HARNESS_AGENT_RAW_LOG_FILE"]).write_text(
                    "external raw log\\n",
                    encoding="utf-8",
                )
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Direct raw conflict job completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "generic-raw-conflict",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=30,
                root=ROOT,
            )

            job = cli.execute_generic_agent_job(
                run_dir,
                "generic-raw-conflict",
                root=ROOT,
            )
            job_dir = run_dir / "jobs" / "generic-raw-conflict"
            raw_log = (job_dir / "raw.log").read_text(encoding="utf-8")
            saved_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))

        self.assertEqual(raw_log, "external raw log\n")
        self.assertEqual(job["status"], "failed")
        self.assertEqual(saved_job["status"], "failed")
        self.assertIn("raw_log_file already exists", job["error_reason"])

    def test_execute_generic_agent_job_rejects_preexisting_output_before_claim(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "generic-stale-output",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "pass"],
                timeout_seconds=30,
                root=ROOT,
            )
            job_dir = run_dir / "jobs" / "generic-stale-output"
            input_payload = json.loads((job_dir / "input.json").read_text(encoding="utf-8"))
            stale_output = {
                "run_id": input_payload["run_id"],
                "job_id": input_payload["job_id"],
                "agent": input_payload["agent"],
                "adapter": input_payload["adapter"],
                "status": "passed",
                "summary": "Stale output should not be trusted.",
                "findings": [],
                "evidence": [],
                "not_tested": [],
                "residual_risks": [],
                "generated_at": input_payload["created_at"],
            }
            write_json(job_dir / "output.json", stale_output)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.execute_generic_agent_job(
                    run_dir,
                    "generic-stale-output",
                    root=ROOT,
                )

            saved_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
            saved_output = json.loads((job_dir / "output.json").read_text(encoding="utf-8"))
            raw_log_exists = (job_dir / "raw.log").exists()

        self.assertIn("output_file already exists", str(raised.exception))
        self.assertEqual(saved_job["status"], "queued")
        self.assertEqual(saved_output, stale_output)
        self.assertFalse(raw_log_exists)

    def test_execute_generic_agent_job_rejects_preexisting_raw_log_before_claim(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "generic-stale-log",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('unused')"],
                timeout_seconds=30,
                root=ROOT,
            )
            job_dir = run_dir / "jobs" / "generic-stale-log"
            raw_log_path = job_dir / "raw.log"
            raw_log_path.write_text("stale raw log\n", encoding="utf-8")

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.execute_generic_agent_job(
                    run_dir,
                    "generic-stale-log",
                    root=ROOT,
                )

            saved_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
            raw_log = raw_log_path.read_text(encoding="utf-8")

        self.assertIn("raw_log_file already exists", str(raised.exception))
        self.assertEqual(saved_job["status"], "queued")
        self.assertEqual(raw_log, "stale raw log\n")

    def test_execute_generic_agent_job_rejects_non_string_job_id(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.execute_generic_agent_job(
                    run_dir,
                    123,
                    root=ROOT,
                )

        self.assertIn("job_id must be a string", str(raised.exception))

    def test_execute_generic_agent_job_rejects_terminal_job_without_overwriting_raw_log(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "terminal_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Terminal agent completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                """,
            )
            cli.run_generic_agent(
                run_dir,
                "generic-terminal",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=30,
                root=ROOT,
            )
            raw_log_path = run_dir / "jobs" / "generic-terminal" / "raw.log"
            raw_log_path.write_text("original raw log\n", encoding="utf-8")

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.execute_generic_agent_job(
                    run_dir,
                    "generic-terminal",
                    root=ROOT,
                )

            raw_log = raw_log_path.read_text(encoding="utf-8")

        self.assertIn("cannot execute job generic-terminal with status succeeded", str(raised.exception))
        self.assertEqual(raw_log, "original raw log\n")

    def test_execute_generic_agent_job_rejects_forward_slash_job_id_before_artifacts(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            nested_job_dir = run_dir / "jobs" / "nested" / "job"
            nested_job_dir.mkdir(parents=True)
            (nested_job_dir / "job.json").write_text("not json\n", encoding="utf-8")

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.execute_generic_agent_job(
                    run_dir,
                    "nested/job",
                    root=ROOT,
                )

            raw_log_exists = (nested_job_dir / "raw.log").exists()

        self.assertIn("job_id must be a single safe path segment", str(raised.exception))
        self.assertFalse(raw_log_exists)

    def test_execute_generic_agent_job_rejects_artifact_paths_that_escape_job_dir(self):
        for field in ("input_file", "output_file", "raw_log_file"):
            with self.subTest(field=field):
                with temporary_run_directory() as raw:
                    run_dir = Path(raw)
                    original_state_text = json.dumps(minimal_state(), indent=2) + "\n"
                    (run_dir / "state.json").write_text(original_state_text, encoding="utf-8")
                    cli.create_generic_agent_job(
                        run_dir,
                        "generic-escape",
                        agent="generic-test-agent",
                        command=[sys.executable, "-c", "print('escape attempt')"],
                        timeout_seconds=30,
                        root=ROOT,
                    )
                    job_path = run_dir / "jobs" / "generic-escape" / "job.json"
                    job = json.loads(job_path.read_text(encoding="utf-8"))
                    job[field] = "../../state.json"
                    write_json(job_path, job)

                    with self.assertRaises(cli.HarnessCliError) as raised:
                        cli.execute_generic_agent_job(
                            run_dir,
                            "generic-escape",
                            root=ROOT,
                        )

                    saved_state_text = (run_dir / "state.json").read_text(encoding="utf-8")

                self.assertIn(f"{field} escapes job directory", str(raised.exception))
                self.assertEqual(saved_state_text, original_state_text)

    def test_execute_generic_agent_job_rejects_job_id_mismatch(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "generic-identity",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('unused')"],
                timeout_seconds=30,
                root=ROOT,
            )
            job_path = run_dir / "jobs" / "generic-identity" / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["job_id"] = "other-job"
            write_json(job_path, job)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.execute_generic_agent_job(
                    run_dir,
                    "generic-identity",
                    root=ROOT,
                )

        self.assertIn("job_id mismatch", str(raised.exception))

    def test_execute_generic_agent_job_rejects_run_id_mismatch(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "generic-run-mismatch",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('unused')"],
                timeout_seconds=30,
                root=ROOT,
            )
            job_path = run_dir / "jobs" / "generic-run-mismatch" / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["run_id"] = "other-run"
            write_json(job_path, job)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.execute_generic_agent_job(
                    run_dir,
                    "generic-run-mismatch",
                    root=ROOT,
                )

        self.assertIn("run_id mismatch", str(raised.exception))

    def test_execute_generic_agent_job_rejects_non_object_input_before_claim(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "generic-input-shape",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('unused')"],
                timeout_seconds=30,
                root=ROOT,
            )
            job_dir = run_dir / "jobs" / "generic-input-shape"
            (job_dir / "input.json").write_text("[]\n", encoding="utf-8")

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.execute_generic_agent_job(
                    run_dir,
                    "generic-input-shape",
                    root=ROOT,
                )

            saved_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
            raw_log_exists = (job_dir / "raw.log").exists()

        self.assertIn("job input must be an object", str(raised.exception))
        self.assertEqual(saved_job["status"], "queued")
        self.assertFalse(raw_log_exists)

    def test_execute_generic_agent_job_rejects_non_string_command_before_claim(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "generic-command-shape",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('unused')"],
                timeout_seconds=30,
                root=ROOT,
            )
            job_dir = run_dir / "jobs" / "generic-command-shape"
            input_path = job_dir / "input.json"
            input_payload = json.loads(input_path.read_text(encoding="utf-8"))
            input_payload["command"] = [sys.executable, 7]
            write_json(input_path, input_payload)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.execute_generic_agent_job(
                    run_dir,
                    "generic-command-shape",
                    root=ROOT,
                )

            saved_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
            raw_log_exists = (job_dir / "raw.log").exists()

        self.assertIn("command must be a non-empty list of strings", str(raised.exception))
        self.assertEqual(saved_job["status"], "queued")
        self.assertFalse(raw_log_exists)

    def test_execute_generic_agent_job_rejects_input_identity_mismatch_before_claim(self):
        for field, value in (
            ("run_id", "other-run"),
            ("job_id", "other-job"),
            ("agent", "other-agent"),
            ("adapter", "other-adapter"),
            ("timeout_seconds", 31),
        ):
            with self.subTest(field=field):
                with temporary_run_directory() as raw:
                    run_dir = Path(raw)
                    write_json(run_dir / "state.json", minimal_state())
                    cli.create_generic_agent_job(
                        run_dir,
                        "generic-input-identity",
                        agent="generic-test-agent",
                        command=[sys.executable, "-c", "print('unused')"],
                        timeout_seconds=30,
                        root=ROOT,
                    )
                    job_dir = run_dir / "jobs" / "generic-input-identity"
                    input_path = job_dir / "input.json"
                    input_payload = json.loads(input_path.read_text(encoding="utf-8"))
                    input_payload[field] = value
                    write_json(input_path, input_payload)

                    with self.assertRaises(cli.HarnessCliError) as raised:
                        cli.execute_generic_agent_job(
                            run_dir,
                            "generic-input-identity",
                            root=ROOT,
                        )

                    saved_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
                    raw_log_exists = (job_dir / "raw.log").exists()

                self.assertIn(f"input {field} mismatch", str(raised.exception))
                self.assertEqual(saved_job["status"], "queued")
                self.assertFalse(raw_log_exists)

    def test_execute_generic_agent_job_rejects_input_path_escape_or_mismatch_before_claim(self):
        cases = (
            ("input_file", "../../state.json", "input input_file escapes job directory"),
            ("output_file", "../../state.json", "input output_file escapes job directory"),
            ("raw_log_file", "../../state.json", "input raw_log_file escapes job directory"),
            ("input_file", "other-input.json", "input input_file mismatch"),
            ("output_file", "other-output.json", "input output_file mismatch"),
            ("raw_log_file", "other-raw.log", "input raw_log_file mismatch"),
        )
        for field, value, expected_error in cases:
            with self.subTest(field=field, value=value):
                with temporary_run_directory() as raw:
                    run_dir = Path(raw)
                    write_json(run_dir / "state.json", minimal_state())
                    cli.create_generic_agent_job(
                        run_dir,
                        "generic-input-path",
                        agent="generic-test-agent",
                        command=[sys.executable, "-c", "print('unused')"],
                        timeout_seconds=30,
                        root=ROOT,
                    )
                    job_dir = run_dir / "jobs" / "generic-input-path"
                    input_path = job_dir / "input.json"
                    input_payload = json.loads(input_path.read_text(encoding="utf-8"))
                    input_payload[field] = value
                    write_json(input_path, input_payload)

                    with self.assertRaises(cli.HarnessCliError) as raised:
                        cli.execute_generic_agent_job(
                            run_dir,
                            "generic-input-path",
                            root=ROOT,
                        )

                    saved_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
                    raw_log_exists = (job_dir / "raw.log").exists()

                self.assertIn(expected_error, str(raised.exception))
                self.assertEqual(saved_job["status"], "queued")
                self.assertFalse(raw_log_exists)

    def test_try_claim_job_creates_owner_and_blocks_second_worker(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "claim-once",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('claim')"],
                timeout_seconds=30,
                root=ROOT,
            )

            claim = cli.try_claim_job(
                run_dir,
                "claim-once",
                worker_id="worker-a",
                root=ROOT,
            )
            second_claim = cli.try_claim_job(
                run_dir,
                "claim-once",
                worker_id="worker-b",
                root=ROOT,
            )
            owner = json.loads(
                (run_dir / "jobs" / "claim-once" / "claim.lock" / "owner.json").read_text(
                    encoding="utf-8",
                ),
            )
            cli.release_job_claim(claim)
            lock_exists_after_release = (
                run_dir / "jobs" / "claim-once" / "claim.lock"
            ).exists()

        self.assertIsNotNone(claim)
        self.assertIsNone(second_claim)
        self.assertEqual(claim.job_id, "claim-once")
        self.assertEqual(claim.worker_id, "worker-a")
        self.assertEqual(owner["schema_version"], 2)
        self.assertEqual(owner["run_id"], "test-run")
        self.assertEqual(owner["job_id"], "claim-once")
        self.assertEqual(owner["worker_id"], "worker-a")
        self.assertRegex(owner["claim_token"], r"^[0-9a-f]{32}$")
        self.assertEqual(owner["lease_started_at"], owner["claimed_at"])
        self.assertEqual(owner["lease_heartbeat_at"], owner["claimed_at"])
        claimed_at = cli.parse_datetime(owner["claimed_at"])
        lease_expires_at = cli.parse_datetime(owner["lease_expires_at"])
        self.assertIsNotNone(claimed_at)
        self.assertIsNotNone(lease_expires_at)
        self.assertEqual(
            lease_expires_at - claimed_at,
            timedelta(seconds=cli.DEFAULT_CLAIM_LEASE_SECONDS),
        )
        self.assertEqual(claim.claim_token, owner["claim_token"])
        self.assertEqual(owner["lock_path"], "jobs/claim-once/claim.lock")
        self.assertNotIn("pid", owner)
        self.assertFalse(lock_exists_after_release)

    def test_release_job_claim_does_not_remove_reclaimed_lock(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "release-race",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('release')"],
                timeout_seconds=30,
                root=ROOT,
            )
            claim_a = cli.try_claim_job(
                run_dir,
                "release-race",
                worker_id="worker-a",
                root=ROOT,
            )
            self.assertIsNotNone(claim_a)
            cli.remove_claim_lock_dir(claim_a.lock_dir, claim_a.job_dir)
            claim_b = cli.try_claim_job(
                run_dir,
                "release-race",
                worker_id="worker-b",
                root=ROOT,
            )
            self.assertIsNotNone(claim_b)

            cli.release_job_claim(claim_a)

            owner = json.loads(claim_b.owner_path.read_text(encoding="utf-8"))
            lock_exists_after_stale_release = claim_b.lock_dir.exists()
            cli.release_job_claim(claim_b)

        self.assertTrue(lock_exists_after_stale_release)
        self.assertEqual(owner["worker_id"], "worker-b")
        self.assertEqual(owner["claim_token"], claim_b.claim_token)

    def test_concurrent_claims_same_worker_id_get_one_token(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "same-worker-token",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('token')"],
                timeout_seconds=30,
                root=ROOT,
            )
            claims: list[object] = []
            errors: list[BaseException] = []

            def claim_job() -> None:
                try:
                    claims.append(
                        cli.try_claim_job(
                            run_dir,
                            "same-worker-token",
                            worker_id="same-worker",
                            root=ROOT,
                        ),
                    )
                except BaseException as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=claim_job) for _ in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)

            winners = [claim for claim in claims if claim is not None]
            for claim in winners:
                cli.release_job_claim(claim)

        self.assertEqual(errors, [])
        self.assertEqual(len(winners), 1)
        self.assertRegex(winners[0].claim_token, r"^[0-9a-f]{32}$")

    def test_refresh_claim_lease_updates_owner_without_changing_job(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "lease-refresh",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('lease')"],
                timeout_seconds=30,
                root=ROOT,
            )
            claim = cli.try_claim_job(
                run_dir,
                "lease-refresh",
                worker_id="worker-a",
                root=ROOT,
            )
            original_job = json.loads(
                (run_dir / "jobs" / "lease-refresh" / "job.json").read_text(
                    encoding="utf-8",
                ),
            )

            refreshed = cli.refresh_claim_lease(
                claim,
                lease_seconds=30,
                now="2026-06-22T00:01:00Z",
                root=ROOT,
            )
            saved_owner = json.loads(
                (
                    run_dir
                    / "jobs"
                    / "lease-refresh"
                    / "claim.lock"
                    / "owner.json"
                ).read_text(encoding="utf-8"),
            )
            saved_job = json.loads(
                (run_dir / "jobs" / "lease-refresh" / "job.json").read_text(
                    encoding="utf-8",
                ),
            )
            cli.release_job_claim(claim)

        self.assertEqual(saved_job, original_job)
        self.assertEqual(refreshed.owner, saved_owner)
        self.assertEqual(saved_owner["lease_heartbeat_at"], "2026-06-22T00:01:00Z")
        self.assertEqual(saved_owner["lease_expires_at"], "2026-06-22T00:01:30Z")

    def test_refresh_claim_lease_does_not_overwrite_reclaimed_owner(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "lease-race",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('race')"],
                timeout_seconds=30,
                root=ROOT,
            )
            claim_a = cli.try_claim_job(
                run_dir,
                "lease-race",
                worker_id="worker-a",
                root=ROOT,
            )
            self.assertIsNotNone(claim_a)
            owner_read = threading.Event()
            release_reclaim_done = threading.Event()
            reclaim_result: dict[str, object] = {}
            reclaim_errors: list[BaseException] = []
            original_validate = cli.validate_json_artifact

            def delayed_owner_validate(path, schema_path, artifact_name):
                result = original_validate(path, schema_path, artifact_name)
                if (
                    Path(path) == claim_a.owner_path
                    and Path(schema_path) == cli.CLAIM_OWNER_SCHEMA
                    and artifact_name == "claim-owner"
                ):
                    owner_read.set()
                    time.sleep(0.2)
                return result

            def release_and_reclaim() -> None:
                try:
                    self.assertTrue(owner_read.wait(timeout=5))
                    cli.release_job_claim(claim_a)
                    claim_b = cli.try_claim_job(
                        run_dir,
                        "lease-race",
                        worker_id="worker-b",
                        root=ROOT,
                    )
                    reclaim_result["claim_b"] = claim_b
                except BaseException as exc:
                    reclaim_errors.append(exc)
                finally:
                    release_reclaim_done.set()

            reclaimer = threading.Thread(target=release_and_reclaim)
            with mock.patch.object(
                cli,
                "validate_json_artifact",
                side_effect=delayed_owner_validate,
            ):
                reclaimer.start()
                refreshed = cli.refresh_claim_lease(
                    claim_a,
                    now="2026-06-22T00:01:00Z",
                    root=ROOT,
                )
                self.assertTrue(release_reclaim_done.wait(timeout=5))
                reclaimer.join(timeout=5)

            saved_owner = json.loads(claim_a.owner_path.read_text(encoding="utf-8"))
            claim_b = reclaim_result.get("claim_b")
            if claim_b is not None:
                cli.release_job_claim(claim_b)

        self.assertEqual(reclaim_errors, [])
        self.assertIsNotNone(claim_b)
        self.assertFalse(reclaimer.is_alive())
        self.assertEqual(saved_owner["worker_id"], "worker-b")
        self.assertEqual(saved_owner["claim_token"], claim_b.claim_token)
        self.assertNotEqual(saved_owner["claim_token"], refreshed.claim_token)

    def test_acquire_claim_lock_retries_transient_windows_access_denied(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            job_dir = run_dir / "jobs" / "claim-transient"
            job_dir.mkdir(parents=True)
            lock_dir = job_dir / "claim.lock"
            owner = cli.build_claim_owner(
                run_id="test-run",
                job_id="claim-transient",
                worker_id="worker-a",
                claim_token="a" * 32,
                claimed_at=cli.resolve_datetime("2026-06-22T00:00:00Z", "claimed_at"),
            )
            path_type = type(run_dir)
            original_rename = path_type.rename
            injected_failures: list[str] = []

            def flaky_rename(self_path: Path, target: Path) -> Path:
                if self_path.name.startswith(".claim.lock.") and not injected_failures:
                    injected_failures.append(str(self_path))
                    exc = PermissionError("transient access denied")
                    exc.winerror = 5
                    raise exc
                return original_rename(self_path, target)

            with (
                mock.patch.object(path_type, "rename", autospec=True, side_effect=flaky_rename),
                mock.patch("harness.cli.time.sleep", return_value=None),
            ):
                acquired = cli.acquire_claim_lock_dir(job_dir, lock_dir, owner)

            saved_owner = json.loads((lock_dir / "owner.json").read_text(encoding="utf-8"))
            temp_dirs = list(job_dir.glob(".claim.lock.*.tmp"))

        self.assertTrue(acquired)
        self.assertEqual(len(injected_failures), 1)
        self.assertEqual(saved_owner, owner)
        self.assertEqual(temp_dirs, [])

    def test_remove_claim_lock_retries_transient_windows_directory_not_empty(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            job_dir = run_dir / "jobs" / "claim-remove-transient"
            lock_dir = job_dir / "claim.lock"
            lock_dir.mkdir(parents=True)
            (lock_dir / "owner.json").write_text("{}\n", encoding="utf-8")
            original_rmtree = cli.shutil.rmtree
            injected_failures: list[str] = []
            expected_lock_dir = lock_dir.resolve(strict=False)

            def flaky_rmtree(path):
                if os.fspath(path) == os.fspath(expected_lock_dir) and not injected_failures:
                    injected_failures.append("failed-once")
                    error = OSError("directory not empty")
                    error.winerror = 145
                    raise error
                return original_rmtree(path)

            with (
                mock.patch.object(cli.os, "name", "nt"),
                mock.patch.object(cli.shutil, "rmtree", side_effect=flaky_rmtree),
                mock.patch("harness.cli.time.sleep", return_value=None),
            ):
                cli.remove_claim_lock_dir(lock_dir, job_dir)

        self.assertEqual(injected_failures, ["failed-once"])
        self.assertFalse(lock_dir.exists())

    def test_try_claim_job_releases_lock_when_reload_finds_non_queued_job(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "claim-race-lost",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('claim')"],
                timeout_seconds=30,
                root=ROOT,
            )
            original_write_json_atomic = cli.write_json_atomic

            def write_owner_then_flip_job(path: Path, payload: dict) -> None:
                original_write_json_atomic(path, payload)
                if path.name == "owner.json":
                    mark_job_running(
                        run_dir,
                        "claim-race-lost",
                        worker_id="external-worker",
                    )

            with mock.patch(
                "harness.cli.write_json_atomic",
                side_effect=write_owner_then_flip_job,
            ):
                claim = cli.try_claim_job(
                    run_dir,
                    "claim-race-lost",
                    worker_id="worker-a",
                    root=ROOT,
                )

            lock_exists = (run_dir / "jobs" / "claim-race-lost" / "claim.lock").exists()
            saved_job = json.loads(
                (run_dir / "jobs" / "claim-race-lost" / "job.json").read_text(
                    encoding="utf-8",
                ),
            )

        self.assertIsNone(claim)
        self.assertFalse(lock_exists)
        self.assertEqual(saved_job["status"], "running")
        self.assertEqual(saved_job["worker_id"], "external-worker")

    def test_scheduler_run_once_executes_queued_jobs_in_order_and_continues_after_failed_terminal_job(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "success_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": f"{payload['job_id']} completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                print(payload["job_id"])
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "001-fails",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "import sys; sys.exit(7)"],
                timeout_seconds=30,
                root=ROOT,
            )
            cli.create_generic_agent_job(
                run_dir,
                "002-succeeds",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=30,
                root=ROOT,
            )

            summary = cli.scheduler_run_once(run_dir, root=ROOT)
            failed_job = json.loads(
                (run_dir / "jobs" / "001-fails" / "job.json").read_text(
                    encoding="utf-8",
                )
            )
            succeeded_job = json.loads(
                (run_dir / "jobs" / "002-succeeds" / "job.json").read_text(
                    encoding="utf-8",
                )
            )

        self.assertEqual(summary["executed_jobs"], ["001-fails", "002-succeeds"])
        self.assertEqual(failed_job["status"], "failed")
        self.assertEqual(succeeded_job["status"], "succeeded")

    def test_scheduler_run_once_skips_running_and_terminal_jobs_without_claiming_them(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "running-job",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('running')"],
                timeout_seconds=30,
                root=ROOT,
            )
            running_path = run_dir / "jobs" / "running-job" / "job.json"
            running_job = json.loads(running_path.read_text(encoding="utf-8"))
            running_job["status"] = "running"
            running_job["started_at"] = running_job["created_at"]
            write_json(running_path, running_job)

            cli.create_generic_agent_job(
                run_dir,
                "terminal-job",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('terminal')"],
                timeout_seconds=30,
                root=ROOT,
            )
            terminal_path = run_dir / "jobs" / "terminal-job" / "job.json"
            terminal_job = json.loads(terminal_path.read_text(encoding="utf-8"))
            terminal_job["status"] = "failed"
            terminal_job["started_at"] = terminal_job["created_at"]
            terminal_job["completed_at"] = terminal_job["created_at"]
            terminal_job["error_reason"] = "preexisting terminal"
            write_json(terminal_path, terminal_job)

            summary = cli.scheduler_run_once(run_dir, root=ROOT)
            saved_running = json.loads(running_path.read_text(encoding="utf-8"))
            saved_terminal = json.loads(terminal_path.read_text(encoding="utf-8"))

        self.assertEqual(summary["executed_jobs"], [])
        self.assertEqual(summary["skipped_jobs"], ["running-job", "terminal-job"])
        self.assertEqual(saved_running["status"], "running")
        self.assertEqual(saved_terminal["error_reason"], "preexisting terminal")

    def test_scheduler_run_once_two_workers_execute_same_queued_job_at_most_once(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "race-once",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('race')"],
                timeout_seconds=30,
                root=ROOT,
            )
            job_path = run_dir / "jobs" / "race-once" / "job.json"
            first_entered = threading.Event()
            allow_finish = threading.Event()
            executions: list[str] = []
            errors: list[BaseException] = []

            def fake_execute(
                run_dir_arg: Path,
                job_id: str,
                *,
                worker_id: str,
                iteration: int,
                poll_interval_seconds: float,
                root: Path,
                claim: cli.JobClaim | None = None,
            ) -> dict:
                executions.append(worker_id)
                first_entered.set()
                self.assertTrue(allow_finish.wait(timeout=5))
                job = json.loads(job_path.read_text(encoding="utf-8"))
                completed_at = cli.utc_now()
                job["status"] = "succeeded"
                job["started_at"] = job["started_at"] or completed_at
                job["completed_at"] = completed_at
                job["updated_at"] = completed_at
                job["worker_id"] = worker_id
                job["error_reason"] = None
                write_json(job_path, job)
                return job

            def run_worker(worker_id: str) -> None:
                try:
                    cli.scheduler_run_once(run_dir, worker_id=worker_id, root=ROOT)
                except BaseException as exc:
                    errors.append(exc)

            with mock.patch(
                "harness.cli.execute_scheduler_job_with_heartbeat",
                side_effect=fake_execute,
            ):
                first = threading.Thread(target=run_worker, args=("worker-a",))
                second = threading.Thread(target=run_worker, args=("worker-b",))
                first.start()
                self.assertTrue(first_entered.wait(timeout=20))
                second.start()
                time.sleep(0.2)
                allow_finish.set()
                first.join(timeout=20)
                second.join(timeout=20)
                saved_job = json.loads(job_path.read_text(encoding="utf-8"))

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(saved_job["status"], "succeeded")
        self.assertLessEqual(executions.count("worker-a") + executions.count("worker-b"), 1)

    def test_scheduler_run_once_aborts_on_invalid_job_record_before_executing_any_job(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            invalid_path = run_dir / "jobs" / "000-invalid" / "job.json"
            invalid_path.parent.mkdir(parents=True, exist_ok=True)
            invalid_path.write_text("[]\n", encoding="utf-8")
            cli.create_generic_agent_job(
                run_dir,
                "001-valid",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('must not run')"],
                timeout_seconds=30,
                root=ROOT,
            )

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.scheduler_run_once(run_dir, root=ROOT)

            valid_job = json.loads(
                (run_dir / "jobs" / "001-valid" / "job.json").read_text(
                    encoding="utf-8",
                )
            )

        self.assertIn("job schema error", str(raised.exception))
        self.assertEqual(valid_job["status"], "queued")

    def test_scheduler_run_once_aborts_on_semantically_invalid_job_before_executing_any_job(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            original_state = minimal_state()
            write_json(run_dir / "state.json", original_state)
            cli.create_generic_agent_job(
                run_dir,
                "bad-running",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('bad running')"],
                timeout_seconds=30,
                root=ROOT,
            )
            bad_path = run_dir / "jobs" / "bad-running" / "job.json"
            bad_job = json.loads(bad_path.read_text(encoding="utf-8"))
            bad_job["status"] = "running"
            bad_job["started_at"] = None
            bad_job["completed_at"] = None
            write_json(bad_path, bad_job)

            cli.create_generic_agent_job(
                run_dir,
                "001-valid",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('must not run')"],
                timeout_seconds=30,
                root=ROOT,
            )

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.scheduler_run_once(run_dir, root=ROOT)

            valid_job = json.loads(
                (run_dir / "jobs" / "001-valid" / "job.json").read_text(
                    encoding="utf-8",
                )
            )

        self.assertIn("running job requires started_at", str(raised.exception))
        self.assertEqual(valid_job["status"], "queued")

    def test_scheduler_artifacts_split_worker_identity_heartbeat_and_jsonl_events(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            original_state = minimal_state()
            write_json(run_dir / "state.json", original_state)

            worker = cli.write_scheduler_worker(
                run_dir,
                worker_id="worker-test",
                poll_interval_seconds=0.1,
                max_iterations=3,
                max_seconds=None,
                root=ROOT,
            )
            heartbeat = cli.write_scheduler_heartbeat(
                run_dir,
                worker_id="worker-test",
                iteration=1,
                status="idle",
                current_job_id=None,
            )
            cli.append_scheduler_event(
                run_dir,
                "worker_started",
                {"worker_id": "worker-test"},
            )
            cli.append_scheduler_event(
                run_dir,
                "poll_completed",
                {"worker_id": "worker-test", "iteration": 1},
            )

            scheduler_dir = run_dir / "jobs" / "scheduler"
            saved_worker = json.loads((scheduler_dir / "worker.json").read_text(encoding="utf-8"))
            saved_heartbeat = json.loads((scheduler_dir / "heartbeat.json").read_text(encoding="utf-8"))
            event_lines = (scheduler_dir / "events.log").read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in event_lines]
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(worker, saved_worker)
        self.assertEqual(heartbeat, saved_heartbeat)
        self.assertEqual(saved_state, original_state)
        self.assertEqual(
            set(saved_worker),
            {
                "worker_id",
                "pid",
                "started_at",
                "run_dir",
                "poll_interval",
                "max_iterations",
                "max_seconds",
                "cli_version",
            },
        )
        self.assertEqual(
            set(saved_heartbeat),
            {
                "worker_id",
                "last_seen_at",
                "iteration",
                "status",
                "current_job_id",
            },
        )
        self.assertEqual(saved_worker["worker_id"], "worker-test")
        self.assertEqual(saved_worker["poll_interval"], 0.1)
        self.assertEqual(saved_worker["max_iterations"], 3)
        self.assertEqual(saved_worker["cli_version"], "0.2.0")
        self.assertIn("pid", saved_worker)
        self.assertIn("started_at", saved_worker)
        self.assertNotIn("iteration", saved_worker)
        self.assertNotIn("status", saved_worker)
        self.assertEqual(saved_heartbeat["worker_id"], "worker-test")
        self.assertEqual(saved_heartbeat["iteration"], 1)
        self.assertEqual(saved_heartbeat["status"], "idle")
        self.assertIsNone(saved_heartbeat["current_job_id"])
        self.assertNotIn("pid", saved_heartbeat)
        self.assertEqual([event["event"] for event in events], ["worker_started", "poll_completed"])
        for event in events:
            self.assertIsInstance(event["ts"], str)
            self.assertIsInstance(event["event"], str)
            self.assertIsInstance(event["detail"], dict)

    def test_clear_scheduler_stop_request_removes_stale_stop_file(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            original_state = minimal_state()
            write_json(run_dir / "state.json", original_state)
            stop = cli.request_scheduler_stop(run_dir, reason="old stop", root=ROOT)
            stop_path = run_dir / "jobs" / "scheduler" / "stop.json"

            cli.clear_scheduler_stop_request(run_dir)
            exists_after_clear = stop_path.exists()
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(stop["reason"], "old stop")
        self.assertEqual(stop["requested_by"], "codex")
        self.assertEqual(saved_state, original_state)
        self.assertFalse(exists_after_clear)

    def test_run_scheduler_requires_exactly_one_mode(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())

            missing = subprocess.run(
                [sys.executable, "-m", "harness.cli", "run-scheduler", str(run_dir)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            both = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "run-scheduler",
                    str(run_dir),
                    "--once",
                    "--watch",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(missing.returncode, 2)
        self.assertIn("one of the arguments --once --watch is required", missing.stderr)
        self.assertEqual(both.returncode, 2)
        self.assertIn("not allowed with argument", both.stderr)

    def test_scheduler_watch_runs_queued_job_writes_artifacts_and_does_not_mutate_state(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            state = minimal_state()
            write_json(run_dir / "state.json", state)
            agent_script = run_dir / "watch_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Watch job completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                print("watch job wrote output")
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "watch-job",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=30,
                root=ROOT,
            )

            summary = cli.scheduler_run_watch(
                run_dir,
                poll_interval_seconds=0,
                max_iterations=3,
                worker_id="watch-worker",
                root=ROOT,
                sleep_fn=lambda seconds: None,
            )
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            job = json.loads((run_dir / "jobs" / "watch-job" / "job.json").read_text(encoding="utf-8"))
            scheduler_dir = run_dir / "jobs" / "scheduler"
            worker = json.loads((scheduler_dir / "worker.json").read_text(encoding="utf-8"))
            heartbeat = json.loads((scheduler_dir / "heartbeat.json").read_text(encoding="utf-8"))
            events = [
                json.loads(line)
                for line in (scheduler_dir / "events.log").read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(saved_state, state)
        self.assertEqual(summary["run_id"], "test-run")
        self.assertEqual(summary["executed_jobs"], ["watch-job"])
        self.assertEqual(summary["skipped_jobs"], [])
        self.assertEqual(summary["stop_reason"], "max_iterations")
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["worker_id"], "watch-worker")
        self.assertIsNotNone(job["updated_at"])
        self.assertEqual(worker["worker_id"], "watch-worker")
        self.assertEqual(heartbeat["worker_id"], "watch-worker")
        self.assertEqual(heartbeat["status"], "stopped")
        self.assertIsNone(heartbeat["current_job_id"])
        self.assertIn("worker_started", [event["event"] for event in events])
        self.assertIn("job_started", [event["event"] for event in events])
        self.assertIn("job_completed", [event["event"] for event in events])
        self.assertIn("worker_stopped", [event["event"] for event in events])
        for event in events:
            self.assertEqual(set(event), {"detail", "event", "ts"})
            self.assertIsInstance(event["detail"], dict)

    def test_scheduler_watch_rejects_unbounded_zero_interval_and_non_finite_options_before_artifacts(self):
        cases = [
            (
                {
                    "poll_interval_seconds": float("nan"),
                    "max_iterations": 1,
                },
                "poll_interval_seconds must be finite",
            ),
            (
                {
                    "poll_interval_seconds": float("inf"),
                    "max_iterations": 1,
                },
                "poll_interval_seconds must be finite",
            ),
            (
                {
                    "poll_interval_seconds": 0,
                },
                "poll_interval_seconds can be zero only with max_iterations or max_seconds",
            ),
            (
                {
                    "poll_interval_seconds": 1,
                    "max_seconds": float("nan"),
                },
                "max_seconds must be finite",
            ),
        ]
        for kwargs, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                with temporary_run_directory() as raw:
                    run_dir = Path(raw)
                    write_json(run_dir / "state.json", minimal_state())

                    with self.assertRaises(cli.HarnessCliError) as raised:
                        cli.scheduler_run_watch(run_dir, root=ROOT, **kwargs)

                    self.assertIn(expected_error, str(raised.exception))
                    self.assertFalse((run_dir / "jobs" / "scheduler").exists())

    def test_scheduler_watch_stops_when_max_seconds_elapsed(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            state = minimal_state()
            write_json(run_dir / "state.json", state)
            monotonic_values = iter([10.0, 10.6])

            summary = cli.scheduler_run_watch(
                run_dir,
                poll_interval_seconds=0,
                max_seconds=0.5,
                worker_id="max-seconds-worker",
                root=ROOT,
                sleep_fn=lambda seconds: None,
                monotonic_fn=lambda: next(monotonic_values),
            )
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            heartbeat = json.loads(
                (run_dir / "jobs" / "scheduler" / "heartbeat.json").read_text(
                    encoding="utf-8",
                ),
            )
            events = [
                json.loads(line)
                for line in (run_dir / "jobs" / "scheduler" / "events.log").read_text(
                    encoding="utf-8",
                ).splitlines()
            ]

        self.assertEqual(saved_state, state)
        self.assertEqual(summary["iterations"], 0)
        self.assertEqual(summary["executed_jobs"], [])
        self.assertEqual(summary["stop_reason"], "max_seconds")
        self.assertEqual(heartbeat["status"], "stopped")
        self.assertIn("max_seconds_reached", [event["event"] for event in events])

    def test_detects_matching_fresh_heartbeat_as_active_running_job(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "active-running",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('active')"],
                timeout_seconds=30,
                root=ROOT,
            )
            job_path = run_dir / "jobs" / "active-running" / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["status"] = "running"
            job["created_at"] = "2026-06-22T00:00:00Z"
            job["started_at"] = "2026-06-22T00:00:00Z"
            job["updated_at"] = "2026-06-22T00:00:00Z"
            job["worker_id"] = "worker-a"
            write_json(job_path, job)
            write_json(
                run_dir / "jobs" / "scheduler" / "heartbeat.json",
                {
                    "worker_id": "worker-a",
                    "last_seen_at": "2026-06-22T00:10:00Z",
                    "iteration": 4,
                    "status": "running-job",
                    "current_job_id": "active-running",
                },
            )

            report = cli.detect_stale_running_jobs(
                run_dir,
                heartbeat_timeout_seconds=60,
                now="2026-06-22T00:10:30Z",
                root=ROOT,
            )

        self.assertEqual(report["active_jobs"], ["active-running"])
        self.assertEqual(report["stale_jobs"], [])
        self.assertEqual(report["jobs"][0]["classification"], "active")
        self.assertIn("fresh matching scheduler heartbeat", report["jobs"][0]["reasons"])

    def test_detects_old_running_job_without_fresh_matching_heartbeat_as_stale(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "orphaned-running",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('orphaned')"],
                timeout_seconds=30,
                root=ROOT,
            )
            job_path = run_dir / "jobs" / "orphaned-running" / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["status"] = "running"
            job["created_at"] = "2026-06-22T00:00:00Z"
            job["started_at"] = "2026-06-22T00:00:00Z"
            job["updated_at"] = "2026-06-22T00:01:00Z"
            job["worker_id"] = "worker-old"
            write_json(job_path, job)
            write_json(
                run_dir / "jobs" / "scheduler" / "heartbeat.json",
                {
                    "worker_id": "worker-old",
                    "last_seen_at": "2026-06-22T00:02:00Z",
                    "iteration": 1,
                    "status": "running-job",
                    "current_job_id": "orphaned-running",
                },
            )

            report = cli.detect_stale_running_jobs(
                run_dir,
                heartbeat_timeout_seconds=60,
                now="2026-06-22T00:10:00Z",
                root=ROOT,
            )

        self.assertEqual(report["active_jobs"], [])
        self.assertEqual(report["stale_jobs"], ["orphaned-running"])
        stale = report["jobs"][0]
        self.assertEqual(stale["classification"], "stale")
        self.assertIn("scheduler heartbeat timed out", stale["reasons"])
        self.assertIn("job updated_at timed out", stale["reasons"])

    def test_detect_stale_reports_missing_claim_owner_without_clearing_lock(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "missing-owner",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('orphaned')"],
                timeout_seconds=30,
                root=ROOT,
            )
            mark_job_running(run_dir, "missing-owner", worker_id="worker-old")
            lock_dir = run_dir / "jobs" / "missing-owner" / "claim.lock"
            lock_dir.mkdir(parents=True)
            write_json(
                run_dir / "jobs" / "scheduler" / "heartbeat.json",
                {
                    "worker_id": "worker-old",
                    "last_seen_at": "2026-06-22T00:02:00Z",
                    "iteration": 1,
                    "status": "running-job",
                    "current_job_id": "missing-owner",
                },
            )

            report = cli.detect_stale_running_jobs(
                run_dir,
                heartbeat_timeout_seconds=60,
                now="2026-06-22T00:10:00Z",
                root=ROOT,
            )
            lock_still_exists = lock_dir.exists()

        self.assertEqual(report["stale_jobs"], ["missing-owner"])
        self.assertEqual(report["jobs"][0]["claim_lock"]["status"], "missing-owner")
        self.assertIsNone(report["jobs"][0]["claim_lock"]["owner"])
        self.assertTrue(lock_still_exists)

    def test_detect_stale_reports_expired_claim_lease(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "expired-lease",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('lease')"],
                timeout_seconds=30,
                root=ROOT,
            )
            mark_job_running(run_dir, "expired-lease", worker_id="worker-old")
            claim_token = "e" * 32
            write_claim_owner(
                run_dir,
                "expired-lease",
                worker_id="worker-old",
                claimed_at="2026-06-22T00:00:00Z",
                claim_token=claim_token,
            )
            owner_path = (
                run_dir / "jobs" / "expired-lease" / "claim.lock" / "owner.json"
            )
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
            owner["lease_heartbeat_at"] = "2026-06-22T00:01:00Z"
            owner["lease_expires_at"] = "2026-06-22T00:02:00Z"
            write_json(owner_path, owner)

            report = cli.detect_stale_running_jobs(
                run_dir,
                heartbeat_timeout_seconds=60,
                now="2026-06-22T00:10:00Z",
                root=ROOT,
            )

        claim_lock = report["jobs"][0]["claim_lock"]
        self.assertEqual(claim_lock["status"], "present")
        self.assertTrue(claim_lock["lease_expired"])
        self.assertEqual(claim_lock["claim_token"], claim_token)
        self.assertEqual(claim_lock["lease_heartbeat_at"], "2026-06-22T00:01:00Z")
        self.assertEqual(claim_lock["lease_expires_at"], "2026-06-22T00:02:00Z")
        self.assertEqual(claim_lock["lease_age_seconds"], 540.0)

    def test_expired_claim_lease_does_not_change_active_classification(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "active-expired-lease",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('active')"],
                timeout_seconds=30,
                root=ROOT,
            )
            mark_job_running(
                run_dir,
                "active-expired-lease",
                worker_id="worker-live",
                updated_at="2026-06-22T00:00:00Z",
            )
            write_json(
                run_dir / "jobs" / "scheduler" / "heartbeat.json",
                {
                    "worker_id": "worker-live",
                    "last_seen_at": "2026-06-22T00:10:00Z",
                    "iteration": 4,
                    "status": "running-job",
                    "current_job_id": "active-expired-lease",
                },
            )
            claim_token = "d" * 32
            write_claim_owner(
                run_dir,
                "active-expired-lease",
                worker_id="worker-live",
                claimed_at="2026-06-22T00:00:00Z",
                claim_token=claim_token,
            )
            owner_path = (
                run_dir / "jobs" / "active-expired-lease" / "claim.lock" / "owner.json"
            )
            owner = json.loads(owner_path.read_text(encoding="utf-8"))
            owner["lease_heartbeat_at"] = "2026-06-22T00:01:00Z"
            owner["lease_expires_at"] = "2026-06-22T00:02:00Z"
            write_json(owner_path, owner)

            report = cli.detect_stale_running_jobs(
                run_dir,
                heartbeat_timeout_seconds=60,
                now="2026-06-22T00:10:30Z",
                root=ROOT,
            )

        self.assertEqual(report["active_jobs"], ["active-expired-lease"])
        self.assertEqual(report["stale_jobs"], [])
        self.assertEqual(report["jobs"][0]["classification"], "active")
        self.assertTrue(report["jobs"][0]["claim_lock"]["lease_expired"])
        self.assertEqual(report["jobs"][0]["claim_lock"]["claim_token"], claim_token)

    def test_assert_claim_matches_job_rejects_mismatched_token(self):
        job = {
            "run_id": "test-run",
            "job_id": "token-job",
            "status": "running",
            "claim_token": "a" * 32,
        }
        owner = {
            "run_id": "test-run",
            "job_id": "token-job",
            "worker_id": "worker-a",
            "claim_token": "b" * 32,
        }

        with self.assertRaises(cli.HarnessCliError) as raised:
            cli.assert_claim_matches_job(
                job,
                owner,
                worker_id="worker-a",
                expected_status="running",
                expected_claim_token="b" * 32,
            )

        self.assertIn("claim_token mismatch", str(raised.exception))

    def test_write_job_if_claim_matches_rejects_unexpected_status(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "conditional-status",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('status')"],
                timeout_seconds=30,
                root=ROOT,
            )
            claim = cli.try_claim_job(
                run_dir,
                "conditional-status",
                worker_id="worker-a",
                root=ROOT,
            )
            job_path = run_dir / "jobs" / "conditional-status" / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["status"] = "running"
            job["claim_token"] = "c" * 32
            write_json(job_path, job)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.write_job_if_claim_matches(
                    claim,
                    expected_status="queued",
                    mutate=lambda current: current,
                )
            cli.release_job_claim(claim)

        self.assertIn("status mismatch", str(raised.exception))

    def test_write_job_if_claim_matches_writes_valid_mutation(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "conditional-write",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('write')"],
                timeout_seconds=30,
                root=ROOT,
            )
            claim = cli.try_claim_job(
                run_dir,
                "conditional-write",
                worker_id="worker-a",
                root=ROOT,
            )
            job_path = run_dir / "jobs" / "conditional-write" / "job.json"

            def start_job(current: dict) -> dict:
                claim_started_at = current["created_at"]
                current["status"] = "running"
                current["started_at"] = claim_started_at
                current["updated_at"] = claim_started_at
                current["worker_id"] = "worker-a"
                current["claim_token"] = claim.claim_token
                current["claim_started_at"] = claim_started_at
                current["claim_updated_at"] = claim_started_at
                return current

            saved = cli.write_job_if_claim_matches(
                claim,
                expected_status="queued",
                mutate=start_job,
            )
            loaded = json.loads(job_path.read_text(encoding="utf-8"))
            cli.release_job_claim(claim)

        self.assertEqual(saved, loaded)
        self.assertEqual(loaded["status"], "running")
        self.assertEqual(loaded["claim_token"], claim.claim_token)

    def test_write_job_if_claim_matches_rejects_invalid_mutation(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "conditional-invalid",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('invalid')"],
                timeout_seconds=30,
                root=ROOT,
            )
            claim = cli.try_claim_job(
                run_dir,
                "conditional-invalid",
                worker_id="worker-a",
                root=ROOT,
            )
            job_path = run_dir / "jobs" / "conditional-invalid" / "job.json"
            original_job = json.loads(job_path.read_text(encoding="utf-8"))

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.write_job_if_claim_matches(
                    claim,
                    expected_status="queued",
                    mutate=lambda current: {**current, "claim_token": "not-hex"},
                )
            saved_job = json.loads(job_path.read_text(encoding="utf-8"))
            cli.release_job_claim(claim)

        self.assertIn("job", str(raised.exception))
        self.assertEqual(saved_job, original_job)

    def test_execute_claimed_job_records_claim_token_on_running_job(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            release_file = run_dir / "release-claim-token.txt"
            agent_script = run_dir / "wait_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                import time
                from pathlib import Path

                release = Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).parents[2] / "release-claim-token.txt"
                while not release.exists():
                    time.sleep(0.05)
                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output_path = Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"])
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Claim token job completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                output_path.write_text(json.dumps(output, indent=2) + "\\n", encoding="utf-8")
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "claim-token-running",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=10,
                root=ROOT,
            )
            result: dict[str, object] = {}
            errors: list[BaseException] = []

            def run_worker() -> None:
                try:
                    result["summary"] = cli.scheduler_run_once(
                        run_dir,
                        worker_id="worker-a",
                        root=ROOT,
                    )
                except BaseException as exc:
                    errors.append(exc)

            worker = threading.Thread(target=run_worker)
            worker.start()
            job_path = run_dir / "jobs" / "claim-token-running" / "job.json"
            for _ in range(200):
                job = json.loads(job_path.read_text(encoding="utf-8"))
                if job["status"] == "running" and job.get("claim_token"):
                    break
                time.sleep(0.05)
            else:
                self.fail("job did not record claim token while running")
            running_job = json.loads(job_path.read_text(encoding="utf-8"))
            release_file.write_text("go\\n", encoding="utf-8")
            worker.join(timeout=20)
            terminal_job = json.loads(job_path.read_text(encoding="utf-8"))

        self.assertEqual(errors, [])
        self.assertEqual(terminal_job["status"], "succeeded")
        self.assertEqual(terminal_job["claim_token"], running_job["claim_token"])

    def test_claimed_execution_does_not_overwrite_raw_log_created_during_run(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "raw_conflict_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                raw_path = Path(os.environ["HARNESS_AGENT_RAW_LOG_FILE"])
                raw_path.write_text("external raw log\\n", encoding="utf-8")
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Raw conflict job completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(json.dumps(output, indent=2) + "\\n", encoding="utf-8")
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "raw-conflict",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=10,
                root=ROOT,
            )

            summary = cli.scheduler_run_once(run_dir, worker_id="worker-a", root=ROOT)

            job_dir = run_dir / "jobs" / "raw-conflict"
            raw_log = (run_dir / "jobs" / "raw-conflict" / "raw.log").read_text(
                encoding="utf-8",
            )
            saved_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
            temp_outputs = list(job_dir.glob("output.*.tmp.json"))
            lock_exists = (job_dir / "claim.lock").exists()

        self.assertEqual(raw_log, "external raw log\n")
        self.assertEqual(saved_job["status"], "failed")
        self.assertIn("raw_log_file already exists", saved_job["error_reason"])
        self.assertEqual(summary["terminal_statuses"], {"raw-conflict": "failed"})
        self.assertEqual(temp_outputs, [])
        self.assertFalse(lock_exists)

    def test_claimed_execution_does_not_write_raw_log_after_losing_claim(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            release_file = run_dir / "release-lost-claim.txt"
            agent_script = run_dir / "lost_claim_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                import time
                from pathlib import Path

                release = Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).parents[1] / "release-lost-claim.txt"
                while not release.exists():
                    time.sleep(0.05)
                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Lost claim job completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "lost-claim-raw",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=10,
                root=ROOT,
            )
            result: dict[str, object] = {}
            errors: list[BaseException] = []

            def run_worker() -> None:
                try:
                    result["summary"] = cli.scheduler_run_once(
                        run_dir,
                        worker_id="worker-a",
                        root=ROOT,
                    )
                except BaseException as exc:
                    errors.append(exc)

            worker = threading.Thread(target=run_worker)
            worker.start()
            job_dir = run_dir / "jobs" / "lost-claim-raw"
            job_path = job_dir / "job.json"
            for _ in range(200):
                job = json.loads(job_path.read_text(encoding="utf-8"))
                if job["status"] == "running" and job.get("claim_token"):
                    break
                time.sleep(0.05)
            else:
                self.fail("job did not enter claimed running state")

            cli.remove_claim_lock_dir(job_dir / "claim.lock", job_dir)
            release_file.write_text("go\n", encoding="utf-8")
            worker.join(timeout=20)
            raw_log_exists = (job_dir / "raw.log").exists()
            output_exists = (job_dir / "output.json").exists()

        self.assertFalse(worker.is_alive())
        self.assertEqual(result, {})
        self.assertEqual(len(errors), 1)
        self.assertTrue(
            "claim owner" in str(errors[0]) or "claim-owner" in str(errors[0]),
        )
        self.assertFalse(raw_log_exists)
        self.assertFalse(output_exists)

    def test_claimed_execution_does_not_overwrite_output_created_during_run(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "output_conflict_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                canonical_output = Path(os.environ["HARNESS_AGENT_RAW_LOG_FILE"]).with_name("output.json")
                canonical_output.write_text(
                    json.dumps({"sentinel": "external output"}, indent=2) + "\\n",
                    encoding="utf-8",
                )
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Output conflict job completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "output-conflict",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=10,
                root=ROOT,
            )

            summary = cli.scheduler_run_once(run_dir, worker_id="worker-a", root=ROOT)

            job_dir = run_dir / "jobs" / "output-conflict"
            output = json.loads(
                (job_dir / "output.json").read_text(encoding="utf-8"),
            )
            saved_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
            temp_outputs = list(job_dir.glob("output.*.tmp.json"))
            lock_exists = (job_dir / "claim.lock").exists()

        self.assertEqual(output, {"sentinel": "external output"})
        self.assertEqual(saved_job["status"], "failed")
        self.assertIn("output_file already exists", saved_job["error_reason"])
        self.assertEqual(summary["terminal_statuses"], {"output-conflict": "failed"})
        self.assertEqual(temp_outputs, [])
        self.assertFalse(lock_exists)

    def test_scheduler_run_once_marks_active_running_job_with_worker_heartbeat(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            release_file = run_dir / "release-once.txt"
            agent_script = run_dir / "once_wait_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                import time
                from pathlib import Path

                input_path = Path(os.environ["HARNESS_AGENT_INPUT_FILE"])
                output_path = Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"])
                payload = json.loads(input_path.read_text(encoding="utf-8"))
                release_file = Path(payload["command"][-1])
                while not release_file.exists():
                    time.sleep(0.05)
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Once job completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                output_path.write_text(json.dumps(output, indent=2) + "\\n", encoding="utf-8")
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "once-active",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script), str(release_file)],
                timeout_seconds=10,
                root=ROOT,
            )
            result: dict[str, object] = {}
            errors: list[BaseException] = []

            def run_once() -> None:
                try:
                    result["summary"] = cli.scheduler_run_once(
                        run_dir,
                        worker_id="once-worker",
                        root=ROOT,
                    )
                except BaseException as exc:
                    errors.append(exc)

            worker_thread = threading.Thread(target=run_once)
            worker_thread.start()
            job_path = run_dir / "jobs" / "once-active" / "job.json"
            for _ in range(100):
                current_job = json.loads(job_path.read_text(encoding="utf-8"))
                if current_job["status"] == "running":
                    break
                time.sleep(0.05)
            else:
                self.fail("job did not enter running state")

            report = cli.detect_stale_running_jobs(
                run_dir,
                heartbeat_timeout_seconds=5,
                root=ROOT,
            )
            release_file.write_text("go\n", encoding="utf-8")
            worker_thread.join(timeout=10)
            saved_job = json.loads(job_path.read_text(encoding="utf-8"))

        self.assertEqual(errors, [])
        self.assertFalse(worker_thread.is_alive())
        self.assertEqual(report["active_jobs"], ["once-active"])
        self.assertEqual(saved_job["status"], "succeeded")
        self.assertEqual(saved_job["worker_id"], "once-worker")
        self.assertEqual(result["summary"]["executed_jobs"], ["once-active"])

    def test_scheduler_job_heartbeat_refreshes_claim_lease(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            release_file = run_dir / "release-lease-refresh.txt"
            agent_script = run_dir / "lease_refresh_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                import time
                from pathlib import Path

                input_path = Path(os.environ["HARNESS_AGENT_INPUT_FILE"])
                output_path = Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"])
                payload = json.loads(input_path.read_text(encoding="utf-8"))
                release_file = Path(payload["command"][-1])
                while not release_file.exists():
                    time.sleep(0.05)
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Lease refresh job completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                output_path.write_text(json.dumps(output, indent=2) + "\\n", encoding="utf-8")
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "lease-heartbeat",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script), str(release_file)],
                timeout_seconds=15,
                root=ROOT,
            )
            result: dict[str, object] = {}
            errors: list[BaseException] = []

            def run_worker() -> None:
                try:
                    result["summary"] = cli.scheduler_run_once(
                        run_dir,
                        worker_id="lease-worker",
                        root=ROOT,
                    )
                except BaseException as exc:
                    errors.append(exc)

            worker = threading.Thread(target=run_worker)
            worker.start()
            job_dir = run_dir / "jobs" / "lease-heartbeat"
            job_path = job_dir / "job.json"
            owner_path = job_dir / "claim.lock" / "owner.json"
            for _ in range(200):
                if owner_path.exists():
                    job = cli.load_json(job_path)
                    if job["status"] == "running":
                        initial_owner = cli.load_json(owner_path)
                        break
                time.sleep(0.05)
            else:
                release_file.write_text("cleanup\n", encoding="utf-8")
                worker.join(timeout=20)
                self.fail("job did not enter claimed running state")

            refreshed_owner = initial_owner
            for _ in range(200):
                refreshed_owner = cli.load_json(owner_path)
                if (
                    cli.parse_datetime(refreshed_owner["lease_heartbeat_at"])
                    > cli.parse_datetime(initial_owner["lease_heartbeat_at"])
                ):
                    break
                time.sleep(0.05)
            release_file.write_text("go\n", encoding="utf-8")
            worker.join(timeout=20)

        self.assertEqual(errors, [])
        self.assertFalse(worker.is_alive())
        self.assertGreater(
            cli.parse_datetime(refreshed_owner["lease_heartbeat_at"]),
            cli.parse_datetime(initial_owner["lease_heartbeat_at"]),
        )
        self.assertGreater(
            cli.parse_datetime(refreshed_owner["lease_expires_at"]),
            cli.parse_datetime(initial_owner["lease_expires_at"]),
        )
        self.assertIn("lease-heartbeat", result["summary"]["executed_jobs"])

    def test_real_scheduler_process_kill_leaves_claimed_running_job_detectable_as_stale(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            release_file = run_dir / "release-crash.txt"
            agent_pid_file = run_dir / "agent.pid"
            agent_script = run_dir / "crash_wait_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                import sys
                import time
                from pathlib import Path

                release_file = Path(sys.argv[1])
                pid_file = Path(sys.argv[2])
                pid_file.write_text(str(os.getpid()), encoding="utf-8")
                while not release_file.exists():
                    time.sleep(0.05)
                input_path = Path(os.environ["HARNESS_AGENT_INPUT_FILE"])
                output_path = Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"])
                payload = json.loads(input_path.read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Crash smoke job completed after release.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                output_path.write_text(json.dumps(output, indent=2) + "\\n", encoding="utf-8")
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "crash-smoke",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script), str(release_file), str(agent_pid_file)],
                timeout_seconds=30,
                root=ROOT,
            )
            command = [
                sys.executable,
                "-m",
                "harness.cli",
                "run-scheduler",
                str(run_dir),
                "--watch",
                "--poll-interval-seconds",
                "0.1",
                "--worker-id",
                "crash-smoke-worker",
            ]
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
            job_path = run_dir / "jobs" / "crash-smoke" / "job.json"
            owner_path = run_dir / "jobs" / "crash-smoke" / "claim.lock" / "owner.json"
            heartbeat_path = run_dir / "jobs" / "scheduler" / "heartbeat.json"

            def read_json_or_none(path: Path) -> dict | None:
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return None

            try:
                for _ in range(200):
                    if process.poll() is not None:
                        self.fail("scheduler exited before crash smoke could kill it")
                    if job_path.exists() and heartbeat_path.exists():
                        current_job = read_json_or_none(job_path)
                        heartbeat = read_json_or_none(heartbeat_path)
                        if (
                            current_job is not None
                            and heartbeat is not None
                            and current_job["status"] == "running"
                            and current_job["worker_id"] == "crash-smoke-worker"
                            and owner_path.exists()
                            and heartbeat["status"] == "running-job"
                            and heartbeat["current_job_id"] == "crash-smoke"
                            and agent_pid_file.exists()
                        ):
                            break
                    time.sleep(0.05)
                else:
                    self.fail("scheduler did not reach claimed running state")

                cli.terminate_process_tree(process)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                future_now = datetime.now(timezone.utc) + timedelta(seconds=2)
                report = cli.detect_stale_running_jobs(
                    run_dir,
                    heartbeat_timeout_seconds=0.1,
                    now=future_now,
                    root=ROOT,
                )
                lock_exists_after_kill = owner_path.parent.exists()
            finally:
                release_file.write_text("cleanup\n", encoding="utf-8")
                if process.poll() is None:
                    cli.terminate_process_tree(process)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                if agent_pid_file.exists():
                    terminate_pid_tree(int(agent_pid_file.read_text(encoding="utf-8")))

        self.assertIn("crash-smoke", report["stale_jobs"])
        self.assertTrue(lock_exists_after_kill)

    def test_live_multi_worker_watch_processes_execute_jobs_once(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            release_file = run_dir / "release-all.txt"
            marker_dir = run_dir / "markers"
            marker_dir.mkdir()
            agent_script = run_dir / "multi_worker_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                import time
                from pathlib import Path

                input_path = Path(os.environ["HARNESS_AGENT_INPUT_FILE"])
                output_path = Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"])
                payload = json.loads(input_path.read_text(encoding="utf-8"))
                run_dir = input_path.parents[2]
                release_file = run_dir / "release-all.txt"
                marker_path = run_dir / "markers" / f"{payload['job_id']}.txt"
                with marker_path.open("x", encoding="utf-8") as marker:
                    marker.write(payload["job_id"] + "\\n")
                while not release_file.exists():
                    time.sleep(0.05)
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Multi-worker job completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                output_path.write_text(json.dumps(output, indent=2) + "\\n", encoding="utf-8")
                """,
            )
            for index in range(5):
                cli.create_generic_agent_job(
                    run_dir,
                    f"multi-{index}",
                    agent="generic-test-agent",
                    command=[sys.executable, str(agent_script)],
                    timeout_seconds=20,
                    root=ROOT,
                )

            processes = [
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "harness.cli",
                        "run-scheduler",
                        str(run_dir),
                        "--watch",
                        "--poll-interval-seconds",
                        "0.1",
                        "--max-seconds",
                        "8",
                        "--worker-id",
                        f"live-worker-{index}",
                    ],
                    cwd=ROOT,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                    start_new_session=os.name != "nt",
                )
                for index in range(3)
            ]
            try:
                for _ in range(200):
                    if len(list(marker_dir.glob("*.txt"))) >= 3:
                        break
                    if any(process.poll() is not None for process in processes):
                        break
                    time.sleep(0.05)
                else:
                    self.fail("live multi-worker smoke did not start concurrent jobs")
                if len(list(marker_dir.glob("*.txt"))) < 3:
                    self.fail("scheduler workers exited before claiming concurrent jobs")

                release_file.write_text("go\n", encoding="utf-8")
                for process in processes:
                    process.wait(timeout=20)
                returncodes = [process.returncode for process in processes]
                jobs = [
                    json.loads(
                        (
                            run_dir
                            / "jobs"
                            / f"multi-{index}"
                            / "job.json"
                        ).read_text(encoding="utf-8"),
                    )
                    for index in range(5)
                ]
                markers = sorted(path.name for path in marker_dir.glob("*.txt"))
                artifacts = [
                    (
                        (run_dir / "jobs" / f"multi-{index}" / "raw.log").exists(),
                        (run_dir / "jobs" / f"multi-{index}" / "output.json").exists(),
                    )
                    for index in range(5)
                ]
            finally:
                release_file.write_text("cleanup\n", encoding="utf-8")
                for process in processes:
                    if process.poll() is None:
                        cli.terminate_process_tree(process)
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)

        self.assertEqual(returncodes, [0, 0, 0])
        self.assertEqual([job["status"] for job in jobs], ["succeeded"] * 5)
        self.assertEqual(markers, [f"multi-{index}.txt" for index in range(5)])
        for index, job in enumerate(jobs):
            self.assertEqual(artifacts[index], (True, True))
            self.assertRegex(job["claim_token"], r"^[0-9a-f]{32}$")

    def test_detect_stale_reports_invalid_running_job_instead_of_aborting(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "bad-running",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('bad')"],
                timeout_seconds=30,
                root=ROOT,
            )
            job_path = run_dir / "jobs" / "bad-running" / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["status"] = "running"
            job["started_at"] = None
            job["updated_at"] = None
            job["worker_id"] = "worker-bad"
            write_json(job_path, job)

            report = cli.detect_stale_running_jobs(
                run_dir,
                heartbeat_timeout_seconds=60,
                now="2026-06-22T00:10:00Z",
                root=ROOT,
            )

        self.assertEqual(report["active_jobs"], [])
        self.assertEqual(report["stale_jobs"], [])
        self.assertEqual(report["invalid_jobs"], ["bad-running"])
        self.assertEqual(report["jobs"][0]["classification"], "invalid")
        self.assertTrue(
            any("running job requires started_at" in reason for reason in report["jobs"][0]["reasons"])
        )

    def test_recover_stale_running_job_requires_confirmation_and_requeues_with_audit_artifact(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            original_state = minimal_state()
            write_json(run_dir / "state.json", original_state)
            cli.create_generic_agent_job(
                run_dir,
                "orphaned-running",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('rerun')"],
                timeout_seconds=30,
                root=ROOT,
            )
            job_path = run_dir / "jobs" / "orphaned-running" / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["status"] = "running"
            job["created_at"] = "2026-06-22T00:00:00Z"
            job["started_at"] = "2026-06-22T00:00:00Z"
            job["updated_at"] = "2026-06-22T00:01:00Z"
            job["worker_id"] = "worker-dead"
            write_json(job_path, job)
            lock_dir = write_claim_owner(
                run_dir,
                "orphaned-running",
                worker_id="worker-dead",
            )

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.recover_stale_running_job(
                    run_dir,
                    "orphaned-running",
                    action="requeue",
                    reason="scheduler process crashed during local smoke",
                    heartbeat_timeout_seconds=60,
                    now="2026-06-22T00:10:00Z",
                    root=ROOT,
                )

            recovery = cli.recover_stale_running_job(
                run_dir,
                "orphaned-running",
                action="requeue",
                reason="scheduler process crashed during local smoke",
                heartbeat_timeout_seconds=60,
                now="2026-06-22T00:10:00Z",
                confirm=True,
                root=ROOT,
            )
            saved_job = json.loads(job_path.read_text(encoding="utf-8"))
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            recovery_files = sorted(
                (run_dir / "jobs" / "orphaned-running" / "recovery").glob("*.json")
            )
            event_lines = (
                run_dir / "jobs" / "scheduler" / "events.log"
            ).read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in event_lines]
            lock_exists_after_recovery = lock_dir.exists()

        self.assertIn("--confirm is required", str(raised.exception))
        self.assertEqual(saved_state, original_state)
        self.assertEqual(saved_job["status"], "queued")
        self.assertIsNone(saved_job["started_at"])
        self.assertIsNone(saved_job["completed_at"])
        self.assertIsNone(saved_job["worker_id"])
        self.assertIsNotNone(saved_job["updated_at"])
        self.assertEqual(len(recovery_files), 1)
        self.assertEqual(Path(recovery["path"]), recovery_files[0])
        self.assertEqual(recovery["artifact"]["action"], "requeue")
        self.assertEqual(recovery["artifact"]["previous_job"]["status"], "running")
        self.assertEqual(recovery["artifact"]["new_job"]["status"], "queued")
        self.assertIn("stale_running_job_recovered", [event["event"] for event in events])
        self.assertFalse(lock_exists_after_recovery)

    def test_requeue_recovery_clears_claim_fields(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "claim-recovery",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('recover')"],
                timeout_seconds=30,
                root=ROOT,
            )
            mark_job_running(run_dir, "claim-recovery", worker_id="worker-dead")
            job_path = run_dir / "jobs" / "claim-recovery" / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["claim_token"] = "d" * 32
            job["claim_started_at"] = "2026-06-22T00:00:00Z"
            job["claim_updated_at"] = "2026-06-22T00:01:00Z"
            write_json(job_path, job)
            lock_dir = write_claim_owner(
                run_dir,
                "claim-recovery",
                worker_id="worker-dead",
                claim_token="d" * 32,
            )

            recovery = cli.recover_stale_running_job(
                run_dir,
                "claim-recovery",
                action="requeue",
                reason="clear claim fields",
                heartbeat_timeout_seconds=60,
                now="2026-06-22T00:10:00Z",
                confirm=True,
                root=ROOT,
            )
            saved_job = json.loads(job_path.read_text(encoding="utf-8"))
            lock_exists_after_recovery = lock_dir.exists()

        self.assertIsNone(saved_job["claim_token"])
        self.assertIsNone(saved_job["claim_started_at"])
        self.assertIsNone(saved_job["claim_updated_at"])
        self.assertFalse(lock_exists_after_recovery)
        self.assertTrue(recovery["claim_lock_removed"])

    def test_recovery_does_not_remove_reclaimed_claim_lock_after_job_write(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "reclaimed-recovery",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('recover')"],
                timeout_seconds=30,
                root=ROOT,
            )
            mark_job_running(run_dir, "reclaimed-recovery", worker_id="worker-dead")
            job_path = run_dir / "jobs" / "reclaimed-recovery" / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["claim_token"] = "a" * 32
            job["claim_started_at"] = "2026-06-22T00:00:00Z"
            job["claim_updated_at"] = "2026-06-22T00:01:00Z"
            write_json(job_path, job)
            lock_dir = write_claim_owner(
                run_dir,
                "reclaimed-recovery",
                worker_id="worker-dead",
                claim_token="a" * 32,
            )
            original_write_json_atomic = cli.write_json_atomic

            def replace_claim_after_job_write(path: Path, payload: dict) -> None:
                original_write_json_atomic(path, payload)
                if Path(path) == job_path:
                    cli.remove_claim_lock_dir(lock_dir, job_path.parent)
                    write_claim_owner(
                        run_dir,
                        "reclaimed-recovery",
                        worker_id="worker-new",
                        claim_token="b" * 32,
                    )

            with mock.patch.object(
                cli,
                "write_json_atomic",
                side_effect=replace_claim_after_job_write,
            ):
                recovery = cli.recover_stale_running_job(
                    run_dir,
                    "reclaimed-recovery",
                    action="requeue",
                    reason="reclaimed lock race",
                    heartbeat_timeout_seconds=60,
                    now="2026-06-22T00:10:00Z",
                    confirm=True,
                    root=ROOT,
                )
            owner = json.loads((lock_dir / "owner.json").read_text(encoding="utf-8"))
            saved_job = json.loads(job_path.read_text(encoding="utf-8"))
            lock_exists_after_recovery = lock_dir.exists()

        self.assertEqual(saved_job["status"], "queued")
        self.assertTrue(lock_exists_after_recovery)
        self.assertEqual(owner["worker_id"], "worker-new")
        self.assertEqual(owner["claim_token"], "b" * 32)
        self.assertFalse(recovery["claim_lock_removed"])

    def test_recovery_does_not_overwrite_terminal_job_written_after_assessment(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "terminal-race",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('recover')"],
                timeout_seconds=30,
                root=ROOT,
            )
            mark_job_running(run_dir, "terminal-race", worker_id="worker-dead")
            job_path = run_dir / "jobs" / "terminal-race" / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["claim_token"] = "c" * 32
            job["claim_started_at"] = "2026-06-22T00:00:00Z"
            job["claim_updated_at"] = "2026-06-22T00:01:00Z"
            write_json(job_path, job)
            lock_dir = write_claim_owner(
                run_dir,
                "terminal-race",
                worker_id="worker-dead",
                claim_token="c" * 32,
            )
            original_append_scheduler_event = cli.append_scheduler_event

            def terminalize_after_recovery_event(run_dir_arg, event, payload) -> None:
                original_append_scheduler_event(run_dir_arg, event, payload)
                terminal_job = json.loads(job_path.read_text(encoding="utf-8"))
                terminal_job["status"] = "succeeded"
                terminal_job["completed_at"] = "2026-06-22T00:09:59Z"
                terminal_job["updated_at"] = "2026-06-22T00:09:59Z"
                terminal_job["error_reason"] = None
                write_json(job_path, terminal_job)

            with mock.patch.object(
                cli,
                "append_scheduler_event",
                side_effect=terminalize_after_recovery_event,
            ):
                with self.assertRaises(cli.HarnessCliError) as raised:
                    cli.recover_stale_running_job(
                        run_dir,
                        "terminal-race",
                        action="requeue",
                        reason="terminal write race",
                        heartbeat_timeout_seconds=60,
                        now="2026-06-22T00:10:00Z",
                        confirm=True,
                        root=ROOT,
                    )
            saved_job = json.loads(job_path.read_text(encoding="utf-8"))
            lock_exists_after_rejection = lock_dir.exists()

        self.assertIn("changed during recovery", str(raised.exception))
        self.assertEqual(saved_job["status"], "succeeded")
        self.assertTrue(lock_exists_after_rejection)

    def test_recovery_rejects_fresh_matching_claim_lease(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "fresh-lease-recovery",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('recover')"],
                timeout_seconds=30,
                root=ROOT,
            )
            mark_job_running(run_dir, "fresh-lease-recovery", worker_id="worker-live")
            job_path = run_dir / "jobs" / "fresh-lease-recovery" / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["claim_token"] = "e" * 32
            job["claim_started_at"] = "2026-06-22T00:09:30Z"
            job["claim_updated_at"] = "2026-06-22T00:09:30Z"
            write_json(job_path, job)
            lock_dir = write_claim_owner(
                run_dir,
                "fresh-lease-recovery",
                worker_id="worker-live",
                claimed_at="2026-06-22T00:09:30Z",
                claim_token="e" * 32,
            )

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.recover_stale_running_job(
                    run_dir,
                    "fresh-lease-recovery",
                    action="requeue",
                    reason="must not recover fresh lease",
                    heartbeat_timeout_seconds=60,
                    now="2026-06-22T00:10:00Z",
                    confirm=True,
                    root=ROOT,
                )
            saved_job = json.loads(job_path.read_text(encoding="utf-8"))
            lock_exists_after_rejection = lock_dir.exists()

        self.assertIn("fresh matching claim lease", str(raised.exception))
        self.assertEqual(saved_job["status"], "running")
        self.assertTrue(lock_exists_after_rejection)

    def test_recover_stale_running_job_does_not_mutate_job_when_event_write_fails(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "event-failure",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('fail')"],
                timeout_seconds=30,
                root=ROOT,
            )
            job_path = run_dir / "jobs" / "event-failure" / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["status"] = "running"
            job["created_at"] = "2026-06-22T00:00:00Z"
            job["started_at"] = "2026-06-22T00:00:00Z"
            job["updated_at"] = "2026-06-22T00:01:00Z"
            job["worker_id"] = "worker-dead"
            write_json(job_path, job)
            scheduler_path = run_dir / "jobs" / "scheduler"
            scheduler_path.write_text("not a directory\n", encoding="utf-8")

            with self.assertRaises((cli.HarnessCliError, OSError)):
                cli.recover_stale_running_job(
                    run_dir,
                    "event-failure",
                    action="fail",
                    reason="event path failure repro",
                    heartbeat_timeout_seconds=60,
                    now="2026-06-22T00:10:00Z",
                    confirm=True,
                    root=ROOT,
                )

            saved_job = json.loads(job_path.read_text(encoding="utf-8"))
            recovery_files = sorted(
                (run_dir / "jobs" / "event-failure" / "recovery").glob("*.json")
            )

        self.assertEqual(saved_job["status"], "running")
        self.assertEqual(saved_job["worker_id"], "worker-dead")
        self.assertEqual(len(recovery_files), 1)

    def test_requeue_recovery_requires_conflicting_artifacts_to_be_corrected_first(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "partial-running",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('rerun')"],
                timeout_seconds=30,
                root=ROOT,
            )
            job_path = run_dir / "jobs" / "partial-running" / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["status"] = "running"
            job["created_at"] = "2026-06-22T00:00:00Z"
            job["started_at"] = "2026-06-22T00:00:00Z"
            job["updated_at"] = "2026-06-22T00:01:00Z"
            job["worker_id"] = "worker-dead"
            write_json(job_path, job)
            lock_dir = write_claim_owner(
                run_dir,
                "partial-running",
                worker_id="worker-dead",
            )
            (run_dir / "jobs" / "partial-running" / "raw.log").write_text(
                "partial output from crashed worker\n",
                encoding="utf-8",
            )

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.recover_stale_running_job(
                    run_dir,
                    "partial-running",
                    action="requeue",
                    reason="retry after crash",
                    heartbeat_timeout_seconds=60,
                    now="2026-06-22T00:10:00Z",
                    confirm=True,
                    root=ROOT,
                )
            saved_job = json.loads(job_path.read_text(encoding="utf-8"))
            lock_exists_after_rejection = lock_dir.exists()

        self.assertIn("artifact correction required before requeue", str(raised.exception))
        self.assertEqual(saved_job["status"], "running")
        self.assertEqual(saved_job["worker_id"], "worker-dead")
        self.assertTrue(lock_exists_after_rejection)

    def test_recover_stale_running_job_can_mark_failed_with_audit_artifact(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "failed-running",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('do not rerun')"],
                timeout_seconds=30,
                root=ROOT,
            )
            job_path = run_dir / "jobs" / "failed-running" / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            job["status"] = "running"
            job["created_at"] = "2026-06-22T00:00:00Z"
            job["started_at"] = "2026-06-22T00:00:00Z"
            job["updated_at"] = "2026-06-22T00:01:00Z"
            job["worker_id"] = "worker-dead"
            write_json(job_path, job)

            recovery = cli.recover_stale_running_job(
                run_dir,
                "failed-running",
                action="fail",
                reason="operator determined partial artifact cannot be safely retried",
                heartbeat_timeout_seconds=60,
                now="2026-06-22T00:10:00Z",
                confirm=True,
                root=ROOT,
            )
            saved_job = json.loads(job_path.read_text(encoding="utf-8"))

        self.assertEqual(saved_job["status"], "failed")
        self.assertEqual(saved_job["worker_id"], "worker-dead")
        self.assertIsNotNone(saved_job["completed_at"])
        self.assertIn("stale running recovery", saved_job["error_reason"])
        self.assertEqual(recovery["artifact"]["action"], "fail")
        self.assertEqual(recovery["artifact"]["new_job"]["status"], "failed")

    def test_scheduler_watch_records_failed_job_and_continues(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            success_script = run_dir / "success_agent.py"
            write_agent_script(
                success_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Follow-up job completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "001-fails",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "import sys; sys.exit(7)"],
                timeout_seconds=10,
                root=ROOT,
            )
            cli.create_generic_agent_job(
                run_dir,
                "002-succeeds",
                agent="generic-test-agent",
                command=[sys.executable, str(success_script)],
                timeout_seconds=10,
                root=ROOT,
            )

            summary = cli.scheduler_run_watch(
                run_dir,
                poll_interval_seconds=0,
                max_iterations=1,
                worker_id="failed-job-worker",
                root=ROOT,
                sleep_fn=lambda seconds: None,
            )
            failed_job = json.loads(
                (run_dir / "jobs" / "001-fails" / "job.json").read_text(encoding="utf-8"),
            )
            succeeded_job = json.loads(
                (run_dir / "jobs" / "002-succeeds" / "job.json").read_text(
                    encoding="utf-8",
                ),
            )
            heartbeat = json.loads(
                (run_dir / "jobs" / "scheduler" / "heartbeat.json").read_text(
                    encoding="utf-8",
                ),
            )
            events = [
                json.loads(line)
                for line in (run_dir / "jobs" / "scheduler" / "events.log").read_text(
                    encoding="utf-8",
                ).splitlines()
            ]

        completed_statuses = [
            event["detail"].get("status")
            for event in events
            if event["event"] == "job_completed"
        ]
        self.assertEqual(summary["executed_jobs"], ["001-fails", "002-succeeds"])
        self.assertEqual(summary["stop_reason"], "max_iterations")
        self.assertEqual(failed_job["status"], "failed")
        self.assertEqual(succeeded_job["status"], "succeeded")
        self.assertEqual(heartbeat["status"], "stopped")
        self.assertEqual(completed_statuses, ["failed", "succeeded"])
        self.assertNotIn("worker_failed", [event["event"] for event in events])

    def test_scheduler_watch_stop_waits_for_current_job_and_does_not_claim_next_job(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "stop_aware_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                import time
                from pathlib import Path

                input_path = Path(os.environ["HARNESS_AGENT_INPUT_FILE"])
                output_path = Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"])
                payload = json.loads(input_path.read_text(encoding="utf-8"))
                stop_path = input_path.parents[1] / "scheduler" / "stop.json"
                for _ in range(50):
                    if stop_path.exists():
                        break
                    time.sleep(0.05)
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Stop-aware job completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                output_path.write_text(json.dumps(output, indent=2) + "\\n", encoding="utf-8")
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "001-current",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=10,
                root=ROOT,
            )
            cli.create_generic_agent_job(
                run_dir,
                "002-next",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('must not run')"],
                timeout_seconds=10,
                root=ROOT,
            )
            result: dict[str, object] = {}
            errors: list[BaseException] = []

            def run_worker() -> None:
                try:
                    result["summary"] = cli.scheduler_run_watch(
                        run_dir,
                        poll_interval_seconds=0,
                        max_iterations=5,
                        worker_id="stop-worker",
                        root=ROOT,
                        sleep_fn=lambda seconds: None,
                    )
                except BaseException as exc:
                    errors.append(exc)

            import threading

            worker_thread = threading.Thread(target=run_worker)
            worker_thread.start()
            current_job_path = run_dir / "jobs" / "001-current" / "job.json"
            for _ in range(100):
                current_job = json.loads(current_job_path.read_text(encoding="utf-8"))
                if current_job["status"] == "running":
                    break
                time.sleep(0.05)
            cli.request_scheduler_stop(run_dir, reason="test stop", root=ROOT)
            worker_thread.join(timeout=10)

            if errors:
                raise errors[0]
            current_job = json.loads(current_job_path.read_text(encoding="utf-8"))
            next_job = json.loads(
                (run_dir / "jobs" / "002-next" / "job.json").read_text(encoding="utf-8"),
            )
            heartbeat = json.loads(
                (run_dir / "jobs" / "scheduler" / "heartbeat.json").read_text(encoding="utf-8"),
            )
            events = [
                json.loads(line)
                for line in (run_dir / "jobs" / "scheduler" / "events.log").read_text(
                    encoding="utf-8",
                ).splitlines()
            ]

        self.assertFalse(worker_thread.is_alive())
        self.assertEqual(current_job["status"], "succeeded")
        self.assertEqual(next_job["status"], "queued")
        self.assertEqual(heartbeat["status"], "stopped")
        self.assertEqual(result["summary"]["stop_reason"], "stop_requested")
        self.assertIn("stop_observed", [event["event"] for event in events])

    def test_scheduler_watch_records_invalid_job_warning_and_does_not_claim_valid_jobs(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            state = minimal_state()
            write_json(run_dir / "state.json", state)
            bad_path = run_dir / "jobs" / "000-bad" / "job.json"
            bad_path.parent.mkdir(parents=True, exist_ok=True)
            bad_path.write_text("[]\n", encoding="utf-8")
            cli.create_generic_agent_job(
                run_dir,
                "001-valid",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('must not run')"],
                timeout_seconds=30,
                root=ROOT,
            )

            summary = cli.scheduler_run_watch(
                run_dir,
                poll_interval_seconds=0,
                max_iterations=1,
                worker_id="warning-worker",
                root=ROOT,
                sleep_fn=lambda seconds: None,
            )
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            valid_job = json.loads(
                (run_dir / "jobs" / "001-valid" / "job.json").read_text(encoding="utf-8"),
            )
            events = [
                json.loads(line)
                for line in (run_dir / "jobs" / "scheduler" / "events.log").read_text(
                    encoding="utf-8",
                ).splitlines()
            ]

        self.assertEqual(saved_state, state)
        self.assertEqual(summary["executed_jobs"], [])
        self.assertEqual(summary["stop_reason"], "max_iterations")
        self.assertEqual(valid_job["status"], "queued")
        self.assertIn("invalid_jobs_observed", [event["event"] for event in events])

    def test_scheduler_watch_observes_existing_stop_before_first_poll(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            state = minimal_state()
            write_json(run_dir / "state.json", state)
            cli.request_scheduler_stop(run_dir, reason="pre-start stop", root=ROOT)

            summary = cli.scheduler_run_watch(
                run_dir,
                poll_interval_seconds=0,
                max_iterations=3,
                worker_id="prestop-worker",
                root=ROOT,
                sleep_fn=lambda seconds: None,
            )
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            stop_exists = (run_dir / "jobs" / "scheduler" / "stop.json").exists()
            heartbeat = json.loads(
                (run_dir / "jobs" / "scheduler" / "heartbeat.json").read_text(encoding="utf-8"),
            )
            events = [
                json.loads(line)
                for line in (run_dir / "jobs" / "scheduler" / "events.log").read_text(
                    encoding="utf-8",
                ).splitlines()
            ]

        self.assertEqual(saved_state, state)
        self.assertTrue(stop_exists)
        self.assertEqual(summary["iterations"], 0)
        self.assertEqual(summary["executed_jobs"], [])
        self.assertEqual(summary["stop_reason"], "stop_requested")
        self.assertEqual(heartbeat["status"], "stopped")
        self.assertIn("stop_observed", [event["event"] for event in events])

    def test_start_scheduler_launches_detached_watch_process(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.request_scheduler_stop(run_dir, reason="stale stop", root=ROOT)
            popen_calls = []

            class FakeProcess:
                pid = 43210

            def fake_popen(command, **kwargs):
                popen_calls.append((command, kwargs))
                return FakeProcess()

            with mock.patch("harness.cli.subprocess.Popen", side_effect=fake_popen):
                result = cli.start_scheduler(
                    run_dir,
                    poll_interval_seconds=0.1,
                    max_iterations=3,
                    max_seconds=None,
                    worker_id="detached-worker",
                    root=ROOT,
                )

        command, kwargs = popen_calls[0]
        self.assertEqual(result["worker_id"], "detached-worker")
        self.assertIn(sys.executable, command[0])
        self.assertEqual(command[1:4], ["-m", "harness.cli", "run-scheduler"])
        self.assertEqual(Path(command[4]), run_dir.resolve(strict=False))
        self.assertIn("--watch", command)
        self.assertIn("--worker-id", command)
        self.assertEqual(kwargs["cwd"], ROOT.resolve(strict=False))
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
        self.assertFalse((run_dir / "jobs" / "scheduler" / "stop.json").exists())
        if os.name == "nt":
            expected_creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            expected_creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
            self.assertEqual(kwargs["creationflags"], expected_creationflags)
            self.assertFalse(kwargs["start_new_session"])
        else:
            self.assertEqual(kwargs["creationflags"], 0)
            self.assertTrue(kwargs["start_new_session"])

    def test_stop_scheduler_cli_writes_stop_without_mutating_state(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            state = minimal_state()
            write_json(run_dir / "state.json", state)

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "stop-scheduler",
                    str(run_dir),
                    "--reason",
                    "cli stop",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            stop = json.loads(
                (run_dir / "jobs" / "scheduler" / "stop.json").read_text(
                    encoding="utf-8",
                )
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("stop requested: test-run", result.stdout)
        self.assertEqual(saved_state, state)
        self.assertEqual(stop["reason"], "cli stop")

    def test_aggregate_jobs_classifies_terminal_and_incomplete_jobs_without_mutating_state(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            state = minimal_state()
            write_json(run_dir / "state.json", state)
            agent_script = run_dir / "finding_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "findings",
                    "summary": "Finding agent completed.",
                    "findings": [
                        {
                            "severity": "low",
                            "title": "Sample finding",
                            "evidence": "Synthetic finding for aggregation.",
                            "recommendation": "Record it in aggregation."
                        }
                    ],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": ["Synthetic residual risk."],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                """,
            )
            cli.run_generic_agent(
                run_dir,
                "succeeded-job",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=30,
                root=ROOT,
            )
            cli.create_generic_agent_job(
                run_dir,
                "running-job",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('still running')"],
                timeout_seconds=30,
                root=ROOT,
            )
            running_path = run_dir / "jobs" / "running-job" / "job.json"
            running_job = json.loads(running_path.read_text(encoding="utf-8"))
            running_job["status"] = "running"
            running_job["started_at"] = running_job["created_at"]
            write_json(running_path, running_job)

            aggregation = cli.aggregate_jobs(run_dir, root=ROOT)
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            saved_aggregation = json.loads(
                (run_dir / "jobs" / "aggregation.json").read_text(encoding="utf-8")
            )

        self.assertEqual(saved_state, state)
        self.assertEqual(aggregation, saved_aggregation)
        self.assertEqual(saved_aggregation["consumed_jobs"], ["succeeded-job"])
        self.assertEqual(saved_aggregation["succeeded_jobs"], ["succeeded-job"])
        self.assertEqual(saved_aggregation["incomplete_jobs"], ["running-job"])
        self.assertEqual(saved_aggregation["findings"][0]["job_id"], "succeeded-job")
        self.assertEqual(saved_aggregation["findings"][0]["severity"], "low")
        self.assertIn("Synthetic residual risk.", saved_aggregation["residual_risks"])

    def test_aggregate_jobs_records_missing_or_invalid_terminal_output_as_residual_risk(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "failed-job",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "import sys; sys.exit(7)"],
                timeout_seconds=30,
                root=ROOT,
            )
            cli.execute_generic_agent_job(run_dir, "failed-job", root=ROOT)

            aggregation = cli.aggregate_jobs(run_dir, root=ROOT)

        self.assertEqual(aggregation["failed_jobs"], ["failed-job"])
        self.assertTrue(
            any("failed-job" in risk and "output" in risk for risk in aggregation["residual_risks"]),
            aggregation["residual_risks"],
        )

    def test_aggregate_jobs_aborts_on_invalid_job_record(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            invalid_path = run_dir / "jobs" / "invalid" / "job.json"
            invalid_path.parent.mkdir(parents=True, exist_ok=True)
            invalid_path.write_text("[]\n", encoding="utf-8")

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.aggregate_jobs(run_dir, root=ROOT)

        self.assertIn("job schema error", str(raised.exception))

    def test_aggregate_jobs_aborts_on_semantically_invalid_job_record(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "bad-terminal",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('unused')"],
                timeout_seconds=30,
                root=ROOT,
            )
            bad_path = run_dir / "jobs" / "bad-terminal" / "job.json"
            bad_job = json.loads(bad_path.read_text(encoding="utf-8"))
            bad_job["status"] = "succeeded"
            bad_job["started_at"] = None
            bad_job["completed_at"] = None
            write_json(bad_path, bad_job)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.aggregate_jobs(run_dir, root=ROOT)

            aggregation_exists = (run_dir / "jobs" / "aggregation.json").exists()

        self.assertIn("terminal job requires", str(raised.exception))
        self.assertFalse(aggregation_exists)

    def test_run_generic_agent_creates_job_result_and_log_without_mutating_state(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            state = minimal_state()
            write_json(run_dir / "state.json", state)
            agent_script = run_dir / "fake_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                input_path = Path(os.environ["HARNESS_AGENT_INPUT_FILE"])
                output_path = Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"])
                payload = json.loads(input_path.read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Fake agent completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                output_path.write_text(json.dumps(output, indent=2) + "\\n", encoding="utf-8")
                print("fake agent wrote output")
                """,
            )

            job = cli.run_generic_agent(
                run_dir,
                "generic-001",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=30,
                root=ROOT,
            )
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))

            job_file = run_dir / "jobs" / "generic-001" / "job.json"
            result_file = run_dir / "jobs" / "generic-001" / "output.json"
            raw_log_file = run_dir / "jobs" / "generic-001" / "raw.log"

            state["evidence"] = [
                {"type": "agent-job", "path": str(job_file.relative_to(ROOT))},
                {"type": "agent-result", "path": str(result_file.relative_to(ROOT))},
            ]
            write_json(run_dir / "state.json", state)
            validation = cli.validate_run(run_dir, root=ROOT)
            job_file_exists = job_file.exists()
            result_file_exists = result_file.exists()
            raw_log = raw_log_file.read_text(encoding="utf-8")

        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(saved_state, minimal_state())
        self.assertTrue(job_file_exists)
        self.assertTrue(result_file_exists)
        self.assertIn("fake agent wrote output", raw_log)
        self.assertEqual(validation.errors, [])

    def test_run_generic_agent_marks_failed_when_agent_result_schema_is_invalid(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "invalid_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps({"status": "passed"}) + "\\n",
                    encoding="utf-8",
                )
                """,
            )

            job = cli.run_generic_agent(
                run_dir,
                "generic-002",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=30,
                root=ROOT,
            )

        self.assertEqual(job["status"], "failed")
        self.assertIn("agent-result schema error", job["error_reason"])

    def test_run_generic_agent_marks_failed_when_command_cannot_start(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())

            job = cli.run_generic_agent(
                run_dir,
                "generic-missing-command",
                agent="generic-test-agent",
                command=["definitely-not-a-real-command-for-harness-tests"],
                timeout_seconds=30,
                root=ROOT,
            )
            saved_job = json.loads(
                (run_dir / "jobs" / "generic-missing-command" / "job.json").read_text(
                    encoding="utf-8",
                )
            )

        self.assertEqual(job["status"], "failed")
        self.assertEqual(saved_job["status"], "failed")
        self.assertIsNotNone(saved_job["completed_at"])
        self.assertIn("agent command could not be executed", saved_job["error_reason"])

    def test_run_generic_agent_marks_failed_on_nonzero_exit(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())

            job = cli.run_generic_agent(
                run_dir,
                "generic-nonzero",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "import sys; sys.exit(7)"],
                timeout_seconds=30,
                root=ROOT,
            )

        self.assertEqual(job["status"], "failed")
        self.assertIn("exited with code 7", job["error_reason"])

    def test_run_generic_agent_marks_timeout(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())

            started = time.monotonic()
            job = cli.run_generic_agent(
                run_dir,
                "generic-timeout",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "import time; time.sleep(10)"],
                timeout_seconds=1,
                root=ROOT,
            )
            duration = time.monotonic() - started

        self.assertEqual(job["status"], "timeout")
        self.assertLess(duration, 5)
        self.assertIn("timed out after 1 seconds", job["error_reason"])

    def test_run_generic_agent_rejects_job_id_path_traversal(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.run_generic_agent(
                    run_dir,
                    "../escape",
                    agent="generic-test-agent",
                    command=[sys.executable, "-c", "print('unused')"],
                    timeout_seconds=30,
                    root=ROOT,
                )

        self.assertIn("job_id must be a single safe path segment", str(raised.exception))

    def test_module_entrypoint_runs_generic_agent_command(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "cli_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "CLI fake agent completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                """,
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "run-generic-agent",
                    "--agent",
                    "generic-test-agent",
                    "--timeout-seconds",
                    "30",
                    str(run_dir),
                    "generic-003",
                    "--",
                    sys.executable,
                    str(agent_script),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            job = json.loads((run_dir / "jobs" / "generic-003" / "job.json").read_text(encoding="utf-8"))

        self.assertEqual(job["status"], "succeeded")
        self.assertIn("generic-agent: test-run/generic-003 -> succeeded", result.stdout)

    def test_module_entrypoint_queues_runs_scheduler_and_aggregates(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "cli_scheduler_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "CLI scheduler agent completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                print("cli scheduler agent wrote output")
                """,
            )

            queue_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "queue-generic-agent",
                    str(run_dir),
                    "cli-scheduler-job",
                    "--agent",
                    "generic-test-agent",
                    "--timeout-seconds",
                    "30",
                    "--",
                    sys.executable,
                    str(agent_script),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            scheduler_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "run-scheduler",
                    str(run_dir),
                    "--once",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            aggregate_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "aggregate-jobs",
                    str(run_dir),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            aggregation = json.loads(
                (run_dir / "jobs" / "aggregation.json").read_text(encoding="utf-8")
            )

        self.assertEqual(queue_result.returncode, 0, queue_result.stderr + queue_result.stdout)
        self.assertEqual(scheduler_result.returncode, 0, scheduler_result.stderr + scheduler_result.stdout)
        self.assertEqual(aggregate_result.returncode, 0, aggregate_result.stderr + aggregate_result.stdout)
        self.assertIn("queued generic-agent: test-run/cli-scheduler-job", queue_result.stdout)
        self.assertIn("scheduler: test-run executed=1 skipped=0", scheduler_result.stdout)
        self.assertIn("aggregated jobs: test-run consumed=1 incomplete=0", aggregate_result.stdout)
        self.assertEqual(aggregation["consumed_jobs"], ["cli-scheduler-job"])

    def test_module_entrypoint_queue_accepts_equals_style_options_after_job_id(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "cli_equals_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "CLI equals agent completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                """,
            )

            queue_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "queue-generic-agent",
                    str(run_dir),
                    "cli-equals-job",
                    "--agent=generic-test-agent",
                    "--adapter=custom-cli-agent",
                    "--timeout-seconds=30",
                    "--",
                    sys.executable,
                    str(agent_script),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            scheduler_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "run-scheduler",
                    str(run_dir),
                    "--once",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            job = json.loads(
                (run_dir / "jobs" / "cli-equals-job" / "job.json").read_text(encoding="utf-8")
            )
            input_payload = json.loads(
                (run_dir / "jobs" / "cli-equals-job" / "input.json").read_text(encoding="utf-8")
            )
            output = json.loads(
                (run_dir / "jobs" / "cli-equals-job" / "output.json").read_text(encoding="utf-8")
            )

        self.assertEqual(queue_result.returncode, 0, queue_result.stderr + queue_result.stdout)
        self.assertEqual(scheduler_result.returncode, 0, scheduler_result.stderr + scheduler_result.stdout)
        self.assertEqual(job["agent"], "generic-test-agent")
        self.assertEqual(job["adapter"], "custom-cli-agent")
        self.assertEqual(job["timeout_seconds"], 30)
        self.assertEqual(input_payload["command"], [sys.executable, str(agent_script)])
        self.assertEqual(output["agent"], "generic-test-agent")
        self.assertEqual(output["adapter"], "custom-cli-agent")

    def test_module_entrypoint_queue_rejects_missing_adapter_value_without_creating_job(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "cli_missing_adapter_agent.py"
            write_agent_script(agent_script, "print('must not run')")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "queue-generic-agent",
                    str(run_dir),
                    "cli-missing-adapter",
                    "--agent",
                    "generic-test-agent",
                    "--adapter",
                    "--",
                    sys.executable,
                    str(agent_script),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            job_dir_exists = (run_dir / "jobs" / "cli-missing-adapter").exists()

        self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("--adapter", result.stderr + result.stdout)
        self.assertFalse(job_dir_exists)

    def test_module_entrypoint_queue_rejects_missing_timeout_value_without_creating_job(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "cli_missing_timeout_agent.py"
            write_agent_script(agent_script, "print('must not run')")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "queue-generic-agent",
                    str(run_dir),
                    "cli-missing-timeout",
                    "--agent",
                    "generic-test-agent",
                    "--timeout-seconds",
                    "--",
                    sys.executable,
                    str(agent_script),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            job_dir_exists = (run_dir / "jobs" / "cli-missing-timeout").exists()

        self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("--timeout-seconds", result.stderr + result.stdout)
        self.assertFalse(job_dir_exists)

    def test_module_entrypoint_queue_preserves_agent_side_options_after_separator(self):
        with temporary_run_directory() as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "cli_inner_agent.py"
            write_agent_script(agent_script, "print('queued only')")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "queue-generic-agent",
                    str(run_dir),
                    "cli-inner-agent",
                    "--agent=outer-agent",
                    "--",
                    sys.executable,
                    str(agent_script),
                    "--agent=inner-agent",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            input_payload = json.loads(
                (run_dir / "jobs" / "cli-inner-agent" / "input.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(
            input_payload["command"],
            [sys.executable, str(agent_script), "--agent=inner-agent"],
        )


if __name__ == "__main__":
    unittest.main()
