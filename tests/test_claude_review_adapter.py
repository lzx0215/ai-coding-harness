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

            if not hasattr(wrapper, "run_from_paths"):
                self.fail("wrapper must expose run_from_paths")

            with mock.patch.object(wrapper, "run_claude_review", return_value={}) as run:
                wrapper.run_from_paths(
                    input_file,
                    payload["output_file"],
                    payload["raw_log_file"],
                )

            called_payload = run.call_args.args[0]
            self.assertEqual(called_payload["output_file"], str(tmp / "outside-output.json"))
            self.assertEqual(called_payload["raw_log_file"], str(tmp / "outside.raw.log"))

    def test_wrapper_path_mismatch_rejects_without_invoking_adapter(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            payload = self.make_payload(tmp)
            input_file = tmp / "input.json"
            input_file.write_text(json.dumps(payload), encoding="utf-8")
            mismatched_output = tmp / "artifacts" / "other-output.json"

            with mock.patch.object(wrapper, "run_claude_review", return_value={}) as run:
                result = wrapper.run_from_paths(
                    input_file,
                    mismatched_output,
                    payload["raw_log_file"],
                )

            run.assert_not_called()
            self.assertEqual(result["status"], "not_available")
            self.assertEqual(result["reason"], "unsupported_environment")
            self.assertFalse(result["completed"])

    def test_wrapper_load_payload_accepts_utf8_bom(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            input_file = Path(raw) / "input.json"
            input_file.write_text(
                "\ufeff" + json.dumps(payload),
                encoding="utf-8",
            )

            loaded = wrapper.load_payload(input_file)

        self.assertEqual(loaded["run_id"], "test-run")

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

    def test_normalize_extracts_model_from_model_usage(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            fake = {
                "modelUsage": {
                    "glm-5.2[1m]": {
                        "inputTokens": 10,
                        "outputTokens": 20,
                    }
                },
                "result": {
                    "summary": "No issues found.",
                    "findings": [],
                    "tested": ["Reviewed adapter tests."],
                    "not_tested": ["Real Claude execution."],
                    "residual_risks": ["None identified."],
                },
            }

            result = adapter.normalize_claude_json(fake, payload)

        self.assertEqual(result["reviewer_model"], "glm-5.2[1m]")
        self.assertIsNone(result["reviewer_model_version"])

    def test_select_primary_model_excludes_incomplete_usage_when_complete_usage_exists(self):
        model_usage = {
            "alpha": {"inputTokens": 1, "outputTokens": 1},
            "beta": {"inputTokens": 999},
        }

        primary = adapter.select_primary_model(model_usage)

        self.assertEqual(primary, "alpha")

    def test_select_primary_model_uses_sorted_key_when_no_complete_usage_exists(self):
        model_usage = {
            "zeta": {"inputTokens": 10},
            "alpha": {"outputTokens": 5},
        }

        primary = adapter.select_primary_model(model_usage)

        self.assertEqual(primary, "alpha")

    def test_normalize_records_structured_provenance_for_model_usage(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            fake = {
                "modelUsage": {
                    "small-model": {"inputTokens": 5, "outputTokens": 5},
                    "large-model": {"inputTokens": 100, "outputTokens": 1},
                },
                "structured_output": {
                    "summary": "No issues found.",
                    "findings": [],
                    "tested": ["Reviewed adapter tests."],
                    "not_tested": ["Real Claude execution."],
                    "residual_risks": ["None identified."],
                },
            }

            result = adapter.normalize_claude_json(
                fake,
                payload,
                reviewer_cli_version="2.1.168 (Claude Code)",
            )

        self.assertEqual(result["reviewer_model"], "large-model")
        provenance = result["reviewer_provenance"]
        self.assertEqual(provenance["schema_version"], "0.2.0")
        self.assertEqual(provenance["primary_model"], "large-model")
        self.assertEqual(
            [model["name"] for model in provenance["models"]],
            ["large-model", "small-model"],
        )
        self.assertIn("model_version", provenance["unknowns"])
        self.assertIn("token_usage", provenance["unknowns"])
        self.assertEqual(provenance["cli"]["raw_version"], "2.1.168 (Claude Code)")

    def test_normalize_prefers_explicit_model_and_preserves_model_usage_models(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            fake = {
                "model": "claude-explicit",
                "modelUsage": {
                    "glm-5.2[1m]": {
                        "inputTokens": 10,
                        "outputTokens": 20,
                    }
                },
                "structured_output": {
                    "summary": "No issues found.",
                    "findings": [],
                    "tested": ["Reviewed adapter tests."],
                    "not_tested": ["Real Claude execution."],
                    "residual_risks": ["None identified."],
                },
            }

            result = adapter.normalize_claude_json(fake, payload)

        self.assertEqual(result["reviewer_model"], "claude-explicit")
        provenance = result["reviewer_provenance"]
        self.assertEqual(provenance["primary_model"], "claude-explicit")
        self.assertEqual(
            [model["name"] for model in provenance["models"]],
            ["claude-explicit", "glm-5.2[1m]"],
        )
        self.assertEqual(provenance["models"][0]["source"], "metadata")
        self.assertEqual(provenance["models"][1]["source"], "modelUsage")
        self.assertIn("token_usage", provenance["unknowns"])

    def test_normalize_uses_metadata_cli_version_in_reviewer_provenance(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            fake = {
                "cli_version": "2.1.168 (Claude Code)",
                "structured_output": {
                    "summary": "No issues found.",
                    "findings": [],
                    "tested": ["Reviewed adapter tests."],
                    "not_tested": ["Real Claude execution."],
                    "residual_risks": ["None identified."],
                },
            }

            result = adapter.normalize_claude_json(fake, payload)

        self.assertEqual(result["reviewer_cli_version"], "2.1.168 (Claude Code)")
        provenance = result["reviewer_provenance"]
        self.assertEqual(provenance["cli"]["raw_version"], "2.1.168 (Claude Code)")
        self.assertEqual(provenance["cli"]["version"], "2.1.168")
        self.assertNotIn("cli_version", provenance["unknowns"])

    def test_normalize_preserves_raw_usage_when_explicit_model_overlaps_model_usage(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            raw_usage = {
                "inputTokens": 10,
                "outputTokens": 20,
                "cacheReadInputTokens": 5,
            }
            fake = {
                "model": "glm-5.2[1m]",
                "modelUsage": {
                    "glm-5.2[1m]": raw_usage,
                },
                "structured_output": {
                    "summary": "No issues found.",
                    "findings": [],
                    "tested": ["Reviewed adapter tests."],
                    "not_tested": ["Real Claude execution."],
                    "residual_risks": ["None identified."],
                },
            }

            result = adapter.normalize_claude_json(fake, payload)

        provenance = result["reviewer_provenance"]
        self.assertEqual(
            [model["name"] for model in provenance["models"]],
            ["glm-5.2[1m]"],
        )
        self.assertEqual(provenance["models"][0]["source"], "metadata")
        self.assertEqual(provenance["models"][0]["raw_usage"], raw_usage)

    def test_normalize_records_model_name_unknown_when_no_model_is_proven(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            fake = {
                "structured_output": {
                    "summary": "No issues found.",
                    "findings": [],
                    "tested": ["Reviewed adapter tests."],
                    "not_tested": ["Real Claude execution."],
                    "residual_risks": ["None identified."],
                },
            }

            result = adapter.normalize_claude_json(fake, payload)

        self.assertIsNone(result["reviewer_model"])
        provenance = result["reviewer_provenance"]
        self.assertEqual(provenance["models"], [])
        self.assertIsNone(provenance["primary_model"])
        self.assertIn("model_name", provenance["unknowns"])
        self.assertIn("primary_model", provenance["unknowns"])

    def test_build_review_evidence_preserves_reviewer_provenance(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            fake = {
                "modelUsage": {
                    "glm-5.2[1m]": {
                        "inputTokens": 10,
                        "outputTokens": 20,
                    }
                },
                "structured_output": {
                    "summary": "No issues found.",
                    "findings": [],
                    "tested": ["Reviewed adapter tests."],
                    "not_tested": ["Real Claude execution."],
                    "residual_risks": ["None identified."],
                },
            }
            envelope = adapter.normalize_claude_json(fake, payload)

            evidence = adapter.build_review_evidence(envelope)

        self.assertEqual(
            evidence["reviewer_provenance"],
            envelope["reviewer_provenance"],
        )

    def test_normalize_prefers_explicit_model_metadata_over_model_usage(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            fake = {
                "model": "claude-explicit",
                "modelUsage": {
                    "glm-5.2[1m]": {
                        "inputTokens": 10,
                        "outputTokens": 20,
                    }
                },
                "result": {
                    "summary": "No issues found.",
                    "findings": [],
                    "tested": ["Reviewed adapter tests."],
                    "not_tested": ["Real Claude execution."],
                    "residual_risks": ["None identified."],
                },
            }

            result = adapter.normalize_claude_json(fake, payload)

        self.assertEqual(result["reviewer_model"], "claude-explicit")

    def test_normalize_ignores_non_dict_model_usage(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            fake = {
                "modelUsage": [],
                "result": {
                    "summary": "No issues found.",
                    "findings": [],
                    "tested": ["Reviewed adapter tests."],
                    "not_tested": ["Real Claude execution."],
                    "residual_risks": ["None identified."],
                },
            }

            result = adapter.normalize_claude_json(fake, payload)

        self.assertIsNone(result["reviewer_model"])

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

    def test_normalize_prefers_structured_output(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            fake = {
                "result": "Natural language wrapper text.",
                "structured_output": {
                    "summary": "No issues found.",
                    "findings": [],
                    "tested": ["Reviewed embedded diff."],
                    "not_tested": ["Did not run tests."],
                    "residual_risks": ["Smoke review only."],
                },
            }

            result = adapter.normalize_claude_json(fake, payload)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["summary"], "No issues found.")
        self.assertEqual(result["tested"], ["Reviewed embedded diff."])

    def test_normalize_prefers_detected_cli_version_over_output_metadata(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            fake = {
                "cli_version": "stale-output-version",
                "result": {
                    "summary": "No issues found.",
                    "findings": [],
                    "tested": ["Reviewed adapter tests."],
                    "not_tested": ["Real Claude execution."],
                    "residual_risks": ["None identified."],
                },
            }

            result = adapter.normalize_claude_json(
                fake,
                payload,
                reviewer_cli_version="2.1.168 (Claude Code)",
            )

        self.assertEqual(result["reviewer_cli_version"], "2.1.168 (Claude Code)")

    def test_normalize_falls_back_when_structured_output_is_null(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            fake = {
                "structured_output": None,
                "result": json.dumps(
                    {
                        "summary": "No issues found.",
                        "findings": [],
                        "tested": ["Reviewed diff."],
                        "not_tested": ["Real Claude execution."],
                        "residual_risks": ["None identified."],
                    }
                ),
            }

            result = adapter.normalize_claude_json(fake, payload)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["summary"], "No issues found.")

    def test_invalid_tested_item_raises_schema_error(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            fake = {
                "result": {
                    "summary": "No issues found.",
                    "findings": [],
                    "tested": [123],
                    "not_tested": ["Real Claude execution."],
                    "residual_risks": ["None identified."],
                }
            }

            with self.assertRaises(adapter.ReviewSchemaError):
                adapter.normalize_claude_json(fake, payload)

    def test_invalid_finding_line_values_raise_schema_error(self):
        invalid_values = (12.5, "12")
        for line_value in invalid_values:
            with self.subTest(line_value=line_value):
                with tempfile.TemporaryDirectory() as raw:
                    payload = self.make_payload(Path(raw))
                    fake = {
                        "result": {
                            "summary": "One issue found.",
                            "findings": [
                                {
                                    "severity": "medium",
                                    "title": "Invalid line",
                                    "evidence": "Line was not an integer.",
                                    "recommendation": "Return an integer line.",
                                    "line": line_value,
                                }
                            ],
                            "tested": ["Reviewed adapter tests."],
                            "not_tested": ["Real Claude execution."],
                            "residual_risks": ["None identified."],
                        }
                    }

                    with self.assertRaises(adapter.ReviewSchemaError):
                        adapter.normalize_claude_json(fake, payload)

    def test_invalid_finding_line_from_subprocess_returns_schema_invalid(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            stdout = json.dumps(
                {
                    "result": {
                        "summary": "One issue found.",
                        "findings": [
                            {
                                "severity": "medium",
                                "title": "Invalid line",
                                "evidence": "Line was not an integer.",
                                "recommendation": "Return an integer line.",
                                "line": "12",
                            }
                        ],
                        "tested": ["Reviewed adapter tests."],
                        "not_tested": ["Real Claude execution."],
                        "residual_risks": ["None identified."],
                    }
                }
            )
            completed = adapter.subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=stdout,
                stderr="",
            )
            version = adapter.subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="2.1.168 (Claude Code)\n",
                stderr="",
            )

            with mock.patch.object(adapter.shutil, "which", return_value="claude"):
                with mock.patch.object(
                    adapter.subprocess,
                    "run",
                    side_effect=[version, completed],
                ):
                    result = adapter.run_claude_review(payload)

            self.assertEqual(result["status"], "schema_invalid")
            self.assertFalse(result["completed"])
            self.assertEqual(result["reviewer_cli_version"], "2.1.168 (Claude Code)")

    def test_nonzero_authenticated_output_remains_failed(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            completed = adapter.subprocess.CompletedProcess(
                args=[],
                returncode=2,
                stdout="already authenticated but command failed\n",
                stderr="",
            )
            version = adapter.subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="2.1.168 (Claude Code)\n",
                stderr="",
            )

            with mock.patch.object(adapter.shutil, "which", return_value="claude"):
                with mock.patch.object(
                    adapter.subprocess,
                    "run",
                    side_effect=[version, completed],
                ):
                    result = adapter.run_claude_review(payload)

            self.assertEqual(result["status"], "failed")
            self.assertNotIn("reason", result)
            self.assertEqual(result["reviewer_cli_version"], "2.1.168 (Claude Code)")

    def test_nonzero_clear_login_missing_output_returns_auth_missing(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            completed = adapter.subprocess.CompletedProcess(
                args=[],
                returncode=2,
                stdout="",
                stderr="Error: not logged in. Please log in first.\n",
            )
            version = adapter.subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="2.1.168 (Claude Code)\n",
                stderr="",
            )

            with mock.patch.object(adapter.shutil, "which", return_value="claude"):
                with mock.patch.object(
                    adapter.subprocess,
                    "run",
                    side_effect=[version, completed],
                ):
                    result = adapter.run_claude_review(payload)

            self.assertEqual(result["status"], "not_available")
            self.assertEqual(result["reason"], "auth_missing")
            self.assertEqual(result["reviewer_cli_version"], "2.1.168 (Claude Code)")

    def test_detect_claude_cli_version_returns_none_for_unavailable_outputs(self):
        cases = [
            OSError("missing"),
            adapter.subprocess.TimeoutExpired(cmd=["claude", "--version"], timeout=10),
            adapter.subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="failed",
            ),
            adapter.subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ]

        for case in cases:
            with self.subTest(case=type(case).__name__):
                with mock.patch.object(adapter.subprocess, "run", side_effect=[case]):
                    result = adapter.detect_claude_cli_version("claude")

            self.assertIsNone(result)

    def test_run_records_detected_cli_version_and_model_usage_metadata(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            stdout = json.dumps(
                {
                    "modelUsage": {
                        "glm-5.2[1m]": {
                            "inputTokens": 10,
                            "outputTokens": 20,
                        }
                    },
                    "structured_output": {
                        "summary": "No issues found.",
                        "findings": [],
                        "tested": ["Reviewed adapter tests."],
                        "not_tested": ["Real Claude execution."],
                        "residual_risks": ["None identified."],
                    },
                }
            )
            version = adapter.subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="2.1.168 (Claude Code)\n",
                stderr="",
            )
            review = adapter.subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=stdout,
                stderr="",
            )

            with mock.patch.object(adapter.shutil, "which", return_value="claude"):
                with mock.patch.object(
                    adapter.subprocess,
                    "run",
                    side_effect=[version, review],
                ) as run:
                    result = adapter.run_claude_review(payload)

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["reviewer_cli_version"], "2.1.168 (Claude Code)")
            self.assertEqual(result["reviewer_model"], "glm-5.2[1m]")
            self.assertIsNone(result["reviewer_model_version"])
            self.assertEqual(run.call_args_list[0].args[0], ["claude", "--version"])

    def test_run_uses_resolved_claude_executable(self):
        with tempfile.TemporaryDirectory() as raw:
            payload = self.make_payload(Path(raw))
            stdout = json.dumps(
                {
                    "result": {
                        "summary": "No issues found.",
                        "findings": [],
                        "tested": ["Reviewed adapter tests."],
                        "not_tested": ["Real Claude execution."],
                        "residual_risks": ["None identified."],
                    }
                }
            )
            completed = adapter.subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=stdout,
                stderr="",
            )
            resolved_claude = r"C:\Tools\claude.cmd"

            with mock.patch.object(adapter.shutil, "which", return_value=resolved_claude):
                version = adapter.subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout="2.1.168 (Claude Code)\n",
                    stderr="",
                )
                with mock.patch.object(
                    adapter.subprocess,
                    "run",
                    side_effect=[version, completed],
                ) as run:
                    result = adapter.run_claude_review(payload)

            self.assertEqual(result["status"], "passed")
            command = run.call_args_list[1].args[0]
            self.assertEqual(command[0], resolved_claude)
            self.assertEqual(run.call_args_list[1].kwargs["encoding"], "utf-8")
            self.assertEqual(run.call_args_list[1].kwargs["errors"], "replace")
            self.assertIn("TASK_CONTENT", run.call_args_list[1].kwargs["input"])
            self.assertNotIn("TASK_CONTENT", " ".join(command))
            self.assertIn("--system-prompt", command)
            self.assertIn("--json-schema", command)
            self.assertEqual(command[command.index("--permission-mode") + 1], "plan")

            schema = json.loads(command[command.index("--json-schema") + 1])
            self.assertEqual(
                schema["required"],
                ["summary", "findings", "tested", "not_tested", "residual_risks"],
            )


if __name__ == "__main__":
    unittest.main()
