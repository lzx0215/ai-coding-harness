import json
import tempfile
import unittest
from pathlib import Path

from harness import readiness


ROOT = Path(__file__).resolve().parents[1]


def write_state(run_dir: Path, state: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "state.json").write_text(
        json.dumps(state, indent=2) + "\n",
        encoding="utf-8",
    )


def minimal_state() -> dict:
    return {
        "run_id": "phase2-test",
        "harness_version": "0.1.0",
        "state_schema_version": "0.1.0",
        "status": "draft",
        "track": "Standard",
        "current_workflow": "standard-doc-system-change",
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


class FrontmatterParserTest(unittest.TestCase):
    def test_parse_frontmatter_accepts_phase2_subset(self):
        text = """---
run_id: phase2-test
schema_version: 0.1.0
track: Standard
review_required: true
recovery_strategy: null
scope:
  - "CLI helpers"
  - "frontmatter checks"
---

# Task
"""

        result = readiness.parse_frontmatter(text)

        self.assertEqual(result.data["run_id"], "phase2-test")
        self.assertEqual(result.data["track"], "Standard")
        self.assertIs(result.data["review_required"], True)
        self.assertIsNone(result.data["recovery_strategy"])
        self.assertEqual(result.data["scope"], ["CLI helpers", "frontmatter checks"])
        self.assertEqual(result.warnings, [])

    def test_parse_frontmatter_reports_missing_block(self):
        result = readiness.parse_frontmatter("# Task\n")

        self.assertEqual(result.data, {})
        self.assertEqual(result.warnings, ["missing frontmatter block"])

    def test_parse_frontmatter_reports_unsupported_nested_yaml(self):
        text = """---
source:
  nested:
    key: value
---

# Task
"""

        result = readiness.parse_frontmatter(text)

        self.assertTrue(
            any("unsupported frontmatter nesting" in warning for warning in result.warnings),
            result.warnings,
        )


class ReadinessCheckTest(unittest.TestCase):
    def test_check_run_readiness_reports_missing_documents_without_mutation(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state()
            write_state(run_dir, state)
            before = (run_dir / "state.json").read_text(encoding="utf-8")

            report = readiness.check_run_readiness(run_dir, state)

            after = (run_dir / "state.json").read_text(encoding="utf-8")

        self.assertEqual(before, after)
        self.assertTrue(report.warnings)
        self.assertTrue(
            any("missing run document: task.md" in warning for warning in report.warnings),
            report.warnings,
        )

    def test_check_run_readiness_warns_on_track_mismatch(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state()
            write_state(run_dir, state)
            (run_dir / "task.md").write_text(
                """---
run_id: phase2-test
schema_version: 0.1.0
track: Fast
workflow: standard-doc-system-change
owner: codex
requested_outcome: "Document behavior."
scope:
  - "docs"
---

# Task
""",
                encoding="utf-8",
            )

            report = readiness.check_run_readiness(run_dir, state)

        self.assertTrue(
            any("task.md frontmatter track Fast does not match state track Standard" in warning for warning in report.warnings),
            report.warnings,
        )


if __name__ == "__main__":
    unittest.main()
