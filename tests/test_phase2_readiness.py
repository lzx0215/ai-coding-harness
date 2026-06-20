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

    def test_parse_frontmatter_accepts_crlf_delimiters(self):
        text = (
            "---\r\n"
            "run_id: phase2-test\r\n"
            "track: Standard\r\n"
            "scope:\r\n"
            "  - \"frontmatter checks\"\r\n"
            "---\r\n"
            "\r\n"
            "# Task\r\n"
        )

        result = readiness.parse_frontmatter(text)

        self.assertEqual(result.data["run_id"], "phase2-test")
        self.assertEqual(result.data["scope"], ["frontmatter checks"])
        self.assertEqual(result.warnings, [])

    def test_parse_frontmatter_accepts_inline_empty_arrays(self):
        text = """---
memory_files: []
scope: []
---

# Task
"""

        result = readiness.parse_frontmatter(text)

        self.assertEqual(result.data["memory_files"], [])
        self.assertEqual(result.data["scope"], [])
        self.assertEqual(result.warnings, [])

    def test_parse_frontmatter_accepts_closing_delimiter_at_eof(self):
        text = """---
run_id: phase2-test
scope: []
---"""

        result = readiness.parse_frontmatter(text)

        self.assertEqual(result.data["run_id"], "phase2-test")
        self.assertEqual(result.data["scope"], [])
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
        self.assertNotEqual(result.data["source"], {"key": "value"})

    def test_parse_frontmatter_warns_on_map_like_sequence_item(self):
        text = """---
scope:
  - name: codex
---

# Task
"""

        result = readiness.parse_frontmatter(text)

        self.assertTrue(
            any("unsupported frontmatter sequence item" in warning for warning in result.warnings),
            result.warnings,
        )

    def test_parse_frontmatter_accepts_quoted_sequence_item_with_colon(self):
        text = """---
scope:
  - "owner: codex"
---

# Task
"""

        result = readiness.parse_frontmatter(text)

        self.assertEqual(result.data["scope"], ["owner: codex"])
        self.assertEqual(result.warnings, [])


class ReadinessCheckTest(unittest.TestCase):
    def test_check_run_readiness_warns_on_missing_phase2_frontmatter_fields(self):
        required_fields_by_document = {
            "task.md": (
                "schema_version",
                "owner",
                "requested_outcome",
                "scope",
                "non_goals",
                "constraints",
            ),
            "triage.md": (
                "schema_version",
                "review_required",
                "strict_triggers",
                "risk_reasons",
                "verification_required",
            ),
            "plan.md": (
                "schema_version",
                "acceptance",
                "verification",
                "review_plan",
                "constraints",
                "recovery_strategy",
                "residual_risk_owner",
            ),
            "handoff.md": (
                "schema_version",
                "changed",
                "verified",
                "not_verified",
                "residual_risks",
                "next_step",
                "memory_update",
                "memory_files",
            ),
        }

        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state()
            write_state(run_dir, state)
            for document_name in readiness.RUN_DOCUMENTS:
                (run_dir / document_name).write_text(
                    """---
run_id: phase2-test
track: Standard
workflow: standard-doc-system-change
---

# Run Document
""",
                    encoding="utf-8",
                )

            report = readiness.check_run_readiness(run_dir, state)

        for document_name, field_names in required_fields_by_document.items():
            with self.subTest(document_name=document_name):
                for field_name in field_names:
                    self.assertIn(
                        f"{document_name} frontmatter missing field: {field_name}",
                        report.warnings,
                    )

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


class Phase2TemplateTest(unittest.TestCase):
    def test_phase2_template_frontmatter_defaults_match_expected_maps(self):
        expected_frontmatter = {
            "task.md": {
                "run_id": "",
                "schema_version": "0.1.0",
                "track": "Standard",
                "workflow": "standard-doc-system-change",
                "owner": "codex",
                "requested_outcome": "",
                "scope": [],
                "non_goals": [],
                "constraints": [],
            },
            "triage.md": {
                "run_id": "",
                "schema_version": "0.1.0",
                "track": "Standard",
                "workflow": "standard-doc-system-change",
                "review_required": True,
                "strict_triggers": [],
                "risk_reasons": [],
                "verification_required": [],
            },
            "plan.md": {
                "run_id": "",
                "schema_version": "0.1.0",
                "workflow": "standard-doc-system-change",
                "acceptance": [],
                "verification": [],
                "review_plan": [],
                "constraints": [],
                "recovery_strategy": None,
                "residual_risk_owner": None,
            },
            "handoff.md": {
                "run_id": "",
                "schema_version": "0.1.0",
                "changed": [],
                "verified": [],
                "not_verified": [],
                "residual_risks": [],
                "next_step": "",
                "memory_update": "none",
                "memory_files": [],
            },
        }

        for template_name, expected_data in expected_frontmatter.items():
            with self.subTest(template_name=template_name):
                text = (ROOT / "harness" / "templates" / template_name).read_text(
                    encoding="utf-8",
                )
                result = readiness.parse_frontmatter(text)

                self.assertEqual(result.warnings, [])
                self.assertEqual(result.data, expected_data)

    def test_phase2_templates_have_frontmatter(self):
        for template_name in ("task.md", "triage.md", "plan.md", "handoff.md"):
            with self.subTest(template_name=template_name):
                text = (ROOT / "harness" / "templates" / template_name).read_text(
                    encoding="utf-8",
                )
                result = readiness.parse_frontmatter(text)

                self.assertEqual(result.warnings, [])
                self.assertIn("run_id", result.data)
                self.assertIn("schema_version", result.data)

    def test_phase2_templates_parse_inline_empty_arrays(self):
        expected_arrays = {
            "task.md": ("scope", "non_goals", "constraints"),
            "triage.md": (
                "strict_triggers",
                "risk_reasons",
                "verification_required",
            ),
            "plan.md": ("acceptance", "verification", "review_plan", "constraints"),
            "handoff.md": (
                "changed",
                "verified",
                "not_verified",
                "residual_risks",
                "memory_files",
            ),
        }

        for template_name, field_names in expected_arrays.items():
            with self.subTest(template_name=template_name):
                text = (ROOT / "harness" / "templates" / template_name).read_text(
                    encoding="utf-8",
                )
                result = readiness.parse_frontmatter(text)

                for field_name in field_names:
                    self.assertEqual(result.data[field_name], [])

    def test_handoff_template_declares_phase3_memory_fields(self):
        text = (ROOT / "harness" / "templates" / "handoff.md").read_text(
            encoding="utf-8",
        )
        result = readiness.parse_frontmatter(text)

        self.assertEqual(result.data["memory_update"], "none")
        self.assertEqual(result.data["memory_files"], [])


if __name__ == "__main__":
    unittest.main()
