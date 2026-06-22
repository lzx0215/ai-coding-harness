# Phase 7.1 Claim Locking & Crash Smoke — External Code Review

| Field | Value |
| --- | --- |
| Review date | 2026-06-22 |
| Reviewer role | External read-only reviewer (harness v0.1 delegation contract) |
| Scope | `harness/cli.py` claim/recovery ordering; Windows crash-smoke stability |
| Subject | `docs/superpowers/specs/2026-06-22-phase-7-1-crash-smoke-claim-locking-design.md` + working-tree implementation |
| HEAD at review | `5386f28` (Phase 7.1 changes uncommitted in working tree, branch `codex/phase6-scheduler-watch-mode`) |
| Platform | win32 / MINGW64_NT-10.0-22631, Python 3.12 |
| Disposition | **Revisions required before commit/merge** (1 medium, 1 low, both same root cause) |

## Summary

The core design is correct. The three defects raised in the prior design review
(G1 orphan `owner.json`, G2 recovery-clears-lock ordering, G3 dangling `pid`
field) have all been adopted and verified against code. Claim mutual exclusion
holds under direct concurrent contention, and the real-kill crash smoke is
stable on Windows.

One medium-severity Windows stability defect remains: `acquire_claim_lock_dir`
re-raises a transient Windows filesystem error (`[WinError 5]` access denied)
as a hard `HarnessCliError` instead of retrying, which surfaces as a full-suite
flake and would cause worker crashes under real Windows multi-worker load. A
race test with an over-tight 5s timeout is flaky for the same file-system
contention reason.

## Scope And Method

This review verified, against the actual working-tree code:

1. **Claim/recovery ordering** — read `acquire_claim_lock_dir`,
   `try_claim_job`, `execute_claimed_generic_agent_job`, `recover_stale_running_job`,
   `scheduler_run_once`, `scheduler_run_watch` end-to-end.
2. **owner.json atomicity** — confirmed the temp-dir + atomic rename pattern
   prevents orphan locks.
3. **Windows crash-smoke stability** — read `terminate_process_tree`, the
   real-kill test, and orphan-agent cleanup; executed the test.
4. **Race correctness** — executed `acquire_claim_lock_dir` under direct
   6-thread contention and ran the race test multiple times.
5. **Exception handling around the claim lifecycle** in both scheduler
   entrypoints.

