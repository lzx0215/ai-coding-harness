# Phase 8 Multi-Worker Concurrency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden local multi-worker scheduler execution so concurrent workers cannot duplicate job execution or overwrite `raw.log` / `output.json`.

**Architecture:** Keep Phase 7.1 `claim.lock` as the local ownership primitive, then add lease metadata, per-claim tokens, claim-aware job state writes, and exclusive artifact publishing. Claimed scheduler execution writes agent output to a claim-specific temporary file and publishes it to `output.json` only after claim comparison succeeds.

**Tech Stack:** Python 3.12 stdlib (`pathlib`, `uuid`, `datetime`, `os`, `shutil`, `subprocess`, `threading`, `time`), JSON Schema 2020-12, `unittest`, existing harness CLI helpers.

---

## File Structure

- Modify `harness/cli.py`: claim token generation, lease owner payloads, claim comparison helpers, scheduler execution integration, staged output publishing, exclusive raw log writes, stale detection lease reporting, recovery claim-field clearing.
- Modify `harness/schemas/claim-owner.schema.json`: schema version 2 with `claim_token` and lease timestamps.
- Modify `harness/schemas/job.schema.json`: nullable `claim_token`, `claim_started_at`, `claim_updated_at`.
- Modify `tests/test_async_job_artifacts.py`: claim owner schema v2 and job schema claim field tests.
- Modify `tests/test_generic_agent_adapter.py`: G1 gate tests, B2 lease tests, B1 conditional write tests, artifact guard tests, deterministic concurrency tests, live multi-worker smoke.
- Modify `docs/INDEX.md`, `harness/core/state-authority.md`, and `harness/core/evidence.md` only if implementation changes the documented control-file contract.

## Task 1: G1 Startup Gate

**Files:**
- Test: `tests/test_generic_agent_adapter.py`
- Modify only if the gate fails: `harness/cli.py`, `tests/test_generic_agent_adapter.py`

- [x] **Step 1: Run the Windows claim-lock retry gate**

Run:

```powershell
python -m unittest `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_acquire_claim_lock_retries_transient_windows_access_denied `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_run_once_two_workers_execute_same_queued_job_at_most_once `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_module_entrypoint_queues_runs_scheduler_and_aggregates `
  -v
```

Expected: all three tests pass. If any test fails, stop Phase 8 work and restore the Phase 7.1 M1/L1 fix before continuing.

- [x] **Step 2: Confirm the retry constants exist**

Check `harness/cli.py` contains:

```python
CLAIM_LOCK_RENAME_ATTEMPTS = 5
CLAIM_LOCK_RENAME_RETRY_SECONDS = 0.01
TRANSIENT_CLAIM_LOCK_WINERRORS = frozenset({5, 32, 33})
```

Expected: constants exist and `acquire_claim_lock_dir` retries transient `winerror` values before raising.

- [x] **Step 3: Commit gate state**

No commit is required if the gate already passes in the current working tree. If fixes were needed, run the gate again and commit only the gate fix:

```powershell
git add harness/cli.py tests/test_generic_agent_adapter.py
git commit -m "fix: keep claim lock retry gate passing"
```

## Task 2: B2 Claim Owner Schema And Lease Creation

**Files:**
- Modify: `harness/schemas/claim-owner.schema.json`
- Modify: `tests/test_async_job_artifacts.py`
- Modify: `harness/cli.py`
- Test: `tests/test_async_job_artifacts.py`
- Test: `tests/test_generic_agent_adapter.py`

- [x] **Step 1: Write failing schema tests**

In `tests/test_async_job_artifacts.py`, update `minimal_claim_owner()` to version 2:

```python
def minimal_claim_owner() -> dict:
    return {
        "schema_version": 2,
        "run_id": "test-run",
        "job_id": "claude-review-001",
        "worker_id": "worker-a",
        "claim_token": "a" * 32,
        "claimed_at": "2026-06-20T00:01:00Z",
        "lease_started_at": "2026-06-20T00:01:00Z",
        "lease_heartbeat_at": "2026-06-20T00:01:00Z",
        "lease_expires_at": "2026-06-20T00:02:00Z",
        "lock_path": "jobs/claude-review-001/claim.lock",
    }
```

Add:

```python
def test_claim_owner_schema_rejects_missing_claim_token(self):
    owner = minimal_claim_owner()
    owner.pop("claim_token")

    errors = validation_errors(CLAIM_OWNER_SCHEMA, owner)

    self.assertTrue(errors)


def test_claim_owner_schema_rejects_malformed_claim_token(self):
    owner = minimal_claim_owner()
    owner["claim_token"] = "a" * 31

    errors = validation_errors(CLAIM_OWNER_SCHEMA, owner)

    self.assertTrue(errors)
```

- [x] **Step 2: Run schema tests and confirm failure**

Run:

```powershell
python -m unittest `
  tests.test_async_job_artifacts.AsyncJobArtifactSchemaTest.test_claim_owner_schema_accepts_minimal_payload `
  tests.test_async_job_artifacts.AsyncJobArtifactSchemaTest.test_claim_owner_schema_rejects_missing_claim_token `
  -v
