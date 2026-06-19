import importlib.util
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path


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

spec = importlib.util.spec_from_file_location("claude_review_adapter", ADAPTER_PATH)
adapter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = adapter
spec.loader.exec_module(adapter)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_schema() -> dict:
    return json.loads(STATE_SCHEMA.read_text(encoding="utf-8"))


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
