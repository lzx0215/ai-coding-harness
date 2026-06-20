# Phase 2 Run Definition and Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Phase 2 run definition, Markdown frontmatter readiness checks, and helper CLI commands without changing `validate` or `advance` authority boundaries.

**Architecture:** Add a focused `harness/readiness.py` module for frontmatter parsing and advisory readiness checks. Keep state/evidence authority in `harness/cli.py`: `validate` remains the fatal evidence validator, `advance` remains the only transition writer, and helper commands only create draft runs, append candidate evidence through existing validation, or report non-mutating readiness warnings.

**Tech Stack:** Python standard library, `unittest`, existing `jsonschema` validation, existing `harness.cli` state helpers.

---

## Scope

Implement Phase 2 only.

In scope:

- Constrained YAML frontmatter parser for Harness Markdown artifacts.
- Readiness warning checks for `task.md`, `triage.md`, `plan.md`, and `handoff.md`.
- Template frontmatter updates.
- New `check-ready`, `index-evidence`, and `init-run` CLI commands.
- Tests proving helper commands do not bypass `validate` or mutate state unexpectedly.

Out of scope:

- Phase 3 `review-decision.json`.
- `harness/schemas/review-decision.schema.json`.
- New Harness states.
- New evidence types.
- Hard `draft -> triaged` or `triaged -> planned` stage gates inside `advance`.
- Any change that makes missing historical frontmatter a fatal `validate` error.

## File Structure

- Create `harness/readiness.py`
  - Owns constrained frontmatter parsing.
  - Owns advisory readiness warnings.
  - Does not write files.
  - Does not decide evidence validity.

- Modify `harness/cli.py`
  - Import readiness helpers.
  - Add `check-ready`, `index-evidence`, and `init-run` commands.
  - Keep `validate_run`, `validate_state`, `validate_evidence_paths`, and `advance_run` authority unchanged.

- Modify `harness/templates/task.md`
  - Add Phase 2 YAML frontmatter.

- Modify `harness/templates/plan.md`
  - Add Phase 2 YAML frontmatter.

- Modify `harness/templates/handoff.md`
  - Add Phase 2 YAML frontmatter.

- Create `harness/templates/triage.md`
  - Add Phase 2 YAML frontmatter and readable sections.

- Create `tests/test_phase2_readiness.py`
  - Tests frontmatter parser, readiness warnings, template structure, and non-mutating `check-ready` behavior.

- Modify `tests/test_harness_cli.py`
  - Tests CLI command behavior for `init-run`, `index-evidence`, and `check-ready`.

---

### Task 1: Add Frontmatter Parser and Readiness Warnings

**Files:**
- Create: `harness/readiness.py`
- Create: `tests/test_phase2_readiness.py`

- [ ] **Step 1: Write failing parser tests**

Add this file:

```python
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
```

- [ ] **Step 2: Run parser tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_phase2_readiness -v
```

Expected: FAIL because `harness.readiness` does not exist.

- [ ] **Step 3: Add `harness/readiness.py`**

Create `harness/readiness.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


RUN_DOCUMENTS = ("task.md", "triage.md", "plan.md", "handoff.md")


@dataclass(frozen=True)
class FrontmatterResult:
    data: dict[str, Any]
    warnings: list[str]


@dataclass(frozen=True)
class ReadinessReport:
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.warnings


def parse_frontmatter(text: str) -> FrontmatterResult:
    if not text.startswith("---\n"):
        return FrontmatterResult({}, ["missing frontmatter block"])

    end_marker = "\n---\n"
    end_index = text.find(end_marker, 4)
    if end_index == -1:
        return FrontmatterResult({}, ["unterminated frontmatter block"])

    raw_lines = text[4:end_index].splitlines()
    data: dict[str, Any] = {}
    warnings: list[str] = []
    index = 0
    while index < len(raw_lines):
        line = raw_lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith(" "):
            warnings.append(f"unsupported frontmatter line: {line}")
            index += 1
            continue
        if ":" not in line:
            warnings.append(f"unsupported frontmatter line: {line}")
            index += 1
            continue

        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            warnings.append(f"unsupported frontmatter line: {line}")
            index += 1
            continue

        if raw_value:
            data[key] = parse_scalar(raw_value)
            index += 1
            continue

        nested, consumed, nested_warnings = parse_nested_block(raw_lines[index + 1 :])
        warnings.extend(nested_warnings)
        data[key] = nested
        index += consumed + 1

    return FrontmatterResult(data, warnings)


