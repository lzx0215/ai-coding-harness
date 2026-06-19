import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE_SCHEMA = ROOT / "harness" / "schemas" / "state.schema.json"
LIFECYCLE = ROOT / "harness" / "core" / "lifecycle.md"
STATE_AUTHORITY = ROOT / "harness" / "core" / "state-authority.md"
ADAPTER_PATH = ROOT / "mcp" / "claude-review" / "adapter.py"

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


class StaticContractsTest(unittest.TestCase):
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
