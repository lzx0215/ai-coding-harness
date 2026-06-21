import json
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
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
        for field, value in (("run_id", "other-run"), ("job_id", "other-job")):
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

        self.assertIn("job_id escapes jobs directory", str(raised.exception))

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


if __name__ == "__main__":
    unittest.main()
