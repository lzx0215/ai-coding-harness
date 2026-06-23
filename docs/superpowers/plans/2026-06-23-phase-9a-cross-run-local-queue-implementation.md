# Phase 9A Cross-Run Local Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Phase 9 slice: a local filesystem cross-run queue that routes existing run-local generic-agent jobs across multiple Harness runs without taking ownership of run state or terminal job artifacts.

**Architecture:** The cross-run queue is a coordination directory supplied by CLI argument, not a new state authority. Queue entries reference an existing owning run and existing queued job; workers claim queue entries, then claim and execute the referenced run-local job through the existing Phase 8 claim-token path. Queue audit files document routing, recovery, and cleanup decisions, while Codex still indexes evidence and advances each owning run explicitly.

**Tech Stack:** Python 3.11+ stdlib, existing `harness.cli`, JSON Schema 2020-12, `unittest`, local filesystem atomic directory claims, PowerShell and GitHub Actions CI.

---

## Entry Gate Status

Phase 9A may proceed because the Phase 9 entry gates are now closed:

- Local scheduler closure run: `harness/runs/2026-06-23-phase-9-entry-gate-local-scheduler-closure`
- Local verification in that run: full suite, run validation, targeted Phase 7 / 7.1 / 8 checks, and whitespace checks passed
- Remote CI after Linux test fix: GitHub Actions run `27999826047` passed for `c2f2299ee5803e770e2e1db6ed71c22d2397abe6`

Do not start Phase 9B cloud work from this plan.

## File Structure

- Modify: `harness/cli.py`
  - Add local cross-run queue helpers, schemas loading, CLI commands, queue claim locking, recovery, cleanup, and scheduler execution.
- Create: `harness/schemas/cross-run-queue-entry.schema.json`
  - Validates durable queue entries.
- Create: `harness/schemas/cross-run-queue-event.schema.json`
  - Validates JSONL audit events written by queue operations.
- Create: `tests/test_cross_run_queue.py`
  - Focused TDD coverage for schema, queue creation, authorization, claiming, execution, recovery, cleanup, and CLI entrypoints.
- Modify: `tests/test_static_contracts.py`
  - Pin new schemas and CLI commands in static contracts.
- Modify: `harness/core/state-authority.md`
  - Document that cross-run queue entries are coordination records, not state authority.
- Modify: `harness/core/evidence.md`
  - Document queue entries/events as control/audit artifacts that are not auto-indexed evidence.
- Modify: `docs/INDEX.md`
  - Add the Phase 9A implementation plan and current status.
- Modify: `harness/memory/progress.md`
  - Record that Phase 9 entry gates are closed and Phase 9A is the active next slice.
- Create: `harness/runs/2026-06-23-phase-9a-cross-run-local-queue/`
  - Strict source-controlled implementation run with task, triage, plan, live smoke artifacts, verification, review handling, and handoff.

## Queue Layout

Use this durable directory shape for local queue operations:

```text
<queue-dir>/
  queue.json
  events.log
  entries/
    <entry-id>/
      entry.json
      claim.lock/
        owner.json
      recovery/
        <timestamp>-<action>.json
      cleanup/
        <timestamp>-cleanup.json
```

`queue.json` identifies the queue. `entry.json` is the routing record. `events.log` is append-only diagnostics. `claim.lock/owner.json` uses the same local atomic directory claim pattern as run-local job claims.

## Task 1: Queue Schemas And Static Contracts

**Files:**
- Create: `harness/schemas/cross-run-queue-entry.schema.json`
- Create: `harness/schemas/cross-run-queue-event.schema.json`
- Create: `tests/test_cross_run_queue.py`
- Modify: `tests/test_static_contracts.py`

- [ ] **Step 1: Write failing schema tests**

Add `tests/test_cross_run_queue.py` with these initial tests:

```python
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
ENTRY_SCHEMA = ROOT / "harness" / "schemas" / "cross-run-queue-entry.schema.json"
EVENT_SCHEMA = ROOT / "harness" / "schemas" / "cross-run-queue-event.schema.json"


def load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def valid_entry() -> dict:
    return {
        "schema_version": "0.1.0",
        "queue_id": "phase9a-local",
        "entry_id": "entry-one",
        "run_id": "run-one",
        "run_dir": "harness/runs/run-one",
        "job_id": "job-one",
        "agent": "generic-test-agent",
        "adapter": "generic-cli-agent",
        "creator": "codex",
        "allowed_worker_id": None,
        "allowed_worker_groups": ["local"],
        "status": "queued",
        "created_at": "2026-06-23T00:00:00Z",
        "updated_at": "2026-06-23T00:00:00Z",
        "claim_owner": None,
        "claim_token": None,
        "claim_started_at": None,
        "claim_updated_at": None,
        "lease_expires_at": None,
        "terminal_job_status": None,
        "recovery": [],
        "cleanup": [],
    }


class CrossRunQueueSchemaTest(unittest.TestCase):
    def test_cross_run_queue_entry_schema_accepts_minimal_queued_entry(self):
        Draft202012Validator(load_schema(ENTRY_SCHEMA)).validate(valid_entry())

    def test_cross_run_queue_entry_schema_rejects_path_traversal_run_dir(self):
        entry = valid_entry()
        entry["run_dir"] = "../outside"
        errors = list(Draft202012Validator(load_schema(ENTRY_SCHEMA)).iter_errors(entry))
        self.assertTrue(errors)

    def test_cross_run_queue_entry_schema_rejects_unknown_status(self):
        entry = valid_entry()
        entry["status"] = "invented"
        errors = list(Draft202012Validator(load_schema(ENTRY_SCHEMA)).iter_errors(entry))
        self.assertTrue(errors)

    def test_cross_run_queue_event_schema_accepts_minimal_event(self):
        event = {
            "schema_version": "0.1.0",
            "queue_id": "phase9a-local",
            "entry_id": "entry-one",
            "event": "entry_created",
            "actor": "codex",
            "created_at": "2026-06-23T00:00:00Z",
            "details": {},
        }
        Draft202012Validator(load_schema(EVENT_SCHEMA)).validate(event)
```

