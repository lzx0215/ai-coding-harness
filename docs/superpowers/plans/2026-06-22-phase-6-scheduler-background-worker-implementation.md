# Phase 6 Scheduler Background Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Phase 6 scheduler watch mode, local background worker launch, heartbeat/control artifacts, structured scheduler events, and stop semantics while keeping Codex as the only actor that indexes evidence or advances `state.json`.

**Architecture:** Extend the existing Phase 5.2 scheduler functions in `harness/cli.py` instead of adding a service layer. The new watch loop shares `execute_generic_agent_job` with `--once`, writes scheduler artifacts under `jobs/scheduler/`, and keeps `--once` strict while making `--watch` resilient to invalid job artifacts.

**Tech Stack:** Python standard library (`argparse`, `json`, `os`, `subprocess`, `sys`, `time`, `uuid`, `threading` in tests), existing Harness CLI, `unittest`, GitHub Actions package smoke.

---

## File Structure

- Modify `harness/cli.py`
  - Add `HARNESS_VERSION = "0.2.0"`.
  - Add scheduler artifact helpers for `worker.json`, `heartbeat.json`, `stop.json`, and JSONL `events.log`.
  - Add `scheduler_run_watch`, `request_scheduler_stop`, and `start_scheduler`.
  - Change `run-scheduler` parser to require exactly one of `--once` and `--watch`.
  - Add `start-scheduler` and `stop-scheduler` subcommands.
- Modify `tests/test_generic_agent_adapter.py`
  - Add parser tests, watch loop tests, stop tests, invalid job warning tests, JSONL event validation tests, and detached launch unit tests.
- Modify `tests/test_static_contracts.py`
  - Pin CI/package-smoke coverage for `run-scheduler --watch`, `start-scheduler`/`stop-scheduler` parser visibility if command help text is documented in workflow comments, and the `--once` command shape.
- Modify `.github/workflows/ci.yml`
  - Keep the existing `run-scheduler --once` package smoke.
  - Add a bounded `run-scheduler --watch --poll-interval-seconds 0.1 --max-iterations 3` package smoke job from a non-editable install.
- Modify `tests/test_async_job_artifacts.py`
  - Add a source-controlled Phase 6 live run regression test.
- Create `harness/runs/2026-06-22-phase-6-scheduler-watch-mode/`
  - Record a real bounded watch-mode scheduler run, scheduler artifacts, aggregation, verification, review evidence or waiver, and handoff.
- Modify `README.md`, `docs/INDEX.md`, and `harness/memory/progress.md`
  - Update durable status and residual risks after the live run is complete.

## Task 1: Add Scheduler Artifact Helpers

**Files:**
- Modify: `tests/test_generic_agent_adapter.py`
- Modify: `harness/cli.py`

- [ ] **Step 1: Add failing helper tests**

Append these tests to `GenericCliAgentOrchestrationTest` in `tests/test_generic_agent_adapter.py`:

```python
    def test_scheduler_artifacts_split_worker_identity_heartbeat_and_jsonl_events(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            original_state = minimal_state()
            write_json(run_dir / "state.json", original_state)

            worker = cli.write_scheduler_worker(
                run_dir,
                worker_id="worker-test",
                poll_interval_seconds=0.1,
                max_iterations=3,
                max_seconds=None,
                root=ROOT,
            )
            heartbeat = cli.write_scheduler_heartbeat(
                run_dir,
                worker_id="worker-test",
                iteration=1,
                status="idle",
                current_job_id=None,
            )
            cli.append_scheduler_event(
                run_dir,
                "worker_started",
                {"worker_id": "worker-test"},
            )
            cli.append_scheduler_event(
                run_dir,
                "poll_completed",
                {"worker_id": "worker-test", "iteration": 1},
            )

            scheduler_dir = run_dir / "jobs" / "scheduler"
            saved_worker = json.loads((scheduler_dir / "worker.json").read_text(encoding="utf-8"))
            saved_heartbeat = json.loads((scheduler_dir / "heartbeat.json").read_text(encoding="utf-8"))
            event_lines = (scheduler_dir / "events.log").read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in event_lines]
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(worker, saved_worker)
        self.assertEqual(heartbeat, saved_heartbeat)
        self.assertEqual(saved_state, original_state)
        self.assertEqual(
            set(saved_worker),
            {
                "worker_id",
                "pid",
                "started_at",
                "run_dir",
                "poll_interval",
                "max_iterations",
                "max_seconds",
                "cli_version",
            },
        )
        self.assertEqual(
            set(saved_heartbeat),
            {
                "worker_id",
                "last_seen_at",
                "iteration",
                "status",
                "current_job_id",
            },
        )
        self.assertEqual(saved_worker["worker_id"], "worker-test")
        self.assertEqual(saved_worker["poll_interval"], 0.1)
        self.assertEqual(saved_worker["max_iterations"], 3)
        self.assertEqual(saved_worker["cli_version"], "0.2.0")
        self.assertIn("pid", saved_worker)
        self.assertIn("started_at", saved_worker)
        self.assertNotIn("iteration", saved_worker)
        self.assertNotIn("status", saved_worker)
        self.assertEqual(saved_heartbeat["worker_id"], "worker-test")
        self.assertEqual(saved_heartbeat["iteration"], 1)
        self.assertEqual(saved_heartbeat["status"], "idle")
        self.assertIsNone(saved_heartbeat["current_job_id"])
        self.assertNotIn("pid", saved_heartbeat)
        self.assertEqual([event["event"] for event in events], ["worker_started", "poll_completed"])
        for event in events:
            self.assertIsInstance(event["ts"], str)
            self.assertIsInstance(event["event"], str)
            self.assertIsInstance(event["detail"], dict)

    def test_clear_scheduler_stop_request_removes_stale_stop_file(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            original_state = minimal_state()
            write_json(run_dir / "state.json", original_state)
            stop = cli.request_scheduler_stop(run_dir, reason="old stop", root=ROOT)
            stop_path = run_dir / "jobs" / "scheduler" / "stop.json"

            cli.clear_scheduler_stop_request(run_dir)
            exists_after_clear = stop_path.exists()
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(stop["reason"], "old stop")
        self.assertEqual(stop["requested_by"], "codex")
        self.assertEqual(saved_state, original_state)
        self.assertFalse(exists_after_clear)
```

