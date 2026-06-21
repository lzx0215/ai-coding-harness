import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import cli, readiness


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


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def review_decision_payload(
    *,
    disposition: str = "passed",
    recommended_status: str = "reviewed",
    source_evidence: list[dict] | None = None,
    severity_counts: dict[str, int] | None = None,
    run_id: str = "test-run",
) -> dict:
    return {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "generated_at": "2026-06-20T00:00:00Z",
        "disposition": disposition,
        "recommended_status": recommended_status,
        "decision_owner": "codex",
        "source_evidence": source_evidence if source_evidence is not None else [],
        "severity_counts": severity_counts
        if severity_counts is not None
        else {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
        },
        "resolved_findings": [],
        "accepted_risks": [],
        "not_tested": [],
        "residual_risks": [],
    }


def indexed_review_decision(path: str = "reviews/review-decision.json") -> dict:
    return {
        "type": "review-evidence",
        "path": path,
        "description": "Review decision artifact.",
    }


def indexed_review_output(path: str = "reviews/claude-review.json") -> dict:
    return {
        "type": "review-output",
        "path": path,
        "description": "Claude review output.",
    }


def evidence_entry(run_dir: Path, evidence_type: str) -> dict:
    path = run_dir / f"{evidence_type}.md"
    if evidence_type == "handoff":
        # Phase 3 requires handoff closure frontmatter before a run may
        # advance to completed. Tests that reach completion index this
        # closure-valid handoff artifact.
        path.write_text(
            """---
run_id: test-run
schema_version: 0.1.0
changed:
  - "Test change."
verified:
  - "Test verification."
not_verified: []
residual_risks: []
next_step: "Next step."
memory_update: none
memory_files: []
---

# handoff
""",
            encoding="utf-8",
        )
    else:
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

    def test_evidence_type_vocabulary_matches_phase_4_contract(self):
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
                    "agent-job",
                    "agent-result",
                    "aggregation",
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

    def test_validate_reports_non_object_state_as_schema_error(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "state.json").write_text("[]\n", encoding="utf-8")

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("schema error at <root>" in error for error in result.errors),
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

    def test_packaged_module_discovers_repository_root_from_absolute_run_dir(self):
        with tempfile.TemporaryDirectory() as raw:
            temp_dir = Path(raw)
            fake_site_packages = temp_dir / "site-packages"
            shutil.copytree(
                ROOT / "harness",
                fake_site_packages / "harness",
                ignore=shutil.ignore_patterns("runs", "__pycache__"),
            )
            env = os.environ.copy()
            env["PYTHONPATH"] = str(fake_site_packages)
            run_dir = ROOT / "harness" / "runs" / "example-fast-doc-change"

            result = subprocess.run(
                [sys.executable, "-m", "harness.cli", "validate", str(run_dir)],
                cwd=temp_dir,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(f"valid: {run_dir}", result.stdout)

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

    def test_advance_allows_standard_unavailable_review_to_risk_accepted(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="external_review_unavailable")
            state["track"] = "Standard"
            state["current_workflow"] = "standard-doc-system-change"
            write_state(run_dir, state)

            advanced = cli.advance_run(
                run_dir,
                "risk_accepted",
                actor="codex",
                root=ROOT,
            )

        self.assertEqual(advanced["status"], "risk_accepted")

    def test_advance_rejects_strict_unavailable_review_to_risk_accepted(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="external_review_unavailable")
            state["track"] = "Strict"
            state["current_workflow"] = "strict-risk-change"
            write_state(run_dir, state)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(
                    run_dir,
                    "risk_accepted",
                    actor="codex",
                    root=ROOT,
                )

        self.assertIn(
            "strict unavailable review requires needs_user_decision",
            str(raised.exception),
        )

    def test_advance_allows_strict_unavailable_review_to_needs_user_decision(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="external_review_unavailable")
            state["track"] = "Strict"
            state["current_workflow"] = "strict-risk-change"
            write_state(run_dir, state)

            advanced = cli.advance_run(
                run_dir,
                "needs_user_decision",
                actor="codex",
                root=ROOT,
            )

        self.assertEqual(advanced["status"], "needs_user_decision")

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

    def test_check_ready_reports_warnings_without_mutating_state(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_state(run_dir, minimal_state(status="draft"))
            before = (run_dir / "state.json").read_text(encoding="utf-8")

            result = subprocess.run(
                [sys.executable, "-m", "harness.cli", "check-ready", str(run_dir)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            after = (run_dir / "state.json").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(before, after)
        self.assertIn("missing run document: task.md", result.stdout)

    def test_check_ready_returns_zero_when_no_warnings(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="draft")
            state["track"] = "Standard"
            state["current_workflow"] = "standard-doc-system-change"
            write_state(run_dir, state)
            before = (run_dir / "state.json").read_text(encoding="utf-8")
            documents = {
                "task.md": """---
run_id: test-run
schema_version: 0.1.0
track: Standard
workflow: standard-doc-system-change
owner: codex
requested_outcome: "Document behavior."
scope: []
non_goals: []
constraints: []
---

# task.md
""",
                "triage.md": """---
run_id: test-run
schema_version: 0.1.0
track: Standard
workflow: standard-doc-system-change
review_required: true
strict_triggers: []
risk_reasons: []
verification_required: []
---

# triage.md
""",
                "plan.md": """---
run_id: test-run
schema_version: 0.1.0
workflow: standard-doc-system-change
acceptance: []
verification: []
review_plan: []
constraints: []
recovery_strategy: null
residual_risk_owner: null
---

# plan.md
""",
                "handoff.md": """---
run_id: test-run
schema_version: 0.1.0
changed: []
verified: []
not_verified: []
residual_risks: []
next_step: ""
memory_update: none
memory_files: []
---

# handoff.md
""",
            }
            for name, text in documents.items():
                (run_dir / name).write_text(
                    text,
                    encoding="utf-8",
                )

            result = subprocess.run(
                [sys.executable, "-m", "harness.cli", "check-ready", str(run_dir)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            after = (run_dir / "state.json").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(before, after)
        self.assertIn("ready: no readiness warnings", result.stdout)

    def test_index_evidence_appends_valid_evidence_without_advancing_state(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_state(run_dir, minimal_state(status="draft"))
            evidence_path = run_dir / "task.md"
            evidence_path.write_text("# Task\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "index-evidence",
                    str(run_dir),
                    "task",
                    "task.md",
                    "--description",
                    "Task definition.",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            saved = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(saved["status"], "draft")
        self.assertNotEqual(saved["updated_at"], "2026-06-19T00:00:00Z")
        self.assertEqual(
            saved["evidence"],
            [
                {
                    "type": "task",
                    "path": "task.md",
                    "description": "Task definition.",
                }
            ],
        )

    def test_index_evidence_rejects_unknown_type_without_writing(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_state(run_dir, minimal_state(status="draft"))
            (run_dir / "note.md").write_text("# Note\n", encoding="utf-8")
            before = (run_dir / "state.json").read_text(encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "index-evidence",
                    str(run_dir),
                    "invented-evidence",
                    "note.md",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            after = (run_dir / "state.json").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(before, after)
        self.assertIn("unknown evidence type", result.stdout)

    def test_index_evidence_rejects_missing_path_without_writing(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_state(run_dir, minimal_state(status="draft"))
            before = (run_dir / "state.json").read_text(encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "index-evidence",
                    str(run_dir),
                    "task",
                    "missing.md",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            after = (run_dir / "state.json").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(before, after)
        self.assertIn("evidence path does not exist", result.stdout)

    def test_index_evidence_rejects_unsafe_path_without_writing(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw) / "run"
            write_state(run_dir, minimal_state(status="draft"))
            before = (run_dir / "state.json").read_bytes()

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "index-evidence",
                    str(run_dir),
                    "task",
                    "../outside.md",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            after = (run_dir / "state.json").read_bytes()

        self.assertEqual(result.returncode, 1)
        self.assertEqual(before, after)
        self.assertIn("outside repository", result.stdout)

    def test_init_run_creates_draft_run_with_phase2_documents(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            parent = Path(raw)
            run_dir = parent / "phase2-created-run"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "init-run",
                    str(run_dir),
                    "--run-id",
                    "phase2-created-run",
                    "--track",
                    "Standard",
                    "--workflow",
                    "standard-doc-system-change",
                    "--base-commit",
                    "HEAD",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            validation = cli.validate_run(run_dir, root=ROOT)
            readiness_report = readiness.check_run_readiness(run_dir, state)
            documents_exist = {
                name: (run_dir / name).exists()
                for name in ("task.md", "triage.md", "plan.md", "handoff.md")
            }

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(validation.errors, [])
        self.assertEqual(readiness_report.warnings, [])
        self.assertEqual(state["status"], "draft")
        self.assertEqual(state["run_id"], "phase2-created-run")
        self.assertEqual(state["track"], "Standard")
        self.assertEqual(state["current_workflow"], "standard-doc-system-change")
        self.assertEqual(
            [entry["type"] for entry in state["evidence"]],
            ["task", "triage", "plan"],
        )
        self.assertTrue(documents_exist["task.md"])
        self.assertTrue(documents_exist["triage.md"])
        self.assertTrue(documents_exist["plan.md"])
        self.assertTrue(documents_exist["handoff.md"])

    def test_init_run_refuses_existing_directory(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw) / "existing"
            run_dir.mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "init-run",
                    str(run_dir),
                    "--run-id",
                    "existing",
                    "--track",
                    "Fast",
                    "--workflow",
                    "fast-doc-change",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("run directory already exists", result.stdout)

    def test_init_run_rejects_invalid_track_workflow_without_leftover_directory(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw) / "invalid-pairing"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "init-run",
                    str(run_dir),
                    "--run-id",
                    "invalid-pairing",
                    "--track",
                    "Fast",
                    "--workflow",
                    "standard-doc-system-change",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            exists_after = run_dir.exists()

        self.assertEqual(result.returncode, 1)
        self.assertFalse(exists_after)
        self.assertIn("schema error at track", result.stdout)

    def test_init_run_prevalidates_static_evidence_before_writing(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw) / "invalid-evidence"

            with mock.patch.object(cli, "EVIDENCE_TYPES", cli.EVIDENCE_TYPES - {"task"}):
                with mock.patch.object(
                    cli,
                    "render_template",
                    side_effect=AssertionError("template rendering should not start"),
                ):
                    with self.assertRaises(cli.HarnessCliError) as raised:
                        cli.init_run(
                            run_dir,
                            run_id="invalid-evidence",
                            track="Standard",
                            workflow="standard-doc-system-change",
                            base_commit="HEAD",
                            root=ROOT,
                        )

            exists_after = run_dir.exists()

        self.assertFalse(exists_after)
        self.assertIn("unknown evidence type", str(raised.exception))

    def test_init_run_cleans_created_directory_when_final_validation_fails(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            parent = Path(raw)
            run_dir = parent / "final-validation-fails"
            failed_validation = cli.ValidationResult(run_dir, ["forced final validation failure"])

            with mock.patch.object(cli, "validate_run", return_value=failed_validation):
                with self.assertRaises(cli.HarnessCliError) as raised:
                    cli.init_run(
                        run_dir,
                        run_id="final-validation-fails",
                        track="Standard",
                        workflow="standard-doc-system-change",
                        base_commit="HEAD",
                        root=ROOT,
                    )

            parent_exists_after = parent.exists()
            run_exists_after = run_dir.exists()

        self.assertTrue(parent_exists_after)
        self.assertFalse(run_exists_after)
        self.assertIn("forced final validation failure", str(raised.exception))

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

    def test_validate_accepts_indexed_review_decision_as_review_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            # Make the referenced source_evidence path indexable (it exists).
            (reviews_dir / "claude-review.json").write_text(
                json.dumps({"status": "passed"}),
                encoding="utf-8",
            )
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "passed",
                        "recommended_status": "reviewed",
                        "decision_owner": "codex",
                        "source_evidence": [
                            {"type": "review-output", "path": "reviews/claude-review.json"}
                        ],
                        "severity_counts": {
                            "critical": 0,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": [],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.errors, [], result.errors)

    def test_validate_rejects_reviewed_decision_without_source_evidence(self):
        required_source_dispositions = [
            ("passed", "reviewed"),
            ("findings-triaged", "reviewed"),
            ("waived", "reviewed"),
            ("risk-accepted", "risk_accepted"),
            ("blocked", "review_blocked"),
        ]
        for disposition, recommended_status in required_source_dispositions:
            with self.subTest(disposition=disposition):
                with tempfile.TemporaryDirectory(dir=ROOT) as raw:
                    run_dir = Path(raw)
                    decision_path = run_dir / "reviews" / "review-decision.json"
                    decision = review_decision_payload(
                        disposition=disposition,
                        recommended_status=recommended_status,
                    )
                    if disposition == "waived":
                        (run_dir / "review-waiver.md").write_text(
                            "# Review Waiver\n",
                            encoding="utf-8",
                        )
                    if disposition == "risk-accepted":
                        (run_dir / "risk-acceptance.md").write_text(
                            "# Risk Acceptance\n",
                            encoding="utf-8",
                        )
                    write_json(decision_path, decision)
                    state = minimal_state(status="reviewing")
                    state["evidence"] = [indexed_review_decision()]
                    if disposition == "waived":
                        state["evidence"].append(
                            {
                                "type": "review-waiver",
                                "path": "review-waiver.md",
                                "description": "Review waiver evidence.",
                            }
                        )
                    if disposition == "risk-accepted":
                        state["evidence"].append(
                            {
                                "type": "risk-acceptance",
                                "path": "risk-acceptance.md",
                                "description": "Risk acceptance evidence.",
                            }
                        )
                    write_state(run_dir, state)

                    result = cli.validate_run(run_dir, root=ROOT)

                self.assertTrue(
                    any("requires non-empty source_evidence" in error for error in result.errors),
                    result.errors,
                )

    def test_validate_allows_process_outcome_decision_without_source_evidence(self):
        allowed_empty_source = [
            ("unavailable", "external_review_unavailable"),
            ("process-failed", "review_failed"),
            ("process-failed", "review_timeout"),
            ("process-failed", "review_schema_invalid"),
        ]
        for disposition, recommended_status in allowed_empty_source:
            with self.subTest(disposition=disposition, recommended_status=recommended_status):
                with tempfile.TemporaryDirectory(dir=ROOT) as raw:
                    run_dir = Path(raw)
                    decision_path = run_dir / "reviews" / "review-decision.json"
                    write_json(
                        decision_path,
                        review_decision_payload(
                            disposition=disposition,
                            recommended_status=recommended_status,
                        ),
                    )
                    state = minimal_state(status="reviewing")
                    state["evidence"] = [indexed_review_decision()]
                    write_state(run_dir, state)

                    result = cli.validate_run(run_dir, root=ROOT)

                self.assertEqual(result.errors, [], result.errors)

    def test_validate_rejects_duplicate_indexed_review_decision_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            source_path = run_dir / "reviews" / "claude-review.json"
            write_json(source_path, {"status": "passed"})
            source_evidence = [{"type": "review-output", "path": "reviews/claude-review.json"}]
            write_json(
                run_dir / "reviews" / "review-decision.json",
                review_decision_payload(source_evidence=source_evidence),
            )
            write_json(
                run_dir / "second" / "review-decision.json",
                review_decision_payload(source_evidence=source_evidence),
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                indexed_review_decision("reviews/review-decision.json"),
                indexed_review_decision("second/review-decision.json"),
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any(
                "evidence[1]: duplicate review-decision evidence" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_validate_rejects_review_decision_severity_count_mismatch(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            review_output_path = run_dir / "reviews" / "claude-review.json"
            write_json(
                review_output_path,
                {
                    "findings": [
                        {"severity": "low", "title": "First"},
                        {"severity": "low", "title": "Second"},
                        {"severity": "info", "title": "Third"},
                    ]
                },
            )
            decision_path = run_dir / "reviews" / "review-decision.json"
            write_json(
                decision_path,
                review_decision_payload(
                    disposition="findings-triaged",
                    recommended_status="reviewed",
                    source_evidence=[
                        {"type": "review-output", "path": "reviews/claude-review.json"}
                    ],
                    severity_counts={
                        "critical": 0,
                        "high": 0,
                        "medium": 0,
                        "low": 1,
                        "info": 1,
                    },
                ),
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                indexed_review_output(),
                indexed_review_decision(),
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("severity_counts" in error and "review-output" in error for error in result.errors),
            result.errors,
        )

    def test_validate_skips_severity_cross_check_when_source_findings_are_not_computable(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            review_output_path = run_dir / "reviews" / "claude-review.json"
            review_output_path.parent.mkdir(parents=True, exist_ok=True)
            review_output_path.write_text("[]\n", encoding="utf-8")
            decision_path = run_dir / "reviews" / "review-decision.json"
            write_json(
                decision_path,
                review_decision_payload(
                    source_evidence=[
                        {"type": "review-output", "path": "reviews/claude-review.json"}
                    ],
                ),
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                indexed_review_output(),
                indexed_review_decision(),
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.errors, [], result.errors)

    def test_validate_rejects_indexed_review_decision_with_unknown_disposition(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "approved",
                        "recommended_status": "reviewed",
                        "decision_owner": "codex",
                        "source_evidence": [],
                        "severity_counts": {
                            "critical": 0,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": [],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("review-decision" in error and "schema error" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_review_decision_run_id_mismatch(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "another-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "passed",
                        "recommended_status": "reviewed",
                        "decision_owner": "codex",
                        "source_evidence": [],
                        "severity_counts": {
                            "critical": 0,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": [],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("does not match state run_id" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_high_finding_reviewed_without_resolution(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "findings-triaged",
                        "recommended_status": "reviewed",
                        "decision_owner": "codex",
                        "source_evidence": [],
                        "severity_counts": {
                            "critical": 0,
                            "high": 1,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": [],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("high or critical finding" in error for error in result.errors),
            result.errors,
        )

    def test_validate_allows_high_finding_blocked_decision(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            write_json(
                reviews_dir / "claude-review.json",
                {"findings": [{"severity": "critical", "title": "Critical finding"}]},
            )
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "blocked",
                        "recommended_status": "review_blocked",
                        "decision_owner": "codex",
                        "source_evidence": [
                            {"type": "review-output", "path": "reviews/claude-review.json"}
                        ],
                        "severity_counts": {
                            "critical": 1,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": ["Critical finding blocks review."],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.errors, [], result.errors)

    def test_validate_allows_high_finding_reviewed_with_risk_acceptance(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            write_json(
                reviews_dir / "claude-review.json",
                {"findings": [{"severity": "high", "title": "High finding"}]},
            )
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "risk-accepted",
                        "recommended_status": "risk_accepted",
                        "decision_owner": "codex",
                        "source_evidence": [
                            {"type": "review-output", "path": "reviews/claude-review.json"}
                        ],
                        "severity_counts": {
                            "critical": 0,
                            "high": 1,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [
                            {"risk": "High finding accepted.", "evidence": "risk-acceptance.md"}
                        ],
                        "not_tested": [],
                        "residual_risks": ["High finding accepted as risk."],
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "risk-acceptance.md").write_text("# Risk Acceptance\n", encoding="utf-8")
            state = minimal_state(status="external_review_unavailable")
            state["track"] = "Standard"
            state["current_workflow"] = "standard-code-change"
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                },
                {
                    "type": "risk-acceptance",
                    "path": "risk-acceptance.md",
                    "description": "Risk acceptance evidence.",
                },
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.errors, [], result.errors)

    def test_validate_rejects_risk_accepted_high_finding_without_accepted_risks(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "risk-accepted",
                        "recommended_status": "risk_accepted",
                        "decision_owner": "codex",
                        "source_evidence": [],
                        "severity_counts": {
                            "critical": 0,
                            "high": 1,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": ["High finding accepted as risk."],
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "risk-acceptance.md").write_text("# Risk Acceptance\n", encoding="utf-8")
            state = minimal_state(status="external_review_unavailable")
            state["track"] = "Standard"
            state["current_workflow"] = "standard-code-change"
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                },
                {
                    "type": "risk-acceptance",
                    "path": "risk-acceptance.md",
                    "description": "Risk acceptance evidence.",
                },
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("risk-accepted review-decision cannot accept" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_waived_decision_without_review_waiver_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "waived",
                        "recommended_status": "reviewed",
                        "decision_owner": "codex",
                        "source_evidence": [],
                        "severity_counts": {
                            "critical": 0,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": [],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("review-waiver" in error for error in result.errors),
            result.errors,
        )

    def test_validate_rejects_review_decision_with_non_indexable_source_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "passed",
                        "recommended_status": "reviewed",
                        "decision_owner": "codex",
                        "source_evidence": [
                            {
                                "type": "review-output",
                                "path": "reviews/never-created.json",
                            }
                        ],
                        "severity_counts": {
                            "critical": 0,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": [],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any(
                "source_evidence" in error and "does not exist" in error
                for error in result.errors
            ),
            result.errors,
        )

    def test_advance_allows_review_target_matching_recommended_status(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            write_json(reviews_dir / "claude-review.json", {"findings": []})
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "passed",
                        "recommended_status": "reviewed",
                        "decision_owner": "codex",
                        "source_evidence": [
                            {"type": "review-output", "path": "reviews/claude-review.json"}
                        ],
                        "severity_counts": {
                            "critical": 0,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": [],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)

            advanced = cli.advance_run(run_dir, "reviewed", actor="codex", root=ROOT)

        self.assertEqual(advanced["status"], "reviewed")

    def test_advance_rejects_review_target_conflicting_with_recommended_status(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            reviews_dir = run_dir / "reviews"
            reviews_dir.mkdir()
            write_json(
                reviews_dir / "claude-review.json",
                {"findings": [{"severity": "critical", "title": "Critical finding"}]},
            )
            decision_path = reviews_dir / "review-decision.json"
            decision_path.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1.0",
                        "run_id": "test-run",
                        "generated_at": "2026-06-20T00:00:00Z",
                        "disposition": "blocked",
                        "recommended_status": "review_blocked",
                        "decision_owner": "codex",
                        "source_evidence": [
                            {"type": "review-output", "path": "reviews/claude-review.json"}
                        ],
                        "severity_counts": {
                            "critical": 1,
                            "high": 0,
                            "medium": 0,
                            "low": 0,
                            "info": 0,
                        },
                        "resolved_findings": [],
                        "accepted_risks": [],
                        "not_tested": [],
                        "residual_risks": ["Critical finding blocks review."],
                    }
                ),
                encoding="utf-8",
            )
            state = minimal_state(status="reviewing")
            state["evidence"] = [
                {
                    "type": "review-evidence",
                    "path": "reviews/review-decision.json",
                    "description": "Review decision artifact.",
                }
            ]
            write_state(run_dir, state)
            before = (run_dir / "state.json").read_text(encoding="utf-8")

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "reviewed", actor="codex", root=ROOT)
            after = (run_dir / "state.json").read_text(encoding="utf-8")

        self.assertIn("recommended_status", str(raised.exception))
        self.assertEqual(before, after)

    def test_advance_ignores_review_decision_gate_for_non_review_target(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="draft")
            write_state(run_dir, state)

            advanced = cli.advance_run(run_dir, "triaged", actor="codex", root=ROOT)

        self.assertEqual(advanced["status"], "triaged")

    def test_advance_requires_decision_when_advancing_review_outcome_with_review_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            (run_dir / "review-output.md").write_text("# Review Output\n", encoding="utf-8")
            state = minimal_state(status="reviewing")
            state["track"] = "Standard"
            state["current_workflow"] = "standard-code-change"
            state["evidence"] = [
                {
                    "type": "review-output",
                    "path": "review-output.md",
                    "description": "Reviewer output without a decision.",
                }
            ]
            write_state(run_dir, state)
            before = (run_dir / "state.json").read_text(encoding="utf-8")

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "reviewed", actor="codex", root=ROOT)
            after = (run_dir / "state.json").read_text(encoding="utf-8")

        self.assertIn("review-decision", str(raised.exception))
        self.assertIn("required", str(raised.exception))
        self.assertEqual(before, after)

    def test_advance_allows_review_outcome_without_review_evidence(self):
        # A run that has not indexed any review evidence (e.g. a Fast run that
        # bypasses review, or a pre-review run) is not required to carry a
        # review decision. This keeps historical runs valid.
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="verified")
            state["track"] = "Fast"
            state["current_workflow"] = "fast-doc-change"
            write_state(run_dir, state)

            advanced = cli.advance_run(run_dir, "reviewed", actor="codex", root=ROOT)

        self.assertEqual(advanced["status"], "reviewed")


if __name__ == "__main__":
    unittest.main()