def parse_nested_block(lines: list[str]) -> tuple[Any, int, list[str]]:
    warnings: list[str] = []
    items: list[str] = []
    mapping: dict[str, Any] = {}
    consumed = 0
    mode: str | None = None

    for line in lines:
        if not line.strip():
            consumed += 1
            continue
        if not line.startswith("  "):
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            if mode == "map":
                warnings.append("mixed frontmatter sequence and map values are unsupported")
            mode = "list"
            items.append(parse_scalar(stripped[2:]))
            consumed += 1
            continue
        if ":" in stripped:
            if mode == "list":
                warnings.append("mixed frontmatter sequence and map values are unsupported")
            mode = "map"
            child_key, child_value = stripped.split(":", 1)
            child_key = child_key.strip()
            child_value = child_value.strip()
            if not child_value:
                warnings.append("unsupported frontmatter nesting")
                consumed += 1
                continue
            mapping[child_key] = parse_scalar(child_value)
            consumed += 1
            continue
        warnings.append(f"unsupported frontmatter line: {line}")
        consumed += 1

    if mode == "map":
        return mapping, consumed, warnings
    return items, consumed, warnings


def parse_scalar(value: str) -> Any:
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if (
        (value.startswith('"') and value.endswith('"'))
        or (value.startswith("'") and value.endswith("'"))
    ):
        return value[1:-1]
    return value


def check_run_readiness(run_dir: Path, state: dict[str, Any]) -> ReadinessReport:
    warnings: list[str] = []
    for document_name in RUN_DOCUMENTS:
        path = run_dir / document_name
        if not path.exists():
            warnings.append(f"missing run document: {document_name}")
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            warnings.append(f"cannot read run document {document_name}: {exc}")
            continue

        result = parse_frontmatter(text)
        warnings.extend(f"{document_name}: {warning}" for warning in result.warnings)
        warnings.extend(validate_document_frontmatter(document_name, result.data, state))

    return ReadinessReport(warnings)


def validate_document_frontmatter(
    document_name: str,
    data: dict[str, Any],
    state: dict[str, Any],
) -> list[str]:
    if not data:
        return []

    warnings: list[str] = []
    state_run_id = state.get("run_id")
    if data.get("run_id") != state_run_id:
        warnings.append(
            f"{document_name} frontmatter run_id {data.get('run_id')} "
            f"does not match state run_id {state_run_id}"
        )

    if "track" in data and data.get("track") != state.get("track"):
        warnings.append(
            f"{document_name} frontmatter track {data.get('track')} "
            f"does not match state track {state.get('track')}"
        )

    if "workflow" in data and data.get("workflow") != state.get("current_workflow"):
        warnings.append(
            f"{document_name} frontmatter workflow {data.get('workflow')} "
            f"does not match state workflow {state.get('current_workflow')}"
        )

    return warnings
```

- [ ] **Step 4: Run parser tests to verify they pass**

Run:

```powershell
python -m unittest tests.test_phase2_readiness -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```powershell
git add harness/readiness.py tests/test_phase2_readiness.py
git commit -m "feat: add phase 2 readiness checks"
```

---

### Task 2: Add Phase 2 Frontmatter to Templates

**Files:**
- Modify: `harness/templates/task.md`
- Modify: `harness/templates/plan.md`
- Modify: `harness/templates/handoff.md`
- Create: `harness/templates/triage.md`
- Modify: `tests/test_phase2_readiness.py`

- [ ] **Step 1: Add failing template tests**

Append this test class to `tests/test_phase2_readiness.py`:

```python
class Phase2TemplateTest(unittest.TestCase):
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

    def test_handoff_template_declares_phase3_memory_fields(self):
        text = (ROOT / "harness" / "templates" / "handoff.md").read_text(
            encoding="utf-8",
        )
        result = readiness.parse_frontmatter(text)

        self.assertEqual(result.data["memory_update"], "none")
        self.assertEqual(result.data["memory_files"], [])
```

- [ ] **Step 2: Run template tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_phase2_readiness.Phase2TemplateTest -v
```

Expected: FAIL because templates do not yet contain Phase 2 frontmatter and `triage.md` does not exist.

- [ ] **Step 3: Update `harness/templates/task.md`**

Replace the file with:

```markdown
---
run_id: ""
schema_version: 0.1.0
track: Standard
workflow: standard-doc-system-change
owner: codex
requested_outcome: ""
scope: []
non_goals: []
constraints: []
---

# Task

## Goal

## Track