- [ ] **Step 2: Run helper tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_artifacts_split_worker_identity_heartbeat_and_jsonl_events tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_clear_scheduler_stop_request_removes_stale_stop_file -v
```

Expected: fail with `AttributeError` for missing scheduler helper functions.

- [ ] **Step 3: Add helper imports and constants**

In `harness/cli.py`, add imports near the existing imports:

```python
import time
import uuid
```

Add constants near `GENERIC_ADAPTER_VERSION`:

```python
HARNESS_VERSION = "0.2.0"
SCHEDULER_DIR_NAME = "scheduler"
SCHEDULER_STATUSES = frozenset(
    {
        "starting",
        "idle",
        "running-job",
        "sleeping",
        "warning",
        "stopping",
        "stopped",
        "failed",
    }
)
```

Update `init_run` so it uses `HARNESS_VERSION`:

```python
        "harness_version": HARNESS_VERSION,
        "state_schema_version": HARNESS_VERSION,
```

- [ ] **Step 4: Add scheduler artifact helper functions**

Add these functions before `scheduler_run_once` in `harness/cli.py`:

```python
def scheduler_dir(run_dir: Path | str) -> Path:
    return Path(run_dir) / "jobs" / SCHEDULER_DIR_NAME


def scheduler_worker_path(run_dir: Path | str) -> Path:
    return scheduler_dir(run_dir) / "worker.json"


def scheduler_heartbeat_path(run_dir: Path | str) -> Path:
    return scheduler_dir(run_dir) / "heartbeat.json"


def scheduler_stop_path(run_dir: Path | str) -> Path:
    return scheduler_dir(run_dir) / "stop.json"


def scheduler_events_path(run_dir: Path | str) -> Path:
    return scheduler_dir(run_dir) / "events.log"


def default_worker_id() -> str:
    return f"scheduler-{uuid.uuid4().hex[:12]}"


def append_scheduler_event(
    run_dir: Path | str,
    event: str,
    detail: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "ts": utc_now(),
        "event": event,
        "detail": detail,
    }
    path = scheduler_events_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return payload


def write_scheduler_worker(
    run_dir: Path | str,
    *,
    worker_id: str,
    poll_interval_seconds: float,
    max_iterations: int | None,
    max_seconds: float | None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    worker = {
        "worker_id": worker_id,
        "pid": os.getpid(),
        "run_dir": str(resolved_run_dir.resolve(strict=False)),
        "started_at": utc_now(),
        "poll_interval": poll_interval_seconds,
        "max_iterations": max_iterations,
        "max_seconds": max_seconds,
        "cli_version": HARNESS_VERSION,
    }
    write_json_file(scheduler_worker_path(resolved_run_dir), worker)
    return worker


def write_scheduler_heartbeat(
    run_dir: Path | str,
    *,
    worker_id: str,
    iteration: int,
    status: str,
    current_job_id: str | None,
) -> dict[str, Any]:
    if status not in SCHEDULER_STATUSES:
        raise HarnessCliError(f"invalid scheduler heartbeat status: {status}")
    heartbeat = {
        "worker_id": worker_id,
        "last_seen_at": utc_now(),
        "iteration": iteration,
        "status": status,
        "current_job_id": current_job_id,
    }
    write_json_file(scheduler_heartbeat_path(run_dir), heartbeat)
    return heartbeat


def request_scheduler_stop(
    run_dir: Path | str,
    *,
    reason: str | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))
    payload = {
        "requested_at": utc_now(),
        "requested_by": CODEX_ACTOR,
        "reason": reason or "operator requested shutdown",
    }
    write_json_file(scheduler_stop_path(resolved_run_dir), payload)
    return payload