- [ ] **Step 2: Verify the tests fail for missing schemas**

Run:

```powershell
python -m unittest tests.test_cross_run_queue.CrossRunQueueSchemaTest -v
```

Expected: errors showing `cross-run-queue-entry.schema.json` and `cross-run-queue-event.schema.json` are missing.

- [ ] **Step 3: Add the schemas**

Create `harness/schemas/cross-run-queue-entry.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://ai-coding-harness.local/schemas/cross-run-queue-entry.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "queue_id",
    "entry_id",
    "run_id",
    "run_dir",
    "job_id",
    "agent",
    "adapter",
    "creator",
    "allowed_worker_id",
    "allowed_worker_groups",
    "status",
    "created_at",
    "updated_at",
    "claim_owner",
    "claim_token",
    "claim_started_at",
    "claim_updated_at",
    "lease_expires_at",
    "terminal_job_status",
    "recovery",
    "cleanup"
  ],
  "properties": {
    "schema_version": { "type": "string", "const": "0.1.0" },
    "queue_id": { "type": "string", "pattern": "^[A-Za-z0-9_.-]+$" },
    "entry_id": { "type": "string", "pattern": "^[A-Za-z0-9_.-]+$" },
    "run_id": { "type": "string", "minLength": 1 },
    "run_dir": {
      "type": "string",
      "minLength": 1,
      "not": { "pattern": "(^/|^[A-Za-z]:|(^|/)\\.\\.(/|$)|\\\\)" }
    },
    "job_id": { "type": "string", "pattern": "^[A-Za-z0-9_.-]+$" },
    "agent": { "type": "string", "minLength": 1 },
    "adapter": { "type": "string", "minLength": 1 },
    "creator": { "type": "string", "minLength": 1 },
    "allowed_worker_id": { "type": ["string", "null"], "minLength": 1 },
    "allowed_worker_groups": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 },
      "uniqueItems": true
    },
    "status": {
      "type": "string",
      "enum": ["queued", "claimed", "running", "succeeded", "failed", "abandoned"]
    },
    "created_at": { "type": "string", "pattern": "Z$" },
    "updated_at": { "type": "string", "pattern": "Z$" },
    "claim_owner": { "type": ["string", "null"], "minLength": 1 },
    "claim_token": { "type": ["string", "null"], "pattern": "^[0-9a-f]{32}$" },
    "claim_started_at": { "type": ["string", "null"], "pattern": "Z$" },
    "claim_updated_at": { "type": ["string", "null"], "pattern": "Z$" },
    "lease_expires_at": { "type": ["string", "null"], "pattern": "Z$" },
    "terminal_job_status": {
      "type": ["string", "null"],
      "enum": ["succeeded", "failed", "timeout", "cancelled", null]
    },
    "recovery": { "type": "array", "items": { "type": "string", "minLength": 1 } },
    "cleanup": { "type": "array", "items": { "type": "string", "minLength": 1 } }
  }
}
```

Create `harness/schemas/cross-run-queue-event.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://ai-coding-harness.local/schemas/cross-run-queue-event.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "queue_id", "entry_id", "event", "actor", "created_at", "details"],
  "properties": {
    "schema_version": { "type": "string", "const": "0.1.0" },
    "queue_id": { "type": "string", "pattern": "^[A-Za-z0-9_.-]+$" },
    "entry_id": { "type": ["string", "null"], "pattern": "^[A-Za-z0-9_.-]+$" },
    "event": {
      "type": "string",
      "enum": [
        "queue_initialized",
        "entry_created",
        "entry_claimed",
        "entry_executing_job",
        "entry_completed",
        "entry_failed",
        "entry_requeued",
        "entry_abandoned",
        "entry_cleanup_recorded"
      ]
    },
    "actor": { "type": "string", "minLength": 1 },
    "created_at": { "type": "string", "pattern": "Z$" },
    "details": { "type": "object" }
  }
}
```

- [ ] **Step 4: Run schema tests**

Run:

```powershell
python -m unittest tests.test_cross_run_queue.CrossRunQueueSchemaTest -v
```

Expected: all tests pass.

- [ ] **Step 5: Add static contract coverage**

Add a test to `tests/test_static_contracts.py`:

```python
    def test_phase9a_cross_run_queue_schemas_exist(self):
        for relative_path in [
            "harness/schemas/cross-run-queue-entry.schema.json",
            "harness/schemas/cross-run-queue-event.schema.json",
        ]:
            with self.subTest(relative_path=relative_path):
                schema = json.loads((ROOT / relative_path).read_text(encoding="utf-8"))
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
```

- [ ] **Step 6: Commit**

Run:

```powershell
python -m unittest tests.test_cross_run_queue.CrossRunQueueSchemaTest tests.test_static_contracts.StaticContractsTest.test_phase9a_cross_run_queue_schemas_exist -v
git add harness/schemas/cross-run-queue-entry.schema.json harness/schemas/cross-run-queue-event.schema.json tests/test_cross_run_queue.py tests/test_static_contracts.py
git commit -m "test: add cross-run queue schemas"
```

## Task 2: Queue Entry Creation

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_cross_run_queue.py`

- [ ] **Step 1: Add failing tests for queue entry creation**

Append these tests:

```python
from harness import cli


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def minimal_state(run_id: str) -> dict:
    return {
        "run_id": run_id,
        "harness_version": "0.2.0",
        "state_schema_version": "0.2.0",
        "status": "verified",
        "track": "Standard",
        "current_workflow": "standard-agent-adapter-change",
        "owner": "codex",
        "base_commit": "HEAD",
        "created_at": "2026-06-23T00:00:00Z",
        "updated_at": "2026-06-23T00:00:00Z",
        "external_agents": [],
        "evidence": [],
    }


class CrossRunQueueCreationTest(unittest.TestCase):
    def test_create_cross_run_queue_entry_references_existing_queued_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            run_dir = base / "harness" / "runs" / "run-a"
            queue_dir = base / "queue"
            write_json(run_dir / "state.json", minimal_state("run-a"))
            cli.create_generic_agent_job(
                run_dir,
                "job-a",
                agent="generic-test-agent",
                command=["python", "-c", "print('ok')"],
                root=base,
            )

            entry = cli.create_cross_run_queue_entry(
                queue_dir,
                "entry-a",
                run_dir=run_dir,
                job_id="job-a",
                creator="codex",
                allowed_worker_id=None,
                allowed_worker_groups=["local"],
                root=base,
            )

            saved = json.loads((queue_dir / "entries" / "entry-a" / "entry.json").read_text(encoding="utf-8"))
            self.assertEqual(entry["entry_id"], "entry-a")
            self.assertEqual(saved["run_id"], "run-a")
            self.assertEqual(saved["job_id"], "job-a")
            self.assertEqual(saved["status"], "queued")
            self.assertEqual(saved["allowed_worker_groups"], ["local"])

    def test_create_cross_run_queue_entry_rejects_missing_job(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            run_dir = base / "harness" / "runs" / "run-a"
            queue_dir = base / "queue"
            write_json(run_dir / "state.json", minimal_state("run-a"))
            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.create_cross_run_queue_entry(
                    queue_dir,
                    "entry-a",
                    run_dir=run_dir,
                    job_id="missing",
                    creator="codex",
                    allowed_worker_id=None,
                    allowed_worker_groups=["local"],
                    root=base,
                )
            self.assertIn("referenced job does not exist", str(raised.exception))
```

- [ ] **Step 2: Verify creation tests fail**

Run:

```powershell
python -m unittest tests.test_cross_run_queue.CrossRunQueueCreationTest -v
```

Expected: `AttributeError` for missing `create_cross_run_queue_entry`.

- [ ] **Step 3: Implement queue creation helpers**

Add to `harness/cli.py` near scheduler path helpers:

```python
CROSS_RUN_QUEUE_ENTRY_SCHEMA = SCHEMA_DIR / "cross-run-queue-entry.schema.json"
CROSS_RUN_QUEUE_EVENT_SCHEMA = SCHEMA_DIR / "cross-run-queue-event.schema.json"
CROSS_RUN_QUEUE_ENTRY_VERSION = "0.1.0"


def cross_run_queue_entries_dir(queue_dir: Path | str) -> Path:
    return Path(queue_dir) / "entries"


def cross_run_queue_entry_dir(queue_dir: Path | str, entry_id: str) -> Path:
    validate_generic_agent_job_id(entry_id)
    return cross_run_queue_entries_dir(queue_dir) / entry_id


def cross_run_queue_entry_path(queue_dir: Path | str, entry_id: str) -> Path:
    return cross_run_queue_entry_dir(queue_dir, entry_id) / "entry.json"


def cross_run_queue_events_path(queue_dir: Path | str) -> Path:
    return Path(queue_dir) / "events.log"


def append_cross_run_queue_event(
    queue_dir: Path | str,
    *,
    queue_id: str,
    entry_id: str | None,
    event: str,
    actor: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "schema_version": CROSS_RUN_QUEUE_ENTRY_VERSION,
        "queue_id": queue_id,
        "entry_id": entry_id,
        "event": event,
        "actor": actor,
        "created_at": utc_now(),
        "details": details,
    }
    validate_json_payload(payload, CROSS_RUN_QUEUE_EVENT_SCHEMA, "cross-run-queue-event")
    events_path = cross_run_queue_events_path(queue_dir)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return payload


def create_cross_run_queue_entry(
    queue_dir: Path | str,
    entry_id: str,
    *,
    run_dir: Path | str,
    job_id: str,
    creator: str,
    allowed_worker_id: str | None,
    allowed_worker_groups: list[str],
    root: Path | str | None = None,
) -> dict[str, Any]:
    validate_generic_agent_job_id(entry_id)
    validate_generic_agent_job_id(job_id)
    validate_non_empty_string(creator, "creator")
    if allowed_worker_id is None and not allowed_worker_groups:
        raise HarnessCliError("cross-run queue entry requires allowed_worker_id or allowed_worker_groups")

    repo_root = resolve_repository_root(Path(run_dir), root=root)
    resolved_run_dir = Path(run_dir).resolve(strict=False)
    result = validate_run(resolved_run_dir, root=repo_root)
    if not result.ok:
        raise HarnessCliError(f"referenced run is invalid: {'; '.join(result.errors)}")

    state = load_json(state_path(resolved_run_dir))
    job_path = resolved_run_dir / "jobs" / job_id / "job.json"
    if not job_path.exists():
        raise HarnessCliError(f"referenced job does not exist: {job_id}")
    job = load_job_payload(job_path)
    if job.get("status") != "queued":
        raise HarnessCliError(f"referenced job must be queued, got {job.get('status')}")

    queue_path = Path(queue_dir)
    queue_id = queue_path.name or "local-cross-run-queue"
    created_at = utc_now()
    entry = {
        "schema_version": CROSS_RUN_QUEUE_ENTRY_VERSION,
        "queue_id": queue_id,
        "entry_id": entry_id,
        "run_id": state["run_id"],
        "run_dir": str(resolved_run_dir.relative_to(repo_root)).replace("\\", "/"),
        "job_id": job_id,
        "agent": job["agent"],
        "adapter": job["adapter"],
        "creator": creator,
        "allowed_worker_id": allowed_worker_id,
        "allowed_worker_groups": allowed_worker_groups,
        "status": "queued",
        "created_at": created_at,
        "updated_at": created_at,
        "claim_owner": None,
        "claim_token": None,
        "claim_started_at": None,
        "claim_updated_at": None,
        "lease_expires_at": None,
        "terminal_job_status": None,
        "recovery": [],
        "cleanup": [],
    }
    validate_json_payload(entry, CROSS_RUN_QUEUE_ENTRY_SCHEMA, "cross-run-queue-entry")
    entry_path = cross_run_queue_entry_path(queue_path, entry_id)
    if entry_path.exists():
        raise HarnessCliError(f"cross-run queue entry already exists: {entry_id}")
    write_json_atomic(entry_path, entry)
    append_cross_run_queue_event(
        queue_path,
        queue_id=queue_id,
        entry_id=entry_id,
        event="entry_created",
        actor=creator,
        details={"run_id": state["run_id"], "job_id": job_id},
    )
    return entry
```

- [ ] **Step 4: Run creation tests**

Run:

```powershell
python -m unittest tests.test_cross_run_queue.CrossRunQueueCreationTest -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
python -m unittest tests.test_cross_run_queue -v
git add harness/cli.py tests/test_cross_run_queue.py
git commit -m "feat: create cross-run queue entries"
```

## Task 3: Queue Claim Authorization And Single Execution

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_cross_run_queue.py`

- [ ] **Step 1: Add failing authorization and execution tests**

Add tests:

```python
class CrossRunQueueExecutionTest(unittest.TestCase):
    def test_worker_group_must_be_authorized_to_claim_queue_entry(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            run_dir, queue_dir = build_queued_entry_fixture(base, allowed_groups=["group-a"])
            denied = cli.try_claim_cross_run_queue_entry(
                queue_dir,
                "entry-a",
                worker_id="worker-b",
                worker_groups=["group-b"],
                root=base,
            )
            allowed = cli.try_claim_cross_run_queue_entry(
                queue_dir,
                "entry-a",
                worker_id="worker-a",
                worker_groups=["group-a"],
                root=base,
            )
            self.assertIsNone(denied)
            self.assertIsNotNone(allowed)

    def test_cross_run_worker_executes_referenced_job_without_mutating_run_state(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            run_dir, queue_dir = build_queued_entry_fixture(base, allowed_groups=["local"])
            before_state = (run_dir / "state.json").read_text(encoding="utf-8")
            result = cli.cross_run_queue_run_once(
                queue_dir,
                worker_id="worker-a",
                worker_groups=["local"],
                root=base,
            )
            after_state = (run_dir / "state.json").read_text(encoding="utf-8")
            job = json.loads((run_dir / "jobs" / "job-a" / "job.json").read_text(encoding="utf-8"))
            entry = json.loads((queue_dir / "entries" / "entry-a" / "entry.json").read_text(encoding="utf-8"))
            self.assertEqual(result["executed_entries"], ["entry-a"])
            self.assertEqual(before_state, after_state)
            self.assertEqual(job["status"], "succeeded")
            self.assertEqual(entry["status"], "succeeded")
            self.assertEqual(entry["terminal_job_status"], "succeeded")
            self.assertTrue((run_dir / "jobs" / "job-a" / "output.json").exists())
```

Add this fixture helper in the test file:

```python
def build_queued_entry_fixture(base: Path, *, allowed_groups: list[str]) -> tuple[Path, Path]:
    run_dir = base / "harness" / "runs" / "run-a"
    queue_dir = base / "queue"
    script = base / "agent.py"
    write_json(run_dir / "state.json", minimal_state("run-a"))
    script.write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "payload=json.loads(Path(os.environ['HARNESS_AGENT_INPUT_FILE']).read_text(encoding='utf-8'))\n"
        "Path(os.environ['HARNESS_AGENT_OUTPUT_FILE']).write_text(json.dumps({"
        "'run_id': payload['run_id'], 'job_id': payload['job_id'], 'agent': payload['agent'], "
        "'adapter': payload['adapter'], 'status': 'passed', 'summary': 'done', "
        "'findings': [], 'evidence': [], 'not_tested': [], 'residual_risks': [], "
        "'generated_at': payload['created_at']"
        "}, indent=2) + '\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    cli.create_generic_agent_job(
        run_dir,
        "job-a",
        agent="generic-test-agent",
        command=[sys.executable, str(script)],
        root=base,
    )
    cli.create_cross_run_queue_entry(
        queue_dir,
        "entry-a",
        run_dir=run_dir,
        job_id="job-a",
        creator="codex",
        allowed_worker_id=None,
        allowed_worker_groups=allowed_groups,
        root=base,
    )
    return run_dir, queue_dir
```

- [ ] **Step 2: Verify execution tests fail**

Run:

```powershell
python -m unittest tests.test_cross_run_queue.CrossRunQueueExecutionTest -v
```

Expected: `AttributeError` for missing claim/execution helpers.

- [ ] **Step 3: Implement queue claim and execution**

Add these functions to `harness/cli.py`:

```python
def cross_run_queue_claim_lock_dir(queue_dir: Path | str, entry_id: str) -> Path:
    return cross_run_queue_entry_dir(queue_dir, entry_id) / CLAIM_LOCK_DIR_NAME


def worker_authorized_for_entry(entry: dict[str, Any], worker_id: str, worker_groups: list[str]) -> bool:
    allowed_worker_id = entry.get("allowed_worker_id")
    if allowed_worker_id is not None and allowed_worker_id == worker_id:
        return True
    allowed_groups = set(entry.get("allowed_worker_groups") or [])
    return bool(allowed_groups.intersection(worker_groups))


def load_cross_run_queue_entry(queue_dir: Path | str, entry_id: str) -> dict[str, Any]:
    path = cross_run_queue_entry_path(queue_dir, entry_id)
    entry = load_json(path)
    validate_json_payload(entry, CROSS_RUN_QUEUE_ENTRY_SCHEMA, "cross-run-queue-entry")
    return entry


def try_claim_cross_run_queue_entry(
    queue_dir: Path | str,
    entry_id: str,
    *,
    worker_id: str,
    worker_groups: list[str],
    root: Path | str | None = None,
) -> dict[str, Any] | None:
    validate_non_empty_string(worker_id, "worker_id")
    entry = load_cross_run_queue_entry(queue_dir, entry_id)
    if entry["status"] != "queued":
        return None
    if not worker_authorized_for_entry(entry, worker_id, worker_groups):
        return None
    lock_dir = cross_run_queue_claim_lock_dir(queue_dir, entry_id)
    owner = build_claim_owner(
        run_id=entry["run_id"],
        job_id=entry_id,
        worker_id=worker_id,
        claim_token=new_claim_token(),
        claimed_at=datetime.now(timezone.utc),
    )
    if not acquire_claim_lock_dir(lock_dir.parent, lock_dir, owner):
        return None
    claimed_at = owner["claimed_at"]
    entry["status"] = "claimed"
    entry["claim_owner"] = worker_id
    entry["claim_token"] = owner["claim_token"]
    entry["claim_started_at"] = claimed_at
    entry["claim_updated_at"] = claimed_at
    entry["lease_expires_at"] = owner["lease_expires_at"]
    entry["updated_at"] = claimed_at
    write_json_atomic(cross_run_queue_entry_path(queue_dir, entry_id), entry)
    append_cross_run_queue_event(
        queue_dir,
        queue_id=entry["queue_id"],
        entry_id=entry_id,
        event="entry_claimed",
        actor=worker_id,
        details={"worker_groups": worker_groups},
    )
    return entry


def cross_run_queue_run_once(
    queue_dir: Path | str,
    *,
    worker_id: str,
    worker_groups: list[str],
    root: Path | str | None = None,
) -> dict[str, Any]:
    repo_root = resolve_repository_root(Path.cwd(), root=root)
    executed_entries: list[str] = []
    skipped_entries: list[str] = []
    for entry_path in sorted(cross_run_queue_entries_dir(queue_dir).glob("*/entry.json")):
        entry_id = entry_path.parent.name
        claimed_entry = try_claim_cross_run_queue_entry(
            queue_dir,
            entry_id,
            worker_id=worker_id,
            worker_groups=worker_groups,
            root=repo_root,
        )
        if claimed_entry is None:
            skipped_entries.append(entry_id)
            continue
        run_dir = repo_root / claimed_entry["run_dir"]
        job_claim = try_claim_job(run_dir, claimed_entry["job_id"], worker_id=worker_id, root=repo_root)
        if job_claim is None:
            claimed_entry["status"] = "failed"
            claimed_entry["updated_at"] = utc_now()
            write_json_atomic(cross_run_queue_entry_path(queue_dir, entry_id), claimed_entry)
            skipped_entries.append(entry_id)
            continue
        append_cross_run_queue_event(
            queue_dir,
            queue_id=claimed_entry["queue_id"],
            entry_id=entry_id,
            event="entry_executing_job",
            actor=worker_id,
            details={"run_id": claimed_entry["run_id"], "job_id": claimed_entry["job_id"]},
        )
        job = execute_claimed_generic_agent_job(run_dir, job_claim, root=repo_root)
        terminal_status = job["status"]
        claimed_entry["status"] = "succeeded" if terminal_status == "succeeded" else "failed"
        claimed_entry["terminal_job_status"] = terminal_status
        claimed_entry["updated_at"] = utc_now()
        write_json_atomic(cross_run_queue_entry_path(queue_dir, entry_id), claimed_entry)
        append_cross_run_queue_event(
            queue_dir,
            queue_id=claimed_entry["queue_id"],
            entry_id=entry_id,
            event="entry_completed" if terminal_status == "succeeded" else "entry_failed",
            actor=worker_id,
            details={"terminal_job_status": terminal_status},
        )
        executed_entries.append(entry_id)
    return {"executed_entries": executed_entries, "skipped_entries": skipped_entries}
```

- [ ] **Step 4: Run execution tests**

Run:

```powershell
python -m unittest tests.test_cross_run_queue.CrossRunQueueExecutionTest -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
python -m unittest tests.test_cross_run_queue -v
git add harness/cli.py tests/test_cross_run_queue.py
git commit -m "feat: execute cross-run queue entries locally"
```

## Task 4: CLI Commands

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_cross_run_queue.py`

- [ ] **Step 1: Add failing CLI tests**

Add tests for module entrypoints:

```python
class CrossRunQueueCliTest(unittest.TestCase):
    def test_module_entrypoint_creates_and_runs_cross_run_queue_entry(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            run_dir, queue_dir = build_queued_entry_fixture(base, allowed_groups=["local"])
            entry_path = queue_dir / "entries" / "entry-b" / "entry.json"
            create_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "queue-cross-run-job",
                    str(queue_dir),
                    "entry-b",
                    "--run-dir",
                    str(run_dir),
                    "--job-id",
                    "job-a",
                    "--creator",
                    "codex",
                    "--worker-group",
                    "local",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            run_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli",
                    "run-cross-run-queue",
                    str(queue_dir),
                    "--once",
                    "--worker-id",
                    "worker-a",
                    "--worker-group",
                    "local",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(create_result.returncode, 0, create_result.stderr + create_result.stdout)
            self.assertTrue(entry_path.exists())
            self.assertEqual(run_result.returncode, 0, run_result.stderr + run_result.stdout)
            self.assertIn("cross-run queue: executed=1", run_result.stdout)
```

- [ ] **Step 2: Verify CLI tests fail**

Run:

```powershell
python -m unittest tests.test_cross_run_queue.CrossRunQueueCliTest -v
```

Expected: argparse rejects unknown commands.

- [ ] **Step 3: Wire CLI parser and main dispatch**

Add parser entries in `build_parser()`:

```python
    cross_run_queue = subparsers.add_parser(
        "queue-cross-run-job",
        help="Create a local cross-run queue entry for an existing queued run-local job.",
    )
    cross_run_queue.add_argument("queue_dir")
    cross_run_queue.add_argument("entry_id")
    cross_run_queue.add_argument("--run-dir", required=True)
    cross_run_queue.add_argument("--job-id", required=True)
    cross_run_queue.add_argument("--creator", default=CODEX_ACTOR)
    cross_run_queue.add_argument("--worker-id")
    cross_run_queue.add_argument("--worker-group", action="append", default=[])

    run_cross_run_queue = subparsers.add_parser(
        "run-cross-run-queue",
        help="Run local cross-run queue entries without mutating Harness state.",
    )
    run_cross_run_queue.add_argument("queue_dir")
    run_cross_run_mode = run_cross_run_queue.add_mutually_exclusive_group(required=True)
    run_cross_run_mode.add_argument("--once", action="store_true")
    run_cross_run_queue.add_argument("--worker-id", required=True)
    run_cross_run_queue.add_argument("--worker-group", action="append", default=[])
```

Add dispatch in `main()`:

```python
        if args.command == "queue-cross-run-job":
            entry = create_cross_run_queue_entry(
                args.queue_dir,
                args.entry_id,
                run_dir=args.run_dir,
                job_id=args.job_id,
                creator=args.creator,
                allowed_worker_id=args.worker_id,
                allowed_worker_groups=args.worker_group,
            )
            print(f"queued cross-run job: {entry['queue_id']}/{entry['entry_id']} -> {entry['run_id']}/{entry['job_id']}")
            return 0

        if args.command == "run-cross-run-queue":
            summary = cross_run_queue_run_once(
                args.queue_dir,
                worker_id=args.worker_id,
                worker_groups=args.worker_group,
            )
            print(
                "cross-run queue: "
                f"executed={len(summary['executed_entries'])} "
                f"skipped={len(summary['skipped_entries'])}",
            )
            return 0
```

- [ ] **Step 4: Run CLI tests**

Run:

```powershell
python -m unittest tests.test_cross_run_queue.CrossRunQueueCliTest -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
python -m unittest tests.test_cross_run_queue -v
git add harness/cli.py tests/test_cross_run_queue.py
git commit -m "feat: add cross-run queue CLI"
```

## Task 5: Recovery And Cleanup Audit

**Files:**
- Modify: `harness/cli.py`
- Modify: `tests/test_cross_run_queue.py`

- [ ] **Step 1: Add failing recovery and cleanup tests**

Add tests:

```python
class CrossRunQueueRecoveryCleanupTest(unittest.TestCase):
    def test_recover_claimed_cross_run_entry_requires_confirmation(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            run_dir, queue_dir = build_queued_entry_fixture(base, allowed_groups=["local"])
            claimed = cli.try_claim_cross_run_queue_entry(
                queue_dir,
                "entry-a",
                worker_id="worker-a",
                worker_groups=["local"],
                root=base,
            )
            self.assertIsNotNone(claimed)
            with self.assertRaises(cli.HarnessCliError) as raised:
                cli.recover_cross_run_queue_entry(
                    queue_dir,
                    "entry-a",
                    action="requeue",
                    reason="stale worker",
                    confirm=False,
                    actor="codex",
                    root=base,
                )
            self.assertIn("requires --confirm", str(raised.exception))

    def test_cleanup_terminal_entry_does_not_delete_run_local_artifacts(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as raw:
            base = Path(raw)
            run_dir, queue_dir = build_queued_entry_fixture(base, allowed_groups=["local"])
            cli.cross_run_queue_run_once(queue_dir, worker_id="worker-a", worker_groups=["local"], root=base)
            result = cli.cleanup_cross_run_queue_entry(
                queue_dir,
                "entry-a",
                confirm=True,
                actor="codex",
                root=base,
            )
            self.assertTrue(result["cleanup_record"].endswith("-cleanup.json"))
            self.assertTrue((run_dir / "jobs" / "job-a" / "job.json").exists())
            self.assertTrue((run_dir / "jobs" / "job-a" / "output.json").exists())
```

- [ ] **Step 2: Verify recovery/cleanup tests fail**

Run:

```powershell
python -m unittest tests.test_cross_run_queue.CrossRunQueueRecoveryCleanupTest -v
```

Expected: `AttributeError` for missing helpers.

- [ ] **Step 3: Implement recovery and cleanup helpers**

Add minimal explicit recovery:

```python
def recover_cross_run_queue_entry(
    queue_dir: Path | str,
    entry_id: str,
    *,
    action: str,
    reason: str,
    confirm: bool,
    actor: str,
    root: Path | str | None = None,
) -> dict[str, Any]:
    if action not in {"requeue", "abandon"}:
        raise HarnessCliError("action must be one of: requeue, abandon")
    if not confirm:
        raise HarnessCliError("cross-run queue recovery requires --confirm")
    entry = load_cross_run_queue_entry(queue_dir, entry_id)
    if entry["status"] not in {"claimed", "running", "failed"}:
        raise HarnessCliError(f"entry {entry_id} is {entry['status']}, not recoverable")
    repo_root = resolve_repository_root(Path.cwd(), root=root)
    run_dir = repo_root / entry["run_dir"]
    result = validate_run(run_dir, root=repo_root)
    if not result.ok:
        raise HarnessCliError(f"owning run is invalid: {'; '.join(result.errors)}")
    timestamp = recovery_timestamp_fragment(utc_now())
    recovery_path = cross_run_queue_entry_dir(queue_dir, entry_id) / "recovery" / f"{timestamp}-{action}.json"
    recovery = {
        "entry_id": entry_id,
        "action": action,
        "reason": reason,
        "actor": actor,
        "created_at": utc_now(),
        "previous_status": entry["status"],
    }
    write_json_atomic(recovery_path, recovery)
    entry["status"] = "queued" if action == "requeue" else "abandoned"
    entry["claim_owner"] = None
    entry["claim_token"] = None
    entry["claim_started_at"] = None
    entry["claim_updated_at"] = None
    entry["lease_expires_at"] = None
    entry["updated_at"] = recovery["created_at"]
    entry["recovery"].append(str(recovery_path.relative_to(Path(queue_dir))).replace("\\", "/"))
    write_json_atomic(cross_run_queue_entry_path(queue_dir, entry_id), entry)
    append_cross_run_queue_event(
        queue_dir,
        queue_id=entry["queue_id"],
        entry_id=entry_id,
        event="entry_requeued" if action == "requeue" else "entry_abandoned",
        actor=actor,
        details={"reason": reason},
    )
    return {"entry": entry, "recovery_path": recovery_path}
```

Add cleanup:

```python
def cleanup_cross_run_queue_entry(
    queue_dir: Path | str,
    entry_id: str,
    *,
    confirm: bool,
    actor: str,
    root: Path | str | None = None,
) -> dict[str, Any]:
    if not confirm:
        raise HarnessCliError("cross-run queue cleanup requires --confirm")
    entry = load_cross_run_queue_entry(queue_dir, entry_id)
    if entry["status"] not in {"succeeded", "failed", "abandoned"}:
        raise HarnessCliError(f"entry {entry_id} is {entry['status']}, not terminal")
    timestamp = recovery_timestamp_fragment(utc_now())
    cleanup_path = cross_run_queue_entry_dir(queue_dir, entry_id) / "cleanup" / f"{timestamp}-cleanup.json"
    cleanup = {
        "entry_id": entry_id,
        "actor": actor,
        "created_at": utc_now(),
        "retained_run_dir": entry["run_dir"],
        "retained_job_id": entry["job_id"],
    }
    write_json_atomic(cleanup_path, cleanup)
    entry["cleanup"].append(str(cleanup_path.relative_to(Path(queue_dir))).replace("\\", "/"))
    entry["updated_at"] = cleanup["created_at"]
    write_json_atomic(cross_run_queue_entry_path(queue_dir, entry_id), entry)
    append_cross_run_queue_event(
        queue_dir,
        queue_id=entry["queue_id"],
        entry_id=entry_id,
        event="entry_cleanup_recorded",
        actor=actor,
        details={"cleanup": entry["cleanup"][-1]},
    )
    return {"entry": entry, "cleanup_record": entry["cleanup"][-1]}
```

- [ ] **Step 4: Run recovery and cleanup tests**

Run:

```powershell
python -m unittest tests.test_cross_run_queue.CrossRunQueueRecoveryCleanupTest -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
python -m unittest tests.test_cross_run_queue -v
git add harness/cli.py tests/test_cross_run_queue.py
git commit -m "feat: audit cross-run queue recovery and cleanup"
```

## Task 6: Source-Controlled Phase 9A Live Run

**Files:**
- Create: `harness/runs/2026-06-23-phase-9a-cross-run-local-queue/`
- Modify: `docs/INDEX.md`
- Modify: `harness/memory/progress.md`

- [ ] **Step 1: Initialize the Strict run**

Run:

```powershell
$RUN_ID = "2026-06-23-phase-9a-cross-run-local-queue"
$RUN_DIR = "harness/runs/$RUN_ID"
$BASE_COMMIT = (git rev-parse HEAD).Trim()
python -m harness.cli init-run $RUN_DIR --run-id $RUN_ID --track Strict --workflow strict-risk-change --base-commit $BASE_COMMIT
```

Expected: run skeleton exists and validates.

- [ ] **Step 2: Fill task, triage, and plan documents**

Use the Phase 9A design and this implementation plan to set:

- task scope: local cross-run queue only
- non-goals: cloud queues, credentials, provider selection, destructive cleanup
- triage: Strict because the queue crosses run ownership boundaries
- plan verification: focused tests, full tests, all run validation, package smoke, remote CI

- [ ] **Step 3: Execute a live cross-run queue smoke**

Create two owning runs under `.tmp/phase9a-live/owning-runs/`, queue one job in each run with `queue-generic-agent`, create two cross-run queue entries in `.tmp/phase9a-live/cross-run-queue`, run:

```powershell
python -m harness.cli run-cross-run-queue .tmp/phase9a-live/cross-run-queue --once --worker-id phase9a-worker --worker-group local
```

Expected: both referenced run-local jobs complete once, each owning run has terminal `jobs/<job-id>/job.json`, `raw.log`, and `output.json`, and no owning `state.json` changes.

- [ ] **Step 4: Copy smoke evidence into the source-controlled run**

Copy non-secret artifacts into:

```text
harness/runs/2026-06-23-phase-9a-cross-run-local-queue/live-smoke/
  owning-run-a/
  owning-run-b/
  cross-run-queue/
  command-log.md
```

Do not include absolute local temp paths, credentials, or user-specific environment details.

- [ ] **Step 5: Run verification**

Run:

```powershell
python -m unittest tests.test_cross_run_queue -v *> harness/runs/2026-06-23-phase-9a-cross-run-local-queue/verification-cross-run-queue.log
python -m unittest discover -s tests -v *> harness/runs/2026-06-23-phase-9a-cross-run-local-queue/verification-full-suite.log
Get-ChildItem -Directory harness\runs | ForEach-Object { python -m harness.cli validate $_.FullName } *> harness/runs/2026-06-23-phase-9a-cross-run-local-queue/verification-run-validation.log
git diff --check *> harness/runs/2026-06-23-phase-9a-cross-run-local-queue/verification-diff-check.log
```

Expected: all commands exit 0.

- [ ] **Step 6: Update docs and memory**

Update `docs/INDEX.md`:

```markdown
- Phase 9A local cross-run queue is implemented by `harness/runs/2026-06-23-phase-9a-cross-run-local-queue/`, covering local queue entries, authorization, claiming, run-local execution, recovery audit, cleanup audit, and source-controlled live smoke evidence. Cloud queue adapters remain unimplemented.
```

Update `harness/memory/progress.md`:

```markdown
Phase 9A local cross-run queue is implemented in source. Queue entries reference existing run-local jobs, local workers claim queue entries before claiming the owning run-local job, terminal job artifacts remain under the owning run, and queue recovery/cleanup decisions are explicit audit records. Cloud queue adapters remain unimplemented and require separate provider, credential, cost, cleanup, and audit approval.
```

- [ ] **Step 7: Review handling**

Because Phase 9A changes queue ownership and scheduler behavior, run an independent Claude Code review if the adapter is available. If unavailable, advance through `needs_user_decision` and record user risk acceptance before completion; do not use a blanket waiver for runtime code.

- [ ] **Step 8: Complete and commit the run**

Index implementation plan, verification logs, live smoke artifacts, review output or risk acceptance, and handoff. Then advance to completed only when validation passes:

```powershell
python -m harness.cli validate harness/runs/2026-06-23-phase-9a-cross-run-local-queue
git add harness/cli.py tests/test_cross_run_queue.py docs/INDEX.md harness/memory/progress.md harness/runs/2026-06-23-phase-9a-cross-run-local-queue
git commit -m "feat: implement Phase 9A cross-run local queue"
```

## Task 7: Final Local And Remote Verification

**Files:**
- Read: `.github/workflows/ci.yml`
- Read: `harness/runs/2026-06-23-phase-9a-cross-run-local-queue/handoff.md`

- [ ] **Step 1: Run final local verification**

Run:

```powershell
python -m unittest discover -s tests -v
Get-ChildItem -Directory harness\runs | ForEach-Object { python -m harness.cli validate $_.FullName }
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 2: Push and wait for CI**

Run:

```powershell
git status --short --branch
git push origin master
```

Then confirm the GitHub Actions `CI` workflow succeeds for the pushed commit.

- [ ] **Step 3: Report completion**

The final report must include:

- what changed
- how it was verified
- what was not verified
- residual risks
- next step

## Residual Risks To Keep In Handoff

- Phase 9A is local filesystem only.
- Queue records coordinate routing but do not replace run-local state, evidence, review, verification, or handoff gates.
- Cloud queue behavior, credentials, provider permissions, cost controls, and cleanup are not implemented.
- Queue cleanup is audit-only in this slice; it does not compact or delete terminal run-local artifacts.
- Cross-machine filesystems, network shares, and cloud object stores are not proven by local atomic directory claims.
