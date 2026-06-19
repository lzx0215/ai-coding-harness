# Phase 1 Local Run Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Phase 1 local run closure hardening so Harness validates evidence types and blocks incomplete `completed` transitions.

**Architecture:** Keep `harness.cli advance` as the only state transition path. Add evidence type validation to `validate_state`, add a track-aware completion evidence gate to `advance_run(..., "completed")`, and add a risk-acceptance evidence template.

**Tech Stack:** Python standard library, `jsonschema`, `unittest`, Markdown Harness docs.

---

## File Structure

- Modify `harness/cli.py`
  - Owns evidence type vocabulary.
  - Owns evidence path validation.
  - Owns completion evidence validation.
  - Owns state advancement.
- Modify `tests/test_harness_cli.py`
  - Unit tests for evidence type validation.
  - Unit tests for track-aware completion gates.
  - Unit tests for risk acceptance completion.
  - Historical run validation coverage.
- Modify `tests/test_static_contracts.py`
  - Static test that the risk acceptance template exists and has required sections.
- Create `harness/templates/risk-acceptance.md`
  - Copyable evidence template for user-approved residual risk.

Do not implement Phase 4 job artifacts in this plan.

## Task 1: Evidence Type Vocabulary

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_harness_cli.py`

- [ ] **Step 1: Add failing tests for evidence type validation**

In `tests/test_harness_cli.py`, add these helpers after `write_state`:

```python
def historical_run_dirs() -> list[Path]:
    return sorted(
        path for path in (ROOT / "harness" / "runs").iterdir()
        if path.is_dir()
    )
```

In `HarnessCliTest`, add:

```python
    def test_validate_accepts_all_existing_run_directories(self):
        errors_by_run = {}
        for run_dir in historical_run_dirs():
            result = cli.validate_run(run_dir, root=ROOT)
            if result.errors:
                errors_by_run[str(run_dir.relative_to(ROOT))] = result.errors

        self.assertEqual(errors_by_run, {})

    def test_evidence_type_vocabulary_matches_phase_1_contract(self):
        self.assertEqual(
            cli.EVIDENCE_TYPES,
            frozenset(
                {
                    "task",
                    "triage",
                    "plan",
                    "design-spec",
                    "implementation-plan",
                    "diff",
                    "changed-files",
                    "diff-meta",
                    "verification",
                    "review-input",
                    "review-output",
                    "review-evidence",
                    "review-raw-log",
                    "review",
                    "review-waiver",
                    "risk-acceptance",
                    "handoff",
                }
            ),
        )

    def test_validate_rejects_unknown_evidence_type(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="verified")
            state["evidence"] = [
                {
                    "type": "invented-evidence",
                    "path": "README.md",
                    "description": "Uses an unsupported evidence type.",
                }
            ]
            write_state(run_dir, state)

            result = cli.validate_run(run_dir, root=ROOT)

        self.assertTrue(
            any("unknown evidence type" in error for error in result.errors),
            result.errors,
        )
```

- [ ] **Step 2: Run the new failing tests**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_evidence_type_vocabulary_matches_phase_1_contract tests.test_harness_cli.HarnessCliTest.test_validate_rejects_unknown_evidence_type tests.test_harness_cli.HarnessCliTest.test_validate_accepts_all_existing_run_directories -v
```

Expected: failure because `cli.EVIDENCE_TYPES` and evidence type validation do not exist.

- [ ] **Step 3: Implement the evidence type vocabulary**

In `harness/cli.py`, add after `CODEX_ACTOR = "codex"`:

```python
EVIDENCE_TYPES = frozenset(
    {
        "task",
        "triage",
        "plan",
        "design-spec",
        "implementation-plan",
        "diff",
        "changed-files",
        "diff-meta",
        "verification",
        "review-input",
        "review-output",
        "review-evidence",
        "review-raw-log",
        "review",
        "review-waiver",
        "risk-acceptance",
        "handoff",
    }
)
```

Add this function after `validate_state`:

```python
def validate_evidence_types(state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for index, evidence in enumerate(state.get("evidence", [])):
        evidence_type = evidence.get("type")
        if not isinstance(evidence_type, str):
            continue
        if evidence_type not in EVIDENCE_TYPES:
            errors.append(
                f"unknown evidence type at evidence[{index}]: {evidence_type}",
            )
    return errors
```

