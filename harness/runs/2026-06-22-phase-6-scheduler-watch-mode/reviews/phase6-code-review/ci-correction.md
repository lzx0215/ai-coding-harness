# Phase 6 CI Correction

Recorded at: 2026-06-22T10:50:57Z

This correction supersedes the earlier review-time statement that remote GitHub Actions had not run for the Phase 6 branch.

## Evidence

- Local `HEAD`: `f0558c77baefaa7cc5ca9257394dab8a440b48f2`
- Local `HEAD~1`: `fa324a73f8d4516b6fb7d00446e73c3578f3c885`
- Branch: `codex/phase6-scheduler-watch-mode`
- `origin/codex/phase6-scheduler-watch-mode`: `f0558c77baefaa7cc5ca9257394dab8a440b48f2`
- `git rev-list --left-right --count HEAD...origin/codex/phase6-scheduler-watch-mode`: `0 0`
- Commit message at local and remote HEAD: `docs: record Phase 6 branch push`

GitHub Actions run `27945733032` for branch `codex/phase6-scheduler-watch-mode` and head SHA `f0558c77baefaa7cc5ca9257394dab8a440b48f2` completed with conclusion `success`.

Job results:

- `test`: success
- `package-smoke`: success

The `package-smoke` job ran on GitHub Actions Ubuntu/bash and covered the packaged console-script smoke path that includes:

- `run-scheduler --once`
- `run-scheduler --watch --poll-interval-seconds 0.1 --max-iterations 3`

## Decision Impact

The review finding and residual risk that remote CI had not executed the watch package smoke are superseded by this evidence. The remaining unverified items and accepted residual risks are unchanged:

- Real non-mocked detached child lifecycle via `start-scheduler`.
- KeyboardInterrupt / BaseException scheduler exit path.
- `events.log` integrity under concurrent append from two workers.
- Heartbeat is observational only.
- Stop requests are cooperative and do not interrupt running jobs.
- Multi-worker double-claim risk remains.
- `events.log` has no rotation or fsync.