## Workflow

## Scope

## Non-goals

## Acceptance Criteria

## Verification Plan

## Risks
```

- [ ] **Step 4: Create `harness/templates/triage.md`**

```markdown
---
run_id: ""
schema_version: 0.1.0
track: Standard
workflow: standard-doc-system-change
review_required: true
strict_triggers: []
risk_reasons: []
verification_required: []
---

# Triage

## Track Decision

## Workflow

## Risk Reasons

## Review Requirement

## Verification Required
```

- [ ] **Step 5: Update `harness/templates/plan.md`**

Replace the file with:

```markdown
---
run_id: ""
schema_version: 0.1.0
workflow: standard-doc-system-change
acceptance: []
verification: []
review_plan: []
constraints: []
recovery_strategy: null
residual_risk_owner: null
---

# Plan

## Goal

## Files

## Steps

## Verification

## Rollback
```

- [ ] **Step 6: Update `harness/templates/handoff.md`**

Replace the file with:

```markdown
---
run_id: ""
schema_version: 0.1.0
changed: []
verified: []
not_verified: []
residual_risks: []
next_step: ""
memory_update: none
memory_files: []
---

# Handoff

## What Changed

## Evidence

## State

## Risks

## Next Step
```

- [ ] **Step 7: Run template tests to verify they pass**

Run:

```powershell
python -m unittest tests.test_phase2_readiness.Phase2TemplateTest -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```powershell
git add harness/templates/task.md harness/templates/triage.md harness/templates/plan.md harness/templates/handoff.md tests/test_phase2_readiness.py
git commit -m "docs: add phase 2 run artifact templates"
```

---