Update `validate_state` so it calls evidence type validation before path validation:

```python
    errors.extend(validate_evidence_types(state))
    errors.extend(validate_evidence_paths(state, root=root, run_dir=run_dir))
    return errors
```

- [ ] **Step 4: Run the evidence type tests again**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_evidence_type_vocabulary_matches_phase_1_contract tests.test_harness_cli.HarnessCliTest.test_validate_rejects_unknown_evidence_type tests.test_harness_cli.HarnessCliTest.test_validate_accepts_all_existing_run_directories -v
```

Expected: exit 0 and all three tests pass.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add harness/cli.py tests/test_harness_cli.py
git commit -m "feat(harness): validate evidence type vocabulary"
```

## Task 2: Completion Evidence Gate

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_harness_cli.py`

- [ ] **Step 1: Add test helpers for completion evidence**

In `tests/test_harness_cli.py`, add after `write_state`:

```python
def evidence_entry(run_dir: Path, evidence_type: str) -> dict:
    path = run_dir / f"{evidence_type}.md"
    path.write_text(f"# {evidence_type}\n", encoding="utf-8")
    return {
        "type": evidence_type,
        "path": str(path.relative_to(ROOT)),
        "description": f"{evidence_type} evidence.",
    }


def state_for_workflow(
    *,
    status: str,
    track: str,
    workflow: str,
    evidence_types: list[str],
    run_dir: Path,
) -> dict:
    state = minimal_state(status=status)
    state["track"] = track
    state["current_workflow"] = workflow
    state["evidence"] = [
        evidence_entry(run_dir, evidence_type)
        for evidence_type in evidence_types
    ]
    return state