def clear_scheduler_stop_request(run_dir: Path | str) -> None:
    path = scheduler_stop_path(run_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        return
```

- [ ] **Step 5: Run helper tests and verify they pass**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_artifacts_split_worker_identity_heartbeat_and_jsonl_events tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_clear_scheduler_stop_request_removes_stale_stop_file -v
```

Expected: both tests pass.

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
git add harness/cli.py tests/test_generic_agent_adapter.py
git commit -m "feat: add scheduler worker artifacts"
```

## Task 2: Make `run-scheduler` Mode Explicit

**Files:**
- Modify: `tests/test_generic_agent_adapter.py`
- Modify: `harness/cli.py`

- [ ] **Step 1: Add failing parser tests**

Append these tests to `GenericCliAgentOrchestrationTest`:

```python
    def test_run_scheduler_requires_exactly_one_mode(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())

            missing = subprocess.run(
                [sys.executable, "-m", "harness.cli", "run-scheduler", str(run_dir)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            both = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "run-scheduler",
                    str(run_dir),
                    "--once",
                    "--watch",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(missing.returncode, 2)
        self.assertIn("one of the arguments --once --watch is required", missing.stderr)
        self.assertEqual(both.returncode, 2)
        self.assertIn("not allowed with argument", both.stderr)
```

- [ ] **Step 2: Run parser test and verify it fails**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_run_scheduler_requires_exactly_one_mode -v
```

Expected: fail because current parser only accepts required `--once` and has no `--watch`.

- [ ] **Step 3: Update parser mode group**

In `build_parser`, replace:

```python
    scheduler.add_argument("--once", action="store_true", required=True)
```

with:

```python
    scheduler_mode = scheduler.add_mutually_exclusive_group(required=True)
    scheduler_mode.add_argument("--once", action="store_true")
    scheduler_mode.add_argument("--watch", action="store_true")
    scheduler.add_argument("--poll-interval-seconds", type=float, default=5.0)
    scheduler.add_argument("--max-iterations", type=int)
    scheduler.add_argument("--max-seconds", type=float)
    scheduler.add_argument("--worker-id")
```

- [ ] **Step 4: Keep `--once` main path explicit**

In `main`, replace the `run-scheduler` branch with:

```python
        if args.command == "run-scheduler":
            if args.once:
                summary = scheduler_run_once(args.run_dir)
                print(
                    f"scheduler: {summary['run_id']} "
                    f"executed={len(summary['executed_jobs'])} "
                    f"skipped={len(summary['skipped_jobs'])}",
                )
                return 0
            summary = scheduler_run_watch(
                args.run_dir,
                poll_interval_seconds=args.poll_interval_seconds,
                max_iterations=args.max_iterations,
                max_seconds=args.max_seconds,
                worker_id=args.worker_id,
            )
            print(
                f"scheduler-watch: {summary['run_id']} "
                f"iterations={summary['iterations']} "
                f"executed={len(summary['executed_jobs'])} "
                f"stop_reason={summary['stop_reason']}",
            )
            return 0
```

`scheduler_run_watch` does not exist yet, so only run the parser test in this task.

- [ ] **Step 5: Run parser test and existing `--once` CLI smoke test**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_run_scheduler_requires_exactly_one_mode tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_module_entrypoint_queues_runs_scheduler_and_aggregates -v
```

Expected: parser test passes; existing CLI smoke passes because it uses `run-scheduler --once`.

- [ ] **Step 6: Commit Task 2**

Run:

```powershell
git add harness/cli.py tests/test_generic_agent_adapter.py
git commit -m "feat: require explicit scheduler mode"
```

## Task 3: Implement Foreground Watch Loop

**Files:**
- Modify: `tests/test_generic_agent_adapter.py`
- Modify: `harness/cli.py`

- [ ] **Step 1: Add failing bounded watch test**

Append this test to `GenericCliAgentOrchestrationTest`:

```python
    def test_scheduler_watch_runs_queued_job_writes_artifacts_and_does_not_mutate_state(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state()
            write_json(run_dir / "state.json", state)
            agent_script = run_dir / "watch_agent.py"
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
                    "summary": "Watch job completed.",
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
                print("watch job wrote output")
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "watch-job",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=30,
                root=ROOT,
            )

            summary = cli.scheduler_run_watch(
                run_dir,
                poll_interval_seconds=0,
                max_iterations=3,
                worker_id="watch-worker",
                root=ROOT,
                sleep_fn=lambda seconds: None,
            )
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            job = json.loads((run_dir / "jobs" / "watch-job" / "job.json").read_text(encoding="utf-8"))
            scheduler_dir = run_dir / "jobs" / "scheduler"
            worker = json.loads((scheduler_dir / "worker.json").read_text(encoding="utf-8"))
            heartbeat = json.loads((scheduler_dir / "heartbeat.json").read_text(encoding="utf-8"))
            events = [
                json.loads(line)
                for line in (scheduler_dir / "events.log").read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(saved_state, state)
        self.assertEqual(summary["run_id"], "test-run")
        self.assertEqual(summary["executed_jobs"], ["watch-job"])
        self.assertEqual(summary["stop_reason"], "max_iterations")
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(worker["worker_id"], "watch-worker")
        self.assertEqual(heartbeat["worker_id"], "watch-worker")
        self.assertEqual(heartbeat["status"], "stopped")
        self.assertIsNone(heartbeat["current_job_id"])
        self.assertIn("worker_started", [event["event"] for event in events])
        self.assertIn("job_started", [event["event"] for event in events])
        self.assertIn("job_completed", [event["event"] for event in events])
        self.assertIn("worker_stopped", [event["event"] for event in events])
        for event in events:
            self.assertEqual(set(event), {"detail", "event", "ts"})
            self.assertIsInstance(event["detail"], dict)
```

- [ ] **Step 2: Run bounded watch test and verify it fails**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_watch_runs_queued_job_writes_artifacts_and_does_not_mutate_state -v
```

Expected: fail with `AttributeError` for missing `scheduler_run_watch`.

- [ ] **Step 3: Add watch validation helpers**

Add these helpers before `scheduler_run_watch`:

```python
def validate_scheduler_watch_options(
    *,
    poll_interval_seconds: float,
    max_iterations: int | None,
    max_seconds: float | None,
) -> None:
    if poll_interval_seconds < 0:
        raise HarnessCliError("poll_interval_seconds must be non-negative")
    if max_iterations is not None and max_iterations < 1:
        raise HarnessCliError("max_iterations must be at least 1")
    if max_seconds is not None and max_seconds <= 0:
        raise HarnessCliError("max_seconds must be greater than 0")


def load_scheduler_jobs_for_watch(
    run_dir: Path | str,
    *,
    root: Path | str,
) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        return load_scheduler_jobs(run_dir, root=root), []
    except HarnessCliError as exc:
        return [], str(exc).splitlines()


def scheduler_stop_requested(run_dir: Path | str) -> tuple[bool, dict[str, Any] | None, list[str]]:
    path = scheduler_stop_path(run_dir)
    if not path.exists():
        return False, None, []
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return False, None, [f"{path}: stop request cannot be read: {exc}"]
    if not isinstance(payload, dict):
        return False, None, [f"{path}: stop request must be an object"]
    return True, payload, []
```

- [ ] **Step 4: Add `scheduler_run_watch`**

Add this function after `scheduler_run_once`:

```python
def scheduler_run_watch(
    run_dir: Path | str,
    *,
    poll_interval_seconds: float = 5.0,
    max_iterations: int | None = None,
    max_seconds: float | None = None,
    worker_id: str | None = None,
    root: Path | str | None = None,
    sleep_fn: Any = time.sleep,
    monotonic_fn: Any = time.monotonic,
) -> dict[str, Any]:
    validate_scheduler_watch_options(
        poll_interval_seconds=poll_interval_seconds,
        max_iterations=max_iterations,
        max_seconds=max_seconds,
    )
    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    state = load_json(state_path(resolved_run_dir))
    active_worker_id = worker_id or default_worker_id()
    write_scheduler_worker(
        resolved_run_dir,
        worker_id=active_worker_id,
        poll_interval_seconds=poll_interval_seconds,
        max_iterations=max_iterations,
        max_seconds=max_seconds,
        root=repo_root,
    )
    write_scheduler_heartbeat(
        resolved_run_dir,
        worker_id=active_worker_id,
        iteration=0,
        status="starting",
        current_job_id=None,
    )
    append_scheduler_event(resolved_run_dir, "worker_started", {"worker_id": active_worker_id})

    started_monotonic = monotonic_fn()
    iteration = 0
    executed_jobs: list[str] = []
    skipped_jobs: list[str] = []
    stop_reason = "unknown"

    try:
        while True:
            if max_iterations is not None and iteration >= max_iterations:
                stop_reason = "max_iterations"
                append_scheduler_event(
                    resolved_run_dir,
                    "max_iterations_reached",
                    {"worker_id": active_worker_id, "iteration": iteration},
                )
                break
            if max_seconds is not None and monotonic_fn() - started_monotonic >= max_seconds:
                stop_reason = "max_seconds"
                append_scheduler_event(
                    resolved_run_dir,
                    "max_seconds_reached",
                    {"worker_id": active_worker_id, "iteration": iteration},
                )
                break

            stop_requested, stop_payload, stop_errors = scheduler_stop_requested(resolved_run_dir)
            if stop_errors:
                append_scheduler_event(
                    resolved_run_dir,
                    "invalid_stop_request",
                    {"worker_id": active_worker_id, "errors": stop_errors},
                )
            if stop_requested:
                stop_reason = "stop_requested"
                write_scheduler_heartbeat(
                    resolved_run_dir,
                    worker_id=active_worker_id,
                    iteration=iteration,
                    status="stopping",
                    current_job_id=None,
                )
                append_scheduler_event(
                    resolved_run_dir,
                    "stop_observed",
                    {"worker_id": active_worker_id, "stop": stop_payload},
                )
                break

            iteration += 1
            append_scheduler_event(
                resolved_run_dir,
                "poll_started",
                {"worker_id": active_worker_id, "iteration": iteration},
            )
            jobs, job_errors = load_scheduler_jobs_for_watch(resolved_run_dir, root=repo_root)
            if job_errors:
                write_scheduler_heartbeat(
                    resolved_run_dir,
                    worker_id=active_worker_id,
                    iteration=iteration,
                    status="warning",
                    current_job_id=None,
                )
                append_scheduler_event(
                    resolved_run_dir,
                    "invalid_jobs_observed",
                    {"worker_id": active_worker_id, "iteration": iteration, "errors": job_errors},
                )
                sleep_fn(poll_interval_seconds)
                continue

            ordered_jobs = sorted(jobs, key=lambda job: (job["created_at"], job["job_id"]))
            queued_jobs = [job for job in ordered_jobs if job["status"] == "queued"]
            if not queued_jobs:
                write_scheduler_heartbeat(
                    resolved_run_dir,
                    worker_id=active_worker_id,
                    iteration=iteration,
                    status="idle",
                    current_job_id=None,
                )
                append_scheduler_event(
                    resolved_run_dir,
                    "poll_completed",
                    {"worker_id": active_worker_id, "iteration": iteration, "executed_jobs": []},
                )
                sleep_fn(poll_interval_seconds)
                continue

            for job in queued_jobs:
                job_id = job["job_id"]
                write_scheduler_heartbeat(
                    resolved_run_dir,
                    worker_id=active_worker_id,
                    iteration=iteration,
                    status="running-job",
                    current_job_id=job_id,
                )
                append_scheduler_event(
                    resolved_run_dir,
                    "job_started",
                    {"worker_id": active_worker_id, "job_id": job_id},
                )
                executed_job = execute_generic_agent_job(resolved_run_dir, job_id, root=repo_root)
                executed_jobs.append(job_id)
                append_scheduler_event(
                    resolved_run_dir,
                    "job_completed",
                    {
                        "worker_id": active_worker_id,
                        "job_id": job_id,
                        "status": executed_job["status"],
                    },
                )
                stop_requested, stop_payload, stop_errors = scheduler_stop_requested(resolved_run_dir)
                if stop_errors:
                    append_scheduler_event(
                        resolved_run_dir,
                        "invalid_stop_request",
                        {"worker_id": active_worker_id, "errors": stop_errors},
                    )
                if stop_requested:
                    stop_reason = "stop_requested"
                    write_scheduler_heartbeat(
                        resolved_run_dir,
                        worker_id=active_worker_id,
                        iteration=iteration,
                        status="stopping",
                        current_job_id=None,
                    )
                    append_scheduler_event(
                        resolved_run_dir,
                        "stop_observed",
                        {"worker_id": active_worker_id, "stop": stop_payload},
                    )
                    raise StopIteration

            write_scheduler_heartbeat(
                resolved_run_dir,
                worker_id=active_worker_id,
                iteration=iteration,
                status="sleeping",
                current_job_id=None,
            )
            append_scheduler_event(
                resolved_run_dir,
                "poll_completed",
                {"worker_id": active_worker_id, "iteration": iteration, "executed_jobs": [job["job_id"] for job in queued_jobs]},
            )
            sleep_fn(poll_interval_seconds)
    except StopIteration:
        pass
    except Exception:
        write_scheduler_heartbeat(
            resolved_run_dir,
            worker_id=active_worker_id,
            iteration=iteration,
            status="failed",
            current_job_id=None,
        )
        append_scheduler_event(
            resolved_run_dir,
            "worker_failed",
            {"worker_id": active_worker_id, "iteration": iteration},
        )
        raise

    write_scheduler_heartbeat(
        resolved_run_dir,
        worker_id=active_worker_id,
        iteration=iteration,
        status="stopped",
        current_job_id=None,
    )
    append_scheduler_event(
        resolved_run_dir,
        "worker_stopped",
        {"worker_id": active_worker_id, "iteration": iteration, "stop_reason": stop_reason},
    )
    return {
        "run_id": state["run_id"],
        "worker_id": active_worker_id,
        "iterations": iteration,
        "executed_jobs": executed_jobs,
        "skipped_jobs": skipped_jobs,
        "stop_reason": stop_reason,
    }
```

- [ ] **Step 5: Run bounded watch test and parser tests**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_watch_runs_queued_job_writes_artifacts_and_does_not_mutate_state tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_run_scheduler_requires_exactly_one_mode -v
```

Expected: both tests pass.

- [ ] **Step 6: Commit Task 3**

Run:

```powershell
git add harness/cli.py tests/test_generic_agent_adapter.py
git commit -m "feat: add scheduler watch loop"
```

## Task 4: Add Stop Semantics And Invalid Job Watch Warnings

**Files:**
- Modify: `tests/test_generic_agent_adapter.py`
- Modify: `harness/cli.py`

- [ ] **Step 1: Add stop and invalid-job tests**

Append these tests:

```python
    def test_scheduler_watch_stop_waits_for_current_job_and_does_not_claim_next_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            agent_script = run_dir / "stop_aware_agent.py"
            write_agent_script(
                agent_script,
                """
                import json
                import os
                import time
                from pathlib import Path

                input_path = Path(os.environ["HARNESS_AGENT_INPUT_FILE"])
                output_path = Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"])
                payload = json.loads(input_path.read_text(encoding="utf-8"))
                stop_path = input_path.parents[1] / "scheduler" / "stop.json"
                for _ in range(50):
                    if stop_path.exists():
                        break
                    time.sleep(0.05)
                output = {
                    "run_id": payload["run_id"],
                    "job_id": payload["job_id"],
                    "agent": payload["agent"],
                    "adapter": payload["adapter"],
                    "status": "passed",
                    "summary": "Stop-aware job completed.",
                    "findings": [],
                    "evidence": [],
                    "not_tested": [],
                    "residual_risks": [],
                    "generated_at": payload["created_at"],
                }
                output_path.write_text(json.dumps(output, indent=2) + "\\n", encoding="utf-8")
                """,
            )
            cli.create_generic_agent_job(
                run_dir,
                "001-current",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=10,
                root=ROOT,
            )
            cli.create_generic_agent_job(
                run_dir,
                "002-next",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('must not run')"],
                timeout_seconds=10,
                root=ROOT,
            )

            def run_worker() -> None:
                cli.scheduler_run_watch(
                    run_dir,
                    poll_interval_seconds=0,
                    max_iterations=5,
                    worker_id="stop-worker",
                    root=ROOT,
                    sleep_fn=lambda seconds: None,
                )

            import threading
            worker_thread = threading.Thread(target=run_worker)
            worker_thread.start()
            current_job_path = run_dir / "jobs" / "001-current" / "job.json"
            for _ in range(100):
                current_job = json.loads(current_job_path.read_text(encoding="utf-8"))
                if current_job["status"] == "running":
                    break
                time.sleep(0.05)
            cli.request_scheduler_stop(run_dir, reason="test stop", root=ROOT)
            worker_thread.join(timeout=10)

            current_job = json.loads(current_job_path.read_text(encoding="utf-8"))
            next_job = json.loads((run_dir / "jobs" / "002-next" / "job.json").read_text(encoding="utf-8"))
            heartbeat = json.loads((run_dir / "jobs" / "scheduler" / "heartbeat.json").read_text(encoding="utf-8"))

        self.assertFalse(worker_thread.is_alive())
        self.assertEqual(current_job["status"], "succeeded")
        self.assertEqual(next_job["status"], "queued")
        self.assertEqual(heartbeat["status"], "stopped")

    def test_scheduler_watch_records_invalid_job_warning_and_does_not_claim_valid_jobs(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            bad_path = run_dir / "jobs" / "000-bad" / "job.json"
            bad_path.parent.mkdir(parents=True, exist_ok=True)
            bad_path.write_text("[]\\n", encoding="utf-8")
            cli.create_generic_agent_job(
                run_dir,
                "001-valid",
                agent="generic-test-agent",
                command=[sys.executable, "-c", "print('must not run')"],
                timeout_seconds=30,
                root=ROOT,
            )

            summary = cli.scheduler_run_watch(
                run_dir,
                poll_interval_seconds=0,
                max_iterations=1,
                worker_id="warning-worker",
                root=ROOT,
                sleep_fn=lambda seconds: None,
            )
            valid_job = json.loads((run_dir / "jobs" / "001-valid" / "job.json").read_text(encoding="utf-8"))
            events = [
                json.loads(line)
                for line in (run_dir / "jobs" / "scheduler" / "events.log").read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(summary["executed_jobs"], [])
        self.assertEqual(valid_job["status"], "queued")
        self.assertIn("invalid_jobs_observed", [event["event"] for event in events])
```

- [ ] **Step 2: Run stop and invalid-job tests and verify they fail if behavior is missing**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_watch_stop_waits_for_current_job_and_does_not_claim_next_job tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_watch_records_invalid_job_warning_and_does_not_claim_valid_jobs -v
```

Expected: pass if Task 3 already implemented the stop-after-job and invalid-job skip behavior; otherwise fail with a queued second job being executed or missing `invalid_jobs_observed`.

- [ ] **Step 3: Add missing behavior if tests fail**

If the stop test fails, update `scheduler_run_watch` so it checks `scheduler_stop_requested` immediately after every `execute_generic_agent_job` call and breaks before the next queued job.

If the invalid-job test fails, update `scheduler_run_watch` so any `load_scheduler_jobs_for_watch` error writes heartbeat `status = "warning"`, appends `invalid_jobs_observed`, does not call `execute_generic_agent_job`, and continues to the next iteration.

Use this exact post-job stop block inside the queued-job loop:

```python
                stop_requested, stop_payload, stop_errors = scheduler_stop_requested(resolved_run_dir)
                if stop_errors:
                    append_scheduler_event(
                        resolved_run_dir,
                        "invalid_stop_request",
                        {"worker_id": active_worker_id, "errors": stop_errors},
                    )
                if stop_requested:
                    stop_reason = "stop_requested"
                    write_scheduler_heartbeat(
                        resolved_run_dir,
                        worker_id=active_worker_id,
                        iteration=iteration,
                        status="stopping",
                        current_job_id=None,
                    )
                    append_scheduler_event(
                        resolved_run_dir,
                        "stop_observed",
                        {"worker_id": active_worker_id, "stop": stop_payload},
                    )
                    raise StopIteration
```

- [ ] **Step 4: Run watch behavior tests**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_watch_runs_queued_job_writes_artifacts_and_does_not_mutate_state tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_watch_stop_waits_for_current_job_and_does_not_claim_next_job tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_watch_records_invalid_job_warning_and_does_not_claim_valid_jobs -v
```

Expected: all three tests pass.

- [ ] **Step 5: Commit Task 4**

Run:

```powershell
git add harness/cli.py tests/test_generic_agent_adapter.py
git commit -m "feat: add scheduler stop and warning semantics"
```

## Task 5: Add `start-scheduler` And `stop-scheduler` CLI Commands

**Files:**
- Modify: `tests/test_generic_agent_adapter.py`
- Modify: `harness/cli.py`

- [ ] **Step 1: Add failing detached launch and stop CLI tests**

Append these tests:

```python
    def test_start_scheduler_launches_detached_watch_process(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            write_json(run_dir / "state.json", minimal_state())
            popen_calls = []

            class FakeProcess:
                pid = 43210

            def fake_popen(command, **kwargs):
                popen_calls.append((command, kwargs))
                return FakeProcess()

            with mock.patch("harness.cli.subprocess.Popen", side_effect=fake_popen):
                result = cli.start_scheduler(
                    run_dir,
                    poll_interval_seconds=0.1,
                    max_iterations=3,
                    max_seconds=None,
                    worker_id="detached-worker",
                    root=ROOT,
                )

        command, kwargs = popen_calls[0]
        self.assertEqual(result["worker_id"], "detached-worker")
        self.assertIn(sys.executable, command[0])
        self.assertEqual(command[1:4], ["-m", "harness.cli", "run-scheduler"])
        self.assertIn("--watch", command)
        self.assertIn("--worker-id", command)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)

    def test_stop_scheduler_cli_writes_stop_without_mutating_state(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            run_dir = Path(raw)
            state = minimal_state()
            write_json(run_dir / "state.json", state)

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "stop-scheduler",
                    str(run_dir),
                    "--reason",
                    "cli stop",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            saved_state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            stop = json.loads((run_dir / "jobs" / "scheduler" / "stop.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("stop requested: test-run", result.stdout)
        self.assertEqual(saved_state, state)
        self.assertEqual(stop["reason"], "cli stop")
```

- [ ] **Step 2: Run command tests and verify they fail**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_start_scheduler_launches_detached_watch_process tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_stop_scheduler_cli_writes_stop_without_mutating_state -v
```

Expected: fail because `start_scheduler` and `stop-scheduler` are not implemented.

- [ ] **Step 3: Add detached launch helper**

Add this function before `run_agent_subprocess`:

```python
def start_scheduler(
    run_dir: Path | str,
    *,
    poll_interval_seconds: float = 5.0,
    max_iterations: int | None = None,
    max_seconds: float | None = None,
    worker_id: str | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    validate_scheduler_watch_options(
        poll_interval_seconds=poll_interval_seconds,
        max_iterations=max_iterations,
        max_seconds=max_seconds,
    )
    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    active_worker_id = worker_id or default_worker_id()
    clear_scheduler_stop_request(resolved_run_dir)
    command = [
        sys.executable,
        "-m",
        "harness.cli",
        "run-scheduler",
        str(resolved_run_dir),
        "--watch",
        "--poll-interval-seconds",
        str(poll_interval_seconds),
        "--worker-id",
        active_worker_id,
    ]
    if max_iterations is not None:
        command.extend(["--max-iterations", str(max_iterations)])
    if max_seconds is not None:
        command.extend(["--max-seconds", str(max_seconds)])

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    process = subprocess.Popen(
        command,
        cwd=repo_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    return {
        "run_id": load_json(state_path(resolved_run_dir))["run_id"],
        "worker_id": active_worker_id,
        "pid": process.pid,
        "command": command,
    }
```

- [ ] **Step 4: Register `start-scheduler` and `stop-scheduler`**

In `build_parser`, add:

```python
    start_scheduler_parser = subparsers.add_parser(
        "start-scheduler",
        help="Start a detached local scheduler worker for a Harness run.",
    )
    start_scheduler_parser.add_argument("run_dir")
    start_scheduler_parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    start_scheduler_parser.add_argument("--max-iterations", type=int)
    start_scheduler_parser.add_argument("--max-seconds", type=float)
    start_scheduler_parser.add_argument("--worker-id")

    stop_scheduler_parser = subparsers.add_parser(
        "stop-scheduler",
        help="Request graceful stop for a scheduler worker.",
    )
    stop_scheduler_parser.add_argument("run_dir")
    stop_scheduler_parser.add_argument("--reason")
```

In `main`, add before `run-generic-agent`:

```python
        if args.command == "start-scheduler":
            result = start_scheduler(
                args.run_dir,
                poll_interval_seconds=args.poll_interval_seconds,
                max_iterations=args.max_iterations,
                max_seconds=args.max_seconds,
                worker_id=args.worker_id,
            )
            print(
                f"started scheduler: {result['run_id']} "
                f"worker_id={result['worker_id']} pid={result['pid']}",
            )
            return 0

        if args.command == "stop-scheduler":
            stop = request_scheduler_stop(args.run_dir, reason=args.reason)
            print(f"stop requested: {load_json(state_path(Path(args.run_dir)))['run_id']} {stop['reason']}")
            return 0
```

- [ ] **Step 5: Run command tests**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_start_scheduler_launches_detached_watch_process tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_stop_scheduler_cli_writes_stop_without_mutating_state -v
```

Expected: both tests pass.

- [ ] **Step 6: Commit Task 5**

Run:

```powershell
git add harness/cli.py tests/test_generic_agent_adapter.py
git commit -m "feat: add scheduler worker controls"
```

## Task 6: Update CI Package Smoke And Static Contracts

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_static_contracts.py`

- [ ] **Step 1: Add failing static contract checks**

In `tests/test_static_contracts.py`, extend `test_ci_workflow_runs_core_validation_steps` with:

```python
            "harness run-scheduler \"$GITHUB_WORKSPACE/.tmp/package-smoke-run\" --watch --poll-interval-seconds 0.1 --max-iterations 3",
            "package-smoke-watch-agent",
```

- [ ] **Step 2: Run static contract test and verify it fails**

Run:

```powershell
python -m unittest tests.test_static_contracts.StaticContractsTest.test_ci_workflow_runs_core_validation_steps -v
```

Expected: fail because CI does not yet include the bounded watch package smoke.

- [ ] **Step 3: Add package-smoke watch job to CI**

In `.github/workflows/ci.yml`, after the existing package-smoke scheduler validation, add:

```bash
          cat > "$GITHUB_WORKSPACE/.tmp/package-smoke-watch-agent.py" <<'PY'
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
              "summary": "Package smoke watch agent completed.",
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
          print("package-smoke-watch-agent wrote output")
          PY
          harness queue-generic-agent "$GITHUB_WORKSPACE/.tmp/package-smoke-run" package-smoke-watch --agent package-smoke-agent --timeout-seconds 30 -- python "$GITHUB_WORKSPACE/.tmp/package-smoke-watch-agent.py"
          harness run-scheduler "$GITHUB_WORKSPACE/.tmp/package-smoke-run" --watch --poll-interval-seconds 0.1 --max-iterations 3
          harness aggregate-jobs "$GITHUB_WORKSPACE/.tmp/package-smoke-run"
          harness validate "$GITHUB_WORKSPACE/.tmp/package-smoke-run"
```

Keep the existing `harness run-scheduler "$GITHUB_WORKSPACE/.tmp/package-smoke-run" --once` command unchanged for backward compatibility coverage.

- [ ] **Step 4: Run static contract test**

Run:

```powershell
python -m unittest tests.test_static_contracts.StaticContractsTest.test_ci_workflow_runs_core_validation_steps -v
```

Expected: test passes.

- [ ] **Step 5: Commit Task 6**

Run:

```powershell
git add .github/workflows/ci.yml tests/test_static_contracts.py
git commit -m "ci: smoke test scheduler watch mode"
```

## Task 7: Add Live Phase 6 Run And Durable Docs

**Files:**
- Create: `harness/runs/2026-06-22-phase-6-scheduler-watch-mode/**`
- Modify: `tests/test_async_job_artifacts.py`
- Modify: `README.md`
- Modify: `docs/INDEX.md`
- Modify: `harness/memory/progress.md`

- [ ] **Step 1: Create and advance the live run**

Run:

```powershell
python -m harness.cli init-run harness/runs/2026-06-22-phase-6-scheduler-watch-mode --run-id 2026-06-22-phase-6-scheduler-watch-mode --track Standard --workflow standard-agent-adapter-change --base-commit HEAD
python -m harness.cli advance harness/runs/2026-06-22-phase-6-scheduler-watch-mode triaged
python -m harness.cli advance harness/runs/2026-06-22-phase-6-scheduler-watch-mode planned
python -m harness.cli advance harness/runs/2026-06-22-phase-6-scheduler-watch-mode in_progress
```

Expected: each command exits 0 and prints the new state.

- [ ] **Step 2: Create run task, triage, and plan documents**

Create these files with concrete content:

```text
harness/runs/2026-06-22-phase-6-scheduler-watch-mode/task.md
harness/runs/2026-06-22-phase-6-scheduler-watch-mode/triage.md
harness/runs/2026-06-22-phase-6-scheduler-watch-mode/plan.md
```

Each document must state:

- the run proves bounded local watch mode
- scheduler writes `worker.json`, `heartbeat.json`, and JSONL `events.log`
- scheduler does not mutate `state.json`
- Codex remains responsible for indexing evidence and advancing state
- stale-running recovery and multi-worker locking are not implemented

- [ ] **Step 3: Add live watch smoke script**

Create:

```text
harness/runs/2026-06-22-phase-6-scheduler-watch-mode/scripts/watch-smoke.py
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
        "summary": "Phase 6 scheduler watch smoke completed.",
        "findings": [],
        "evidence": [
            {
                "path": "raw.log",
                "description": "raw.log captures deterministic Phase 6 watch smoke stdout.",
            }
        ],
        "not_tested": [
            "Multi-worker claim locking.",
            "Automatic stale-running recovery.",
            "Cloud queue execution.",
            "Cross-run queue execution.",
        ],
        "residual_risks": [
            "Heartbeat is observational only.",
            "Stop requests are cooperative and do not interrupt running jobs.",
            "Double-claim risk remains if multiple workers are launched against the same run.",
        ],
        "generated_at": payload["created_at"],
    }
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print("phase6 scheduler watch agent wrote output")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Queue, watch, stop, and aggregate**

Run:

```powershell
python -m harness.cli queue-generic-agent harness/runs/2026-06-22-phase-6-scheduler-watch-mode phase6-watch-agent --agent generic-cli-agent --timeout-seconds 30 -- python ..\..\scripts\watch-smoke.py
python -m harness.cli run-scheduler harness/runs/2026-06-22-phase-6-scheduler-watch-mode --watch --poll-interval-seconds 0.1 --max-iterations 3 --worker-id phase6-live-watch
python -m harness.cli stop-scheduler harness/runs/2026-06-22-phase-6-scheduler-watch-mode --reason "live run stop command exercised after bounded watch"
python -m harness.cli aggregate-jobs harness/runs/2026-06-22-phase-6-scheduler-watch-mode
```

Expected:

- queue prints `queued generic-agent: 2026-06-22-phase-6-scheduler-watch-mode/phase6-watch-agent`
- watch prints `scheduler-watch: 2026-06-22-phase-6-scheduler-watch-mode iterations=3 executed=1 stop_reason=max_iterations`
- stop prints `stop requested: 2026-06-22-phase-6-scheduler-watch-mode live run stop command exercised after bounded watch`
- aggregate prints `aggregated jobs: 2026-06-22-phase-6-scheduler-watch-mode consumed=1 incomplete=0`

- [ ] **Step 5: Index consumed evidence and closure artifacts**

Run:

```powershell
python -m harness.cli index-evidence harness/runs/2026-06-22-phase-6-scheduler-watch-mode agent-job jobs/phase6-watch-agent/job.json --description "Terminal watch-executed async job consumed by Codex."
python -m harness.cli index-evidence harness/runs/2026-06-22-phase-6-scheduler-watch-mode agent-result jobs/phase6-watch-agent/output.json --description "Structured watch-executed agent result consumed by Codex."
python -m harness.cli index-evidence harness/runs/2026-06-22-phase-6-scheduler-watch-mode aggregation jobs/aggregation.json --description "Codex fan-in aggregation generated after watch execution."
```

Expected: each command exits 0.

- [ ] **Step 6: Write verification, review, and handoff**

Create:

```text
harness/runs/2026-06-22-phase-6-scheduler-watch-mode/verification.md
harness/runs/2026-06-22-phase-6-scheduler-watch-mode/review-waiver.md
harness/runs/2026-06-22-phase-6-scheduler-watch-mode/handoff.md
```

`handoff.md` frontmatter must include these exact risk statements:

```yaml
not_verified:
  - "Multi-worker claim locking."
  - "Automatic stale-running recovery."
  - "Cloud queue execution."
  - "Cross-run queue execution."
residual_risks:
  - "Heartbeat is observational only."
  - "Stop requests are cooperative and do not interrupt running jobs."
  - "Double-claim risk remains if multiple workers are launched against the same run."
```

- [ ] **Step 7: Complete and validate live run**

Run:

```powershell
python -m harness.cli advance harness/runs/2026-06-22-phase-6-scheduler-watch-mode implemented
python -m harness.cli index-evidence harness/runs/2026-06-22-phase-6-scheduler-watch-mode verification verification.md --description "Verification record."
python -m harness.cli index-evidence harness/runs/2026-06-22-phase-6-scheduler-watch-mode review-waiver review-waiver.md --description "Scoped run-record review waiver."
python -m harness.cli index-evidence harness/runs/2026-06-22-phase-6-scheduler-watch-mode handoff handoff.md --description "Completion handoff."
python -m harness.cli advance harness/runs/2026-06-22-phase-6-scheduler-watch-mode verified
python -m harness.cli advance harness/runs/2026-06-22-phase-6-scheduler-watch-mode reviewed
python -m harness.cli advance harness/runs/2026-06-22-phase-6-scheduler-watch-mode completed
python -m harness.cli validate harness/runs/2026-06-22-phase-6-scheduler-watch-mode
```

Expected: final validation exits 0 and prints `valid: harness\runs\2026-06-22-phase-6-scheduler-watch-mode`.

- [ ] **Step 8: Add live run regression test**

In `tests/test_async_job_artifacts.py`, add:

```python
PHASE6_WATCH_RUN = ROOT / "harness" / "runs" / "2026-06-22-phase-6-scheduler-watch-mode"
```

Add this test to `Phase4ClosureRunTest`:

```python
    def test_phase6_watch_run_was_produced_by_watch_scheduler_path(self):
        result = cli.validate_run(PHASE6_WATCH_RUN, root=ROOT)
        state = json.loads((PHASE6_WATCH_RUN / "state.json").read_text(encoding="utf-8"))
        evidence_types = {item["type"] for item in state["evidence"]}
        scheduler_dir = PHASE6_WATCH_RUN / "jobs" / "scheduler"
        worker = json.loads((scheduler_dir / "worker.json").read_text(encoding="utf-8"))
        heartbeat = json.loads((scheduler_dir / "heartbeat.json").read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in (scheduler_dir / "events.log").read_text(encoding="utf-8").splitlines()
        ]
        aggregation = json.loads(
            PHASE6_WATCH_RUN.joinpath("jobs", "aggregation.json").read_text(encoding="utf-8")
        )

        self.assertEqual(result.errors, [])
        self.assertEqual(state["status"], "completed")
        self.assertIn("agent-job", evidence_types)
        self.assertIn("agent-result", evidence_types)
        self.assertIn("aggregation", evidence_types)
        self.assertEqual(worker["worker_id"], "phase6-live-watch")
        self.assertEqual(heartbeat["status"], "stopped")
        self.assertIn("worker_started", [event["event"] for event in events])
        self.assertIn("job_completed", [event["event"] for event in events])
        self.assertEqual(aggregation["consumed_jobs"], ["phase6-watch-agent"])
        self.assertEqual(aggregation["incomplete_jobs"], [])
```

- [ ] **Step 9: Update durable docs**

Update:

- `README.md`: add Phase 6 scheduler watch mode to current capabilities and keep multi-worker/stale recovery listed as not implemented.
- `docs/INDEX.md`: add the Phase 6 design, plan, and live run to the current status/index.
- `harness/memory/progress.md`: record Phase 6 outcome, heartbeat semantics, stop semantics, double-claim residual risk, and verification baseline.

- [ ] **Step 10: Run live run tests and commit**

Run:

```powershell
python -m unittest tests.test_async_job_artifacts.Phase4ClosureRunTest.test_phase6_watch_run_was_produced_by_watch_scheduler_path -v
python -m harness.cli validate harness/runs/2026-06-22-phase-6-scheduler-watch-mode
```

Expected: both commands exit 0.

Commit:

```powershell
git add harness/runs/2026-06-22-phase-6-scheduler-watch-mode tests/test_async_job_artifacts.py README.md docs/INDEX.md harness/memory/progress.md
git commit -m "feat: add Phase 6 scheduler watch smoke run"
```

## Task 8: Full Verification And Review

**Files:**
- Verify all changed files.
- Add review artifacts if external review is available.

- [ ] **Step 1: Run full unit suite**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: all tests pass, with only documented environment-gated skips.

- [ ] **Step 2: Validate every source-controlled run**

First verify the current shell used by the execution environment. In local PowerShell, run:

```powershell
Get-ChildItem -Directory harness/runs | ForEach-Object { python -m harness.cli validate $_.FullName }
```

Expected: every run prints `valid:`.

If running in bash, use:

```bash
for run_dir in harness/runs/*; do
  if [ -d "$run_dir" ]; then
    python -m harness.cli validate "$run_dir"
  fi
done
```

Expected: every run prints `valid:`.

- [ ] **Step 3: Run package install smoke locally**

Run:

```powershell
$venv = Join-Path $env:TEMP "harness-phase6-package-smoke"
if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }
python -m venv $venv
& "$venv\Scripts\python.exe" -m pip install --upgrade pip
& "$venv\Scripts\python.exe" -m pip install .
Push-Location $env:TEMP
& "$venv\Scripts\harness.exe" validate "C:\ai\ai-coding-harness\harness\runs\example-fast-doc-change"
Pop-Location
Remove-Item -Recurse -Force $venv
```

Expected: packaged `harness.exe` validates the example run from outside the repository.

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
- Phase 6 live run
- README/docs/memory status updates

- [ ] **Step 6: Run external review or record unavailability**

This implementation touches CLI orchestration, scheduler lifecycle behavior, CI, tests, and run evidence. It qualifies for external review under `harness/core/delegation.md`.

If the Claude review adapter is available, run it against:

- Phase 6 design spec
- this implementation plan
- `git diff "$(git merge-base origin/master HEAD)" HEAD`
- verification outputs

Acceptable outcomes:

- `passed`
- `findings` with no high or critical findings after triage

If the adapter is unavailable, record a scoped review waiver in the Phase 6 run or final handoff. Do not claim external review passed without a concrete artifact.

- [ ] **Step 7: Final commit if review or verification artifacts changed**

If Step 6 changes source-controlled artifacts, commit them:

```powershell
git add harness/runs/2026-06-22-phase-6-scheduler-watch-mode README.md docs/INDEX.md harness/memory/progress.md
git commit -m "docs: record Phase 6 scheduler review outcome"
```

## Acceptance Checklist

- [ ] `run-scheduler` requires exactly one of `--once` or `--watch`.
- [ ] `run-scheduler --once` remains strict on invalid job records.
- [ ] `run-scheduler --watch` writes `worker.json`, `heartbeat.json`, and JSONL `events.log`.
- [ ] `worker.json` stores identity/configuration only.
- [ ] `heartbeat.json` stores volatile state only.
- [ ] `events.log` lines are valid JSON objects with `ts`, `event`, and `detail`.
- [ ] A pre-existing `stop.json` is cleared at watch startup.
- [ ] `stop-scheduler` writes stop request artifacts without mutating `state.json`.
- [ ] Stop requests do not interrupt a running job.
- [ ] Watch mode does not claim later queued jobs after observing stop.
- [ ] Watch mode records invalid job records as warnings and does not partially execute other queued jobs in a corrupt job set.
- [ ] `start-scheduler` launches a detached child using the same watch loop and redirects stdio away from the caller.
- [ ] Scheduler commands never index evidence.
- [ ] Scheduler commands never advance `state.json`.
- [ ] No lockfile or stale-running recovery is introduced.
- [ ] CI package smoke covers both `--once` and bounded `--watch`.
- [ ] A live Phase 6 scheduler watch run exists and validates.
- [ ] Full unit tests pass.
- [ ] Every source-controlled run validates.
- [ ] `git diff --check` reports no whitespace errors.