```

Expected: fail because `claim-owner.schema.json` still expects schema version 1 and lacks lease fields.

- [x] **Step 3: Update claim owner schema**

Change `harness/schemas/claim-owner.schema.json` to require version 2 fields:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Harness Scheduler Claim Owner",
  "type": "object",
  "required": [
    "schema_version",
    "run_id",
    "job_id",
    "worker_id",
    "claim_token",
    "claimed_at",
    "lease_started_at",
    "lease_heartbeat_at",
    "lease_expires_at",
    "lock_path"
  ],
  "properties": {
    "schema_version": { "type": "integer", "const": 2 },
    "run_id": { "type": "string", "minLength": 1 },
    "job_id": { "type": "string", "minLength": 1 },
    "worker_id": { "type": "string", "minLength": 1 },
    "claim_token": {
      "type": "string",
      "pattern": "^[0-9a-f]{32}$"
    },
    "claimed_at": {
      "type": "string",
      "minLength": 1,
      "format": "date-time",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:Z|[+-]\\d{2}:\\d{2})$"
    },
    "lease_started_at": {
      "type": "string",
      "minLength": 1,
      "format": "date-time",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:Z|[+-]\\d{2}:\\d{2})$"
    },
    "lease_heartbeat_at": {
      "type": "string",
      "minLength": 1,
      "format": "date-time",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:Z|[+-]\\d{2}:\\d{2})$"
    },
    "lease_expires_at": {
      "type": "string",
      "minLength": 1,
      "format": "date-time",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:Z|[+-]\\d{2}:\\d{2})$"
    },
    "lock_path": { "type": "string", "minLength": 1 }
  },
  "additionalProperties": false
}
```

- [x] **Step 4: Write failing claim creation test**

In `tests/test_generic_agent_adapter.py`, update `test_try_claim_job_creates_owner_and_blocks_second_worker` assertions:

```python
self.assertEqual(owner["schema_version"], 2)
self.assertRegex(owner["claim_token"], r"^[0-9a-f]{32}$")
self.assertEqual(owner["lease_started_at"], owner["claimed_at"])
self.assertEqual(owner["lease_heartbeat_at"], owner["claimed_at"])
claimed_at = cli.parse_datetime(owner["claimed_at"])
lease_expires_at = cli.parse_datetime(owner["lease_expires_at"])
self.assertIsNotNone(claimed_at)
self.assertIsNotNone(lease_expires_at)
self.assertEqual(
    lease_expires_at - claimed_at,
    timedelta(seconds=cli.DEFAULT_CLAIM_LEASE_SECONDS),
)
self.assertEqual(claim.claim_token, owner["claim_token"])
```

Expected: fail because `JobClaim` and owner payload do not include lease fields yet.

- [x] **Step 5: Implement claim token and lease owner payload**

In `harness/cli.py`, extend `JobClaim`:

```python
@dataclass(frozen=True)
class JobClaim:
    run_dir: Path
    job_id: str
    worker_id: str
    claim_token: str
    job_dir: Path
    lock_dir: Path
    owner_path: Path
    owner: dict[str, Any]
```

Add helpers near claim path helpers:

```python
DEFAULT_CLAIM_LEASE_SECONDS = 60.0


def new_claim_token() -> str:
    return uuid.uuid4().hex


def add_seconds(timestamp: datetime, seconds: float) -> datetime:
    return timestamp + timedelta(seconds=seconds)


def build_claim_owner(
    *,
    run_id: str,
    job_id: str,
    worker_id: str,
    claim_token: str,
    claimed_at: datetime,
    lease_seconds: float = DEFAULT_CLAIM_LEASE_SECONDS,
) -> dict[str, Any]:
    lease_expires_at = add_seconds(claimed_at, lease_seconds)
    formatted_claimed_at = format_datetime(claimed_at)
    return {
        "schema_version": 2,
        "run_id": run_id,
        "job_id": job_id,
        "worker_id": worker_id,
        "claim_token": claim_token,
        "claimed_at": formatted_claimed_at,
        "lease_started_at": formatted_claimed_at,
        "lease_heartbeat_at": formatted_claimed_at,
        "lease_expires_at": format_datetime(lease_expires_at),
        "lock_path": claim_lock_relative_path(job_id),
    }
```

Update `try_claim_job` owner creation:

```python
claim_token = new_claim_token()
owner = build_claim_owner(
    run_id=state["run_id"],
    job_id=job_id,
    worker_id=worker_id,
    claim_token=claim_token,
    claimed_at=datetime.now(timezone.utc),
)
```

Pass `claim_token=claim_token` into every `JobClaim(...)` construction.

- [x] **Step 6: Run B2 schema and claim creation tests**

Run:

```powershell
python -m unittest `
  tests.test_async_job_artifacts.AsyncJobArtifactSchemaTest.test_claim_owner_schema_accepts_minimal_payload `
  tests.test_async_job_artifacts.AsyncJobArtifactSchemaTest.test_claim_owner_schema_rejects_missing_claim_token `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_try_claim_job_creates_owner_and_blocks_second_worker `
  -v
```

