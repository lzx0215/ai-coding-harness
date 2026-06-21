import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
STATE_SCHEMA = ROOT / "harness" / "schemas" / "state.schema.json"
LIFECYCLE = ROOT / "harness" / "core" / "lifecycle.md"
STATE_AUTHORITY = ROOT / "harness" / "core" / "state-authority.md"
ADAPTER_PATH = ROOT / "mcp" / "claude-review" / "adapter.py"
ADAPTER_REQUIREMENTS = ROOT / "mcp" / "claude-review" / "requirements.txt"
ADAPTER_LOCKFILE = ROOT / "mcp" / "claude-review" / "requirements.lock.txt"
ADAPTER_OUTPUT_SCHEMA = (
    ROOT / "mcp" / "claude-review" / "schema" / "claude-review-output.schema.json"
)
RISK_ACCEPTANCE_TEMPLATE = ROOT / "harness" / "templates" / "risk-acceptance.md"
V011_REVIEW_FIXTURE = (
    ROOT / "tests" / "fixtures" / "claude-review" / "v0.1.1-envelope.json"
)
PYPROJECT = ROOT / "pyproject.toml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

spec = importlib.util.spec_from_file_location("claude_review_adapter", ADAPTER_PATH)
adapter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = adapter
spec.loader.exec_module(adapter)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_schema() -> dict:
    return json.loads(STATE_SCHEMA.read_text(encoding="utf-8"))


def load_output_schema() -> dict:
    return json.loads(read_text(ADAPTER_OUTPUT_SCHEMA))


def output_schema_errors(payload: dict) -> list:
    return list(Draft202012Validator(load_output_schema()).iter_errors(payload))


def parse_markdown_table(text: str, header_first_cell: str) -> list[list[str]]:
    lines = text.splitlines()
    rows: list[list[str]] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue

        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not in_table:
            if cells and cells[0] == header_first_cell:
                in_table = True
            continue

        if cells and all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        rows.append(cells)

    return rows


def code_spans(text: str) -> list[str]:
    return re.findall(r"`([^`]+)`", text)


def logical_requirements(path: Path) -> list[str]:
    requirements: list[str] = []
    current: list[str] = []

    for line in read_text(path).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("--") and not stripped.startswith("--hash="):
            continue

        value = stripped[:-1].rstrip() if stripped.endswith("\\") else stripped
        if value.startswith("--hash="):
            current.append(value)
            continue

        if current:
            requirements.append(" ".join(current))
        current = [value]

    if current:
        requirements.append(" ".join(current))

    return requirements


