import json
import unittest
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]


class StateSchemaTest(unittest.TestCase):
    def load_schema(self):
        return json.loads((ROOT / "harness/schemas/state.schema.json").read_text())

    def minimal_valid_state(self):
        return {
            "run_id": "test-run",
            "harness_version": "0.1.0",
            "state_schema_version": "0.1.0",
            "status": "draft",
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

    def validation_errors(self, state):
        schema = self.load_schema()
        return list(Draft202012Validator(schema).iter_errors(state))

    def test_schema_accepts_v0_1_and_v0_2_versions(self):
        base = self.minimal_valid_state()
        for harness_version in ["0.1.0", "0.2.0"]:
            for state_schema_version in ["0.1.0", "0.2.0"]:
                with self.subTest(
                    harness_version=harness_version,
                    state_schema_version=state_schema_version,
                ):
                    state = deepcopy(base)
                    state["harness_version"] = harness_version
                    state["state_schema_version"] = state_schema_version

                    self.assertEqual(self.validation_errors(state), [])

    def test_schema_rejects_unknown_future_versions(self):
        state = self.minimal_valid_state()
        state["harness_version"] = "0.3.0"
        state["state_schema_version"] = "0.3.0"

        errors = self.validation_errors(state)

        self.assertGreaterEqual(len(errors), 2)

    def test_schema_has_required_statuses(self):
        schema = self.load_schema()
        statuses = schema["properties"]["status"]["enum"]
        self.assertIn("review_blocked", statuses)
        self.assertIn("review_failed", statuses)
        self.assertIn("external_review_unavailable", statuses)

    def test_schema_has_registered_workflows(self):
        schema = self.load_schema()
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

    def test_schema_ties_workflows_to_tracks(self):
        schema = self.load_schema()
        constraints = {}
        for clause in schema["allOf"]:
            self.assertEqual(clause["if"]["required"], ["current_workflow"])
            self.assertEqual(clause["then"]["required"], ["track"])
            workflows = tuple(clause["if"]["properties"]["current_workflow"]["enum"])
            track = clause["then"]["properties"]["track"]["const"]
            constraints[workflows] = track

        self.assertEqual(
            constraints,
            {
                ("fast-doc-change", "fast-code-change"): "Fast",
                (
                    "standard-doc-system-change",
                    "standard-code-change",
                    "standard-agent-adapter-change",
                ): "Standard",
                ("strict-risk-change", "strict-destructive-change"): "Strict",
            },
        )

    def test_schema_rejects_empty_nested_identity_and_evidence_strings(self):
        schema = self.load_schema()
        agent_properties = schema["properties"]["external_agents"]["items"]["properties"]
        for field in [
            "name",
            "role",
            "adapter",
            "adapter_version",
            "tool",
            "prompt_version",
        ]:
            self.assertEqual(agent_properties[field]["minLength"], 1, field)

        for field in ["model", "model_version", "cli_version"]:
            self.assertEqual(agent_properties[field]["type"], ["string", "null"], field)
            self.assertEqual(agent_properties[field]["minLength"], 1, field)

        evidence_properties = schema["properties"]["evidence"]["items"]["properties"]
        for field in ["type", "path", "description"]:
            self.assertEqual(evidence_properties[field]["minLength"], 1, field)

    def test_schema_requires_iso_timestamps(self):
        schema = self.load_schema()
        for field in ["created_at", "updated_at"]:
            timestamp = schema["properties"][field]
            self.assertEqual(timestamp["minLength"], 1)
            self.assertEqual(timestamp["format"], "date-time")
            self.assertIn("pattern", timestamp)

    def test_external_review_template_is_not_successful_evidence_by_default(self):
        template = json.loads(
            (ROOT / "harness/templates/external-review-template.json").read_text()
        )
        self.assertEqual(template["status"], "replace-me")
        self.assertNotEqual(template["status"], "passed")
        for field in [
            "run_id",
            "adapter_version",
            "prompt_version",
            "reviewer",
            "reviewer_model",
            "reviewer_model_version",
            "reviewer_cli_version",
            "summary",
            "raw_log_file",
        ]:
            self.assertNotEqual(template[field], "", field)


if __name__ == "__main__":
    unittest.main()