Expected: all pass.

## Task 3: B2 Lease Refresh And Stale Detection Boundaries

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_generic_agent_adapter.py`
- Test: `tests/test_generic_agent_adapter.py`

- [x] **Step 1: Write failing lease refresh test**

Add:

```python
def test_refresh_claim_lease_updates_owner_without_changing_job(self):
    with tempfile.TemporaryDirectory(dir=ROOT) as raw:
        run_dir = Path(raw)
        write_json(run_dir / "state.json", minimal_state())
        cli.create_generic_agent_job(
            run_dir,
            "lease-refresh",
            agent="generic-test-agent",
            command=[sys.executable, "-c", "print('lease')"],
            timeout_seconds=30,
            root=ROOT,
        )
        claim = cli.try_claim_job(run_dir, "lease-refresh", worker_id="worker-a", root=ROOT)
        original_job = json.loads((run_dir / "jobs" / "lease-refresh" / "job.json").read_text(encoding="utf-8"))

        refreshed = cli.refresh_claim_lease(
            claim,
            lease_seconds=30,
            now="2026-06-22T00:01:00Z",
            root=ROOT,
        )
        saved_owner = json.loads((run_dir / "jobs" / "lease-refresh" / "claim.lock" / "owner.json").read_text(encoding="utf-8"))
        saved_job = json.loads((run_dir / "jobs" / "lease-refresh" / "job.json").read_text(encoding="utf-8"))
        cli.release_job_claim(claim)

    self.assertEqual(saved_job, original_job)
    self.assertEqual(refreshed.owner, saved_owner)
    self.assertEqual(saved_owner["lease_heartbeat_at"], "2026-06-22T00:01:00Z")
    self.assertEqual(saved_owner["lease_expires_at"], "2026-06-22T00:01:30Z")
```

- [x] **Step 2: Write failing stale detection lease report test**

Add:

```python
def test_detect_stale_reports_expired_claim_lease(self):
    with tempfile.TemporaryDirectory(dir=ROOT) as raw:
        run_dir = Path(raw)
        write_json(run_dir / "state.json", minimal_state())
        cli.create_generic_agent_job(
            run_dir,
            "expired-lease",
            agent="generic-test-agent",
            command=[sys.executable, "-c", "print('lease')"],
            timeout_seconds=30,
            root=ROOT,
        )
        mark_job_running(run_dir, "expired-lease", worker_id="worker-old")
        write_claim_owner(
            run_dir,
            "expired-lease",
            worker_id="worker-old",
            claimed_at="2026-06-22T00:00:00Z",
            claim_token="e" * 32,
        )
        owner_path = run_dir / "jobs" / "expired-lease" / "claim.lock" / "owner.json"
        owner = json.loads(owner_path.read_text(encoding="utf-8"))
        owner.update(
            {
                "schema_version": 2,
                "lease_started_at": "2026-06-22T00:00:00Z",
                "lease_heartbeat_at": "2026-06-22T00:01:00Z",
                "lease_expires_at": "2026-06-22T00:02:00Z",
            }
        )
        write_json(owner_path, owner)

        report = cli.detect_stale_running_jobs(
            run_dir,
            heartbeat_timeout_seconds=60,
            now="2026-06-22T00:10:00Z",
            root=ROOT,
        )

    claim_lock = report["jobs"][0]["claim_lock"]
    self.assertEqual(claim_lock["status"], "present")
    self.assertTrue(claim_lock["lease_expired"])
    self.assertEqual(claim_lock["claim_token"], "e" * 32)
    self.assertEqual(claim_lock["lease_heartbeat_at"], "2026-06-22T00:01:00Z")
    self.assertEqual(claim_lock["lease_expires_at"], "2026-06-22T00:02:00Z")
    self.assertEqual(claim_lock["lease_age_seconds"], 540.0)
```

- [x] **Step 3: Run tests and confirm failure**

Run:

```powershell
python -m unittest `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_refresh_claim_lease_updates_owner_without_changing_job `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_detect_stale_reports_expired_claim_lease `
  -v
```

Expected: fail because `refresh_claim_lease` and lease status fields do not exist.

- [x] **Step 4: Implement lease refresh**

In `harness/cli.py`, add:

```python
def refresh_claim_lease(
    claim: JobClaim,
    *,
    lease_seconds: float = DEFAULT_CLAIM_LEASE_SECONDS,
    now: str | datetime | None = None,
    root: Path | str | None = None,
) -> JobClaim:
    resolved_run_dir = Path(claim.run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    state = load_json(state_path(resolved_run_dir))
    with claim_lifecycle_lock(claim.job_dir):
        owner, owner_errors = validate_json_artifact(
            claim.owner_path,
            CLAIM_OWNER_SCHEMA,
            "claim-owner",
        )
        if owner_errors:
            raise HarnessCliError(format_errors(owner_errors))
        if owner is None:
            raise HarnessCliError(f"claim owner cannot be loaded: {claim.owner_path}")
        if owner.get("run_id") != state["run_id"]:
            raise HarnessCliError("claim owner run_id mismatch")
        if owner.get("job_id") != claim.job_id:
            raise HarnessCliError("claim owner job_id mismatch")
        if owner.get("worker_id") != claim.worker_id:
            raise HarnessCliError("claim owner worker_id mismatch")
        if owner.get("claim_token") != claim.claim_token:
            raise HarnessCliError("claim owner claim_token mismatch")

        now_dt = resolve_datetime(now, "now")
        refreshed_owner = dict(owner)
        refreshed_owner["lease_heartbeat_at"] = format_datetime(now_dt)
        refreshed_owner["lease_expires_at"] = format_datetime(add_seconds(now_dt, lease_seconds))
        write_json_atomic(claim.owner_path, refreshed_owner)
        return replace(claim, owner=refreshed_owner)
```

`try_claim_job`, `release_job_claim`, `refresh_claim_lease`, and recovery lock cleanup must use the same per-job `claim_lifecycle_lock` so an old worker cannot refresh an owner path after another worker has released and reclaimed the job.

- [x] **Step 5: Extend claim lock status**

Update `read_claim_lock_status` after valid owner load:

```python
now_dt = resolve_datetime(now, "now")
lease_expires_at = parse_datetime(owner.get("lease_expires_at"))
lease_heartbeat_at = parse_datetime(owner.get("lease_heartbeat_at"))
status["claim_token"] = owner.get("claim_token")
status["lease_heartbeat_at"] = owner.get("lease_heartbeat_at")
status["lease_expires_at"] = owner.get("lease_expires_at")
status["lease_age_seconds"] = seconds_since(lease_heartbeat_at, now_dt)
status["lease_expired"] = (
    lease_expires_at is not None and seconds_since(lease_expires_at, now_dt) > 0
)
```

Change the helper signature so stale detection passes deterministic time into claim status:

```python
def read_claim_lock_status(run_dir: Path | str, job_id: str, *, run_id: str, now: str | datetime | None = None) -> dict[str, Any]:
```

Pass the same `now_dt` used by `detect_stale_running_jobs` into `read_claim_lock_status`.

- [x] **Step 6: Run B2 tests**

Run:

```powershell
python -m unittest `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_refresh_claim_lease_updates_owner_without_changing_job `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_refresh_claim_lease_does_not_overwrite_reclaimed_owner `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_remove_claim_lock_retries_transient_windows_directory_not_empty `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_detect_stale_reports_expired_claim_lease `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_expired_claim_lease_does_not_change_active_classification `
  -v
```

Expected: pass.

## Task 4: B1 Conditional Job Write Helpers

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_generic_agent_adapter.py`
- Test: `tests/test_generic_agent_adapter.py`

- [x] **Step 1: Write failing compare tests**

Add:

```python
def test_assert_claim_matches_job_rejects_mismatched_token(self):
    job = {
        "run_id": "test-run",
        "job_id": "token-job",
        "status": "running",
        "claim_token": "a" * 32,
    }
    owner = {
        "run_id": "test-run",
        "job_id": "token-job",
        "worker_id": "worker-a",
        "claim_token": "b" * 32,
    }

    with self.assertRaises(cli.HarnessCliError) as raised:
        cli.assert_claim_matches_job(
            job,
            owner,
            worker_id="worker-a",
            expected_status="running",
            expected_claim_token="b" * 32,
        )

    self.assertIn("claim_token mismatch", str(raised.exception))
```

Add:

```python
def test_write_job_if_claim_matches_rejects_unexpected_status(self):
    with tempfile.TemporaryDirectory(dir=ROOT) as raw:
        run_dir = Path(raw)
        write_json(run_dir / "state.json", minimal_state())
        cli.create_generic_agent_job(
            run_dir,
            "conditional-status",
            agent="generic-test-agent",
            command=[sys.executable, "-c", "print('status')"],
            timeout_seconds=30,
            root=ROOT,
        )
        claim = cli.try_claim_job(run_dir, "conditional-status", worker_id="worker-a", root=ROOT)
        job_path = run_dir / "jobs" / "conditional-status" / "job.json"
        job = json.loads(job_path.read_text(encoding="utf-8"))
        job["status"] = "running"
        job["claim_token"] = "c" * 32
        write_json(job_path, job)

        with self.assertRaises(cli.HarnessCliError) as raised:
            cli.write_job_if_claim_matches(
                claim,
                expected_status="queued",
                mutate=lambda current: current,
            )
        cli.release_job_claim(claim)

    self.assertIn("status mismatch", str(raised.exception))
```

- [x] **Step 2: Run compare tests and confirm failure**

Run:

```powershell
python -m unittest `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_assert_claim_matches_job_rejects_mismatched_token `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_write_job_if_claim_matches_rejects_unexpected_status `
  -v
```

Expected: fail with missing helper attributes.

- [x] **Step 3: Implement claim compare helpers**

In `harness/cli.py`, add:

```python
def assert_claim_matches_job(
    job: dict[str, Any],
    owner: dict[str, Any],
    *,
    worker_id: str,
    expected_status: str,
    expected_claim_token: str | None,
) -> None:
    errors: list[str] = []
    if owner.get("run_id") != job.get("run_id"):
        errors.append("run_id mismatch")
    if owner.get("job_id") != job.get("job_id"):
        errors.append("job_id mismatch")
    if owner.get("worker_id") != worker_id:
        errors.append("worker_id mismatch")
    if owner.get("claim_token") != expected_claim_token:
        errors.append("owner claim_token mismatch")
    if job.get("status") != expected_status:
        errors.append(f"status mismatch: expected {expected_status}, got {job.get('status')}")
    job_claim_token = job.get("claim_token")
    if expected_status == "queued" and job_claim_token is not None:
        errors.append(f"claim_token mismatch: expected null, got {job_claim_token}")
    if expected_status == "running" and job_claim_token != expected_claim_token:
        errors.append("claim_token mismatch")
    if errors:
        raise HarnessCliError(format_errors(errors))
```

Add:

```python
def load_claim_owner_for_claim(claim: JobClaim) -> dict[str, Any]:
    owner, owner_errors = validate_json_artifact(claim.owner_path, CLAIM_OWNER_SCHEMA, "claim-owner")
    if owner_errors:
        raise HarnessCliError(format_errors(owner_errors))
    if owner is None:
        raise HarnessCliError(f"claim owner cannot be loaded: {claim.owner_path}")
    return owner
```

Add:

```python
def write_job_if_claim_matches(
    claim: JobClaim,
    *,
    expected_status: str,
    mutate: Any,
) -> dict[str, Any]:
    owner = load_claim_owner_for_claim(claim)
    job_path = claim.job_dir / "job.json"
    job, job_errors = validate_json_artifact(job_path, JOB_SCHEMA, "job")
    if job_errors:
        raise HarnessCliError(format_errors(job_errors))
    if job is None:
        raise HarnessCliError(f"job cannot be loaded: {job_path}")
    assert_claim_matches_job(
        job,
        owner,
        worker_id=claim.worker_id,
        expected_status=expected_status,
        expected_claim_token=claim.claim_token,
    )
    new_job = mutate(json.loads(json.dumps(job)))
    write_json_atomic(job_path, new_job)
    return new_job
```

- [x] **Step 4: Add job schema claim fields**

In `harness/schemas/job.schema.json`, add properties:

```json
"claim_token": {
  "anyOf": [
    { "type": "null" },
    { "type": "string", "pattern": "^[0-9a-f]{32}$" }
  ]
},
"claim_started_at": {
  "type": ["string", "null"],
  "minLength": 1,
  "format": "date-time",
  "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:Z|[+-]\\d{2}:\\d{2})$"
},
"claim_updated_at": {
  "type": ["string", "null"],
  "minLength": 1,
  "format": "date-time",
  "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:\\.\\d+)?(?:Z|[+-]\\d{2}:\\d{2})$"
}
```

- [x] **Step 5: Add schema test for job claim fields**

In `tests/test_async_job_artifacts.py`, add:

```python
def test_job_schema_accepts_claim_fields(self):
    job = minimal_job("running")
    job["worker_id"] = "worker-a"
    job["claim_token"] = "a" * 32
    job["claim_started_at"] = "2026-06-20T00:01:00Z"
    job["claim_updated_at"] = "2026-06-20T00:01:30Z"

    self.assertEqual(validation_errors(JOB_SCHEMA, job), [])
```

- [x] **Step 6: Run B1 helper tests**

Run:

```powershell
python -m unittest `
  tests.test_async_job_artifacts.AsyncJobArtifactSchemaTest.test_job_schema_accepts_claim_fields `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_assert_claim_matches_job_rejects_mismatched_token `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_write_job_if_claim_matches_rejects_unexpected_status `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_write_job_if_claim_matches_writes_valid_mutation `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_write_job_if_claim_matches_rejects_invalid_mutation `
  -v
```

Expected: pass.

