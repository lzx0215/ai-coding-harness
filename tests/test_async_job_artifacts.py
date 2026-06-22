import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from harness import cli


ROOT = Path(__file__).resolve().parents[1]
PHASE4_RUN = ROOT / "harness" / "runs" / "2026-06-21-phase-4-async-substrate-closure"
PHASE4_LIVE_RUN = ROOT / "harness" / "runs" / "2026-06-21-phase-4-live-generic-agent-smoke"
PHASE5_LIVE_RUN = ROOT / "harness" / "runs" / "2026-06-22-phase-5-live-scheduler-smoke"
JOB_SCHEMA = ROOT / "harness" / "schemas" / "job.schema.json"
AGGREGATION_SCHEMA = ROOT / "harness" / "schemas" / "aggregation.schema.json"
AGENT_RESULT_SCHEMA = ROOT / "harness" / "schemas" / "agent-result.schema.json"


def load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validation_errors(schema_path: Path, payload: dict) -> list:
    return list(Draft202012Validator(load_schema(schema_path)).iter_errors(payload))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class Phase4ClosureRunTest(unittest.TestCase):
    def test_phase4_closure_run_indexes_async_substrate_artifacts(self):
        result = cli.validate_run(PHASE4_RUN, root=ROOT)
        state = json.loads((PHASE4_RUN / "state.json").read_text(encoding="utf-8"))
        evidence_types = {item["type"] for item in state["evidence"]}

        self.assertEqual(result.errors, [])
        self.assertEqual(state["status"], "completed")
        self.assertIn("agent-job", evidence_types)
        self.assertIn("agent-result", evidence_types)
        self.assertIn("aggregation", evidence_types)
        self.assertTrue(PHASE4_RUN.joinpath("jobs", "phase4-substrate-smoke", "job.json").exists())
        self.assertTrue(PHASE4_RUN.joinpath("jobs", "phase4-substrate-smoke", "output.json").exists())
        self.assertTrue(PHASE4_RUN.joinpath("jobs", "aggregation.json").exists())

    def test_phase4_live_run_was_produced_by_run_generic_agent(self):
        result = cli.validate_run(PHASE4_LIVE_RUN, root=ROOT)
        state = json.loads((PHASE4_LIVE_RUN / "state.json").read_text(encoding="utf-8"))
        evidence_types = {item["type"] for item in state["evidence"]}
        raw_log = PHASE4_LIVE_RUN.joinpath(
            "jobs",
            "phase4-live-generic-agent",
            "raw.log",
        ).read_text(encoding="utf-8")

        self.assertEqual(result.errors, [])
        self.assertEqual(state["status"], "completed")
        self.assertIn("agent-job", evidence_types)
        self.assertIn("agent-result", evidence_types)
        self.assertIn("aggregation", evidence_types)
        self.assertTrue(
            PHASE4_LIVE_RUN.joinpath(
                "jobs",
                "phase4-live-generic-agent",
                "input.json",
            ).exists()
        )
        self.assertIn("phase4 live generic agent wrote output", raw_log)

    def test_phase5_live_run_was_produced_by_scheduler_path(self):
        result = cli.validate_run(PHASE5_LIVE_RUN, root=ROOT)
        state = json.loads((PHASE5_LIVE_RUN / "state.json").read_text(encoding="utf-8"))
        evidence_types = {item["type"] for item in state["evidence"]}
        evidence_paths = {item["path"] for item in state["evidence"]}
        raw_log = PHASE5_LIVE_RUN.joinpath(
            "jobs",
            "phase5-live-scheduler-agent",
            "raw.log",
        ).read_text(encoding="utf-8")
        aggregation = json.loads(
            PHASE5_LIVE_RUN.joinpath("jobs", "aggregation.json").read_text(encoding="utf-8")
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(state["status"], "completed")
        self.assertIn("agent-job", evidence_types)
        self.assertIn("agent-result", evidence_types)
        self.assertIn("aggregation", evidence_types)
        self.assertIn(
            "reviews/phase5-code-review/review-decision.json",
            evidence_paths,
        )
        self.assertIn("phase5 live scheduler agent wrote output", raw_log)
        self.assertEqual(aggregation["consumed_jobs"], ["phase5-live-scheduler-agent"])
        self.assertEqual(aggregation["incomplete_jobs"], [])


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


def minimal_agent_result(status: str = "passed") -> dict:
    return {
        "run_id": "test-run",
        "job_id": "claude-review-001",
        "agent": "claude-code",
        "adapter": "claude-review",
        "status": status,
        "summary": "No issues found.",
        "findings": [],
        "evidence": [],
        "not_tested": [],
        "residual_risks": [],
        "generated_at": "2026-06-20T00:02:00Z",
    }


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

    def test_agent_result_schema_accepts_minimal_payload(self):
        self.assertEqual(validation_errors(AGENT_RESULT_SCHEMA, minimal_agent_result()), [])

    def test_agent_result_schema_rejects_unknown_status(self):
        result = minimal_agent_result("silently_completed")

        errors = validation_errors(AGENT_RESULT_SCHEMA, result)

        self.assertTrue(errors)


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

    def test_validate_rejects_terminal_agent_job_without_completed_at(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            job = minimal_job("succeeded")
            job["completed_at"] = None
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
            any("terminal job requires completed_at" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_agent_job_timestamp_order_violation(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            job = minimal_job("succeeded")
            job["completed_at"] = "2026-06-19T23:59:59Z"
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
            any("completed_at must be on or after started_at" in error for error in result.errors),
            result.errors,
        )

    def test_job_timestamp_semantics_requires_created_at(self):
        job = minimal_job("succeeded")
        del job["created_at"]

        errors = cli.validate_job_timestamp_semantics(job)

        self.assertIn("job requires created_at", errors)

    def test_job_timestamp_semantics_rejects_malformed_timestamp(self):
        job = minimal_job("succeeded")
        job["created_at"] = "not-a-date"

        errors = cli.validate_job_timestamp_semantics(job)

        self.assertIn("created_at must be a valid ISO 8601 timestamp", errors)

    def test_job_timestamp_semantics_rejects_naive_timestamp_without_crashing(self):
        job = minimal_job("succeeded")
        job["started_at"] = "2026-06-20T00:00:01"

        errors = cli.validate_job_timestamp_semantics(job)

        self.assertIn("started_at must be a valid ISO 8601 timestamp", errors)

    def test_validate_rejects_agent_job_run_id_mismatch(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            job = minimal_job("succeeded")
            job["run_id"] = "different-run"
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
            any(
                "job run_id different-run does not match state run_id test-run" in error
                for error in result.errors
            ),
            result.errors,
        )

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

    def test_validate_accepts_agent_result_evidence_with_matching_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            result_file = run_dir / "jobs" / "claude-review-001" / "output.json"
            write_json(job_file, minimal_job("succeeded"))
            write_json(result_file, minimal_agent_result())
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "agent-job",
                    "path": str(job_file.relative_to(ROOT)),
                },
                {
                    "type": "agent-result",
                    "path": str(result_file.relative_to(ROOT)),
                },
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.errors, [])

    def test_validate_rejects_invalid_agent_result_schema(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            result_file = run_dir / "jobs" / "claude-review-001" / "output.json"
            write_json(job_file, minimal_job("succeeded"))
            agent_result = minimal_agent_result()
            agent_result["status"] = "done"
            write_json(result_file, agent_result)
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "agent-job",
                    "path": str(job_file.relative_to(ROOT)),
                },
                {
                    "type": "agent-result",
                    "path": str(result_file.relative_to(ROOT)),
                },
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("agent-result schema error" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_agent_result_run_id_mismatch(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            result_file = run_dir / "jobs" / "claude-review-001" / "output.json"
            write_json(job_file, minimal_job("succeeded"))
            agent_result = minimal_agent_result()
            agent_result["run_id"] = "different-run"
            write_json(result_file, agent_result)
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "agent-job",
                    "path": str(job_file.relative_to(ROOT)),
                },
                {
                    "type": "agent-result",
                    "path": str(result_file.relative_to(ROOT)),
                },
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any(
                "agent-result run_id different-run does not match state run_id test-run"
                in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_validate_rejects_agent_result_without_matching_agent_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            result_file = run_dir / "jobs" / "claude-review-001" / "output.json"
            write_json(result_file, minimal_agent_result())
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "agent-result",
                    "path": str(result_file.relative_to(ROOT)),
                },
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any(
                "agent-result job_id claude-review-001 has no matching agent-job evidence"
                in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_validate_rejects_agent_result_path_that_does_not_match_job_output_file(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            result_file = run_dir / "jobs" / "claude-review-001" / "elsewhere.json"
            write_json(job_file, minimal_job("succeeded"))
            write_json(result_file, minimal_agent_result())
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "agent-job",
                    "path": str(job_file.relative_to(ROOT)),
                },
                {
                    "type": "agent-result",
                    "path": str(result_file.relative_to(ROOT)),
                },
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("agent-result path does not match job output_file" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_agent_result_adapter_mismatch(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            result_file = run_dir / "jobs" / "claude-review-001" / "output.json"
            write_json(job_file, minimal_job("succeeded"))
            agent_result = minimal_agent_result()
            agent_result["adapter"] = "different-adapter"
            write_json(result_file, agent_result)
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "agent-job",
                    "path": str(job_file.relative_to(ROOT)),
                },
                {
                    "type": "agent-result",
                    "path": str(result_file.relative_to(ROOT)),
                },
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("agent-result adapter different-adapter does not match job adapter" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_duplicate_agent_job_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            duplicate_file = run_dir / "jobs" / "duplicate" / "job.json"
            write_json(job_file, minimal_job("succeeded"))
            write_json(duplicate_file, minimal_job("succeeded"))
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "agent-job",
                    "path": str(job_file.relative_to(ROOT)),
                },
                {
                    "type": "agent-job",
                    "path": str(duplicate_file.relative_to(ROOT)),
                },
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("duplicate agent-job evidence for job_id claude-review-001" in error for error in result.errors),
            result.errors,
        )

    def test_validate_accepts_aggregation_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            aggregation_file = run_dir / "jobs" / "aggregation.json"
            write_json(job_file, minimal_job("succeeded"))
            write_json(aggregation_file, minimal_aggregation())
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "agent-job",
                    "path": str(job_file.relative_to(ROOT)),
                },
                {
                    "type": "aggregation",
                    "path": str(aggregation_file.relative_to(ROOT)),
                }
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.errors, [])

    def test_validate_aggregation_evidence_does_not_mutate_state_status(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            aggregation_file = run_dir / "jobs" / "aggregation.json"
            write_json(job_file, minimal_job("succeeded"))
            write_json(aggregation_file, minimal_aggregation())
            state = minimal_state(status="verified")
            state["evidence"] = [
                {
                    "type": "agent-job",
                    "path": str(job_file.relative_to(ROOT)),
                },
                {
                    "type": "aggregation",
                    "path": str(aggregation_file.relative_to(ROOT)),
                }
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)
            saved = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(result.errors, [])
        self.assertEqual(saved["status"], "verified")

    def test_validate_accepts_incomplete_aggregation_job_outside_consumed_jobs(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            aggregation_file = run_dir / "jobs" / "aggregation.json"
            aggregation = minimal_aggregation()
            aggregation["incomplete_jobs"] = ["pending-job"]
            write_json(job_file, minimal_job("succeeded"))
            write_json(aggregation_file, aggregation)
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "agent-job",
                    "path": str(job_file.relative_to(ROOT)),
                },
                {
                    "type": "aggregation",
                    "path": str(aggregation_file.relative_to(ROOT)),
                },
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.errors, [])

    def test_validate_rejects_aggregation_run_id_mismatch(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            aggregation_file = run_dir / "jobs" / "aggregation.json"
            aggregation = minimal_aggregation()
            aggregation["run_id"] = "different-run"
            write_json(job_file, minimal_job("succeeded"))
            write_json(aggregation_file, aggregation)
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "agent-job",
                    "path": str(job_file.relative_to(ROOT)),
                },
                {
                    "type": "aggregation",
                    "path": str(aggregation_file.relative_to(ROOT)),
                },
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any(
                "aggregation run_id different-run does not match state run_id test-run"
                in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_validate_rejects_aggregation_consumed_job_without_agent_job_evidence(self):
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

        self.assertTrue(
            any(
                "aggregation consumed job claude-review-001 has no matching agent-job evidence"
                in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_validate_rejects_aggregation_bucket_status_mismatch(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            aggregation_file = run_dir / "jobs" / "aggregation.json"
            aggregation = minimal_aggregation()
            aggregation["succeeded_jobs"] = []
            aggregation["failed_jobs"] = ["claude-review-001"]
            write_json(job_file, minimal_job("succeeded"))
            write_json(aggregation_file, aggregation)
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "agent-job",
                    "path": str(job_file.relative_to(ROOT)),
                },
                {
                    "type": "aggregation",
                    "path": str(aggregation_file.relative_to(ROOT)),
                },
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any(
                "aggregation bucket failed_jobs expects job status failed" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_validate_rejects_incomplete_aggregation_job_with_terminal_agent_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "terminal-job" / "job.json"
            aggregation_file = run_dir / "jobs" / "aggregation.json"
            job = minimal_job("succeeded")
            job["job_id"] = "terminal-job"
            aggregation = minimal_aggregation()
            aggregation["consumed_jobs"] = []
            aggregation["succeeded_jobs"] = []
            aggregation["incomplete_jobs"] = ["terminal-job"]
            write_json(job_file, job)
            write_json(aggregation_file, aggregation)
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "agent-job",
                    "path": str(job_file.relative_to(ROOT)),
                },
                {
                    "type": "aggregation",
                    "path": str(aggregation_file.relative_to(ROOT)),
                },
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any(
                "aggregation incomplete job terminal-job has terminal agent-job status succeeded"
                in error
                for error in result.errors
            ),
            result.errors,
        )

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

    def test_validate_rejects_aggregation_bucket_outside_consumed_jobs(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            aggregation_file = run_dir / "jobs" / "aggregation.json"
            aggregation = minimal_aggregation()
            aggregation["failed_jobs"] = ["not-consumed"]
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
            any("aggregation semantic error" in error for error in result.errors),
            result.errors,
        )
        self.assertTrue(
            any("failed_jobs" in error and "consumed_jobs" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_aggregation_terminal_bucket_conflict(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            aggregation_file = run_dir / "jobs" / "aggregation.json"
            aggregation = minimal_aggregation()
            aggregation["failed_jobs"] = ["claude-review-001"]
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
            any("multiple terminal aggregation buckets" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_aggregation_incomplete_terminal_conflict(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            aggregation_file = run_dir / "jobs" / "aggregation.json"
            aggregation = minimal_aggregation()
            aggregation["incomplete_jobs"] = ["claude-review-001"]
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
            any("both incomplete and terminal" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_consumed_aggregation_job_without_classification(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            aggregation_file = run_dir / "jobs" / "aggregation.json"
            aggregation = minimal_aggregation()
            aggregation["consumed_jobs"] = ["claude-review-001", "claude-review-002"]
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
            any("has no terminal classification" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_duplicate_aggregation_job_ids(self):
        for bucket in cli.AGGREGATION_JOB_BUCKETS:
            with self.subTest(bucket=bucket):
                with tempfile.TemporaryDirectory(dir=ROOT) as raw:
                    run_dir = Path(raw)
                    aggregation_file = run_dir / "jobs" / "aggregation.json"
                    aggregation = minimal_aggregation()
                    aggregation["consumed_jobs"] = ["claude-review-001"]
                    aggregation[bucket] = ["claude-review-001", "claude-review-001"]
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
                    any("duplicate job id" in error for error in result.errors),
                    result.errors,
                )

    def test_validate_does_not_schema_validate_non_aggregation_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            review_output_file = run_dir / "reviews" / "review-output.json"
            aggregation = minimal_aggregation()
            aggregation["recommended_transition"] = "completed"
            write_json(review_output_file, aggregation)
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "review-output",
                    "path": str(review_output_file.relative_to(ROOT)),
                }
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertFalse(
            any("aggregation schema error" in error for error in result.errors),
            result.errors,
        )

    def test_validate_reports_missing_aggregation_path_without_schema_error(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            missing_aggregation_file = run_dir / "jobs" / "missing-aggregation.json"
            state = minimal_state()
            state["evidence"] = [
                {
                    "type": "aggregation",
                    "path": str(missing_aggregation_file.relative_to(ROOT)),
                }
            ]
            write_json(run_dir / "state.json", state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("evidence path does not exist" in error for error in result.errors),
            result.errors,
        )
        self.assertFalse(
            any("aggregation schema error" in error for error in result.errors),
            result.errors,
        )

    def test_validate_does_not_read_aggregation_outside_repository(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            with tempfile.TemporaryDirectory() as outside_raw:
                outside_aggregation = Path(outside_raw) / "aggregation.json"
                aggregation = minimal_aggregation()
                aggregation["recommended_transition"] = "completed"
                write_json(outside_aggregation, aggregation)
                state = minimal_state()
                state["evidence"] = [
                    {
                        "type": "aggregation",
                        "path": str(outside_aggregation),
                    }
                ]
                write_json(run_dir / "state.json", state)

                result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("outside repository" in error for error in result.errors),
            result.errors,
        )
        self.assertFalse(
            any("aggregation schema error" in error for error in result.errors),
            result.errors,
        )

    def test_validate_does_not_read_agent_job_outside_repository(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            with tempfile.TemporaryDirectory() as outside_raw:
                outside_job = Path(outside_raw) / "job.json"
                write_json(outside_job, minimal_job("running"))
                state = minimal_state()
                state["evidence"] = [
                    {
                        "type": "agent-job",
                        "path": str(outside_job),
                    }
                ]
                write_json(run_dir / "state.json", state)

                result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("outside repository" in error for error in result.errors),
            result.errors,
        )
        self.assertFalse(
            any("non-terminal job cannot be consumed" in error for error in result.errors),
            result.errors,
        )

    def test_validate_does_not_read_agent_job_when_any_candidate_escapes_repository(self):
        proof_job = ROOT / "proof-job.json"
        try:
            write_json(proof_job, minimal_job("running"))
            with tempfile.TemporaryDirectory(dir=ROOT) as raw:
                run_dir = Path(raw)
                state = minimal_state()
                state["evidence"] = [
                    {
                        "type": "agent-job",
                        "path": "../proof-job.json",
                    }
                ]
                write_json(run_dir / "state.json", state)

                result = cli.validate_run(run_dir, root=ROOT)
        finally:
            proof_job.unlink(missing_ok=True)

        self.assertTrue(
            any("outside repository" in error for error in result.errors),
            result.errors,
        )
        self.assertFalse(
            any("non-terminal job cannot be consumed" in error for error in result.errors),
            result.errors,
        )

    def test_validate_reports_non_object_agent_job_schema_error(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            job_file = run_dir / "jobs" / "claude-review-001" / "job.json"
            job_file.parent.mkdir(parents=True, exist_ok=True)
            job_file.write_text("[]\n", encoding="utf-8")
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
            any("job schema error at <root>" in error for error in result.errors),
            result.errors,
        )


if __name__ == "__main__":
    unittest.main()
