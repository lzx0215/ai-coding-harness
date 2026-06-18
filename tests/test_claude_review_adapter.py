import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "mcp" / "claude-review" / "adapter.py"
spec = importlib.util.spec_from_file_location("claude_review_adapter", ADAPTER_PATH)
adapter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = adapter
spec.loader.exec_module(adapter)

WRAPPER_PATH = ROOT / "mcp" / "claude-review" / "scripts" / "invoke-claude-reviewer.py"
wrapper_spec = importlib.util.spec_from_file_location(
    "invoke_claude_reviewer",
    WRAPPER_PATH,
)
wrapper = importlib.util.module_from_spec(wrapper_spec)
sys.modules[wrapper_spec.name] = wrapper
wrapper_spec.loader.exec_module(wrapper)


class ClaudeReviewAdapterTest(unittest.TestCase):
    def make_payload(self, tmp: Path) -> dict:
        artifact_dir = tmp / "artifacts"
        artifact_dir.mkdir()
        task_file = tmp / "task.md"
        plan_file = tmp / "plan.md"
        diff_file = tmp / "diff.patch"
        diff_meta_file = tmp / "diff-meta.json"
        changed_files_file = tmp / "changed-files.txt"
        verification_file = tmp / "verification.md"

        task_file.write_text("Implement adapter.\n", encoding="utf-8")
        plan_file.write_text("Plan content.\n", encoding="utf-8")
        diff_file.write_text("diff --git a/a.py b/a.py\n+print('hi')\n", encoding="utf-8")
        diff_meta_file.write_text('{"files": 1}\n', encoding="utf-8")
        changed_files_file.write_text("a.py\n", encoding="utf-8")
        verification_file.write_text("Tests pending.\n", encoding="utf-8")

        return {
            "run_id": "test-run",
            "harness_version": "0.1.0",
            "prompt_version": "0.1.0",
            "artifact_dir": str(artifact_dir),
            "task_file": str(task_file),
            "plan_file": str(plan_file),
            "diff_file": str(diff_file),
            "diff_meta_file": str(diff_meta_file),
            "changed_files_file": str(changed_files_file),
            "verification_file": str(verification_file),
            "review_scope": ["correctness"],
            "output_file": str(artifact_dir / "claude-review.json"),
            "review_file": str(artifact_dir / "claude-review-evidence.json"),
            "raw_log_file": str(artifact_dir / "claude-review.raw.log"),
            "timeout_seconds": 1,
            "max_input_chars": 120000,
            "max_files": 30,
            "max_diff_lines": 2000,
        }

    def test_budget_passes_for_small_diff(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))

            self.assertIsNone(adapter.check_budget(payload))

    def test_budget_blocks_large_diff(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            Path(payload["diff_file"]).write_text("x\n" * 6, encoding="utf-8")
            payload["max_diff_lines"] = 5

            self.assertEqual(adapter.check_budget(payload), "input_over_budget")

    def test_budget_blocks_large_prompt_input_outside_diff(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            Path(payload["diff_file"]).write_text("x\n", encoding="utf-8")
            Path(payload["task_file"]).write_text("x" * 50, encoding="utf-8")
            payload["max_input_chars"] = 20

            self.assertEqual(adapter.check_budget(payload), "input_over_budget")

    def test_path_containment_rejects_outside_artifact_dir_without_invoking_claude(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            payload = self.make_payload(tmp)
            payload["review_file"] = str(tmp / "outside-review.json")

            with mock.patch.object(adapter.subprocess, "run") as run:
                result = adapter.run_claude_review(payload)

            run.assert_not_called()
            self.assertEqual(result["status"], "not_available")
            self.assertEqual(result["reason"], "unsupported_environment")
            self.assertFalse((tmp / "outside-review.json").exists())

    def test_missing_artifact_dir_rejects_without_invoking_claude(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            payload = self.make_payload(Path(raw))
            payload.pop("artifact_dir")

            with mock.patch.object(adapter.shutil, "which", return_value="claude"):
                with mock.patch.object(adapter.subprocess, "run") as run:
                    run.return_value = adapter.subprocess.CompletedProcess(
                        args=[],
                        returncode=1,
                        stdout="",
                        stderr="failed\n",
                    )
                    result = adapter.run_claude_review(payload)

            run.assert_not_called()
            self.assertEqual(result["status"], "not_available")
            self.assertEqual(result["reason"], "unsupported_environment")
            self.assertFalse(Path(payload["output_file"]).exists())
            self.assertFalse(Path(payload["raw_log_file"]).exists())
            self.assertFalse(Path(payload["output_file"]).exists())
            self.assertFalse(Path(payload["raw_log_file"]).exists())

    def test_empty_artifact_dir_rejects_without_invoking_claude(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            payload = self.make_payload(Path(raw))
            payload["artifact_dir"] = "   "

            with mock.patch.object(adapter.shutil, "which", return_value="claude"):
                with mock.patch.object(adapter.subprocess, "run") as run:
                    run.return_value = adapter.subprocess.CompletedProcess(
                        args=[],
                        returncode=1,
                        stdout="",
                        stderr="failed\n",
                    )
                    result = adapter.run_claude_review(payload)

            run.assert_not_called()
            self.assertEqual(result["status"], "not_available")
            self.assertEqual(result["reason"], "unsupported_environment")

    def test_payload_write_paths_remain_authoritative_over_cli_args(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            tmp = Path(raw)
            payload = self.make_payload(tmp)
            payload["output_file"] = str(tmp / "outside-output.json")
            payload["raw_log_file"] = str(tmp / "outside.raw.log")
            input_file = tmp / "input.json"
            input_file.write_text(json.dumps(payload), encoding="utf-8")
            safe_output_arg = tmp / "artifacts" / "safe-output.json"
            safe_raw_arg = tmp / "artifacts" / "safe.raw.log"

            if not hasattr(wrapper, "run_from_paths"):
                self.fail("wrapper must expose run_from_paths")

            with mock.patch.object(wrapper, "run_claude_review", return_value={}) as run:
                wrapper.run_from_paths(input_file, safe_output_arg, safe_raw_arg)

            called_payload = run.call_args.args[0]
            self.assertEqual(called_payload["output_file"], str(tmp / "outside-output.json"))
            self.assertEqual(called_payload["raw_log_file"], str(tmp / "outside.raw.log"))

    def test_tool_missing_returns_not_available_tool_missing(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))

            with mock.patch.object(adapter.shutil, "which", return_value=None):
                result = adapter.run_claude_review(payload)

            self.assertEqual(result["status"], "not_available")
            self.assertEqual(result["reason"], "tool_missing")
            self.assertFalse(result["completed"])
            self.assertTrue(Path(payload["output_file"]).exists())
            self.assertTrue(Path(payload["raw_log_file"]).exists())

    def test_normalize_fake_claude_json_with_findings(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            fake = {
                "result": {
                    "summary": "One issue found.",
                    "findings": [
                        {
                            "severity": "medium",
                            "title": "Missing path guard",
                            "evidence": "The write path is not checked.",
                            "recommendation": "Resolve and contain output paths.",
                            "file": "adapter.py",
                            "line": 12,
                        }
                    ],
                    "tested": ["Reviewed adapter tests."],
                    "not_tested": ["Real Claude execution."],
                    "residual_risks": ["Subprocess integration is mocked."],
                },
                "model": "claude-test",
            }

            result = adapter.normalize_claude_json(fake, payload)

            self.assertEqual(result["status"], "findings")
            self.assertEqual(result["findings"][0]["title"], "Missing path guard")

    def test_normalize_no_findings_yields_passed(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            fake = {
                "result": json.dumps(
                    {
                        "summary": "No issues found.",
                        "findings": [],
                        "tested": ["Reviewed diff."],
                        "not_tested": ["Real Claude execution."],
                        "residual_risks": ["None identified."],
                    }
                )
            }

            result = adapter.normalize_claude_json(fake, payload)

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["findings"], [])


if __name__ == "__main__":
    unittest.main()
