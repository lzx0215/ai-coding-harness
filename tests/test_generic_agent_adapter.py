import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest import mock
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


class GenericCliAgentOrchestrationTest(unittest.TestCase):
    def test_create_generic_agent_job_writes_queued_artifacts_without_mutating_state(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
                with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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

    def test_execute_generic_agent_job_rejects_preexisting_output_before_claim(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
                with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
                with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
                with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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

    def test_scheduler_run_once_executes_queued_jobs_in_order_and_continues_after_failed_terminal_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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

    def test_scheduler_run_once_aborts_on_invalid_job_record_before_executing_any_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
                with tempfile.TemporaryDirectory(dir=ROOT) as raw:
                    run_dir = Path(raw)
                    write_json(run_dir / "state.json", minimal_state())

                    with self.assertRaises(cli.HarnessCliError) as raised:
                        cli.scheduler_run_watch(run_dir, root=ROOT, **kwargs)

                    self.assertIn(expected_error, str(raised.exception))
                    self.assertFalse((run_dir / "jobs" / "scheduler").exists())

    def test_scheduler_watch_stops_when_max_seconds_elapsed(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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

    def test_scheduler_watch_stop_waits_for_current_job_and_does_not_claim_next_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            invalid_path = run_dir / "jobs" / "invalid" / "job.json"
            invalid_path.parent.mkdir(parents=True, exist_ok=True)
            invalid_path.write_text("[]\n", encoding="utf-8")

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.aggregate_jobs(run_dir, root=ROOT)

        self.assertIn("job schema error", str(raised.exception))

    def test_aggregate_jobs_aborts_on_semantically_invalid_job_record(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
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