```

- [ ] **Step 2: Add failing tests for Fast and Standard completion**

In `HarnessCliTest`, add:

```python
    def test_advance_allows_fast_completion_without_review_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = state_for_workflow(
                status="reviewed",
                track="Fast",
                workflow="fast-doc-change",
                evidence_types=["verification", "handoff"],
                run_dir=run_dir,
            )
            write_state(run_dir, state)

            advanced = cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertEqual(advanced["status"], "completed")

    def test_advance_allows_standard_completion_with_review_handling(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = state_for_workflow(
                status="reviewed",
                track="Standard",
                workflow="standard-doc-system-change",
                evidence_types=["verification", "handoff", "review"],
                run_dir=run_dir,
            )
            write_state(run_dir, state)

            advanced = cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertEqual(advanced["status"], "completed")
```

- [ ] **Step 3: Add failing tests for missing completion evidence**

In `HarnessCliTest`, add:

```python
    def test_advance_rejects_standard_completion_without_verification(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = state_for_workflow(
                status="reviewed",
                track="Standard",
                workflow="standard-doc-system-change",
                evidence_types=["handoff", "review"],
                run_dir=run_dir,
            )
            write_state(run_dir, state)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertIn("missing completion evidence type: verification", str(raised.exception))

    def test_advance_rejects_standard_completion_without_handoff(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = state_for_workflow(
                status="reviewed",
                track="Standard",
                workflow="standard-doc-system-change",
                evidence_types=["verification", "review"],
                run_dir=run_dir,
            )
            write_state(run_dir, state)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertIn("missing completion evidence type: handoff", str(raised.exception))

    def test_advance_rejects_standard_completion_without_review_handling(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = state_for_workflow(
                status="reviewed",
                track="Standard",
                workflow="standard-doc-system-change",
                evidence_types=["verification", "handoff"],
                run_dir=run_dir,
            )
            write_state(run_dir, state)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertIn(
            "missing completion evidence type: one of review, review-evidence, review-waiver",
            str(raised.exception),
        )
```

- [ ] **Step 4: Add failing tests for risk acceptance and intermediate transitions**

In `HarnessCliTest`, add:

```python
    def test_advance_allows_risk_accepted_completion_with_risk_acceptance(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = state_for_workflow(
                status="external_review_unavailable",
                track="Standard",
                workflow="standard-doc-system-change",
                evidence_types=["verification", "handoff", "review", "risk-acceptance"],
                run_dir=run_dir,
            )
            write_state(run_dir, state)

            risk_state = cli.advance_run(
                run_dir,
                "risk_accepted",
                actor="codex",
                root=ROOT,
            )
            completed = cli.advance_run(
                run_dir,
                "completed",
                actor="codex",
                root=ROOT,
            )

        self.assertEqual(risk_state["status"], "risk_accepted")
        self.assertEqual(completed["status"], "completed")

    def test_advance_rejects_risk_accepted_completion_without_risk_acceptance(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = state_for_workflow(
                status="risk_accepted",
                track="Standard",
                workflow="standard-doc-system-change",
                evidence_types=["verification", "handoff", "review"],
                run_dir=run_dir,
            )
            write_state(run_dir, state)

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.advance_run(run_dir, "completed", actor="codex", root=ROOT)

        self.assertIn("missing completion evidence type: risk-acceptance", str(raised.exception))

    def test_advance_does_not_require_completion_evidence_for_intermediate_transition(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state(status="planned")
            state["track"] = "Standard"
            state["current_workflow"] = "standard-doc-system-change"
            write_state(run_dir, state)

            advanced = cli.advance_run(run_dir, "in_progress", actor="codex", root=ROOT)

        self.assertEqual(advanced["status"], "in_progress")
```

- [ ] **Step 5: Run the completion tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_advance_allows_fast_completion_without_review_evidence tests.test_harness_cli.HarnessCliTest.test_advance_allows_standard_completion_with_review_handling tests.test_harness_cli.HarnessCliTest.test_advance_rejects_standard_completion_without_verification tests.test_harness_cli.HarnessCliTest.test_advance_rejects_standard_completion_without_handoff tests.test_harness_cli.HarnessCliTest.test_advance_rejects_standard_completion_without_review_handling tests.test_harness_cli.HarnessCliTest.test_advance_allows_risk_accepted_completion_with_risk_acceptance tests.test_harness_cli.HarnessCliTest.test_advance_rejects_risk_accepted_completion_without_risk_acceptance tests.test_harness_cli.HarnessCliTest.test_advance_does_not_require_completion_evidence_for_intermediate_transition -v
```

Expected: failures because completion gate functions do not exist.

- [ ] **Step 6: Implement completion gate constants and helpers**

In `harness/cli.py`, add after `EVIDENCE_TYPES`:

```python
REVIEW_COMPLETION_EVIDENCE_TYPES = frozenset(
    {"review", "review-evidence", "review-waiver"},
)
COMPLETION_REQUIRED_EVIDENCE_TYPES = frozenset({"verification", "handoff"})
```

Add this function after `can_transition`:

```python
def validate_completion_evidence(
    state: dict[str, Any],
    next_status: str,
) -> list[str]:
    if next_status != "completed":
        return []

    errors: list[str] = []
    evidence_types = {
        evidence.get("type")
        for evidence in state.get("evidence", [])
        if isinstance(evidence.get("type"), str)
    }

    for required_type in sorted(COMPLETION_REQUIRED_EVIDENCE_TYPES):
        if required_type not in evidence_types:
            errors.append(f"missing completion evidence type: {required_type}")

    if state.get("track") in {"Standard", "Strict"}:
        if not evidence_types.intersection(REVIEW_COMPLETION_EVIDENCE_TYPES):
            options = ", ".join(sorted(REVIEW_COMPLETION_EVIDENCE_TYPES))
            errors.append(f"missing completion evidence type: one of {options}")

    if state.get("status") == "risk_accepted":
        if "risk-acceptance" not in evidence_types:
            errors.append("missing completion evidence type: risk-acceptance")

    return errors
```

- [ ] **Step 7: Call completion gate from `advance_run`**

In `advance_run`, after the `can_transition` check and before constructing `candidate`, add:

```python
    completion_errors = validate_completion_evidence(state, next_status)
    if completion_errors:
        raise HarnessCliError(format_errors(completion_errors))
```

- [ ] **Step 8: Run completion tests again**

Run:

```powershell
python -m unittest tests.test_harness_cli.HarnessCliTest.test_advance_allows_fast_completion_without_review_evidence tests.test_harness_cli.HarnessCliTest.test_advance_allows_standard_completion_with_review_handling tests.test_harness_cli.HarnessCliTest.test_advance_rejects_standard_completion_without_verification tests.test_harness_cli.HarnessCliTest.test_advance_rejects_standard_completion_without_handoff tests.test_harness_cli.HarnessCliTest.test_advance_rejects_standard_completion_without_review_handling tests.test_harness_cli.HarnessCliTest.test_advance_allows_risk_accepted_completion_with_risk_acceptance tests.test_harness_cli.HarnessCliTest.test_advance_rejects_risk_accepted_completion_without_risk_acceptance tests.test_harness_cli.HarnessCliTest.test_advance_does_not_require_completion_evidence_for_intermediate_transition -v
```

Expected: exit 0 and all listed tests pass.

- [ ] **Step 9: Commit Task 2**

Run:

```powershell
git add harness/cli.py tests/test_harness_cli.py
git commit -m "feat(harness): gate completed transitions on evidence"
```

## Task 3: Risk Acceptance Template

**Files:**
- Create: `harness/templates/risk-acceptance.md`
- Modify: `tests/test_static_contracts.py`

- [ ] **Step 1: Add failing static test for risk acceptance template**

In `tests/test_static_contracts.py`, add near the other path constants:

```python
RISK_ACCEPTANCE_TEMPLATE = ROOT / "harness" / "templates" / "risk-acceptance.md"
```

In `StaticContractsTest`, add:

```python
    def test_risk_acceptance_template_exists_with_required_sections(self):
        text = read_text(RISK_ACCEPTANCE_TEMPLATE)

        for heading in [
            "# Risk Acceptance",
            "## Decision",
            "## Accepted Risk",
            "## Reason",
            "## Scope",
            "## Evidence",
            "## Decided By",
            "## Decided At",
            "## Residual Risks",
        ]:
            self.assertIn(heading, text)
```

- [ ] **Step 2: Run the template test and verify it fails**

Run:

```powershell
python -m unittest tests.test_static_contracts.StaticContractsTest.test_risk_acceptance_template_exists_with_required_sections -v
```

Expected: failure because `harness/templates/risk-acceptance.md` does not exist.

- [ ] **Step 3: Create the risk acceptance template**

Create `harness/templates/risk-acceptance.md`:

```markdown
# Risk Acceptance

## Decision

Accepted or rejected.

## Accepted Risk

Describe the residual risk being accepted.

## Reason

Explain why the run may proceed despite the residual risk.

## Scope

Name the run, workflow, files, or behavior covered by this decision.

## Evidence

List verification, review, or unavailable-review evidence that informed the decision.

## Decided By

Name the user or authority who accepted the risk.

## Decided At

Record the decision timestamp.

## Residual Risks

List risks that remain after acceptance.
```

- [ ] **Step 4: Run the template test again**

Run:

```powershell
python -m unittest tests.test_static_contracts.StaticContractsTest.test_risk_acceptance_template_exists_with_required_sections -v
```

Expected: exit 0 and the template test passes.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add harness/templates/risk-acceptance.md tests/test_static_contracts.py
git commit -m "docs(harness): add risk acceptance template"
```

## Task 4: Full Verification and Handoff

**Files:**
- No new source files.
- Verify all modified files from Tasks 1-3.

- [ ] **Step 1: Run full unit test suite**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: exit 0, `OK`, with the known env-gated pip hash test skipped unless `HARNESS_RUN_PIP_HASH_CHECK=1` is set.

- [ ] **Step 2: Validate all existing run directories**

Run:

```powershell
Get-ChildItem -Directory harness/runs | ForEach-Object { python -m harness.cli validate $_.FullName }
```

Expected: exit 0 and eight `valid:` lines, one for each existing run directory.

- [ ] **Step 3: Run diff hygiene**

Run:

```powershell
git diff --check
```

Expected: exit 0. Windows line-ending warnings are acceptable if no whitespace errors are reported.

- [ ] **Step 4: Inspect final diff**

Run:

```powershell
git diff --stat
git status --short --branch
```

Expected: only intended files from Tasks 1-3 are modified or added.

- [ ] **Step 5: Decide whether external review is required**

Apply `harness/core/delegation.md`:

- If the implementation diff touches state management, workflow rules, completion criteria, at least three files, or at least 200 lines, external review is required when the `claude_review` tool is available.
- If `claude_review` is not available, record that review was not verified and the residual risk in the final handoff.

- [ ] **Step 6: Confirm no accidental files remain**

Run:

```powershell
git status --short --branch
```

Expected: a clean worktree after the task commits, with the branch ahead of `origin/master` by the new implementation commits.
