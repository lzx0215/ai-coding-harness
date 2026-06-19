import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import cli


ROOT = Path(__file__).resolve().parents[1]


def minimal_state(status: str = "draft") -> dict:
    return {
        "run_id": "test-run",
        "harness_version": "0.1.0",
        "state_schema_version": "0.1.0",
        "status": status,
        "track": "Fast",
        "current_workflow": "fast-doc-change",
        "owner": "codex",
        "base_commit": "HEAD",
        "created_at": "2026-06-19T00:00:00Z",
        "updated_at": "2026-06-19T00:00:00Z",
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


def evidence_entry(run_dir: Path, evidence_type: str) -> dict:
    path = run_dir / f"{evidence_type}.md"
    path.write_text(f"# {evidence_type}\n", encoding="utf-8")
    return {
        "type": evidence_type,
        "path": str(path.relative_to(ROOT)),
        "description": f"{evidence_type} evidence.",
    }


def state_for_workflow(
    *,
    status: str,
    track: str,
    workflow: str,
    evidence_types: list[str],
    run_dir: Path,
) -> dict:
    state = minimal_state(status=status)
    state["track"] = track
    state["current_workflow"] = workflow
    state["evidence"] = [
        evidence_entry(run_dir, evidence_type)
        for evidence_type in evidence_types
    ]
    return state


def historical_run_dirs() -> list[Path]:
    return sorted(
        path for path in (ROOT / "harness" / "runs").iterdir()
        if path.is_dir()
    )


class HarnessCliTest(unittest.TestCase):
    def test_validate_accepts_example_run(self):
        result = cli.validate_run(
            ROOT / "harness" / "runs" / "example-fast-doc-change",
            root=ROOT,
        )

        self.assertEqual(result.errors, [])

    def test_validate_accepts_all_existing_run_directories(self):
        errors_by_run = {}
        for run_dir in historical_run_dirs():
            result = cli.validate_run(run_dir, root=ROOT)
            if result.errors:
                errors_by_run[str(run_dir.relative_to(ROOT))] = result.errors

        self.assertEqual(errors_by_run, {})

    def test_evidence_type_vocabulary_matches_phase_1_contract(self):
        self.assertEqual(
            cli.EVIDENCE_TYPES,
            frozenset(
                {
                    "task",
                    "triage",
                    "plan",
                    "design-spec",
                    "implementation-plan",
                    "diff",
                    "changed-files",
                    "diff-meta",
                    "verification",
                    "review-input",
                    "review-output",
                    "review-evidence",
                    "review-raw-log",
                    "review",
                    "review-waiver",
                    "risk-acceptance",
                    "handoff",
                }
            ),
        )

    def test_validate_rejects_unknown_evidence_type(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="verified")
            state["evidence"] = [
                {
                    "type": "invented-evidence",
                    "path": "README.md",
                    "description": "Uses an unsupported evidence type.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("unknown evidence type" in error for error in result.errors),
            result.errors,
        )

    def test_validate_reports_null_evidence_as_schema_error(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="verified")
            state["evidence"] = None
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("schema error at evidence" in error for error in result.errors),
            result.errors,
        )

    def test_validate_reports_non_object_evidence_item_as_schema_error(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="verified")
            state["evidence"] = ["not-an-object"]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("schema error at evidence.0" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_missing_evidence_path(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="verified")
            state["evidence"] = [
                {
                    "type": "verification",
                    "path": "harness/runs/test-run/missing-verification.md",
                    "description": "Missing evidence file.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("evidence path does not exist" in error for error in result.errors),
            result.errors,
        )

    def test_validate_accepts_root_relative_evidence_path_inside_repository(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw) / "run"
            state = minimal_state(status="verified")
            state["evidence"] = [
                {
                    "type": "verification",
                    "path": "README.md",
                    "description": "Repository-level evidence file.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.errors, [])

    def test_validate_rejects_evidence_path_outside_repository(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw) / "run"
            with tempfile.TemporaryDirectory() as external_raw:
                outside_evidence = Path(external_raw) / "outside.md"
                outside_evidence.write_text("outside evidence\n", encoding="utf-8")
                state = minimal_state(status="verified")
                state["evidence"] = [
                    {
                        "type": "verification",
                        "path": str(outside_evidence),
                        "description": "Escapes the repository.",
                    }
                ]
                write_state(run_dir, state)

                result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("outside repository" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_relative_evidence_path_traversal_outside_repository(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw) / "run"
            state = minimal_state(status="verified")
            state["evidence"] = [
                {
                    "type": "verification",
                    "path": "../outside.md",
                    "description": "Traverses outside the repository.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("outside repository" in error for error in result.errors),
            result.errors,
        )

    def test_validate_accepts_bom_prefixed_state_json(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "state.json").write_text(
                "\ufeff" + json.dumps(minimal_state()),
                encoding="utf-8",
            )

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.errors, [])

    def test_validate_reports_non_utf8_state_json_as_error(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "state.json").write_bytes(b"\xff\xfe\x00")

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("invalid state encoding" in error for error in result.errors),
            result.errors,
        )

    def test_advance_allows_codex_normal_transition_and_updates_timestamp(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="draft")
            write_state(run_dir, state)

            advanced = cli.advance_run(run_dir, "triaged", actor="codex", root=ROOT)

            saved = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(advanced["status"], "triaged")
        self.assertEqual(saved["status"], "triaged")
        self.assertNotEqual(saved["updated_at"], "2026-06-19T00:00:00Z")

    def test_advance_does_not_write_candidate_when_validation_fails(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="draft")
            write_state(run_dir, state)

            with mock.patch.object(cli, "utc_now", return_value="not-a-date"):
                with self.assertRaises(cli.HarnessCliError):
                    cli.advance_run(run_dir, "triaged", actor="codex", root=ROOT)

            saved = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(saved["status"], "draft")
        self.assertEqual(saved["updated_at"], "2026-06-19T00:00:00Z")

    def test_advance_keeps_original_state_when_atomic_replace_fails(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_state(run_dir, minimal_state(status="draft"))

            with mock.patch.object(Path, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(cli.HarnessCliError):
                    cli.advance_run(run_dir, "triaged", actor="codex", root=ROOT)

            saved = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(saved["status"], "draft")
        self.assertEqual(saved["updated_at"], "2026-06-19T00:00:00Z")

    def test_advance_reports_state_read_error_after_validation(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="draft")
            write_state(run_dir, state)
            schema = cli.load_json(ROOT / "harness" / "schemas" / "state.schema.json")
            encoding_error = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")

            with mock.patch.object(
                cli,
                "load_json",
                side_effect=[state, schema, encoding_error],
            ):
                with self.assertRaises(cli.HarnessCliError) as raised:
                    cli.advance_run(run_dir, "triaged", actor="codex", root=ROOT)

        self.assertIn("cannot read state file", str(raised.exception))

    def test_atomic_write_cleans_temp_file_when_serialization_fails(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            run_dir.mkdir(parents=True, exist_ok=True)
            state_file = run_dir / "state.json"

            with mock.patch.object(cli.json, "dumps", side_effect=TypeError("boom")):
                with self.assertRaises(TypeError):
                    cli.write_json_atomic(state_file, minimal_state(status="draft"))

            temp_files = list(run_dir.glob(".state.json.*.tmp"))

        self.assertEqual(temp_files, [])

    def test_advance_rejects_invalid_transition(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_state(run_dir, minimal_state(status="completed"))

            with self.assertRaises(cli.HarnessCliError):
                cli.advance_run(run_dir, "planned", actor="codex", root=ROOT)

    def test_advance_rejects_external_actor(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_state(run_dir, minimal_state(status="draft"))

            with self.assertRaises(cli.HarnessCliError):
                cli.advance_run(run_dir, "triaged", actor="claude-code", root=ROOT)

    def test_advance_allows_fast_completion_without_review_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = state_for_workflow(
                status="reviewed",
                track="Fast",
                workflow="fast-doc-change",
                evidence_types=["verification", "handoff"],
                run_dir=run_dir,
            )
            write_state(run_dir, state)

            advanced = cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertEqual(advanced["status"], "completed")

    def test_advance_allows_standard_completion_with_review_handling(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = state_for_workflow(
                status="reviewed",
                track="Standard",
                workflow="standard-doc-system-change",
                evidence_types=["verification", "handoff", "review"],
                run_dir=run_dir,
            )
            write_state(run_dir, state)

            advanced = cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertEqual(advanced["status"], "completed")

    def test_advance_rejects_standard_completion_without_verification(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = state_for_workflow(
                status="reviewed",
                track="Standard",
                workflow="standard-doc-system-change",
                evidence_types=["handoff", "review"],
                run_dir=run_dir,
            )
            write_state(run_dir, state)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertIn("missing completion evidence type: verification", str(raised.exception))

    def test_advance_rejects_standard_completion_without_handoff(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = state_for_workflow(
                status="reviewed",
                track="Standard",
                workflow="standard-doc-system-change",
                evidence_types=["verification", "review"],
                run_dir=run_dir,
            )
            write_state(run_dir, state)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertIn("missing completion evidence type: handoff", str(raised.exception))

    def test_advance_rejects_standard_completion_without_review_handling(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = state_for_workflow(
                status="reviewed",
                track="Standard",
                workflow="standard-doc-system-change",
                evidence_types=["verification", "handoff"],
                run_dir=run_dir,
            )
            write_state(run_dir, state)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertIn(
            "missing completion evidence type: one of review, review-evidence, review-waiver",
            str(raised.exception),
        )

    def test_advance_allows_risk_accepted_completion_with_risk_acceptance(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = state_for_workflow(
                status="external_review_unavailable",
                track="Standard",
                workflow="standard-doc-system-change",
                evidence_types=["verification", "handoff", "review", "risk-acceptance"],
                run_dir=run_dir,
            )
            write_state(run_dir, state)

            risk_state = cli.advance_run(
                run_dir,
                "risk_accepted",
                actor="codex",
                root=ROOT,
            )
            completed = cli.advance_run(
                run_dir,
                "completed",
                actor="codex",
                root=ROOT,
            )

        self.assertEqual(risk_state["status"], "risk_accepted")
        self.assertEqual(completed["status"], "completed")

    def test_advance_rejects_risk_accepted_completion_without_risk_acceptance(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = state_for_workflow(
                status="risk_accepted",
                track="Standard",
                workflow="standard-doc-system-change",
                evidence_types=["verification", "handoff", "review"],
                run_dir=run_dir,
            )
            write_state(run_dir, state)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertIn("missing completion evidence type: risk-acceptance", str(raised.exception))

    def test_advance_does_not_require_completion_evidence_for_intermediate_transition(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="planned")
            state["track"] = "Standard"
            state["current_workflow"] = "standard-doc-system-change"
            write_state(run_dir, state)

            advanced = cli.advance_run(run_dir, "in_progress", actor="codex", root=ROOT)

        self.assertEqual(advanced["status"], "in_progress")

    def test_module_entrypoint_validates_run_from_command_line(self):
        run_dir = ROOT / "harness" / "runs" / "example-fast-doc-change"

        result = subprocess.run(
            [sys.executable, "-m", "harness.cli", "validate", str(run_dir)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(f"valid: {run_dir}", result.stdout)

    def test_module_entrypoint_advances_run_from_command_line(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_state(run_dir, minimal_state(status="draft"))

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "advance",
                    str(run_dir),
                    "triaged",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            saved = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(saved["status"], "triaged")
        self.assertIn("advanced: test-run -> triaged", result.stdout)


if __name__ == "__main__":
    unittest.main()