## Task 5: Core Claimed Execution And Artifact Guards

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_generic_agent_adapter.py`
- Test: `tests/test_generic_agent_adapter.py`

- [x] **Step 1: Write failing queued-to-running test**

Add:

```python
def test_execute_claimed_job_records_claim_token_on_running_job(self):
    with tempfile.TemporaryDirectory(dir=ROOT) as raw:
        run_dir = Path(raw)
        write_json(run_dir / "state.json", minimal_state())
        release_file = run_dir / "release-claim-token.txt"
        agent_script = run_dir / "wait_agent.py"
        write_agent_script(
            agent_script,
            """
            import json
            import os
            import time
            from pathlib import Path

            release = Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).parents[2] / "release-claim-token.txt"
            while not release.exists():
                time.sleep(0.05)
            payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
            output_path = Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"])
            output = {
                "run_id": payload["run_id"],
                "job_id": payload["job_id"],
                "agent": payload["agent"],
                "adapter": payload["adapter"],
                "status": "passed",
                "summary": "Claim token job completed.",
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
            "claim-token-running",
            agent="generic-test-agent",
            command=[sys.executable, str(agent_script)],
            timeout_seconds=10,
            root=ROOT,
        )
        result: dict[str, object] = {}
        errors: list[BaseException] = []

        def run_worker() -> None:
            try:
                result["summary"] = cli.scheduler_run_once(run_dir, worker_id="worker-a", root=ROOT)
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=run_worker)
        worker.start()
        job_path = run_dir / "jobs" / "claim-token-running" / "job.json"
        for _ in range(200):
            job = json.loads(job_path.read_text(encoding="utf-8"))
            if job["status"] == "running" and job.get("claim_token"):
                break
            time.sleep(0.05)
        else:
            self.fail("job did not record claim token while running")
        running_job = json.loads(job_path.read_text(encoding="utf-8"))
        release_file.write_text("go\\n", encoding="utf-8")
        worker.join(timeout=20)
        terminal_job = json.loads(job_path.read_text(encoding="utf-8"))

    self.assertEqual(errors, [])
    self.assertEqual(terminal_job["status"], "succeeded")
    self.assertEqual(terminal_job["claim_token"], running_job["claim_token"])
```

- [x] **Step 2: Write failing raw log exclusive test**

Add:

```python
def test_claimed_execution_does_not_overwrite_raw_log_created_during_run(self):
    with tempfile.TemporaryDirectory(dir=ROOT) as raw:
        run_dir = Path(raw)
        write_json(run_dir / "state.json", minimal_state())
        agent_script = run_dir / "raw_conflict_agent.py"
        write_agent_script(
            agent_script,
            """
            import json
            import os
            from pathlib import Path

            payload = json.loads(Path(os.environ["HARNESS_AGENT_INPUT_FILE"]).read_text(encoding="utf-8"))
            raw_path = Path(os.environ["HARNESS_AGENT_RAW_LOG_FILE"])
            raw_path.write_text("external raw log\\n", encoding="utf-8")
            output = {
                "run_id": payload["run_id"],
                "job_id": payload["job_id"],
                "agent": payload["agent"],
                "adapter": payload["adapter"],
                "status": "passed",
                "summary": "Raw conflict job completed.",
                "findings": [],
                "evidence": [],
                "not_tested": [],
                "residual_risks": [],
                "generated_at": payload["created_at"],
            }
            Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"]).write_text(json.dumps(output, indent=2) + "\\n", encoding="utf-8")
            """,
        )
        cli.create_generic_agent_job(
            run_dir,
            "raw-conflict",
            agent="generic-test-agent",
            command=[sys.executable, str(agent_script)],
            timeout_seconds=10,
            root=ROOT,
        )

        with self.assertRaises(cli.HarnessCliError):
            cli.scheduler_run_once(run_dir, worker_id="worker-a", root=ROOT)

        raw_log = (run_dir / "jobs" / "raw-conflict" / "raw.log").read_text(encoding="utf-8")

    self.assertEqual(raw_log, "external raw log\n")
```

- [x] **Step 3: Implement exclusive raw log write**

Change `write_raw_log` to fail if the file exists:

```python
def write_raw_log(
    path: Path,
    command: list[str],
    returncode: int | None,
    stdout: str | None,
    stderr: str | None,
) -> None:
    content = "\n".join(
        [
            f"command: {json.dumps(command)}",
            f"returncode: {returncode}",
            "",
            "stdout:",
            stdout or "",
            "",
            "stderr:",
            stderr or "",
            "",
        ]
    )
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise HarnessCliError(f"raw_log_file already exists: {path}") from exc
```

- [x] **Step 4: Implement claimed running transition**

Add helper:

```python
def mark_claimed_job_running(claim: JobClaim, *, started_at: str) -> dict[str, Any]:
    def mutate(job: dict[str, Any]) -> dict[str, Any]:
        job["status"] = "running"
        job["started_at"] = started_at
        job["updated_at"] = started_at
        job["worker_id"] = claim.worker_id
        job["claim_token"] = claim.claim_token
        job["claim_started_at"] = started_at
        job["claim_updated_at"] = started_at
        return job

    return write_job_if_claim_matches(claim, expected_status="queued", mutate=mutate)
```

Modify scheduler-owned execution so it calls `mark_claimed_job_running` instead of the unlocked running write inside `execute_generic_agent_job`.

- [x] **Step 5: Implement claim-specific output staging**

Add helpers:

```python
def claimed_output_temp_path(job_dir: Path, claim_token: str) -> Path:
    return job_dir / f"output.{claim_token}.tmp.json"


def publish_claimed_output(temp_path: Path, output_path: Path) -> None:
    if output_path.exists():
        raise HarnessCliError(f"output_file already exists: {output_path}")
    try:
        with temp_path.open("rb") as source, output_path.open("xb") as target:
            shutil.copyfileobj(source, target)
    except FileExistsError as exc:
        raise HarnessCliError(f"output_file already exists: {output_path}") from exc
    temp_path.unlink(missing_ok=True)
```

For claimed scheduler execution, pass `HARNESS_AGENT_OUTPUT_FILE` as `claimed_output_temp_path(job_dir, claim.claim_token)` and publish only after the running claim still matches.

- [x] **Step 6: Run core artifact tests**

Run:

```powershell
python -m unittest `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_execute_claimed_job_records_claim_token_on_running_job `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_claimed_execution_does_not_overwrite_raw_log_created_during_run `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_claimed_execution_does_not_overwrite_output_created_during_run `
  -v
```

Expected: pass.

## Task 6: Stale Detection And Recovery Claim Field Integration

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_generic_agent_adapter.py`
- Test: `tests/test_generic_agent_adapter.py`

- [x] **Step 1: Write failing recovery claim-field test**

Add:

```python
def test_requeue_recovery_clears_claim_fields(self):
    with tempfile.TemporaryDirectory(dir=ROOT) as raw:
        run_dir = Path(raw)
        write_json(run_dir / "state.json", minimal_state())
        cli.create_generic_agent_job(
            run_dir,
            "claim-recovery",
            agent="generic-test-agent",
            command=[sys.executable, "-c", "print('recover')"],
            timeout_seconds=30,
            root=ROOT,
        )
        mark_job_running(run_dir, "claim-recovery", worker_id="worker-dead")
        job_path = run_dir / "jobs" / "claim-recovery" / "job.json"
        job = json.loads(job_path.read_text(encoding="utf-8"))
        job["claim_token"] = "dead-token"
        job["claim_started_at"] = "2026-06-22T00:00:00Z"
        job["claim_updated_at"] = "2026-06-22T00:01:00Z"
        write_json(job_path, job)
        write_claim_owner(run_dir, "claim-recovery", worker_id="worker-dead")

        cli.recover_stale_running_job(
            run_dir,
            "claim-recovery",
            action="requeue",
            reason="clear claim fields",
            heartbeat_timeout_seconds=60,
            now="2026-06-22T00:10:00Z",
            confirm=True,
            root=ROOT,
        )
        saved_job = json.loads(job_path.read_text(encoding="utf-8"))

    self.assertIsNone(saved_job["claim_token"])
    self.assertIsNone(saved_job["claim_started_at"])
    self.assertIsNone(saved_job["claim_updated_at"])
```

- [x] **Step 2: Implement recovery clearing**

In `recover_stale_running_job`, when `action == "requeue"`, add:

```python
new_job["claim_token"] = None
new_job["claim_started_at"] = None
new_job["claim_updated_at"] = None
```

For `action == "fail"`, keep the claim fields present in `previous_job` and copied into `new_job` unless the job schema requires a different terminal diagnostic shape.

Also add `test_recovery_does_not_remove_reclaimed_claim_lock_after_job_write` to ensure recovery only removes a `claim.lock` whose owner still matches the stale assessment captured before the recovery state transition.

- [x] **Step 3: Run recovery test**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_requeue_recovery_clears_claim_fields -v
```

Expected: pass.

## Task 7: T1 Deterministic Concurrency Tests

**Files:**
- Modify: `tests/test_generic_agent_adapter.py`
- Modify if tests expose gaps: `harness/cli.py`

- [x] **Step 1: Add direct contention test for claim tokens**

Add:

```python
def test_concurrent_claims_same_worker_id_get_one_token(self):
    with tempfile.TemporaryDirectory(dir=ROOT) as raw:
        run_dir = Path(raw)
        write_json(run_dir / "state.json", minimal_state())
        cli.create_generic_agent_job(
            run_dir,
            "same-worker-token",
            agent="generic-test-agent",
            command=[sys.executable, "-c", "print('token')"],
            timeout_seconds=30,
            root=ROOT,
        )
        claims: list[object] = []
        errors: list[BaseException] = []

        def claim_job() -> None:
            try:
                claims.append(cli.try_claim_job(run_dir, "same-worker-token", worker_id="same-worker", root=ROOT))
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=claim_job) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        winners = [claim for claim in claims if claim is not None]
        for claim in winners:
            cli.release_job_claim(claim)

    self.assertEqual(errors, [])
    self.assertEqual(len(winners), 1)
    self.assertRegex(winners[0].claim_token, r"^[0-9a-f]{32}$")
```

- [x] **Step 2: Run deterministic concurrency tests**

Run:

```powershell
python -m unittest `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_concurrent_claims_same_worker_id_get_one_token `
  tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_scheduler_run_once_two_workers_execute_same_queued_job_at_most_once `
  -v
```

Expected: pass.

## Task 8: T2 Live Multi-Worker Smoke

**Files:**
- Modify: `tests/test_generic_agent_adapter.py`
- Test: `tests/test_generic_agent_adapter.py`

- [x] **Step 1: Write live multi-worker smoke**

Add:

```python
def test_live_multi_worker_watch_processes_execute_jobs_once(self):
    with tempfile.TemporaryDirectory(dir=ROOT) as raw:
        run_dir = Path(raw)
        write_json(run_dir / "state.json", minimal_state())
        release_file = run_dir / "release-all.txt"
        marker_dir = run_dir / "markers"
        marker_dir.mkdir()
        agent_script = run_dir / "multi_worker_agent.py"
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
            run_dir = input_path.parents[2]
            release_file = run_dir / "release-all.txt"
            marker_path = run_dir / "markers" / f"{payload['job_id']}.txt"
            with marker_path.open("x", encoding="utf-8") as marker:
                marker.write(payload["job_id"] + "\\n")
            while not release_file.exists():
                time.sleep(0.05)
            output = {
                "run_id": payload["run_id"],
                "job_id": payload["job_id"],
                "agent": payload["agent"],
                "adapter": payload["adapter"],
                "status": "passed",
                "summary": "Multi-worker job completed.",
                "findings": [],
                "evidence": [],
                "not_tested": [],
                "residual_risks": [],
                "generated_at": payload["created_at"],
            }
            output_path.write_text(json.dumps(output, indent=2) + "\\n", encoding="utf-8")
            """,
        )
        for index in range(5):
            cli.create_generic_agent_job(
                run_dir,
                f"multi-{index}",
                agent="generic-test-agent",
                command=[sys.executable, str(agent_script)],
                timeout_seconds=20,
                root=ROOT,
            )

        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "run-scheduler",
                    str(run_dir),
                    "--watch",
                    "--poll-interval-seconds",
                    "0.1",
                    "--max-seconds",
                    "8",
                    "--worker-id",
                    f"live-worker-{index}",
                ],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            for index in range(3)
        ]
        try:
            release_file.write_text("go\\n", encoding="utf-8")
            for process in processes:
                process.wait(timeout=20)
            jobs = [
                json.loads((run_dir / "jobs" / f"multi-{index}" / "job.json").read_text(encoding="utf-8"))
                for index in range(5)
            ]
            markers = sorted(path.name for path in marker_dir.glob("*.txt"))
        finally:
            for process in processes:
                if process.poll() is None:
                    cli.terminate_process_tree(process)
                    process.wait(timeout=10)

    self.assertEqual([job["status"] for job in jobs], ["succeeded"] * 5)
    self.assertEqual(markers, [f"multi-{index}.txt" for index in range(5)])
    for index, job in enumerate(jobs):
        self.assertTrue((run_dir / "jobs" / f"multi-{index}" / "raw.log").exists())
        self.assertTrue((run_dir / "jobs" / f"multi-{index}" / "output.json").exists())
        self.assertRegex(job["claim_token"], r"^[0-9a-f]{32}$")