class StaticContractsTest(unittest.TestCase):
    def test_pyproject_defines_harness_console_script(self):
        payload = tomllib.loads(read_text(PYPROJECT))

        self.assertEqual(payload["project"]["name"], "ai-coding-harness")
        self.assertEqual(payload["project"]["scripts"]["harness"], "harness.cli:main")
        self.assertIn("jsonschema>=4.26,<5", payload["project"]["dependencies"])
        self.assertIn("harness*", payload["tool"]["setuptools"]["packages"]["find"]["include"])
        self.assertEqual(
            payload["tool"]["setuptools"]["package-data"]["harness"],
            ["schemas/*.json", "templates/*.md"],
        )

    def test_ci_workflow_runs_core_validation_steps(self):
        text = read_text(CI_WORKFLOW)

        for command in [
            "python -m pip install -e .",
            "python -m pip install .",
            "python -m unittest discover -s tests",
            "python -m harness.cli validate",
            "harness validate harness/runs/example-fast-doc-change",
            "harness queue-generic-agent",
            "harness run-scheduler",
            "harness aggregate-jobs",
            "package-smoke-scheduler-agent",
            "github.event.before",
            "github.base_ref",
            "git merge-base HEAD origin/master",
            "git diff --check \"$base\" HEAD",
            "for run_dir in \"$GITHUB_WORKSPACE\"/harness/runs/*",
        ]:
            self.assertIn(command, text)

    def test_risk_acceptance_template_exists_with_required_sections(self):
        text = read_text(RISK_ACCEPTANCE_TEMPLATE)

        for heading in [
            "# Risk Acceptance",
            "## Decision",
            "## Accepted Risk",
            "## Reason",
            "## Scope",
            "## Evidence",
            "## Decided By",
            "## Decided At",
            "## Residual Risks",
        ]:
            self.assertIn(heading, text)

    def test_claude_review_output_schema_accepts_v0_1_1_fixture_without_provenance(self):
        fixture = json.loads(read_text(V011_REVIEW_FIXTURE))

        self.assertEqual(output_schema_errors(fixture), [])

    def test_claude_review_output_schema_accepts_v0_2_reviewer_provenance(self):
        payload = json.loads(read_text(V011_REVIEW_FIXTURE))
        payload["harness_version"] = "0.2.0"
        payload["reviewer_provenance"] = {
            "schema_version": "0.2.0",
            "reviewer": "claude-code",
            "cli": {
                "name": "Claude Code",
                "raw_version": "2.1.168 (Claude Code)",
                "version": "2.1.168",
            },
            "models": [
                {
                    "name": "glm-5.2[1m]",
                    "version": None,
                    "source": "modelUsage",
                    "usage": {
                        "input_tokens": None,
                        "output_tokens": None,
                    },
                    "raw_usage": {
                        "inputTokens": 10,
                        "outputTokens": 20,
                    },
                }
            ],
            "primary_model": "glm-5.2[1m]",
            "unknowns": ["model_version", "token_usage"],
        }

        self.assertEqual(output_schema_errors(payload), [])

    def test_claude_review_output_schema_rejects_unknowns_outside_vocabulary(self):
        payload = json.loads(read_text(V011_REVIEW_FIXTURE))
        payload["harness_version"] = "0.2.0"
        payload["reviewer_provenance"] = {
            "schema_version": "0.2.0",
            "reviewer": "claude-code",
            "cli": {"name": "Claude Code", "raw_version": None, "version": None},
            "models": [],
            "primary_model": None,
            "unknowns": ["invented_unknown"],
        }

        errors = output_schema_errors(payload)

        self.assertTrue(errors)

    def test_claude_review_output_schema_rejects_empty_models_without_model_name_unknown(self):
        payload = json.loads(read_text(V011_REVIEW_FIXTURE))
        payload["reviewer_model"] = None
        payload["harness_version"] = "0.2.0"
        payload["reviewer_provenance"] = {
            "schema_version": "0.2.0",
            "reviewer": "claude-code",
            "cli": {"name": "Claude Code", "raw_version": None, "version": None},
            "models": [],
            "primary_model": None,
            "unknowns": ["primary_model", "token_usage"],
        }

        errors = output_schema_errors(payload)

        self.assertTrue(errors)

    def test_claude_review_output_schema_rejects_nonempty_models_with_null_primary_model(self):
        payload = json.loads(read_text(V011_REVIEW_FIXTURE))
        payload["harness_version"] = "0.2.0"
        payload["reviewer_provenance"] = {
            "schema_version": "0.2.0",
            "reviewer": "claude-code",
            "cli": {"name": "Claude Code", "raw_version": None, "version": None},
            "models": [
                {
                    "name": "glm-5.2[1m]",
                    "version": None,
                    "source": "modelUsage",
                    "usage": {
                        "input_tokens": None,
                        "output_tokens": None,
                    },
                }
            ],
            "primary_model": None,
            "unknowns": ["model_version", "token_usage"],
        }

        errors = output_schema_errors(payload)

        self.assertTrue(errors)

    def test_claude_review_output_schema_accepts_nonempty_models_with_present_primary_model(self):
        payload = json.loads(read_text(V011_REVIEW_FIXTURE))
        payload["harness_version"] = "0.2.0"
        payload["reviewer_provenance"] = {
            "schema_version": "0.2.0",
            "reviewer": "claude-code",
            "cli": {"name": "Claude Code", "raw_version": None, "version": None},
            "models": [
                {
                    "name": "glm-5.2[1m]",
                    "version": None,
                    "source": "modelUsage",
                    "usage": {
                        "input_tokens": None,
                        "output_tokens": None,
                    },
                }
            ],
            "primary_model": "glm-5.2[1m]",
            "unknowns": ["model_version", "token_usage"],
        }

        self.assertEqual(output_schema_errors(payload), [])

    def test_claude_review_output_schema_allows_nullable_identity_metadata(self):
        schema = json.loads(read_text(ADAPTER_OUTPUT_SCHEMA))
        for field in [
            "reviewer_model",
            "reviewer_model_version",
            "reviewer_cli_version",
        ]:
            self.assertEqual(schema["properties"][field]["type"], ["string", "null"])
            self.assertEqual(schema["properties"][field]["minLength"], 1)

    def test_claude_review_adapter_dependencies_are_locked(self):
        direct_requirements = logical_requirements(ADAPTER_REQUIREMENTS)
        locked_requirements = logical_requirements(ADAPTER_LOCKFILE)

        self.assertTrue(locked_requirements)
        for requirement in locked_requirements:
            self.assertIn("==", requirement)
            self.assertNotIn(">=", requirement)
            self.assertNotIn("<=", requirement)
            self.assertIn("--hash=sha256:", requirement)

        for requirement in direct_requirements:
            self.assertTrue(
                any(locked.startswith(requirement) for locked in locked_requirements),
                requirement,
            )

        self.assertTrue(
            any(
                locked.startswith("pywin32==312")
                and 'platform_system == "Windows"' in locked
                for locked in locked_requirements
            ),
            locked_requirements,
        )
        for requirement in [
            "cryptography==49.0.0",
            "cffi==2.0.0",
            "pycparser==3.0",
        ]:
            self.assertTrue(
                any(locked.startswith(requirement) for locked in locked_requirements),
                requirement,
            )

    @unittest.skipUnless(
        os.environ.get("HARNESS_RUN_PIP_HASH_CHECK") == "1",
        "set HARNESS_RUN_PIP_HASH_CHECK=1 to run live pip hash validation",
    )
    def test_claude_review_adapter_lockfile_hash_validation_passes(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--dry-run",
                "--require-hashes",
                "--ignore-installed",
                "--no-input",
                "-r",
                str(ADAPTER_LOCKFILE),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_lifecycle_workflow_registry_matches_state_schema(self):
        schema = load_schema()
        lifecycle_rows = parse_markdown_table(read_text(LIFECYCLE), "Workflow ID")

        workflows_from_docs = [code_spans(row[0])[0] for row in lifecycle_rows]
        tracks_from_docs = {
            code_spans(row[0])[0]: row[1]
            for row in lifecycle_rows
        }

        self.assertEqual(
            workflows_from_docs,
            schema["properties"]["current_workflow"]["enum"],
        )

        expected_constraints = {
            tuple(
                workflow
                for workflow, track in tracks_from_docs.items()
                if track == expected_track
            ): expected_track
            for expected_track in ("Fast", "Standard", "Strict")
        }
        actual_constraints = {
            tuple(clause["if"]["properties"]["current_workflow"]["enum"]):
            clause["then"]["properties"]["track"]["const"]
            for clause in schema["allOf"]
        }

        self.assertEqual(actual_constraints, expected_constraints)

    def test_state_authority_states_match_state_schema(self):
        schema_statuses = load_schema()["properties"]["status"]["enum"]
        text = read_text(STATE_AUTHORITY)

        normal_line = next(
            line for line in text.splitlines()
            if line.startswith("`draft ->")
        )
        normal_states = [part.strip() for part in code_spans(normal_line)[0].split("->")]

        exceptional_section = text.split("## Exceptional States", 1)[1].split(
            "## Transition Rules",
            1,
        )[0]
        exceptional_states = [
            code_spans(line)[0]
            for line in exceptional_section.splitlines()
            if line.strip().startswith("- `")
        ]

        self.assertEqual(schema_statuses, normal_states + exceptional_states)

    def test_review_status_mapping_matches_adapter_terminal_statuses(self):
        rows = parse_markdown_table(read_text(STATE_AUTHORITY), "Review status")
        statuses_from_docs = {code_spans(row[0])[0] for row in rows}

        self.assertEqual(statuses_from_docs, adapter.TERMINAL_STATUSES)

        mapping = {
            code_spans(row[0])[0]: code_spans(row[1])[0]
            for row in rows
            if code_spans(row[0])[0] != "findings"
        }
        self.assertEqual(
            mapping,
            {
                "passed": "reviewed",
                "failed": "review_failed",
                "timeout": "review_timeout",
                "schema_invalid": "review_schema_invalid",
                "not_available": "external_review_unavailable",
            },
        )

        findings_rows = [
            row for row in rows
            if code_spans(row[0])[0] == "findings"
        ]
        self.assertEqual(len(findings_rows), 2)
        self.assertIn("reviewed", code_spans(findings_rows[0][1]))
        self.assertIn("review_blocked", code_spans(findings_rows[1][1]))


if __name__ == "__main__":
    unittest.main()
