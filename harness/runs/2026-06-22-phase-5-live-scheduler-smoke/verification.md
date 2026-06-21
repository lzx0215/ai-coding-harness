# Verification

## Commands Run

```powershell
python -m harness.cli queue-generic-agent harness/runs/2026-06-22-phase-5-live-scheduler-smoke phase5-live-scheduler-agent --agent generic-cli-agent --timeout-seconds 30 -- python ..\..\scripts\scheduler-smoke.py
python -m harness.cli run-scheduler harness/runs/2026-06-22-phase-5-live-scheduler-smoke --once
python -m harness.cli aggregate-jobs harness/runs/2026-06-22-phase-5-live-scheduler-smoke
Get-FileHash harness\runs\2026-06-22-phase-5-live-scheduler-smoke\state.json -Algorithm SHA256
python -m unittest tests.test_async_job_artifacts.Phase4ClosureRunTest.test_phase5_live_run_was_produced_by_scheduler_path -v
python -m harness.cli validate harness/runs/2026-06-22-phase-5-live-scheduler-smoke
git diff --check
```

## Results

- `queue-generic-agent` exited 0 and printed `queued generic-agent: 2026-06-22-phase-5-live-scheduler-smoke/phase5-live-scheduler-agent`.
- `run-scheduler --once` exited 0 and printed `scheduler: 2026-06-22-phase-5-live-scheduler-smoke executed=1 skipped=0`.
- `aggregate-jobs` exited 0 and printed `aggregated jobs: 2026-06-22-phase-5-live-scheduler-smoke consumed=1 incomplete=0`.
- `state.json` SHA256 was `1CDB1AE718DCD48B9489124CC96C2657C2483B1848786D1DCB4F638A443A9A42` immediately before and immediately after `run-scheduler --once`. This was a point-in-time scheduler-step check; later lifecycle commands intentionally updated `state.json` while indexing evidence and completing the run.
- `jobs/phase5-live-scheduler-agent/raw.log` contains `phase5 live scheduler agent wrote output`.
- `jobs/aggregation.json` contains `consumed_jobs` as `["phase5-live-scheduler-agent"]` and `incomplete_jobs` as `[]`.
- `jobs/phase5-live-scheduler-agent/input.json` is the historical runtime input from the original queue command. Its `input_file`, `output_file`, and `raw_log_file` fields record the absolute paths used in this worktree at execution time and are not a cross-machine replay contract.
- The targeted Phase 5 live scheduler regression test exited 0 and passed 1 test.
- `validate` exited 0 and printed `valid: harness\runs\2026-06-22-phase-5-live-scheduler-smoke`.
- `git diff --check` exited 0. It printed CRLF replacement warnings for touched text files, but no whitespace errors.

## Not Verified

- Watch mode.
- Multi-worker concurrency.
- Cloud queue integration.
- Automatic stale-running recovery.
- Orphaned running job recovery.

## Residual Risks

- This proves local single-process scheduler execution only.
- Orphaned running jobs are skipped, not recovered.