```

- [x] **Step 2: Run live smoke**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter.GenericCliAgentOrchestrationTest.test_live_multi_worker_watch_processes_execute_jobs_once -v
```

Expected: pass. If this flakes on Windows, inspect process cleanup before changing timeouts.

## Task 9: Documentation And Full Verification

**Files:**
- Modify: `docs/INDEX.md`
- Modify: `harness/core/state-authority.md`
- Modify: `harness/core/evidence.md`
- Modify: `docs/superpowers/plans/2026-06-22-phase-8-multi-worker-concurrency-implementation.md`

- [x] **Step 1: Update docs**

Update `docs/INDEX.md` current status with:

```markdown
- Phase 8 multi-worker concurrency hardening adds claim tokens, lease diagnostics, claim-aware job writes, artifact overwrite guards, and a live multi-worker scheduler smoke for local filesystem workers.
```

Update `harness/core/state-authority.md` claim section with:

```markdown
Claim leases are diagnostic. An expired lease does not authorize ordinary scheduler polling to steal a lock or rewrite a running job. Claimed job state transitions must compare `worker_id` and `claim_token` before writing `job.json`.
```

Update `harness/core/evidence.md` scheduler control files section with:

```markdown
Claim tokens and lease timestamps are control metadata, not evidence. They must not be auto-indexed.
```