Evidence commands and their results are reproduced in the
[Verification Evidence](#verification-evidence) section.

## Verification Evidence

All commands run from `E:\ai-coding-harness` on win32.

### E1. Claim mutual exclusion holds under direct contention

Reproduced a 6-thread race on `acquire_claim_lock_dir` directly (bypassing the
scheduler, removing test-timing noise):

```text
wins=1 fails=5 errors=0
```

Exactly one thread wins; the other five cleanly return `False`. No exceptions.
**Claim lock is correct and mutually exclusive.**

### E2. Windows rename-to-existing semantics

`temp_dir.rename(target)` when `target` exists on Windows raises
`FileExistsError` (winerror 183, errno 17) — **not** `PermissionError`. The
`except FileExistsError` branch at `cli.py:2155` is therefore correct for the
normal race path.

### E3. Full test suite — intermittent failure

```text
python -m unittest discover -s tests
Ran 286 tests in 66.118s
FAILED (failures=1, skipped=1)

FAIL: test_module_entrypoint_queues_runs_scheduler_and_aggregates
AssertionError: 1 != 0 : failed to acquire claim lock
...\jobs\cli-scheduler-job\claim.lock: [WinError 5] 拒绝访问。:
'...\.claim.lock.228019b22fca45a1a698c94374adbf24.tmp' -> '...\claim.lock'
```

### E4. Same test in isolation — passes reliably

```text
run 1: Ran 1 test in 1.203s  OK
run 2: Ran 1 test in 1.195s  OK
run 3: Ran 1 test in 1.179s  OK
```

Isolation passes 3/3 → the E3 failure is full-suite filesystem contention, not
a deterministic logic bug. The single scheduler subprocess means no
inter-process double-claim race exists in this test.

### E5. Race test flakiness

`test_scheduler_run_once_two_workers_execute_same_queued_job_at_most_once`:

```text
run 1: Ran 1 test in 11.731s  FAIL   (first_entered.wait(timeout=5) timed out)
run 2: Ran 1 test in 0.833s   OK
run 3: Ran 1 test in 0.826s   OK
```

1 failure in 3 runs. The 11.7s run hit both 5s wait timeouts.

### E6. Crash smoke stable on Windows

`test_real_scheduler_process_kill_leaves_claimed_running_job_detectable_as_stale`:

```text
run 1: Ran 1 test in 1.210s OK
run 2: Ran 1 test in 1.377s OK
```

`taskkill /F /T /PID` kills the tree; release-file lets the orphan agent exit;
`terminate_pid_tree` is the backstop. No process leakage observed.

## Findings

### Passed (verified correct)

- **C1 — owner.json orphan-lock fix (was G1).** `acquire_claim_lock_dir`
  (`cli.py:2148-2167`) builds `owner.json` inside a temp dir then atomically
  renames the whole dir to `claim.lock`. `owner.json` can never be separated
  from its lock dir, even on pre-rename kill. Schema enforces
  `additionalProperties: false`.
- **C2 — recovery clears lock after job.json (was G2).**
  `recover_stale_running_job` orders: `detect_stale` → requeue
  artifact-conflict refusal (`cli.py:~2520`) → `write_job_recovery_artifact`
  → `append_scheduler_event` → `write_json_atomic(job.json)` →
  `remove_claim_lock_dir`. The requeue refusal `raise` fires *before* any
  lock removal, so a failed recovery leaves the lock intact and the job still
  `running`/re-detectable as stale. The prior "lockless stale job after failed
  recovery" risk does not exist.
- **C3 — `pid` removed from schema (was G3).** `claim-owner.schema.json`
  contains only `schema_version, run_id, job_id, worker_id, claimed_at,
  lock_path`. Resolves the "diagnostic vs liveness signal" ambiguity.
- **C4 — Windows crash smoke stable.** See E6.
- **C5 — claim-then-reload double check.** `try_claim_job` (`cli.py:2271`)
  releases and returns `None` if the reloaded job is no longer `queued`,
  promoting the lock from first-come to first-come-and-state-consistent.

### M1 (medium) — claim lock rename re-raises transient Windows `[WinError 5]` as a hard error

**Location:** `acquire_claim_lock_dir`, `cli.py:2158-2162`

```python
except OSError as exc:
    if lock_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False
    raise HarnessCliError(f"failed to acquire claim lock {lock_dir}: {exc}") from exc
```

**Problem.** On Windows, `temp_dir.rename(lock_dir)` can transiently raise
`PermissionError` (WinError 5 = access denied) when Windows Defender real-time
scanning or a concurrent `TemporaryDirectory` cleanup touches the parent dir.
This is *not* "another worker holds the lock" — at that moment
`lock_dir.exists()` is `False`, so the code falls through to `raise`,
converting a retryable FS error into `HarnessCliError`.

**Evidence.** E3 (full-suite `[WinError 5] 拒绝访问`) vs E4 (isolated 3/3 pass).
The signature — passes in isolation, fails under full-suite FS load, error is
WinError 5 not WinError 183 — is consistent with transient FS contention.

**Impact.** In real Windows multi-worker deployments under FS load, a worker
occasionally crashes out of a `--once` pass instead of retrying. Non-fatal for
correctness (no lock created, job stays `queued`, next poll retries), but the
scheduler raises out of its current invocation and, if uncaught by the caller,
propagates as `worker_failed`. This directly undercuts Phase 7.1's
multi-worker-stability deliverable on the platform where it is claimed to work.

**Recommended fix.** Distinguish transient access errors from "target held"
and apply bounded backoff retry — mirroring the existing
`write_json_atomic` retry pattern at `cli.py:3280-3289`:

```python
except OSError as exc:
    winerror = getattr(exc, "winerror", None)
    transient = winerror in (5, 32, 33)  # access denied / sharing violation
    if transient and not lock_dir.exists():
        # bounded retry with backoff, do NOT raise
        ...
    if lock_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False
    raise HarnessCliError(...) from exc
```

### L1 (low) — race test is flaky due to an over-tight timeout

**Location:** `test_generic_agent_adapter.py:1001`

```python
self.assertTrue(first_entered.wait(timeout=5))
```

**Problem.** The test assumes worker-a enters `fake_execute` (and thus has
claimed) within 5s, then starts worker-b. On Windows cold start (first
`import harness.cli`, temp-dir creation, `validate_run` scanning jobs) this can
exceed 5s, so worker-b starts before worker-a's claim — breaking the test's
"claim first, race second" precondition. See E5 (1 failure in 3, the failure
took 11.7s = two 5s timeouts).

**Note.** This is a *test construction* flake, not a claim-lock bug (E1 proves
the lock is correct). But it will intermittently red CI and obscure real
signal.

**Recommended fix.** Either raise the timeout to 15–30s, or — more
deterministic — add a `claim_acquired` event set inside `fake_execute` and
gate worker-b startup on it, removing reliance on wall-clock timing.

### I1–I3 (info, non-blocking)

- **I1.** `execute_claimed_generic_agent_job` `finally` (`cli.py:2354-2365`)
  reloads job.json when `executed_job is None` to decide release; on read
  failure it sets `should_release=False` (lock retained, safe — recover
  handles it). Invariant is correct but undocumented; a one-line comment would
  help.
- **I2.** The watch path's outer `except Exception` writes
  `heartbeat.status="failed"` and re-raises but does *not* release the current
  claim — correct, because `execute_claimed_generic_agent_job`'s inner
  `finally` already did. The two-finally responsibility split is correct but
  implicit; a comment at the top of `execute_claimed_generic_agent_job` would
  prevent future regressions.
- **I3.** `read_claim_lock_status` (`cli.py:2304-2306`) reports
  `missing-owner` without clearing the lock, covered by
  `test_detect_stale_reports_missing_claim_owner_without_clearing_lock`. Good
  defensive diagnostic; retained correctly alongside C1.

## Conclusion

| Dimension | Verdict |
| --- | --- |
| Prior G1/G2/G3 fixes | ✅ all correctly adopted and verified |
| Claim mutual exclusion | ✅ correct (E1: 6-thread wins=1/fails=5/errors=0) |
| Recovery ordering | ✅ artifact → event → job.json → lock; failed recovery retains lock |
| Windows crash smoke | ✅ stable (E6: 2/2 pass) |
| **Windows claim-lock rename stability** | **⚠ M1 — transient WinError 5 re-raised as hard error** |
| Race test reliability | ⚠ L1 — 5s timeout too tight, CI will flake |

**Recommended disposition:** resolve M1 and L1 before commit/merge. They share
a root cause (Windows filesystem contention around claim-lock rename) and can
be fixed together. C1–C5 and I1–I3 are acceptable as-is.

## Not Covered By This Review (honest disclosure)

- M1 is **Windows-specific**. On Linux, rename contention raises only
  `FileExistsError`, already handled correctly at `cli.py:2155`. M1 will not
  surface on Ubuntu CI; it remains a real bug for Windows users.
- No Linux/CI execution was performed in this review (environment is win32).
- The reviewer did not modify any code or tests (read-only role per harness
  v0.1 delegation contract).
- Code-review-of-tests scope was limited to the claim/race/crash tests
  relevant to the two focus areas; other Phase 7.1 tests were not individually
  audited for quality.
