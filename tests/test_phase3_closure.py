import json
import tempfile
import unittest
from pathlib import Path

from harness import cli


ROOT = Path(__file__).resolve().parents[1]


def minimal_state(status: str = "reviewed") -> dict:
    return {
        "run_id": "phase3-test",
        "harness_version": "0.1.0",
        "state_schema_version": "0.1.0",
        "status": status,
        "track": "Standard",
        "current_workflow": "standard-code-change",
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


def write_state(run_dir: Path, state: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "state.json").write_text(
        json.dumps(state, indent=2) + "\n",
        encoding="utf-8",
    )


def complete_evidence(run_dir: Path) -> list[dict]:
    return [
        {
            "type": "verification",
            "path": "verification.md",
            "description": "Verification evidence.",
        },
        {
            "type": "handoff",
            "path": "handoff.md",
            "description": "Handoff evidence.",
        },
        {
            "type": "review",
            "path": "review.md",
            "description": "Review evidence.",
        },
    ]


def write_artifacts(run_dir: Path, *, handoff_text: str) -> None:
    (run_dir / "verification.md").write_text("# Verification\n", encoding="utf-8")
    (run_dir / "review.md").write_text("# Review\n", encoding="utf-8")
    (run_dir / "handoff.md").write_text(handoff_text, encoding="utf-8")


def complete_handoff(memory_update: str = "none", memory_files: list[str] | None = None) -> str:
    memory_files = memory_files if memory_files is not None else []
    if memory_files:
        # Block sequence: `memory_files:` then an indented item per entry.
        memory_files_line = "memory_files:\n" + "\n".join(
            f'  - "{entry}"' for entry in memory_files
        )
    else:
        memory_files_line = "memory_files: []"
    return f"""---
run_id: phase3-test
schema_version: 0.1.0
changed:
  - "Added review decision schema and gates."
verified:
  - "Unit tests cover schema and gates."
not_verified: []
residual_risks: []
next_step: "Merge to master."
memory_update: {memory_update}
{memory_files_line}
---

# Handoff
"""


class HandoffClosureTest(unittest.TestCase):
    def test_advance_to_completed_requires_handoff_closure_fields(self):
        required = ("changed", "verified", "not_verified", "residual_risks", "next_step")
        for missing in required:
            with tempfile.TemporaryDirectory(dir=ROOT) as raw:
                run_dir = Path(raw)
                state = minimal_state(status="reviewed")
                state["evidence"] = complete_evidence(run_dir)
                write_state(run_dir, state)
                full = complete_handoff()
                # Strip one field line to force its absence.
                marker = f"{missing}:"
                stripped = "\n".join(
                    line for line in full.splitlines() if not line.lstrip().startswith(marker)
                )
                write_artifacts(run_dir, handoff_text=stripped)

                with self.subTest(missing=missing):
                    with self.assertRaises(cli.HarnessCliError) as raised:
                        cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

            self.assertIn(f"handoff frontmatter missing field: {missing}", str(raised.exception))

    def test_advance_to_completed_fails_when_memory_update_lacks_files(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="reviewed")
            state["evidence"] = complete_evidence(run_dir)
            write_state(run_dir, state)
            write_artifacts(run_dir, handoff_text=complete_handoff(memory_update="updated"))

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertIn("memory_update is updated but memory_files is empty", str(raised.exception))

    def test_advance_to_completed_fails_when_listed_memory_file_missing(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="reviewed")
            state["evidence"] = complete_evidence(run_dir)
            write_state(run_dir, state)
            write_artifacts(
                run_dir,
                handoff_text=complete_handoff(
                    memory_update="updated",
                    memory_files=["harness/memory/does-not-exist.md"],
                ),
            )

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertIn("memory file does not exist", str(raised.exception))

    def test_advance_to_completed_allows_consistent_handoff(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="reviewed")
            state["evidence"] = complete_evidence(run_dir)
            write_state(run_dir, state)
            (run_dir / "verification.md").write_text("# Verification\n", encoding="utf-8")
            (run_dir / "review.md").write_text("# Review\n", encoding="utf-8")
            (run_dir / "handoff.md").write_text(
                complete_handoff(memory_update="none"),
                encoding="utf-8",
            )

            advanced = cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertEqual(advanced["status"], "completed")


if __name__ == "__main__":
    unittest.main()