- [x] **Step 2: Run targeted tests**

Run:

```powershell
python -m unittest tests.test_generic_agent_adapter tests.test_async_job_artifacts tests.test_harness_cli -v
```

Expected: all tests pass.

- [x] **Step 3: Run full suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass, with the existing optional dependency/hash test skipped unless its environment flag is set.

- [x] **Step 4: Validate source-controlled runs**

Run:

```powershell
Get-ChildItem -Directory harness\runs | ForEach-Object { python -m harness.cli validate $_.FullName }
```

Expected: every run prints `valid:`.

- [x] **Step 5: Check whitespace**

Run:

```powershell
git diff --check
```

Expected: exit code 0. CRLF warnings are acceptable on this Windows workspace; whitespace errors are not.

- [x] **Step 6: Mark plan tasks complete**

After verification passes, update this plan's checkboxes for completed tasks and include the verification commands in the final report.

## Residual Risks To Report

- This remains local-filesystem coordination only.
- A malicious or incompatible agent can ignore `HARNESS_AGENT_OUTPUT_FILE`; the harness will then treat missing staged output or canonical output conflicts as a failed/blocked execution path.
- Lease expiry is diagnostic and does not stop an already-running agent subprocess.
- Output staging changes scheduler-owned execution behavior; direct `run-generic-agent` should keep its existing canonical output behavior unless a separate scoped phase migrates it.
