# Phase 5.2 Live Async Worker Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 5.2 local run-scoped scheduler path for queued generic-agent jobs, one-shot execution, aggregation, package-smoke coverage, and a live scheduler run.

**Architecture:** Refactor the existing `run_generic_agent` function into create and execute primitives, then add a deterministic single-process scheduler that executes queued jobs without mutating `state.json`. Add aggregation as a separate job-artifact writer, keeping Codex responsible for explicit evidence indexing and state advancement.

**Tech Stack:** Python standard library, `jsonschema`, `unittest`, existing Harness CLI, GitHub Actions, Markdown run evidence.

---

## File Structure

- Modify `harness/cli.py`
  - Add `create_generic_agent_job`, `execute_generic_agent_job`, `scheduler_run_once`, and `aggregate_jobs`.
  - Keep `run_generic_agent` backward compatible by composing create plus execute.
  - Add CLI subcommands `queue-generic-agent`, `run-scheduler --once`, and `aggregate-jobs`.
- Modify `tests/test_generic_agent_adapter.py`
  - Add create/execute split tests, scheduler tests, CLI entrypoint tests, and aggregation generation tests.
- Modify `tests/test_static_contracts.py`
  - Pin new CI/package-smoke command coverage.
- Modify `.github/workflows/ci.yml`
  - Exercise the new commands from a non-editable packaged install outside the repository.
- Modify `tests/test_async_job_artifacts.py`
  - Add a source-controlled Phase 5 live run regression test.
- Create `harness/runs/2026-06-21-phase-5-live-scheduler-smoke/`
  - Record a real queued job, scheduler execution, aggregation, verification, review waiver or review evidence, and handoff.
- Modify `README.md`, `docs/INDEX.md`, and `harness/memory/progress.md`
  - Update project status after the live run exists.

## Task 1: Split Generic Agent Create And Execute

**Files:**
- Modify: `tests/test_generic_agent_adapter.py`
- Modify: `harness/cli.py`

- [ ] **Step 1: Add failing create/execute tests**

Append these tests to `GenericCliAgentOrchestrationTest` in `tests/test_generic_agent_adapter.py`:

```python
    def test_create_generic_agent_job_writes_queued_artifacts_without_mutating_state(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            original_state = minimal_state()
            write_json(run_dir / "state.json", original_state)

            job = cli.create_generic_agent_job(
                run_dir,
                "generic-queued",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('not executed')"],
                timeout_seconds=30,
                root=ROOT,
            )
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            saved_job = json.loads(
                (run_dir / "jobs" / "generic-queued" / "job.json").read_text(
                    encoding="utf-8",
                )
            )
            input_payload = json.loads(
                (run_dir / "jobs" / "generic-queued" / "input.json").read_text(
                    encoding="utf-8",
                )
            )
            raw_log_exists = (
                run_dir / "jobs" / "generic-queued" / "raw.log"
            ).exists()

        self.assertEqual(job["status"], "queued")
        self.assertEqual(saved_job["status"], "queued")
        self.assertIsNone(saved_job["started_at"])
        self.assertIsNone(saved_job["completed_at"])
        self.assertEqual(input_payload["command"], [sys.executable, "-c", "print('not executed')"])
        self.assertFalse(raw_log_exists)
        self.assertEqual(saved_state, original_state)

    def test_execute_generic_agent_job_consumes_preexisting_queued_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "queued_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Queued agent completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                print("queued agent wrote output")
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "generic-queued",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=30,
                root=ROOT,
            )

            job = cli.execute_generic_agent_job(
                run_dir,
                "generic-queued",
                root=ROOT,
            )
            raw_log = (run_dir / "jobs" / "generic-queued" / "raw.log").read_text(
                encoding="utf-8",
            )

        self.assertEqual(job["status"], "succeeded")
        self.assertIn("queued agent wrote output", raw_log)

    def test_execute_generic_agent_job_rejects_terminal_job_without_overwriting_raw_log(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "terminal_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Terminal agent completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                """,
            )
            cli.run_generic_agent(
                run_dir,
                "generic-terminal",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=30,
                root=ROOT,
            )
            raw_log_path = run_dir / "jobs" / "generic-terminal" / "raw.log"
            raw_log_path.write_text("original raw log\\n", encoding="utf-8")

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.execute_generic_agent_job(
                    run_dir,
                    "generic-terminal",
                    root=ROOT,
                )

            raw_log = raw_log_path.read_text(encoding="utf-8")

        self.assertIn("cannot execute job generic-terminal with status succeeded", str(raised.exception))
        self.assertEqual(raw_log, "original raw log\\n")
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_create_generic_agent_job_writes_queued_artifacts_without_mutating_state tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_execute_generic_agent_job_consumes_preexisting_queued_job tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_execute_generic_agent_job_rejects_terminal_job_without_overwriting_raw_log -v
```

Expected: fail with `AttributeError` for `create_generic_agent_job` and `execute_generic_agent_job`.

- [ ] **Step 3: Refactor `run_generic_agent` into create and execute functions**

In `harness/cli.py`, replace the body of `run_generic_agent` with composition and add these functions immediately before it:

```python
def create_generic_agent_job(
    run_dir: Path | str,
    job_id: str,
    *,
    agent: str,
    command: list[str],
    adapter: str = "generic-cli-agent",
    timeout_seconds: int = 1800,
    root: Path | str | None = None,
) -> dict[str, Any]:
    if not job_id.strip():
        raise HarnessCliError("job_id must be non-empty")
    if not agent.strip():
        raise HarnessCliError("agent must be non-empty")
    if not command:
        raise HarnessCliError("generic agent command must be non-empty")
    if timeout_seconds < 1:
        raise HarnessCliError("timeout_seconds must be at least 1")

    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    state = load_json(state_path(resolved_run_dir))
    run_id = state["run_id"]
    jobs_dir = (resolved_run_dir / "jobs").resolve(strict=False)
    job_dir = (jobs_dir / job_id).resolve(strict=False)
    if not is_within_path(job_dir, jobs_dir):
        raise HarnessCliError(f"job_id escapes jobs directory: {job_id}")
    try:
        job_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise HarnessCliError(f"job directory already exists: {job_dir}") from exc
    except OSError as exc:
        raise HarnessCliError(f"failed to create job directory: {exc}") from exc

    input_path = job_dir / "input.json"
    output_path = job_dir / "output.json"
    raw_log_path = job_dir / "raw.log"
    job_path = job_dir / "job.json"
    created_at = utc_now()
    job = {
        "job_id": job_id,
        "run_id": run_id,
        "agent": agent,
        "adapter": adapter,
        "status": "queued",
        "input_file": input_path.name,
        "output_file": output_path.name,
        "raw_log_file": raw_log_path.name,
        "created_at": created_at,
        "started_at": None,
        "completed_at": None,
        "timeout_seconds": timeout_seconds,
        "error_reason": None,
        "provenance": {
            "agent": agent,
            "adapter_version": GENERIC_ADAPTER_VERSION,
            "runtime": "local-cli",
        },
    }
    write_json_file(job_path, job)
    write_json_file(
        input_path,
        {
            "run_id": run_id,
            "job_id": job_id,
            "agent": agent,
            "adapter": adapter,
            "command": command,
            "created_at": created_at,
            "timeout_seconds": timeout_seconds,
            "input_file": str(input_path),
            "output_file": str(output_path),
            "raw_log_file": str(raw_log_path),
        },
    )
    return job


def execute_generic_agent_job(
    run_dir: Path | str,
    job_id: str,
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    job_dir = (resolved_run_dir / "jobs" / job_id).resolve(strict=False)
    jobs_dir = (resolved_run_dir / "jobs").resolve(strict=False)
    if not is_within_path(job_dir, jobs_dir):
        raise HarnessCliError(f"job_id escapes jobs directory: {job_id}")
    job_path = job_dir / "job.json"
    input_path = job_dir / "input.json"
    job, job_errors = validate_json_artifact(job_path, JOB_SCHEMA, "job")
    if job_errors:
        raise HarnessCliError(format_errors(job_errors))
    if job is None:
        raise HarnessCliError(f"job cannot be read: {job_path}")
    if job.get("status") != "queued":
        raise HarnessCliError(
            f"cannot execute job {job_id} with status {job.get('status')}",
        )

    try:
        input_payload = load_json(input_path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HarnessCliError(f"job input cannot be read: {exc}") from exc
    command = input_payload.get("command")
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise HarnessCliError(f"job input command must be a list of strings: {input_path}")

    output_path = job_dir / str(job["output_file"])
    raw_log_path = job_dir / str(job["raw_log_file"])
    timeout_seconds = int(job["timeout_seconds"])
    job["status"] = "running"
    job["started_at"] = utc_now()
    write_json_file(job_path, job)

    env = os.environ.copy()
    env.update(
        {
            "HARNESS_RUN_ID": str(job["run_id"]),
            "HARNESS_JOB_ID": str(job["job_id"]),
            "HARNESS_AGENT": str(job["agent"]),
            "HARNESS_AGENT_ADAPTER": str(job["adapter"]),
            "HARNESS_AGENT_INPUT_FILE": str(input_path),
            "HARNESS_AGENT_OUTPUT_FILE": str(output_path),
            "HARNESS_AGENT_RAW_LOG_FILE": str(raw_log_path),
        }
    )

    status = "succeeded"
    error_reason: str | None = None
    raw_stdout: str | None = None
    raw_stderr: str | None = None
    returncode: int | None = None
    try:
        returncode, raw_stdout, raw_stderr = run_agent_subprocess(
            command,
            cwd=job_dir,
            env=env,
            timeout_seconds=timeout_seconds,
        )
        if returncode != 0:
            status = "failed"
            error_reason = f"agent command exited with code {returncode}"
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        error_reason = f"agent command timed out after {timeout_seconds} seconds"
        raw_stdout = output_to_text(exc.stdout)
        raw_stderr = output_to_text(exc.stderr)
    except OSError as exc:
        status = "failed"
        error_reason = f"agent command could not be executed: {exc}"

    write_raw_log(raw_log_path, command, returncode, raw_stdout, raw_stderr)

    if status == "succeeded":
        if not output_path.exists():
            status = "failed"
            error_reason = "agent did not write output_file"
        else:
            agent_result, result_errors = validate_json_artifact(
                output_path,
                AGENT_RESULT_SCHEMA,
                "agent-result",
            )
            if result_errors:
                status = "failed"
                error_reason = "; ".join(result_errors)
            elif agent_result is not None:
                result_contract_errors = validate_agent_result_matches_job(
                    agent_result,
                    job,
                )
                if result_contract_errors:
                    status = "failed"
                    error_reason = "; ".join(result_contract_errors)

    job["status"] = status
    job["completed_at"] = utc_now()
    job["error_reason"] = error_reason
    write_json_file(job_path, job)
    return job
```

Then reduce `run_generic_agent` to:

