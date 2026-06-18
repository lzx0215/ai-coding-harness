import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StateSchemaTest(unittest.TestCase):
    def test_schema_has_required_statuses(self):
        schema = json.loads((ROOT / "harness/schemas/state.schema.json").read_text())
        statuses = schema["properties"]["status"]["enum"]
        self.assertIn("review_blocked", statuses)
        self.assertIn("review_failed", statuses)
        self.assertIn("external_review_unavailable", statuses)

    def test_schema_has_registered_workflows(self):
        schema = json.loads((ROOT / "harness/schemas/state.schema.json").read_text())
        workflows = schema["properties"]["current_workflow"]["enum"]
        self.assertEqual(
            workflows,
            [
                "fast-doc-change",
                "fast-code-change",
                "standard-doc-system-change",
                "standard-code-change",
                "standard-agent-adapter-change",
                "strict-risk-change",
                "strict-destructive-change",
            ],
        )


if __name__ == "__main__":
    unittest.main()