### Task 3: Add Non-Mutating `check-ready` CLI Command

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_harness_cli.py`

- [ ] **Step 1: Add failing CLI tests**

Add these tests inside `HarnessCliTest` in `tests/test_harness_cli.py`:

```python
    def test_check_ready_reports_warnings_without_mutating_state(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_state(run_dir, minimal_state(status="draft"))
            before = (run_dir / "state.json").read_text(encoding="utf-8")

            result = subprocess.run(
                [sys.executable, "-m", "harness.cli", "check-ready", str(run_dir)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            after = (run_dir / "state.json").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(before, after)
        self.assertIn("missing run document: task.md", result.stdout)

    def test_check_ready_returns_zero_when_no_warnings(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="draft")
            state["track"] = "Standard"
            state["current_workflow"] = "standard-doc-system-change"
            write_state(run_dir, state)
            for name in ("task.md", "triage.md", "plan.md", "handoff.md"):
                (run_dir / name).write_text(
                    f"""---
run_id: test-run
schema_version: 0.1.0
track: Standard
workflow: standard-doc-system-change
---

# {name}
""",
                    encoding="utf-8",
                )

            result = subprocess.run(
                [sys.executable, "-m", "harness.cli", "check-ready", str(run_dir)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("ready: no readiness warnings", result.stdout)
```

- [ ] **Step 2: Run CLI readiness tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_check_ready_reports_warnings_without_mutating_state tests.test_harness_cli.HarnessCliTest.test_check_ready_returns_zero_when_no_warnings -v
```

Expected: FAIL because `check-ready` is not registered.

- [ ] **Step 3: Import readiness helpers in `harness/cli.py`**

Add near existing imports:

```python
from harness import readiness
```

- [ ] **Step 4: Add command function in `harness/cli.py`**

Add after `advance_run`:

```python
def check_ready(run_dir: Path | str, *, root: Path = ROOT) -> readiness.ReadinessReport:
    resolved_run_dir = Path(run_dir)
    validation = validate_run(resolved_run_dir, root=root)
    if not validation.ok:
        raise HarnessCliError(format_errors(validation.errors))

    try:
        state = load_json(state_path(resolved_run_dir))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HarnessCliError(f"cannot read state file: {exc}") from exc

    return readiness.check_run_readiness(resolved_run_dir, state)
```

- [ ] **Step 5: Register parser branch**

In `build_parser`, add before `advance`:

```python
    check_ready_parser = subparsers.add_parser(
        "check-ready",
        help="Report non-mutating Phase 2 readiness warnings for a Harness run.",
    )
    check_ready_parser.add_argument("run_dir")
```

In `main`, add before the `advance` branch:

```python
        if args.command == "check-ready":
            report = check_ready(args.run_dir)
            if report.warnings:
                print(format_errors(report.warnings))
                return 1
            print("ready: no readiness warnings")
            return 0
```

- [ ] **Step 6: Run CLI readiness tests to verify they pass**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_check_ready_reports_warnings_without_mutating_state tests.test_harness_cli.HarnessCliTest.test_check_ready_returns_zero_when_no_warnings -v
```

Expected: PASS.

- [ ] **Step 7: Run parser and CLI readiness tests together**

Run:

```powershell
python -m unittest tests.test_phase2_readiness tests.test_harness_cli.HarnessCliTest.test_check_ready_reports_warnings_without_mutating_state tests.test_harness_cli.HarnessCliTest.test_check_ready_returns_zero_when_no_warnings -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```powershell
git add harness/cli.py tests/test_harness_cli.py
git commit -m "feat: add phase 2 check-ready command"
```

---

### Task 4: Add `index-evidence` CLI Command Through Existing Validation

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_harness_cli.py`

- [ ] **Step 1: Add failing `index-evidence` tests**

Add these tests inside `HarnessCliTest`:

```python
    def test_index_evidence_appends_valid_evidence_without_advancing_state(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_state(run_dir, minimal_state(status="draft"))
            evidence_path = run_dir / "task.md"
            evidence_path.write_text("# Task\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "index-evidence",
                    str(run_dir),
                    "task",
                    "task.md",
                    "--description",
                    "Task definition.",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            saved = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(saved["status"], "draft")
        self.assertEqual(
            saved["evidence"],
            [
                {
                    "type": "task",
                    "path": "task.md",
                    "description": "Task definition.",
                }
            ],
        )

    def test_index_evidence_rejects_unknown_type_without_writing(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_state(run_dir, minimal_state(status="draft"))
            (run_dir / "note.md").write_text("# Note\n", encoding="utf-8")
            before = (run_dir / "state.json").read_text(encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "index-evidence",
                    str(run_dir),
                    "invented-evidence",
                    "note.md",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            after = (run_dir / "state.json").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(before, after)
        self.assertIn("unknown evidence type", result.stdout)

    def test_index_evidence_rejects_missing_path_without_writing(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_state(run_dir, minimal_state(status="draft"))
            before = (run_dir / "state.json").read_text(encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "index-evidence",
                    str(run_dir),
                    "task",
                    "missing.md",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            after = (run_dir / "state.json").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(before, after)
        self.assertIn("evidence path does not exist", result.stdout)
```

- [ ] **Step 2: Run `index-evidence` tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_index_evidence_appends_valid_evidence_without_advancing_state tests.test_harness_cli.HarnessCliTest.test_index_evidence_rejects_unknown_type_without_writing tests.test_harness_cli.HarnessCliTest.test_index_evidence_rejects_missing_path_without_writing -v
```

Expected: FAIL because `index-evidence` is not registered.

- [ ] **Step 3: Add `index_evidence` implementation**

Add after `check_ready` in `harness/cli.py`:

```python
def index_evidence(
    run_dir: Path | str,
    evidence_type: str,
    evidence_path: str,
    *,
    description: str | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    resolved_run_dir = Path(run_dir)
    validation = validate_run(resolved_run_dir, root=root)
    if not validation.ok:
        raise HarnessCliError(format_errors(validation.errors))

    path = state_path(resolved_run_dir)
    try:
        state = load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HarnessCliError(f"cannot read state file: {exc}") from exc

    entry = {"type": evidence_type, "path": evidence_path}
    if description:
        entry["description"] = description

    candidate = dict(state)
    candidate["evidence"] = list(state.get("evidence", [])) + [entry]
    candidate["updated_at"] = utc_now()

    candidate_errors = validate_state(candidate, root=root, run_dir=resolved_run_dir)
    if candidate_errors:
        raise HarnessCliError(format_errors(candidate_errors))

    write_json_atomic(path, candidate)
    return candidate
```

- [ ] **Step 4: Register parser branch**

In `build_parser`, add:

```python
    index_evidence_parser = subparsers.add_parser(
        "index-evidence",
        help="Append an evidence entry after existing validation accepts it.",
    )
    index_evidence_parser.add_argument("run_dir")
    index_evidence_parser.add_argument("evidence_type")
    index_evidence_parser.add_argument("path")
    index_evidence_parser.add_argument("--description")
```

In `main`, add:

```python
        if args.command == "index-evidence":
            state = index_evidence(
                args.run_dir,
                args.evidence_type,
                args.path,
                description=args.description,
            )
            print(f"indexed evidence: {state['run_id']} {args.evidence_type} {args.path}")
            return 0
```

- [ ] **Step 5: Run `index-evidence` tests to verify they pass**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_index_evidence_appends_valid_evidence_without_advancing_state tests.test_harness_cli.HarnessCliTest.test_index_evidence_rejects_unknown_type_without_writing tests.test_harness_cli.HarnessCliTest.test_index_evidence_rejects_missing_path_without_writing -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```powershell
git add harness/cli.py tests/test_harness_cli.py
git commit -m "feat: add evidence indexing helper"
```

---

### Task 5: Add `init-run` CLI Command

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_harness_cli.py`

- [ ] **Step 1: Add failing `init-run` test**

Add this test inside `HarnessCliTest`:

```python
    def test_init_run_creates_draft_run_with_phase2_documents(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            parent = Path(raw)
            run_dir = parent / "phase2-created-run"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "init-run",
                    str(run_dir),
                    "--run-id",
                    "phase2-created-run",
                    "--track",
                    "Standard",
                    "--workflow",
                    "standard-doc-system-change",
                    "--base-commit",
                    "HEAD",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            validation = cli.validate_run(run_dir, root=ROOT)

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(validation.errors, [])
        self.assertEqual(state["status"], "draft")
        self.assertEqual(state["run_id"], "phase2-created-run")
        self.assertEqual(state["track"], "Standard")
        self.assertEqual(state["current_workflow"], "standard-doc-system-change")
        self.assertEqual(
            [entry["type"] for entry in state["evidence"]],
            ["task", "triage", "plan"],
        )
        self.assertTrue((run_dir / "task.md").exists())
        self.assertTrue((run_dir / "triage.md").exists())
        self.assertTrue((run_dir / "plan.md").exists())
        self.assertTrue((run_dir / "handoff.md").exists())

    def test_init_run_refuses_existing_directory(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw) / "existing"
            run_dir.mkdir()

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "init-run",
                    str(run_dir),
                    "--run-id",
                    "existing",
                    "--track",
                    "Fast",
                    "--workflow",
                    "fast-doc-change",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn("run directory already exists", result.stdout)
```

- [ ] **Step 2: Run `init-run` tests to verify they fail**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_init_run_creates_draft_run_with_phase2_documents tests.test_harness_cli.HarnessCliTest.test_init_run_refuses_existing_directory -v
```

Expected: FAIL because `init-run` is not registered.

- [ ] **Step 3: Add template rendering helpers**

Add after `index_evidence` in `harness/cli.py`:

```python
TEMPLATE_DIR = ROOT / "harness" / "templates"


def render_template(template_name: str, replacements: dict[str, str]) -> str:
    text = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(key, value)
    return text


def frontmatter_text_for_run(
    template_name: str,
    *,
    run_id: str,
    track: str,
    workflow: str,
) -> str:
    text = render_template(
        template_name,
        {
            'run_id: ""': f"run_id: {run_id}",
            "track: Standard": f"track: {track}",
            "workflow: standard-doc-system-change": f"workflow: {workflow}",
        },
    )
    return text
```

- [ ] **Step 4: Add `init_run` implementation**

Add after the template helpers:

```python
def init_run(
    run_dir: Path | str,
    *,
    run_id: str,
    track: str,
    workflow: str,
    base_commit: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    resolved_run_dir = Path(run_dir)
    if resolved_run_dir.exists():
        raise HarnessCliError(f"run directory already exists: {resolved_run_dir}")

    resolved_run_dir.mkdir(parents=True)
    created_at = utc_now()
    state = {
        "run_id": run_id,
        "harness_version": "0.2.0",
        "state_schema_version": "0.2.0",
        "status": "draft",
        "track": track,
        "current_workflow": workflow,
        "owner": CODEX_ACTOR,
        "base_commit": base_commit,
        "created_at": created_at,
        "updated_at": created_at,
        "external_agents": [
            {
                "name": "claude-code",
                "role": "reviewer",
                "state_access": "none",
                "status": "not_requested",
            }
        ],
        "evidence": [
            {
                "type": "task",
                "path": "task.md",
                "description": "Task definition.",
            },
            {
                "type": "triage",
                "path": "triage.md",
                "description": "Task triage.",
            },
            {
                "type": "plan",
                "path": "plan.md",
                "description": "Implementation plan.",
            },
        ],
    }

    for template_name in ("task.md", "triage.md", "plan.md", "handoff.md"):
        (resolved_run_dir / template_name).write_text(
            frontmatter_text_for_run(
                template_name,
                run_id=run_id,
                track=track,
                workflow=workflow,
            ),
            encoding="utf-8",
        )

    write_json_file(state_path(resolved_run_dir), state)
    validation = validate_run(resolved_run_dir, root=root)
    if not validation.ok:
        raise HarnessCliError(format_errors(validation.errors))
    return state
```

Rationale: `handoff.md` is created for the run record but is not indexed as `handoff` evidence at creation time. This avoids letting a placeholder handoff satisfy completion evidence.

- [ ] **Step 5: Register parser branch**

In `build_parser`, add:

```python
    init_run_parser = subparsers.add_parser(
        "init-run",
        help="Create a draft Harness run with Phase 2 run documents.",
    )
    init_run_parser.add_argument("run_dir")
    init_run_parser.add_argument("--run-id", required=True)
    init_run_parser.add_argument("--track", required=True, choices=["Fast", "Standard", "Strict"])
    init_run_parser.add_argument("--workflow", required=True)
    init_run_parser.add_argument("--base-commit", default="HEAD")
```

In `main`, add:

```python
        if args.command == "init-run":
            state = init_run(
                args.run_dir,
                run_id=args.run_id,
                track=args.track,
                workflow=args.workflow,
                base_commit=args.base_commit,
            )
            print(f"initialized run: {state['run_id']} -> {state['status']}")
            return 0
```

- [ ] **Step 6: Run `init-run` tests to verify they pass**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_init_run_creates_draft_run_with_phase2_documents tests.test_harness_cli.HarnessCliTest.test_init_run_refuses_existing_directory -v
```

Expected: PASS.

- [ ] **Step 7: Run all Phase 2 tests**

Run:

```powershell
python -m unittest tests.test_phase2_readiness tests.test_harness_cli.HarnessCliTest.test_check_ready_reports_warnings_without_mutating_state tests.test_harness_cli.HarnessCliTest.test_check_ready_returns_zero_when_no_warnings tests.test_harness_cli.HarnessCliTest.test_index_evidence_appends_valid_evidence_without_advancing_state tests.test_harness_cli.HarnessCliTest.test_index_evidence_rejects_unknown_type_without_writing tests.test_harness_cli.HarnessCliTest.test_index_evidence_rejects_missing_path_without_writing tests.test_harness_cli.HarnessCliTest.test_init_run_creates_draft_run_with_phase2_documents tests.test_harness_cli.HarnessCliTest.test_init_run_refuses_existing_directory -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 5**

```powershell
git add harness/cli.py tests/test_harness_cli.py
git commit -m "feat: add phase 2 run initialization"
```

---

### Task 6: Final Verification

**Files:**
- None.

- [ ] **Step 1: Run full test suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass, with the existing opt-in pip hash validation test skipped unless `HARNESS_RUN_PIP_HASH_CHECK=1` is set.

- [ ] **Step 2: Validate historical runs**

Run:

```powershell
python -m harness.cli validate harness/runs/example-fast-doc-change
python -m harness.cli validate harness/runs/2026-06-19-standard-adapter-cli
python -m harness.cli validate harness/runs/2026-06-19-v0.1.1-audit-closure
python -m harness.cli validate harness/runs/2026-06-19-v0.2-implementation-plan
python -m harness.cli validate harness/runs/2026-06-19-v0.2-plan-amendment
python -m harness.cli validate harness/runs/2026-06-19-v0.2-reviewer-provenance-design
python -m harness.cli validate harness/runs/2026-06-19-v0.2-reviewer-provenance-implementation
python -m harness.cli validate harness/runs/2026-06-19-v0.2-spec-amendment
```

Expected: every command prints `valid: <run-dir>` and exits 0. This proves historical runs still validate without Markdown frontmatter migration.

- [ ] **Step 3: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected: exit 0. Windows LF-to-CRLF warnings may appear in prior commands and do not fail this check.

- [ ] **Step 4: Confirm the implementation branch is clean after committed task work**

```powershell
git status --short
```

Expected: no output after all task commits are created.

---

## Self-Review Checklist

- Phase 2 helper commands do not define evidence validity.
- `validate` remains the fatal state and evidence authority.
- `advance` remains the only state transition authority.
- `check-ready` is non-mutating and advisory.
- Missing historical Markdown frontmatter is not a fatal `validate` error.
- `init-run` does not index placeholder `handoff.md` as completion evidence.
- Phase 3 `review-decision.json` is not implemented in this plan.
- Full test suite and historical run validation are required before completion.