```python
def run_generic_agent(
    run_dir: Path | str,
    job_id: str,
    *,
    agent: str,
    command: list[str],
    adapter: str = "generic-cli-agent",
    timeout_seconds: int = 1800,
    root: Path | str | None = None,
) -> dict[str, Any]:
    create_generic_agent_job(
        run_dir,
        job_id,
        agent=agent,
        adapter=adapter,
        command=command,
        timeout_seconds=timeout_seconds,
        root=root,
    )
    return execute_generic_agent_job(run_dir, job_id, root=root)
```

- [ ] **Step 4: Run split tests and existing generic adapter tests**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter -v
```

Expected: all tests in `tests.test_generic_agent_adapter` pass.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add harness/cli.py tests/test_generic_agent_adapter.py
git commit -m "feat: split generic agent queue and execution"
```

## Task 2: Add One-Shot Scheduler

**Files:**
- Modify: `tests/test_generic_agent_adapter.py`
- Modify: `harness/cli.py`

- [ ] **Step 1: Add failing scheduler tests**

Append these tests to `GenericCliAgentOrchestrationTest`:

```python
    def test_scheduler_run_once_executes_queued_jobs_in_order_and_continues_after_failed_terminal_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "success_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": f"{payload['job_id']} completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                print(payload["job_id"])
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "001-fails",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "import sys; sys.exit(7)"],
                timeout_seconds=30,
                root=ROOT,
            )
            cli.create_generic_agent_job(
                run_dir,
                "002-succeeds",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=30,
                root=ROOT,
            )

            summary = cli.scheduler_run_once(run_dir, root=ROOT)
            failed_job = json.loads(
                (run_dir / "jobs" / "001-fails" / "job.json").read_text(
                    encoding="utf-8",
                )
            )
            succeeded_job = json.loads(
                (run_dir / "jobs" / "002-succeeds" / "job.json").read_text(
                    encoding="utf-8",
                )
            )

        self.assertEqual(summary["executed_jobs"], ["001-fails", "002-succeeds"])
        self.assertEqual(failed_job["status"], "failed")
        self.assertEqual(succeeded_job["status"], "succeeded")

    def test_scheduler_run_once_skips_running_and_terminal_jobs_without_claiming_them(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "running-job",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('running')"],
                timeout_seconds=30,
                root=ROOT,
            )
            running_path = run_dir / "jobs" / "running-job" / "job.json"
            running_job = json.loads(running_path.read_text(encoding="utf-8"))
            running_job["status"] = "running"
            running_job["started_at"] = "2026-06-20T00:00:01Z"
            write_json(running_path, running_job)

            cli.create_generic_agent_job(
                run_dir,
                "terminal-job",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('terminal')"],
                timeout_seconds=30,
                root=ROOT,
            )
            terminal_path = run_dir / "jobs" / "terminal-job" / "job.json"
            terminal_job = json.loads(terminal_path.read_text(encoding="utf-8"))
            terminal_job["status"] = "failed"
            terminal_job["started_at"] = "2026-06-20T00:00:01Z"
            terminal_job["completed_at"] = "2026-06-20T00:00:02Z"
            terminal_job["error_reason"] = "preexisting terminal"
            write_json(terminal_path, terminal_job)

            summary = cli.scheduler_run_once(run_dir, root=ROOT)
            saved_running = json.loads(running_path.read_text(encoding="utf-8"))
            saved_terminal = json.loads(terminal_path.read_text(encoding="utf-8"))

        self.assertEqual(summary["executed_jobs"], [])
        self.assertEqual(summary["skipped_jobs"], ["running-job", "terminal-job"])
        self.assertEqual(saved_running["status"], "running")
        self.assertEqual(saved_terminal["error_reason"], "preexisting terminal")

    def test_scheduler_run_once_aborts_on_invalid_job_record_before_executing_any_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            invalid_path = run_dir / "jobs" / "000-invalid" / "job.json"
            invalid_path.parent.mkdir(parents=True, exist_ok=True)
            invalid_path.write_text("[]\\n", encoding="utf-8")
            cli.create_generic_agent_job(
                run_dir,
                "001-valid",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('must not run')"],
                timeout_seconds=30,
                root=ROOT,
            )

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.scheduler_run_once(run_dir, root=ROOT)

            valid_job = json.loads(
                (run_dir / "jobs" / "001-valid" / "job.json").read_text(
                    encoding="utf-8",
                )
            )

        self.assertIn("job schema error", str(raised.exception))
        self.assertEqual(valid_job["status"], "queued")
```

- [ ] **Step 2: Run scheduler tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_run_once_executes_queued_jobs_in_order_and_continues_after_failed_terminal_job tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_run_once_skips_running_and_terminal_jobs_without_claiming_them tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_run_once_aborts_on_invalid_job_record_before_executing_any_job -v
```

Expected: fail with `AttributeError` for `scheduler_run_once`.

- [ ] **Step 3: Implement scheduler helpers**

In `harness/cli.py`, add this helper and scheduler function after `execute_generic_agent_job`:

```python
def load_scheduler_jobs(
    run_dir: Path,
    *,
    root: Path,
) -> list[dict[str, Any]]:
    jobs_dir = run_dir / "jobs"
    if not jobs_dir.exists():
        return []

    jobs: list[dict[str, Any]] = []
    for job_path in sorted(jobs_dir.glob("*/job.json")):
        job, job_errors = validate_json_artifact(job_path, JOB_SCHEMA, "job")
        if job_errors:
            raise HarnessCliError(format_errors(job_errors))
        if job is None:
            raise HarnessCliError(f"job cannot be read: {job_path}")
        if job.get("run_id") != load_json(state_path(run_dir)).get("run_id"):
            raise HarnessCliError(
                f"job run_id {job.get('run_id')} does not match run state",
            )
        jobs.append(job)
    return jobs


