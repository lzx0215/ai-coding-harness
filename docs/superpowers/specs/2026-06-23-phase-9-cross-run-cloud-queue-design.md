# Phase 9 Cross-Run / Cloud Queue Design

## Summary

Phase 9 extends the Harness async job model beyond a single run-local
`jobs/<job-id>` directory. The phase covers cross-run scheduling and, later,
cloud or remote queue adapters.

This is a Strict-risk phase. It introduces ownership, permissions,
authentication, recovery, cleanup, and audit concerns. Phase 9 implementation
must not begin until local watch mode, stale recovery, claim locking, claim
tokens, lease diagnostics, and artifact overwrite protection are stable and
verified through source-controlled run evidence.

The first implementable slice should be a local cross-run queue. Cloud queue
execution is a later adapter slice after the local cross-run ownership and audit
model is proven.

## Goals

- Define the boundary between run-local job authority and cross-run queue
  coordination.
- Preserve Codex as the authority for Harness state transitions.
- Keep external workers and remote queue systems as evidence producers, not
  state authorities.
- Require explicit ownership, recovery, cleanup, and audit records for every
  cross-run or cloud queue operation.
- Stage Phase 9 so local cross-run scheduling is proven before any cloud queue
  implementation.
- Make cloud credentials and remote execution permissions explicit user-approved
  inputs, never implicit repository state.

## Non-Goals

- No Phase 9 implementation in this design step.
- No cloud provider selection in this design step.
- No credentials, tokens, secrets, or production resource identifiers in source
  control.
- No automatic destructive cleanup of historical queue, run, job, or audit
  artifacts.
- No weakening of run-local evidence validation, review handling, handoff, or
  completion gates.
- No direct external-agent mutation of `state.json`.

## Risk Classification

Phase 9 uses the `strict-risk-change` workflow when implementation begins.

Strict handling is required because this phase can affect:

- permissions and execution ownership across multiple runs
- credentials and cloud authentication
- remote queue visibility and access control
- recovery decisions for jobs outside the current run directory
- cleanup of queue records and potentially remote artifacts
- audit trails that may be needed to explain cross-run or remote execution

Before any implementation plan is accepted, the scope must name the specific
queue boundary, non-goals, recovery strategy, verification plan, and residual
risk owner.

## Entry Gates

Phase 9 implementation may start only after these gates pass:

1. Phase 6 bounded local watch mode has source-controlled run evidence.
2. Phase 7 stale-running detection and explicit recovery has source-controlled
   run evidence.
3. Phase 7.1 local claim locking has source-controlled crash-smoke evidence.
4. Phase 8 claim tokens, lease diagnostics, claim-aware writes, and artifact
   overwrite guards have source-controlled multi-worker evidence.
5. `docs/INDEX.md`, `harness/memory/progress.md`, and relevant run handoffs
   agree on the current baseline.
6. All source-controlled runs validate with `python -m harness.cli validate`.
7. The full local test suite passes.
8. Remote CI status for the baseline branch is known, or the missing remote CI
   run is recorded as residual risk with an explicit user decision.

If any gate is missing, Codex may write or refine Phase 9 design documents, but
must not start implementation.

## Phase Split

### Phase 9A: Cross-Run Local Queue

Phase 9A proves cross-run scheduling on one machine and one local filesystem.

A queue entry should reference an existing run and job rather than becoming the
job authority itself. The referenced run's `state.json`, job artifact schemas,
and evidence gates remain authoritative for that run.

The cross-run queue may coordinate work selection, claiming, and worker routing,
but completion remains run-local:

- terminal job artifacts stay under the owning run
- Codex explicitly indexes consumed evidence in the owning run
- run state transitions still use `harness.cli advance`
- review, verification, handoff, and memory closure remain run-local gates

Phase 9A must prove:

- one worker cannot execute the same run-local job twice through the cross-run
  queue
- a worker cannot claim a job for a run it is not authorized to handle
- queue records can be recovered or abandoned without rewriting historical run
  records silently
- cleanup is explicit, audited, and non-destructive by default

### Phase 9B: Cloud Queue Adapter

Phase 9B adds a provider-specific or provider-neutral cloud queue adapter after
Phase 9A is stable.

The cloud adapter must not store credentials in source-controlled files. It must
read credentials from an explicit runtime configuration path, environment, or
connector approved for the session. The adapter must record non-secret audit
metadata sufficient to explain what remote queue, account boundary, and worker
identity participated in a job.

Cloud queue execution must preserve the same authority model:

- remote queue systems do not mutate `state.json`
- remote workers return artifacts or evidence for Codex to consume
- Codex decides whether to index evidence and advance state
- cloud-side retries do not imply Harness recovery unless Codex records that
  decision in the run

## Ownership Model

Each future cross-run queue entry should capture at least:

- queue entry id
- owning run id
- owning run path or stable run locator
- job id
- requested agent or adapter
- requested worker class
- creator identity
- allowed worker identity or worker group
- created timestamp
- current queue status
- claim owner and claim token when claimed
- lease heartbeat and expiry diagnostics
- recovery and cleanup audit pointers

The owning run remains the lifecycle authority. The queue entry is a routing and
coordination record, not completion evidence by itself.

## Authentication And Permission Boundary

Local cross-run scheduling may use local filesystem permissions and explicit
worker identity configuration. Cloud scheduling must use a named credential
source approved before execution.

Implementation must reject ambiguous authority boundaries:

- no default cloud account
- no silent credential discovery for Strict execution
- no queue operation without a declared owner
- no destructive cleanup without explicit confirmation
- no cross-run state mutation through a queue worker

For cloud adapters, the design or implementation plan must name the provider,
credential source, least-privilege permissions, revocation path, and audit
metadata before any real cloud call is made.

## Recovery Model

Recovery remains explicit and audited.

For Phase 9A, a stale or orphaned queue claim may be recovered only after the
owning run and referenced job are revalidated. Recovery must not remove or
rewrite run-local artifacts unless the existing Phase 7 recovery preconditions
for that run-local job are satisfied.

For Phase 9B, cloud queue retries, visibility timeouts, dead-letter queues, or
provider redelivery semantics are signals only. They are not Harness recovery
decisions until Codex records a recovery or risk decision in the relevant run.

## Cleanup Model

Cleanup must be conservative:

- terminal run-local job artifacts are retained
- queue coordination records may be compacted only after an audit record exists
- remote queue messages may be deleted only after local durable records are
  written and verified
- cleanup failures are residual risks, not silently ignored success paths

Any implementation that deletes local or remote queue records must use Strict
confirmation unless the cleanup behavior was already approved in the
implementation spec and verified against non-production test resources.

## Evidence And Audit

Phase 9 may need new evidence types, but adding them requires updating the
controlled evidence vocabulary and tests.

Likely future evidence categories:

- cross-run queue audit
- queue recovery decision
- queue cleanup record
- cloud adapter audit

Queue control files, cloud receipt handles, leases, and provider delivery
metadata are not automatically evidence. Codex must explicitly index any
consumed artifact before it can satisfy a validation, review, handoff, or
completion gate.

## Verification Strategy

Phase 9A verification should include:

- schema tests for queue entries and audit records
- unit tests for ownership and permission rejection
- deterministic concurrent local queue claim tests
- stale queue claim detection and explicit recovery tests
- cleanup tests that prove run-local artifacts are not deleted
- a source-controlled live run that creates jobs in multiple runs and proves
  cross-run scheduling without duplicate execution

Phase 9B verification should include:

- provider adapter tests with fake or local emulator APIs first
- credential-source rejection tests
- permission-denied tests
- retry and redelivery tests
- audit record validation
- real cloud smoke only after explicit user approval of provider, account,
  resource names, cost boundary, and cleanup plan

All implementation slices require:

```powershell
python -m unittest discover -s tests -v
Get-ChildItem -Directory harness\runs | ForEach-Object { python -m harness.cli validate $_.FullName }
git diff --check
```

Strict slices also require independent review unless the user explicitly accepts
a documented review waiver.

## Completion Criteria

Phase 9 design is complete when:

- this spec is source-controlled
- Phase 9 is recorded as a Strict, gated future phase
- entry gates and non-goals are explicit
- local cross-run queue and cloud queue are separated into ordered slices

Phase 9 implementation is complete only when:

- the relevant slice has a completed source-controlled run
- verification evidence is indexed
- review evidence or a scoped review waiver is indexed
- handoff records residual risks and memory updates
- all source-controlled runs validate

## Residual Risks

- Cross-run queue coordination expands blast radius beyond a single run
  directory.
- Cloud queue behavior depends on provider delivery semantics that may not map
  exactly to Harness leases or claims.
- Credential handling mistakes can expose secrets or grant broader execution
  permissions than intended.
- Cleanup bugs can orphan remote messages or hide local audit history.
- Recovery decisions across run boundaries can become ambiguous unless the
  owning run is always treated as the lifecycle authority.