def scheduler_run_once(
    run_dir: Path | str,
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    state = load_json(state_path(resolved_run_dir))
    jobs = load_scheduler_jobs(resolved_run_dir, root=repo_root)
    queued_jobs = sorted(
        (job for job in jobs if job.get("status") == "queued"),
        key=lambda job: (str(job.get("created_at")), str(job.get("job_id"))),
    )
    skipped_jobs = [
        str(job["job_id"])
        for job in jobs
        if job.get("status") != "queued"
    ]
    executed_jobs: list[str] = []
    terminal_statuses: dict[str, str] = {}
    for job in queued_jobs:
        job_id = str(job["job_id"])
        result = execute_generic_agent_job(resolved_run_dir, job_id, root=repo_root)
        executed_jobs.append(job_id)
        terminal_statuses[job_id] = str(result["status"])

    return {
        "run_id": state["run_id"],
        "executed_jobs": executed_jobs,
        "skipped_jobs": skipped_jobs,
        "terminal_statuses": terminal_statuses,
    }
```

Before finalizing this code, hoist `state = load_json(state_path(run_dir))` out of the loop in `load_scheduler_jobs` if the implementation would otherwise reread state per job. Keep behavior identical.

- [ ] **Step 4: Run scheduler tests and generic adapter suite**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter -v
```

Expected: all tests in `tests.test_generic_agent_adapter` pass.

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
git add harness/cli.py tests/test_generic_agent_adapter.py
git commit -m "feat: add one-shot generic agent scheduler"
```

## Task 3: Add Job Aggregation Generation

**Files:**
- Modify: `tests/test_generic_agent_adapter.py`
- Modify: `harness/cli.py`

- [ ] **Step 1: Add failing aggregation generation tests**

Append these tests to `GenericCliAgentOrchestrationTest`:

```python
    def test_aggregate_jobs_classifies_terminal_and_incomplete_jobs_without_mutating_state(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state()
            write_json(run_dir / "state.json", state)
            agent_script = run_dir / "finding_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "findings",
                    "summary": "Finding agent completed.",
                    "findings": [
                        {
                            "severity": "low",
                            "title": "Sample finding",
                            "evidence": "Synthetic finding for aggregation.",
                            "recommendation": "Record it in aggregation."
                        }
                    ],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": ["Synthetic residual risk."],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                """,
            )
            cli.run_generic_agent(
                run_dir,
                "succeeded-job",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=30,
                root=ROOT,
            )
            cli.create_generic_agent_job(
                run_dir,
                "running-job",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('still running')"],
                timeout_seconds=30,
                root=ROOT,
            )
            running_path = run_dir / "jobs" / "running-job" / "job.json"
            running_job = json.loads(running_path.read_text(encoding="utf-8"))
            running_job["status"] = "running"
            running_job["started_at"] = "2026-06-20T00:00:01Z"
            write_json(running_path, running_job)

            aggregation = cli.aggregate_jobs(run_dir, root=ROOT)
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            saved_aggregation = json.loads(
                (run_dir / "jobs" / "aggregation.json").read_text(encoding="utf-8")
            )

        self.assertEqual(saved_state, state)
        self.assertEqual(aggregation, saved_aggregation)
        self.assertEqual(saved_aggregation["consumed_jobs"], ["succeeded-job"])
        self.assertEqual(saved_aggregation["succeeded_jobs"], ["succeeded-job"])
        self.assertEqual(saved_aggregation["incomplete_jobs"], ["running-job"])
        self.assertEqual(saved_aggregation["findings"][0]["job_id"], "succeeded-job")
        self.assertEqual(saved_aggregation["findings"][0]["severity"], "low")
        self.assertIn("Synthetic residual risk.", saved_aggregation["residual_risks"])

    def test_aggregate_jobs_records_missing_or_invalid_terminal_output_as_residual_risk(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            cli.create_generic_agent_job(
                run_dir,
                "failed-job",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "import sys; sys.exit(7)"],
                timeout_seconds=30,
                root=ROOT,
            )
            cli.execute_generic_agent_job(run_dir, "failed-job", root=ROOT)

            aggregation = cli.aggregate_jobs(run_dir, root=ROOT)

        self.assertEqual(aggregation["failed_jobs"], ["failed-job"])
        self.assertTrue(
            any("failed-job" in risk and "output" in risk for risk in aggregation["residual_risks"]),
            aggregation["residual_risks"],
        )

    def test_aggregate_jobs_aborts_on_invalid_job_record(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            invalid_path = run_dir / "jobs" / "invalid" / "job.json"
            invalid_path.parent.mkdir(parents=True, exist_ok=True)
            invalid_path.write_text("[]\\n", encoding="utf-8")

            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.aggregate_jobs(run_dir, root=ROOT)

        self.assertIn("job schema error", str(raised.exception))
```

- [ ] **Step 2: Run aggregation tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_aggregate_jobs_classifies_terminal_and_incomplete_jobs_without_mutating_state tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_aggregate_jobs_records_missing_or_invalid_terminal_output_as_residual_risk tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_aggregate_jobs_aborts_on_invalid_job_record -v
```

Expected: fail with `AttributeError` for `aggregate_jobs`.

- [ ] **Step 3: Implement aggregation generation**

In `harness/cli.py`, add after `scheduler_run_once`:

```python
def aggregate_jobs(
    run_dir: Path | str,
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    state = load_json(state_path(resolved_run_dir))
    jobs = sorted(
        load_scheduler_jobs(resolved_run_dir, root=repo_root),
        key=lambda job: str(job.get("job_id")),
    )
    aggregation = {
        "run_id": state["run_id"],
        "generated_at": utc_now(),
        "consumed_jobs": [],
        "succeeded_jobs": [],
        "failed_jobs": [],
        "timeout_jobs": [],
        "cancelled_jobs": [],
        "incomplete_jobs": [],
        "findings": [],
        "conflicts": [],
        "recommended_transition": None,
        "residual_risks": [],
    }

    for job in jobs:
        job_id = str(job["job_id"])
        status = str(job["status"])
        if status not in TERMINAL_JOB_STATUSES:
            aggregation["incomplete_jobs"].append(job_id)
            continue

        aggregation["consumed_jobs"].append(job_id)
        bucket = {
            "succeeded": "succeeded_jobs",
            "failed": "failed_jobs",
            "timeout": "timeout_jobs",
            "cancelled": "cancelled_jobs",
        }[status]
        aggregation[bucket].append(job_id)

        output_file = job.get("output_file")
        if not isinstance(output_file, str) or not output_file.strip():
            aggregation["residual_risks"].append(
                f"Job {job_id} has no output_file value.",
            )
            continue

        output_path = resolved_run_dir / "jobs" / job_id / output_file
        if not output_path.exists():
            aggregation["residual_risks"].append(
                f"Job {job_id} has no output artifact at {output_file}.",
            )
            continue

        agent_result, result_errors = validate_json_artifact(
            output_path,
            AGENT_RESULT_SCHEMA,
            "agent-result",
        )
        if result_errors:
            aggregation["residual_risks"].append(
                f"Job {job_id} output is not a valid agent-result: {'; '.join(result_errors)}",
            )
            continue
        if agent_result is None:
            aggregation["residual_risks"].append(
                f"Job {job_id} output could not be read.",
            )
            continue

        for finding in agent_result.get("findings", []):
            aggregation["findings"].append(
                {
                    "job_id": job_id,
                    "severity": finding["severity"],
                    "title": finding["title"],
                    "evidence": finding["evidence"],
                    "recommendation": finding["recommendation"],
                }
            )
        aggregation["residual_risks"].extend(agent_result.get("residual_risks", []))

    aggregation_path = resolved_run_dir / "jobs" / "aggregation.json"
    write_json_file(aggregation_path, aggregation)
    return aggregation
```

- [ ] **Step 4: Run aggregation and async artifact tests**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter tests.test_async_job_artifacts -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add harness/cli.py tests/test_generic_agent_adapter.py
git commit -m "feat: aggregate async job artifacts"
```

## Task 4: Add CLI Commands And Package Smoke Coverage

**Files:**
- Modify: `tests/test_generic_agent_adapter.py`
- Modify: `tests/test_static_contracts.py`
- Modify: `harness/cli.py`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add failing CLI entrypoint test**

Append this test to `GenericCliAgentOrchestrationTest`:

```python
    def test_module_entrypoint_queues_runs_scheduler_and_aggregates(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "cli_scheduler_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                from pathlib import Path

                payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "CLI scheduler agent completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
                    json.dumps(output, indent=2) + "\\n",
                    encoding="utf-8",
                )
                print("cli scheduler agent wrote output")
                """,
            )

            queue_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "queue-generic-agent",
                    str(run_dir),
                    "cli-scheduler-job",
                    "--agent",
                    "generic-test-agent",
                    "--timeout-seconds",
                    "30",
                    "--",
                    sys.executable,
                    str(agent_script),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            scheduler_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "run-scheduler",
                    str(run_dir),
                    "--once",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            aggregate_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "aggregate-jobs",
                    str(run_dir),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            aggregation = json.loads(
                (run_dir / "jobs" / "aggregation.json").read_text(encoding="utf-8")
            )

        self.assertEqual(queue_result.returncode, 0, queue_result.stderr + queue_result.stdout)
        self.assertEqual(scheduler_result.returncode, 0, scheduler_result.stderr + scheduler_result.stdout)
        self.assertEqual(aggregate_result.returncode, 0, aggregate_result.stderr + aggregate_result.stdout)
        self.assertIn("queued generic-agent: test-run/cli-scheduler-job", queue_result.stdout)
        self.assertIn("scheduler: test-run executed=1 skipped=0", scheduler_result.stdout)
        self.assertIn("aggregated jobs: test-run consumed=1 incomplete=0", aggregate_result.stdout)
        self.assertEqual(aggregation["consumed_jobs"], ["cli-scheduler-job"])
```

- [ ] **Step 2: Add failing static CI contract assertions**

In `tests/test_static_contracts.py`, extend the command list in `test_ci_workflow_runs_core_validation_steps` with:

```python
            "harness queue-generic-agent",
            "harness run-scheduler",
            "harness aggregate-jobs",
            "package-smoke-scheduler-agent",
```

- [ ] **Step 3: Run CLI/static tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_module_entrypoint_queues_runs_scheduler_and_aggregates tests.test_static_contracts.StaticContractsTest.test_ci_workflow_runs_core_validation_steps -v
```

Expected: CLI test fails because subcommands do not exist; static contract test fails because CI does not mention the new commands.

- [ ] **Step 4: Register CLI subcommands**

In `build_parser`, add:

```python
    queue_generic = subparsers.add_parser(
        "queue-generic-agent",
        help="Queue a generic CLI agent as a run-local async job without executing it.",
    )
    queue_generic.add_argument("run_dir")
    queue_generic.add_argument("job_id")
    queue_generic.add_argument("--agent", required=True)
    queue_generic.add_argument("--adapter", default="generic-cli-agent")
    queue_generic.add_argument("--timeout-seconds", type=int, default=1800)
    queue_generic.add_argument("agent_command", nargs=argparse.REMAINDER)

    scheduler = subparsers.add_parser(
        "run-scheduler",
        help="Run the local async scheduler for queued jobs.",
    )
    scheduler.add_argument("run_dir")
    scheduler.add_argument("--once", action="store_true", required=True)

    aggregate = subparsers.add_parser(
        "aggregate-jobs",
        help="Write jobs/aggregation.json for a Harness run.",
    )
    aggregate.add_argument("run_dir")
```

In `main`, add before the existing `run-generic-agent` branch:

```python
        if args.command == "queue-generic-agent":
            command = args.agent_command
            if command and command[0] == "--":
                command = command[1:]
            job = create_generic_agent_job(
                args.run_dir,
                args.job_id,
                agent=args.agent,
                adapter=args.adapter,
                command=command,
                timeout_seconds=args.timeout_seconds,
            )
            print(f"queued generic-agent: {job['run_id']}/{job['job_id']}")
            return 0

        if args.command == "run-scheduler":
            summary = scheduler_run_once(args.run_dir)
            print(
                f"scheduler: {summary['run_id']} "
                f"executed={len(summary['executed_jobs'])} "
                f"skipped={len(summary['skipped_jobs'])}",
            )
            return 0

        if args.command == "aggregate-jobs":
            aggregation = aggregate_jobs(args.run_dir)
            print(
                f"aggregated jobs: {aggregation['run_id']} "
                f"consumed={len(aggregation['consumed_jobs'])} "
                f"incomplete={len(aggregation['incomplete_jobs'])}",
            )
            return 0
```

- [ ] **Step 5: Update package-smoke workflow**

In `.github/workflows/ci.yml`, extend the package-smoke script after `harness validate "$GITHUB_WORKSPACE/.tmp/package-smoke-run"`:

```bash
          cat > "$GITHUB_WORKSPACE/.tmp/package-smoke-scheduler-agent.py" <<'PY'
          import json
          import os
          from pathlib import Path

          payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
          output = {
              "run_id": payload["run_id"],
              "job_id": payload["job_id"],
              "agent": payload["agent"],
              "adapter": payload["adapter"],
              "status": "passed",
              "summary": "Package smoke scheduler agent completed.",
              "findings": [],
              "evidence": [],
              "not_tested": [],
              "residual_risks": [],
              "generated_at": payload["created_at"],
          }
          Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(
              json.dumps(output, indent=2) + "\n",
              encoding="utf-8",
          )
          print("package-smoke-scheduler-agent wrote output")
          PY
          harness queue-generic-agent "$GITHUB_WORKSPACE/.tmp/package-smoke-run" package-smoke-scheduler --agent package-smoke-agent --timeout-seconds 30 -- python "$GITHUB_WORKSPACE/.tmp/package-smoke-scheduler-agent.py"
          harness run-scheduler "$GITHUB_WORKSPACE/.tmp/package-smoke-run" --once
          harness aggregate-jobs "$GITHUB_WORKSPACE/.tmp/package-smoke-run"
          harness validate "$GITHUB_WORKSPACE/.tmp/package-smoke-run"
```

- [ ] **Step 6: Run CLI/static tests**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_module_entrypoint_queues_runs_scheduler_and_aggregates tests.test_static_contracts.StaticContractsTest.test_ci_workflow_runs_core_validation_steps -v
```

Expected: both tests pass.

- [ ] **Step 7: Commit Task 4**

Run:

```powershell
git add harness/cli.py tests/test_generic_agent_adapter.py tests/test_static_contracts.py .github/workflows/ci.yml
git commit -m "feat: expose scheduler CLI and package smoke"
```

## Task 5: Add Phase 5 Live Scheduler Smoke Run

**Files:**
- Create: `harness/runs/2026-06-21-phase-5-live-scheduler-smoke/**`
- Modify: `tests/test_async_job_artifacts.py`
- Modify: `README.md`
- Modify: `docs/INDEX.md`
- Modify: `harness/memory/progress.md`

- [ ] **Step 1: Create the run through the CLI**

Run:

```powershell
python -m harness.cli init-run harness/runs/2026-06-21-phase-5-live-scheduler-smoke --run-id 2026-06-21-phase-5-live-scheduler-smoke --track Standard --workflow standard-agent-adapter-change --base-commit HEAD
python -m harness.cli advance harness/runs/2026-06-21-phase-5-live-scheduler-smoke triaged
python -m harness.cli advance harness/runs/2026-06-21-phase-5-live-scheduler-smoke planned
python -m harness.cli advance harness/runs/2026-06-21-phase-5-live-scheduler-smoke in_progress
```

Expected: each command exits 0 and prints the new state.

- [ ] **Step 2: Write run task, triage, and plan documents**

Create or replace these files with concrete content:

```text
harness/runs/2026-06-21-phase-5-live-scheduler-smoke/task.md
harness/runs/2026-06-21-phase-5-live-scheduler-smoke/triage.md
harness/runs/2026-06-21-phase-5-live-scheduler-smoke/plan.md
```

The documents must state:

- this run proves queue plus `run-scheduler --once`
- `state.json` is not mutated by scheduler execution
- `aggregate-jobs` writes `jobs/aggregation.json`
- watch mode, multi-worker behavior, cloud queue, and stale-running recovery are outside scope
- orphaned `running` jobs are skipped, not recovered

- [ ] **Step 3: Add the live scheduler smoke script**

Create:

```text
harness/runs/2026-06-21-phase-5-live-scheduler-smoke/scripts/scheduler-smoke.py
```

Use:

```python
import json
import os
from pathlib import Path


def main() -> int:
    input_path = Path(os.environ["HARNESS_AGENT_INPUT_FILE"])
    output_path = Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    output = {
        "run_id": payload["run_id"],
        "job_id": payload["job_id"],
        "agent": payload["agent"],
        "adapter": payload["adapter"],
        "status": "passed",
        "summary": "Phase 5 live scheduler smoke completed.",
        "findings": [],
        "evidence": [
            {
                "path": "raw.log",
                "description": "raw.log captures deterministic scheduler smoke stdout.",
            }
        ],
        "not_tested": [
            "Scheduler watch mode.",
            "Multi-worker concurrency.",
            "Cloud queue execution.",
            "Automatic stale-running recovery.",
        ],
        "residual_risks": [
            "This proves local single-process run-scheduler --once behavior only.",
            "Orphaned running jobs are skipped, not automatically recovered.",
        ],
        "generated_at": payload["created_at"],
    }
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print("phase5 live scheduler agent wrote output")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Queue, schedule, and aggregate the live job**

Run:

```powershell
python -m harness.cli queue-generic-agent harness/runs/2026-06-21-phase-5-live-scheduler-smoke phase5-live-scheduler-agent --agent generic-cli-agent --timeout-seconds 30 -- python ..\..\scripts\scheduler-smoke.py
python -m harness.cli run-scheduler harness/runs/2026-06-21-phase-5-live-scheduler-smoke --once
python -m harness.cli aggregate-jobs harness/runs/2026-06-21-phase-5-live-scheduler-smoke
```

Expected:

- queue command prints `queued generic-agent: 2026-06-21-phase-5-live-scheduler-smoke/phase5-live-scheduler-agent`
- scheduler command prints `scheduler: 2026-06-21-phase-5-live-scheduler-smoke executed=1 skipped=0`
- aggregate command prints `aggregated jobs: 2026-06-21-phase-5-live-scheduler-smoke consumed=1 incomplete=0`

- [ ] **Step 5: Index consumed evidence**

Run:

```powershell
python -m harness.cli index-evidence harness/runs/2026-06-21-phase-5-live-scheduler-smoke agent-job jobs/phase5-live-scheduler-agent/job.json --description "Terminal scheduler-executed async job consumed by Codex."
python -m harness.cli index-evidence harness/runs/2026-06-21-phase-5-live-scheduler-smoke agent-result jobs/phase5-live-scheduler-agent/output.json --description "Structured scheduler-executed agent result consumed by Codex."
python -m harness.cli index-evidence harness/runs/2026-06-21-phase-5-live-scheduler-smoke aggregation jobs/aggregation.json --description "Codex fan-in aggregation generated by aggregate-jobs."
```

Expected: each command exits 0.

- [ ] **Step 6: Write verification, review waiver, and handoff**

Create:

```text
harness/runs/2026-06-21-phase-5-live-scheduler-smoke/verification.md
harness/runs/2026-06-21-phase-5-live-scheduler-smoke/review-waiver.md
harness/runs/2026-06-21-phase-5-live-scheduler-smoke/handoff.md
```

The `review-waiver.md` reason must be scoped:

```markdown
# Review Waiver

## Reason

This run is a narrow source-controlled live smoke of the scheduler artifact path. It does not waive review for the Phase 5.2 runtime implementation diff, scheduler state-machine changes, permission changes, or future multi-worker behavior.

## Scope

- Applies only to the run record artifacts under this run directory.
- Does not apply to `harness/cli.py`, CI, tests, or scheduler implementation code.
```

The `handoff.md` frontmatter must include:

```yaml
not_verified:
  - "Scheduler watch mode."
  - "Multi-worker concurrency."
  - "Cloud queue execution."
  - "Automatic stale-running recovery."
residual_risks:
  - "This run proves local single-process run-scheduler --once behavior only."
  - "Orphaned running jobs are skipped, not automatically recovered."
```

- [ ] **Step 7: Index verification, review waiver, and handoff, then complete the run**

Run:

```powershell
python -m harness.cli advance harness/runs/2026-06-21-phase-5-live-scheduler-smoke implemented
python -m harness.cli index-evidence harness/runs/2026-06-21-phase-5-live-scheduler-smoke verification verification.md --description "Verification record."
python -m harness.cli index-evidence harness/runs/2026-06-21-phase-5-live-scheduler-smoke review-waiver review-waiver.md --description "Scoped run-record review waiver."
python -m harness.cli index-evidence harness/runs/2026-06-21-phase-5-live-scheduler-smoke handoff handoff.md --description "Completion handoff."
python -m harness.cli advance harness/runs/2026-06-21-phase-5-live-scheduler-smoke verified
python -m harness.cli advance harness/runs/2026-06-21-phase-5-live-scheduler-smoke reviewed
python -m harness.cli advance harness/runs/2026-06-21-phase-5-live-scheduler-smoke completed
python -m harness.cli validate harness/runs/2026-06-21-phase-5-live-scheduler-smoke
```

Expected: final validation exits 0 and prints `valid: harness\runs\2026-06-21-phase-5-live-scheduler-smoke`.

- [ ] **Step 8: Add live run regression test**

In `tests/test_async_job_artifacts.py`, add:

```python
PHASE5_LIVE_RUN = ROOT / "harness" / "runs" / "2026-06-21-phase-5-live-scheduler-smoke"
```

Add to `Phase4ClosureRunTest`:

```python
    def test_phase5_live_run_was_produced_by_scheduler_path(self):
        result = cli.validate_run(PHASE5_LIVE_RUN, root=ROOT)
        state = json.loads((PHASE5_LIVE_RUN / "state.json").read_text(encoding="utf-8"))
        evidence_types = {item["type"] for item in state["evidence"]}
        raw_log = PHASE5_LIVE_RUN.joinpath(
            "jobs",
            "phase5-live-scheduler-agent",
            "raw.log",
        ).read_text(encoding="utf-8")
        aggregation = json.loads(
            PHASE5_LIVE_RUN.joinpath("jobs", "aggregation.json").read_text(
                encoding="utf-8",
            )
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(state["status"], "completed")
        self.assertIn("agent-job", evidence_types)
        self.assertIn("agent-result", evidence_types)
        self.assertIn("aggregation", evidence_types)
        self.assertIn("phase5 live scheduler agent wrote output", raw_log)
        self.assertEqual(aggregation["consumed_jobs"], ["phase5-live-scheduler-agent"])
        self.assertEqual(aggregation["incomplete_jobs"], [])
```

- [ ] **Step 9: Update status docs**

Update:

- `README.md`: current status should say Phase 5.2 local scheduler smoke is implemented and exercised by a live run.
- `docs/INDEX.md`: add the Phase 5 live run to Current Status.
- `harness/memory/progress.md`: append the Phase 5.2 scheduler implementation outcome and residual risks.

- [ ] **Step 10: Run live run tests and commit**

Run:

```powershell
python -m unittest tests.test_async_job_artifacts.Phase4ClosureRunTest.test_phase5_live_run_was_produced_by_scheduler_path -v
python -m harness.cli validate harness/runs/2026-06-21-phase-5-live-scheduler-smoke
```

Expected: both commands exit 0.

Commit:

```powershell
git add harness/runs/2026-06-21-phase-5-live-scheduler-smoke tests/test_async_job_artifacts.py README.md docs/INDEX.md harness/memory/progress.md
git commit -m "feat: add Phase 5 live scheduler smoke run"
```

## Task 6: Full Verification And Review

**Files:**
- Verify all changed files.
- Add review artifact or scoped waiver only if required by the implementation run.

- [ ] **Step 1: Run the full unit suite**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: all tests pass, with only env-gated tests skipped.

- [ ] **Step 2: Validate every source-controlled run**

Run:

```powershell
Get-ChildItem -Directory harness/runs | ForEach-Object { python -m harness.cli validate $_.FullName }
```

Expected: every run prints `valid:`.

- [ ] **Step 3: Run package install smoke locally**

Run:

```powershell
$venv = Join-Path $env:TEMP "harness-phase5-package-smoke"
if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }
python -m venv $venv
& "$venv\Scripts\python.exe" -m pip install --upgrade pip
& "$venv\Scripts\python.exe" -m pip install .
Push-Location $env:TEMP
& "$venv\Scripts\harness.exe" validate "E:\ai-coding-harness\harness\runs\example-fast-doc-change"
Pop-Location
Remove-Item -Recurse -Force $venv
```

Expected: packaged `harness` console script validates the example run from outside the repository.

- [ ] **Step 4: Run diff hygiene**

Run:

```powershell
git diff --check
```

Expected: exit 0. CRLF warnings are acceptable when there are no whitespace errors.

- [ ] **Step 5: Inspect final diff**

Run:

```powershell
git diff --stat
git status --short --branch
```

Expected changed areas are limited to:

- `harness/cli.py`
- scheduler/generic agent tests
- CI workflow and static CI contract tests
- Phase 5 live run
- README/docs/memory status updates

- [ ] **Step 6: Run external review or record unavailability**

This implementation touches CLI orchestration, async job semantics, CI, tests, and run evidence. It qualifies for external review under `harness/core/delegation.md`.

If the Claude review adapter is available, run it against:

- task summary
- Phase 5.2 design spec
- this implementation plan
- `git diff "$(git merge-base origin/master HEAD)" HEAD`
- verification outputs

Acceptable outcomes:

- `passed`
- `findings` with no high or critical findings after triage

If the adapter is unavailable, record a scoped `review-waiver.md` in the Phase 5 run or final handoff. Do not claim external review passed without a concrete artifact.

- [ ] **Step 7: Final commit if review or verification artifacts changed**

If Step 6 changes source-controlled artifacts, commit them:

```powershell
git add harness/runs/2026-06-21-phase-5-live-scheduler-smoke README.md docs/INDEX.md harness/memory/progress.md
git commit -m "docs: record Phase 5 scheduler review outcome"
```

## Acceptance Checklist

- [ ] `run-generic-agent` remains backward compatible.
- [ ] `queue-generic-agent` creates queued jobs without starting subprocesses.
- [ ] `execute_generic_agent_job` can execute a queued job created in a prior call.
- [ ] `execute_generic_agent_job` rejects running and terminal jobs.
- [ ] `run-scheduler --once` executes queued jobs in deterministic order.
- [ ] A terminal failed job does not abort scheduler execution of later queued jobs.
- [ ] Invalid job records abort scheduler execution before any job is claimed.
- [ ] `aggregate-jobs` consumes terminal jobs and lists non-terminal jobs under `incomplete_jobs`.
- [ ] `aggregate-jobs` uses current disk `job.json` values and does not cache stale job state.
- [ ] Scheduler and aggregation never mutate `state.json`.
- [ ] CI package smoke invokes `queue-generic-agent`, `run-scheduler`, and `aggregate-jobs` from a non-editable install outside the repository.
- [ ] A live Phase 5 scheduler smoke run exists and validates.
- [ ] The live run handoff records that watch mode, multi-worker behavior, cloud queue, and stale-running recovery are not verified.
- [ ] Full unit tests pass.
- [ ] Every source-controlled run validates.
- [ ] `git diff --check` reports no whitespace errors.
