from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator

from harness import readiness


PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parent
SCHEMA_DIR = PACKAGE_DIR / "schemas"
STATE_SCHEMA = SCHEMA_DIR / "state.schema.json"
CLAIM_OWNER_SCHEMA = SCHEMA_DIR / "claim-owner.schema.json"
CODEX_ACTOR = "codex"
HARNESS_VERSION = "0.2.0"
GENERIC_ADAPTER_VERSION = "0.1.0"
CROSS_RUN_QUEUE_ENTRY_VERSION = "0.1.0"
SCHEDULER_DIR_NAME = "scheduler"
CLAIM_LOCK_DIR_NAME = "claim.lock"
DEFAULT_CLAIM_LEASE_SECONDS = 60.0
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
ATOMIC_REPLACE_ATTEMPTS = 5
ATOMIC_REPLACE_RETRY_SECONDS = 0.01
CLAIM_LOCK_RENAME_ATTEMPTS = 5
CLAIM_LOCK_RENAME_RETRY_SECONDS = 0.01
TRANSIENT_CLAIM_LOCK_WINERRORS = frozenset({5, 32, 33})
CLAIM_LOCK_REMOVE_ATTEMPTS = 5
CLAIM_LOCK_REMOVE_RETRY_SECONDS = 0.01
TRANSIENT_CLAIM_LOCK_REMOVE_WINERRORS = frozenset({5, 32, 33, 145})
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
        "agent-job",
        "agent-result",
        "aggregation",
        "job-recovery",
    }
)
REVIEW_COMPLETION_EVIDENCE_TYPES = frozenset(
    {"review", "review-evidence", "review-waiver"},
)
COMPLETION_REQUIRED_EVIDENCE_TYPES = frozenset({"verification", "handoff"})
JOB_SCHEMA = SCHEMA_DIR / "job.schema.json"
JOB_RECOVERY_SCHEMA = SCHEMA_DIR / "job-recovery.schema.json"
AGGREGATION_SCHEMA = SCHEMA_DIR / "aggregation.schema.json"
AGENT_RESULT_SCHEMA = SCHEMA_DIR / "agent-result.schema.json"
REVIEW_DECISION_SCHEMA = SCHEMA_DIR / "review-decision.schema.json"
CROSS_RUN_QUEUE_ENTRY_SCHEMA = SCHEMA_DIR / "cross-run-queue-entry.schema.json"
CROSS_RUN_QUEUE_EVENT_SCHEMA = SCHEMA_DIR / "cross-run-queue-event.schema.json"
REVIEW_DECISION_FILENAME = "review-decision.json"
REVIEW_DECISION_SOURCE_REQUIRED_DISPOSITIONS = frozenset(
    {"passed", "findings-triaged", "waived", "risk-accepted", "blocked"},
)
REVIEW_DECISION_TARGETS = frozenset(
    {
        "reviewed",
        "review_blocked",
        "review_failed",
        "review_timeout",
        "review_schema_invalid",
        "external_review_unavailable",
        "risk_accepted",
    }
)
# Targets where Codex's triaged decision must be recorded as a
# review-decision.json. These are the states that represent Codex's review
# disposition (review passed/triaged), not adapter-reported outcomes, reviewer
# unavailability, or the user-driven risk acceptance path. `reviewed` and
# `review_blocked` require a decision record; the remaining review-related
# states reuse their own evidence contracts (process-failure states,
# external_review_unavailable) or the Phase 1 risk-acceptance path.
REVIEW_DECISION_REQUIRED_TARGETS = frozenset({"reviewed", "review_blocked"})
# Evidence types that signal a review actually happened. When any of these are
# indexed and a run advances to a REVIEW_DECISION_TARGETS state, an indexed
# review-decision.json is required. Absence of all of these (e.g. a Fast run, or
# a pre-review run) means no decision is required, which keeps historical runs
# valid without migration.
REVIEW_SIGNAL_EVIDENCE_TYPES = frozenset(
    {
        "review-input",
        "review-output",
        "review-evidence",
        "review-raw-log",
        "review",
    }
)
TERMINAL_JOB_STATUSES = frozenset({"succeeded", "failed", "timeout", "cancelled"})
CLAIM_LIFECYCLE_MUTEX_FILE = ".claim-lock.mutex"
_CLAIM_LIFECYCLE_LOCKS_GUARD = threading.Lock()
_CLAIM_LIFECYCLE_LOCKS: dict[Path, threading.RLock] = {}


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
AGGREGATION_JOB_BUCKETS = (
    "consumed_jobs",
    "succeeded_jobs",
    "failed_jobs",
    "timeout_jobs",
    "cancelled_jobs",
    "incomplete_jobs",
)
TERMINAL_AGGREGATION_JOB_BUCKETS = (
    "succeeded_jobs",
    "failed_jobs",
    "timeout_jobs",
    "cancelled_jobs",
)
SEVERITIES = ("critical", "high", "medium", "low", "info")
AGGREGATION_BUCKET_STATUSES = {
    "succeeded_jobs": "succeeded",
    "failed_jobs": "failed",
    "timeout_jobs": "timeout",
    "cancelled_jobs": "cancelled",
}

NORMAL_TRANSITIONS = {
    "draft": {"triaged"},
    "triaged": {"planned"},
    "planned": {"in_progress"},
    "in_progress": {"implemented"},
    "implemented": {"verified", "failed_verification"},
    "failed_verification": {"implemented"},
    "verified": {"reviewing", "reviewed"},
    "reviewing": {
        "reviewed",
        "review_blocked",
        "review_failed",
        "review_timeout",
        "review_schema_invalid",
        "external_review_unavailable",
    },
    "review_blocked": {"implemented"},
    "review_failed": {"reviewing"},
    "review_timeout": {"reviewing"},
    "review_schema_invalid": {"reviewing"},
    "external_review_unavailable": {"risk_accepted"},
    "reviewed": {"completed"},
    "risk_accepted": {"completed"},
}
NON_TERMINAL_STATES = set(NORMAL_TRANSITIONS)
EXCEPTION_TARGETS = {"blocked", "needs_user_decision"}
ALLOWED_TRANSITIONS = {
    state: targets | EXCEPTION_TARGETS
    for state, targets in NORMAL_TRANSITIONS.items()
}


class HarnessCliError(RuntimeError):
    pass


@dataclass(frozen=True)
class ValidationResult:
    run_dir: Path
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class IndexedJob:
    evidence_index: int
    path: Path
    payload: dict[str, Any]


def is_repository_root(path: Path) -> bool:
    return (
        (path / "AGENTS.md").is_file()
        and (path / "harness" / "core" / "state-authority.md").is_file()
    )


def walk_candidate_roots(start: Path) -> Iterable[Path]:
    resolved = start.resolve(strict=False)
    yield resolved
    yield from resolved.parents


def resolve_repository_root(
    run_dir: Path | str | None = None,
    *,
    root: Path | str | None = None,
) -> Path:
    if root is not None:
        return Path(root).resolve(strict=False)

    env_root = os.environ.get("HARNESS_ROOT")
    if env_root:
        return Path(env_root).resolve(strict=False)

    for candidate in walk_candidate_roots(Path.cwd()):
        if is_repository_root(candidate):
            return candidate

    if run_dir is not None:
        for candidate in walk_candidate_roots(Path(run_dir)):
            if is_repository_root(candidate):
                return candidate

    return ROOT.resolve(strict=False)


def load_json(path: Path) -> dict[str, Any]:
    retry_seconds = ATOMIC_REPLACE_RETRY_SECONDS
    for attempt in range(ATOMIC_REPLACE_ATTEMPTS):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except PermissionError:
            if attempt + 1 == ATOMIC_REPLACE_ATTEMPTS:
                raise
            time.sleep(retry_seconds)
            retry_seconds *= 2
    raise RuntimeError("unreachable")


def state_path(run_dir: Path) -> Path:
    return run_dir / "state.json"


def validate_run(
    run_dir: Path | str,
    *,
    root: Path | str | None = None,
) -> ValidationResult:
    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    errors: list[str] = []
    state_file = state_path(resolved_run_dir)

    if not state_file.exists():
        return ValidationResult(resolved_run_dir, [f"missing state file: {state_file}"])

    try:
        state = load_json(state_file)
    except UnicodeDecodeError as exc:
        return ValidationResult(resolved_run_dir, [f"invalid state encoding: {exc}"])
    except json.JSONDecodeError as exc:
        return ValidationResult(resolved_run_dir, [f"invalid state JSON: {exc}"])
    except OSError as exc:
        return ValidationResult(resolved_run_dir, [f"cannot read state file: {exc}"])

    errors.extend(validate_state(state, root=repo_root, run_dir=resolved_run_dir))

    return ValidationResult(resolved_run_dir, errors)


def validate_state(
    state: Any,
    *,
    root: Path | str | None = None,
    run_dir: Path,
    validate_paths: bool = True,
) -> list[str]:
    repo_root = resolve_repository_root(run_dir, root=root)
    errors: list[str] = []
    schema = load_json(STATE_SCHEMA)
    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(state), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.path) or "<root>"
        errors.append(f"schema error at {location}: {error.message}")

    if not isinstance(state, dict):
        return errors

    errors.extend(validate_evidence_types(state))
    if validate_paths:
        errors.extend(validate_evidence_paths(state, root=repo_root, run_dir=run_dir))
    indexed_jobs, job_errors = load_indexed_job_evidence(
        state,
        root=repo_root,
        run_dir=run_dir,
    )
    errors.extend(job_errors)
    errors.extend(validate_indexed_job_evidence(state, indexed_jobs))
    errors.extend(
        validate_agent_result_evidence(
            state,
            root=repo_root,
            run_dir=run_dir,
            indexed_jobs=indexed_jobs,
        )
    )
    errors.extend(
        validate_aggregation_evidence(
            state,
            root=repo_root,
            run_dir=run_dir,
            indexed_jobs=indexed_jobs,
        )
    )
    errors.extend(
        validate_job_recovery_evidence(
            state,
            root=repo_root,
            run_dir=run_dir,
        )
    )
    errors.extend(
        validate_review_decision_evidence(
            state,
            root=repo_root,
            run_dir=run_dir,
        )
    )
    return errors


def evidence_items(state: dict[str, Any]) -> Iterable[tuple[int, dict[str, Any]]]:
    evidence_entries = state.get("evidence", [])
    if not isinstance(evidence_entries, list):
        return

    for index, evidence in enumerate(evidence_entries):
        if isinstance(evidence, dict):
            yield index, evidence


def validate_evidence_types(state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for index, evidence in evidence_items(state):
        evidence_type = evidence.get("type")
        if not isinstance(evidence_type, str):
            continue
        if evidence_type not in EVIDENCE_TYPES:
            errors.append(
                f"unknown evidence type at evidence[{index}]: {evidence_type}",
            )
    return errors


def validate_job_evidence(
    state: dict[str, Any],
    *,
    root: Path,
    run_dir: Path,
) -> list[str]:
    indexed_jobs, errors = load_indexed_job_evidence(state, root=root, run_dir=run_dir)
    errors.extend(validate_indexed_job_evidence(state, indexed_jobs))
    return errors


def load_indexed_job_evidence(
    state: dict[str, Any],
    *,
    root: Path,
    run_dir: Path,
) -> tuple[dict[str, IndexedJob], list[str]]:
    errors: list[str] = []
    indexed_jobs: dict[str, IndexedJob] = {}
    for index, evidence in evidence_items(state):
        evidence_type = evidence.get("type")
        if evidence_type != "agent-job":
            continue

        raw_path = evidence.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue

        job_path = first_existing_evidence_path(raw_path, root=root, run_dir=run_dir)
        if job_path is None:
            continue

        job, job_errors = validate_json_artifact(job_path, JOB_SCHEMA, "job")
        errors.extend(f"evidence[{index}]: {error}" for error in job_errors)
        if job is None:
            continue

        job_id = job.get("job_id")
        if not isinstance(job_id, str):
            continue
        if job_id in indexed_jobs:
            errors.append(
                f"duplicate agent-job evidence for job_id {job_id} at evidence[{index}]",
            )
            continue
        indexed_jobs[job_id] = IndexedJob(index, job_path, job)

    return indexed_jobs, errors


def validate_indexed_job_evidence(
    state: dict[str, Any],
    indexed_jobs: dict[str, IndexedJob],
) -> list[str]:
    errors: list[str] = []
    state_run_id = state.get("run_id")
    for indexed_job in indexed_jobs.values():
        job = indexed_job.payload
        index = indexed_job.evidence_index
        job_run_id = job.get("run_id")
        if isinstance(state_run_id, str) and job_run_id != state_run_id:
            errors.append(
                f"evidence[{index}]: job run_id {job_run_id} "
                f"does not match state run_id {state_run_id}",
            )

        status = job.get("status")
        if status not in TERMINAL_JOB_STATUSES:
            errors.append(
                f"non-terminal job cannot be consumed at evidence[{index}]: {status}",
            )

        timestamp_errors = validate_job_timestamp_semantics(job)
        errors.extend(f"evidence[{index}]: {error}" for error in timestamp_errors)

    return errors


def validate_job_timestamp_semantics(job: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    status = job.get("status")
    created_at = job.get("created_at")
    started_at = job.get("started_at")
    completed_at = job.get("completed_at")
    updated_at = job.get("updated_at")

    if created_at is None:
        errors.append("job requires created_at")
    elif parse_datetime(created_at) is None:
        errors.append("created_at must be a valid ISO 8601 timestamp")
    if started_at is not None and parse_datetime(started_at) is None:
        errors.append("started_at must be a valid ISO 8601 timestamp")
    if completed_at is not None and parse_datetime(completed_at) is None:
        errors.append("completed_at must be a valid ISO 8601 timestamp")
    if updated_at is not None and parse_datetime(updated_at) is None:
        errors.append("updated_at must be a valid ISO 8601 timestamp")

    if status == "queued":
        if started_at is not None:
            errors.append("queued job must not have started_at")
        if completed_at is not None:
            errors.append("queued job must not have completed_at")
    elif status == "running":
        if not started_at:
            errors.append("running job requires started_at")
        if completed_at is not None:
            errors.append("running job must not have completed_at")
    elif status in TERMINAL_JOB_STATUSES:
        if not started_at:
            errors.append("terminal job requires started_at")
        if not completed_at:
            errors.append("terminal job requires completed_at")

    created_dt = parse_datetime(created_at)
    started_dt = parse_datetime(started_at)
    completed_dt = parse_datetime(completed_at)
    updated_dt = parse_datetime(updated_at)
    if created_dt is not None and started_dt is not None and started_dt < created_dt:
        errors.append("started_at must be on or after created_at")
    if started_dt is not None and completed_dt is not None and completed_dt < started_dt:
        errors.append("completed_at must be on or after started_at")
    if created_dt is not None and completed_dt is not None and completed_dt < created_dt:
        errors.append("completed_at must be on or after created_at")
    if created_dt is not None and updated_dt is not None and updated_dt < created_dt:
        errors.append("updated_at must be on or after created_at")
    if started_dt is not None and updated_dt is not None and updated_dt < started_dt:
        errors.append("updated_at must be on or after started_at")
    if completed_dt is not None and updated_dt is not None and updated_dt < completed_dt:
        errors.append("updated_at must be on or after completed_at")

    return errors


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def resolve_datetime(value: str | datetime | None, field: str) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise HarnessCliError(f"{field} must include timezone information")
        return value.astimezone(timezone.utc)
    parsed = parse_datetime(value)
    if parsed is None:
        raise HarnessCliError(f"{field} must be a valid ISO 8601 timestamp")
    return parsed


def format_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def validate_agent_result_evidence(
    state: dict[str, Any],
    *,
    root: Path,
    run_dir: Path,
    indexed_jobs: dict[str, IndexedJob],
) -> list[str]:
    errors: list[str] = []
    state_run_id = state.get("run_id")
    for index, evidence in evidence_items(state):
        evidence_type = evidence.get("type")
        if evidence_type != "agent-result":
            continue

        raw_path = evidence.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue

        result_path = first_existing_evidence_path(raw_path, root=root, run_dir=run_dir)
        if result_path is None:
            continue

        agent_result, result_errors = validate_json_artifact(
            result_path,
            AGENT_RESULT_SCHEMA,
            "agent-result",
        )
        errors.extend(f"evidence[{index}]: {error}" for error in result_errors)
        if agent_result is None:
            continue

        result_run_id = agent_result.get("run_id")
        if isinstance(state_run_id, str) and result_run_id != state_run_id:
            errors.append(
                f"evidence[{index}]: agent-result run_id {result_run_id} "
                f"does not match state run_id {state_run_id}",
            )

        job_id = agent_result.get("job_id")
        indexed_job = indexed_jobs.get(job_id)
        if indexed_job is None:
            errors.append(
                f"evidence[{index}]: agent-result job_id {job_id} "
                "has no matching agent-job evidence",
            )
            continue

        job = indexed_job.payload
        for field in ("agent", "adapter"):
            if agent_result.get(field) != job.get(field):
                errors.append(
                    f"evidence[{index}]: agent-result {field} "
                    f"{agent_result.get(field)} does not match job {field} {job.get(field)}",
                )

        output_file = job.get("output_file")
        if isinstance(output_file, str) and output_file.strip():
            expected_paths = job_artifact_path_candidates(
                output_file,
                job_path=indexed_job.path,
                root=root,
                run_dir=run_dir,
            )
            if not any(same_path(result_path, expected_path) for expected_path in expected_paths):
                errors.append(
                    f"evidence[{index}]: agent-result path does not match job output_file",
                )

    return errors


def validate_aggregation_evidence(
    state: dict[str, Any],
    *,
    root: Path,
    run_dir: Path,
    indexed_jobs: dict[str, IndexedJob],
) -> list[str]:
    errors: list[str] = []
    state_run_id = state.get("run_id")
    for index, evidence in evidence_items(state):
        evidence_type = evidence.get("type")
        if evidence_type != "aggregation":
            continue

        raw_path = evidence.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue

        aggregation_path = first_existing_evidence_path(raw_path, root=root, run_dir=run_dir)
        if aggregation_path is None:
            continue

        aggregation, aggregation_errors = validate_json_artifact(
            aggregation_path,
            AGGREGATION_SCHEMA,
            "aggregation",
        )
        errors.extend(f"evidence[{index}]: {error}" for error in aggregation_errors)
        if aggregation is None:
            continue

        semantic_errors = validate_aggregation_semantics(aggregation)
        errors.extend(f"evidence[{index}]: {error}" for error in semantic_errors)
        if isinstance(state_run_id, str) and aggregation.get("run_id") != state_run_id:
            errors.append(
                f"evidence[{index}]: aggregation run_id {aggregation.get('run_id')} "
                f"does not match state run_id {state_run_id}",
            )
        cross_check_errors = validate_aggregation_against_jobs(
            aggregation,
            indexed_jobs,
        )
        errors.extend(f"evidence[{index}]: {error}" for error in cross_check_errors)

    return errors


def validate_aggregation_semantics(aggregation: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    bucket_values = {
        bucket: list(aggregation.get(bucket, []))
        for bucket in AGGREGATION_JOB_BUCKETS
    }

    for bucket, job_ids in bucket_values.items():
        seen: set[str] = set()
        for job_id in job_ids:
            if job_id in seen:
                errors.append(
                    f"aggregation semantic error at {bucket}: duplicate job id {job_id}",
                )
            seen.add(job_id)

    consumed_jobs = set(bucket_values["consumed_jobs"])
    for bucket in TERMINAL_AGGREGATION_JOB_BUCKETS:
        for job_id in bucket_values[bucket]:
            if job_id not in consumed_jobs:
                errors.append(
                    f"aggregation semantic error at {bucket}: "
                    f"job id {job_id} is not listed in consumed_jobs",
                )

    for job_id in bucket_values["incomplete_jobs"]:
        if job_id in consumed_jobs:
            errors.append(
                "aggregation semantic error at incomplete_jobs: "
                f"job id {job_id} must not be listed in consumed_jobs",
            )

    terminal_bucket_by_job: dict[str, str] = {}
    for bucket in TERMINAL_AGGREGATION_JOB_BUCKETS:
        for job_id in bucket_values[bucket]:
            previous_bucket = terminal_bucket_by_job.get(job_id)
            if previous_bucket is not None and previous_bucket != bucket:
                errors.append(
                    "aggregation semantic error: "
                    f"job id {job_id} appears in multiple terminal aggregation "
                    f"buckets: {previous_bucket}, {bucket}",
                )
            terminal_bucket_by_job[job_id] = bucket

    for job_id in bucket_values["incomplete_jobs"]:
        terminal_bucket = terminal_bucket_by_job.get(job_id)
        if terminal_bucket is not None:
            errors.append(
                "aggregation semantic error: "
                f"job id {job_id} is both incomplete and terminal ({terminal_bucket})",
            )

    classified_jobs: set[str] = set()
    for bucket in TERMINAL_AGGREGATION_JOB_BUCKETS:
        classified_jobs.update(bucket_values[bucket])
    for job_id in sorted(consumed_jobs - classified_jobs):
        errors.append(
            "aggregation semantic error at consumed_jobs: "
            f"consumed job id {job_id} has no terminal classification",
        )

    return errors


def validate_aggregation_against_jobs(
    aggregation: dict[str, Any],
    indexed_jobs: dict[str, IndexedJob],
) -> list[str]:
    errors: list[str] = []
    consumed_jobs = aggregation.get("consumed_jobs", [])
    for job_id in consumed_jobs:
        if job_id not in indexed_jobs:
            errors.append(
                f"aggregation consumed job {job_id} has no matching agent-job evidence",
            )

    for bucket, expected_status in AGGREGATION_BUCKET_STATUSES.items():
        for job_id in aggregation.get(bucket, []):
            indexed_job = indexed_jobs.get(job_id)
            if indexed_job is None:
                continue
            actual_status = indexed_job.payload.get("status")
            if actual_status != expected_status:
                errors.append(
                    f"aggregation bucket {bucket} expects job status {expected_status} "
                    f"for job {job_id}, got {actual_status}",
                )

    for job_id in aggregation.get("incomplete_jobs", []):
        indexed_job = indexed_jobs.get(job_id)
        if indexed_job is None:
            continue
        actual_status = indexed_job.payload.get("status")
        if actual_status in TERMINAL_JOB_STATUSES:
            errors.append(
                f"aggregation incomplete job {job_id} has terminal agent-job status "
                f"{actual_status}",
            )

    return errors


def validate_job_recovery_evidence(
    state: dict[str, Any],
    *,
    root: Path,
    run_dir: Path,
) -> list[str]:
    errors: list[str] = []
    run_id = state.get("run_id")
    for index, evidence in evidence_items(state):
        if evidence.get("type") != "job-recovery":
            continue

        raw_path = evidence.get("path")
        if not isinstance(raw_path, str):
            continue

        recovery_path = first_existing_evidence_path(
            raw_path,
            root=root,
            run_dir=run_dir,
        )
        if recovery_path is None:
            continue

        recovery, recovery_errors = validate_json_artifact(
            recovery_path,
            JOB_RECOVERY_SCHEMA,
            "job-recovery",
        )
        errors.extend(f"evidence[{index}]: {error}" for error in recovery_errors)
        if recovery is None:
            continue

        if recovery.get("run_id") != run_id:
            errors.append(
                f"evidence[{index}]: job-recovery run_id mismatch: "
                f"expected {run_id}, got {recovery.get('run_id')}",
            )

    return errors


def load_indexed_review_decision(
    state: dict[str, Any],
    *,
    root: Path,
    run_dir: Path,
) -> tuple[dict[str, Any] | None, int, list[str]]:
    """Return (decision_payload_or_None, evidence_index, errors) for the indexed
    review-decision.json. Detection is by basename == review-decision.json among
    review-evidence entries, matching the canonical path in the Phase 3 spec."""
    errors: list[str] = []
    state_run_id = state.get("run_id")
    decision: dict[str, Any] | None = None
    decision_index = -1
    for index, evidence in evidence_items(state):
        if evidence.get("type") != "review-evidence":
            continue
        raw_path = evidence.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue

        candidate_path = first_existing_evidence_path(raw_path, root=root, run_dir=run_dir)
        if candidate_path is None:
            continue
        if candidate_path.name != REVIEW_DECISION_FILENAME:
            continue

        if decision_index != -1:
            errors.append(
                f"evidence[{index}]: duplicate review-decision evidence",
            )
            continue

        loaded_decision, decision_errors = validate_json_artifact(
            candidate_path,
            REVIEW_DECISION_SCHEMA,
            "review-decision",
        )
        errors.extend(f"evidence[{index}]: {error}" for error in decision_errors)
        decision_index = index
        if loaded_decision is None:
            continue
        decision = loaded_decision

        if isinstance(state_run_id, str) and decision.get("run_id") != state_run_id:
            errors.append(
                f"evidence[{index}]: review-decision run_id {decision.get('run_id')} "
                f"does not match state run_id {state_run_id}",
            )

    if decision_index != -1:
        return decision, decision_index, errors

    return None, -1, errors


def validate_review_decision_evidence(
    state: dict[str, Any],
    *,
    root: Path,
    run_dir: Path,
) -> list[str]:
    errors: list[str] = []
    decision, index, load_errors = load_indexed_review_decision(
        state,
        root=root,
        run_dir=run_dir,
    )
    errors.extend(load_errors)
    if decision is None:
        return errors

    errors.extend(
        validate_review_decision_semantics(
            decision,
            state,
            index=index,
            root=root,
            run_dir=run_dir,
        )
    )
    return errors


def validate_review_decision_semantics(
    decision: dict[str, Any],
    state: dict[str, Any],
    *,
    index: int,
    root: Path,
    run_dir: Path,
) -> list[str]:
    errors: list[str] = []
    severity = decision.get("severity_counts", {}) if isinstance(
        decision.get("severity_counts"), dict
    ) else {}
    high_or_critical = (severity.get("high", 0) or 0) > 0 or (
        severity.get("critical", 0) or 0
    ) > 0

    indexed_paths = {
        evidence.get("path")
        for _index, evidence in evidence_items(state)
        if isinstance(evidence.get("path"), str) and evidence.get("path").strip()
    }
    evidence_types = {
        evidence.get("type")
        for _index, evidence in evidence_items(state)
        if isinstance(evidence.get("type"), str)
    }

    recommended_status = decision.get("recommended_status")
    disposition = decision.get("disposition")
    source_evidence = decision.get("source_evidence")

    if (
        disposition in REVIEW_DECISION_SOURCE_REQUIRED_DISPOSITIONS
        and not source_evidence
    ):
        errors.append(
            f"evidence[{index}]: {disposition} review-decision requires non-empty "
            "source_evidence",
        )

    if high_or_critical and recommended_status == "reviewed":
        if not decision.get("resolved_findings") and not decision.get("accepted_risks"):
            errors.append(
                f"evidence[{index}]: review-decision cannot override a high or critical "
                "finding without resolved_findings or accepted_risks",
            )

    if high_or_critical and (
        disposition == "risk-accepted" or recommended_status == "risk_accepted"
    ):
        if not decision.get("accepted_risks"):
            errors.append(
                f"evidence[{index}]: risk-accepted review-decision cannot accept "
                "a high or critical finding without accepted_risks",
            )

    if disposition == "waived" and "review-waiver" not in evidence_types:
        errors.append(
            f"evidence[{index}]: waived review-decision requires indexed review-waiver evidence",
        )

    if disposition == "risk-accepted" and "risk-acceptance" not in evidence_types:
        errors.append(
            f"evidence[{index}]: risk-accepted review-decision requires indexed "
            "risk-acceptance evidence",
        )

    if isinstance(source_evidence, list):
        for position, entry in enumerate(source_evidence):
            if not isinstance(entry, dict):
                continue
            raw_path = entry.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            # Not indexed, so it must at least be indexable: the artifact must
            # exist within the repository or the run directory.
            candidate = first_existing_evidence_path(raw_path, root=root, run_dir=run_dir)
            if raw_path not in indexed_paths and candidate is None:
                errors.append(
                    f"evidence[{index}]: review-decision source_evidence[{position}] "
                    f"path {raw_path} is not indexed and does not exist",
                )
                continue
            if candidate is None:
                continue

            errors.extend(
                validate_review_decision_severity_counts(
                    decision,
                    source_type=entry.get("type"),
                    source_path=candidate,
                    index=index,
                    position=position,
                )
            )

    return errors


def validate_review_decision_severity_counts(
    decision: dict[str, Any],
    *,
    source_type: Any,
    source_path: Path,
    index: int,
    position: int,
) -> list[str]:
    if source_type not in {"review-output", "review-evidence"}:
        return []
    expected_counts = decision.get("severity_counts")
    if not isinstance(expected_counts, dict):
        return []

    try:
        payload = load_json(source_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []

    findings = extract_review_findings(payload)
    if findings is None:
        return []
    actual_counts = severity_counts_from_findings(findings)
    if actual_counts is None:
        return []

    expected = {severity: expected_counts.get(severity, 0) for severity in SEVERITIES}
    if actual_counts == expected:
        return []

    return [
        f"evidence[{index}]: review-decision severity_counts {expected} do not match "
        f"{source_type} source_evidence[{position}] findings counts {actual_counts}",
    ]


def extract_review_findings(payload: dict[str, Any]) -> list[Any] | None:
    findings = payload.get("findings")
    if isinstance(findings, list):
        return findings

    for container_name in ("structured_output", "content"):
        container = payload.get(container_name)
        if isinstance(container, dict) and isinstance(container.get("findings"), list):
            return container["findings"]

    return None


def severity_counts_from_findings(findings: list[Any]) -> dict[str, int] | None:
    counts = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        if not isinstance(finding, dict):
            return None
        severity = finding.get("severity")
        if severity not in counts:
            return None
        counts[severity] += 1
    return counts


def validate_evidence_paths(
    state: dict[str, Any],
    *,
    root: Path,
    run_dir: Path,
) -> list[str]:
    errors: list[str] = []
    resolved_root = root.resolve()
    resolved_run_dir = run_dir.resolve()
    for index, evidence in evidence_items(state):
        raw_path = evidence.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue

        candidates = evidence_path_candidates(
            raw_path,
            root=resolved_root,
            run_dir=resolved_run_dir,
        )

        if any(not is_within_path(candidate, resolved_root) for candidate in candidates):
            errors.append(
                f"evidence path is outside repository at evidence[{index}]: {raw_path}",
            )
            continue

        if not any(candidate.exists() for candidate in candidates):
            errors.append(f"evidence path does not exist at evidence[{index}]: {raw_path}")

    return errors


def first_existing_evidence_path(
    raw_path: str,
    *,
    root: Path,
    run_dir: Path,
    require_within_root: bool = True,
) -> Path | None:
    resolved_root = root.resolve()
    candidates = evidence_path_candidates(raw_path, root=root, run_dir=run_dir)
    if require_within_root and any(
        not is_within_path(candidate, resolved_root) for candidate in candidates
    ):
        return None

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def format_schema_errors(prefix: str, errors: Iterable[Any]) -> list[str]:
    formatted: list[str] = []
    for error in sorted(errors, key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.path) or "<root>"
        formatted.append(f"{prefix} schema error at {location}: {error.message}")
    return formatted


def validate_json_artifact(
    path: Path,
    schema_path: Path,
    prefix: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        payload = load_json(path)
    except UnicodeDecodeError as exc:
        return None, [f"{prefix} invalid encoding: {exc}"]
    except json.JSONDecodeError as exc:
        return None, [f"{prefix} invalid JSON: {exc}"]
    except OSError as exc:
        return None, [f"{prefix} cannot read file: {exc}"]

    schema = load_json(schema_path)
    errors = format_schema_errors(prefix, Draft202012Validator(schema).iter_errors(payload))
    if errors:
        return None, errors
    return payload, []


def validate_json_payload(payload: dict[str, Any], schema_path: Path, prefix: str) -> None:
    schema = load_json(schema_path)
    errors = format_schema_errors(prefix, Draft202012Validator(schema).iter_errors(payload))
    if errors:
        raise HarnessCliError(format_errors(errors))


def evidence_path_candidates(raw_path: str, *, root: Path, run_dir: Path) -> list[Path]:
    evidence_path = Path(raw_path)
    candidates = [evidence_path]
    if not evidence_path.is_absolute():
        candidates = [root / evidence_path, run_dir / evidence_path]

    resolved: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved_candidate = candidate.resolve(strict=False)
        if resolved_candidate not in seen:
            resolved.append(resolved_candidate)
            seen.add(resolved_candidate)
    return resolved


def job_artifact_path_candidates(
    raw_path: str,
    *,
    job_path: Path,
    root: Path,
    run_dir: Path,
) -> list[Path]:
    artifact_path = Path(raw_path)
    candidates = [artifact_path]
    if not artifact_path.is_absolute():
        candidates = [
            job_path.parent / artifact_path,
            root / artifact_path,
            run_dir / artifact_path,
        ]

    resolved: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved_candidate = candidate.resolve(strict=False)
        if resolved_candidate not in seen:
            resolved.append(resolved_candidate)
            seen.add(resolved_candidate)
    return resolved


def is_within_path(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def same_path(left: Path, right: Path) -> bool:
    try:
        if left.exists() and right.exists():
            return left.samefile(right)
    except OSError:
        pass
    left_text = os.path.normcase(os.path.normpath(str(left.resolve(strict=False))))
    right_text = os.path.normcase(os.path.normpath(str(right.resolve(strict=False))))
    return left_text == right_text


def can_transition(current_status: str, next_status: str) -> bool:
    return next_status in ALLOWED_TRANSITIONS.get(current_status, set())


def validate_completion_evidence(
    state: dict[str, Any],
    next_status: str,
) -> list[str]:
    if next_status != "completed":
        return []

    errors: list[str] = []
    evidence_types = {
        evidence.get("type")
        for _index, evidence in evidence_items(state)
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


HANDOFF_REQUIRED_CLOSURE_FIELDS = (
    "changed",
    "verified",
    "not_verified",
    "residual_risks",
    "next_step",
    "memory_update",
    "memory_files",
)


def validate_handoff_closure(
    state: dict[str, Any],
    next_status: str,
    *,
    root: Path,
    run_dir: Path,
) -> list[str]:
    if next_status != "completed":
        return []

    handoff_path = first_indexed_evidence_path(state, "handoff", root=root, run_dir=run_dir)
    if handoff_path is None:
        return []

    try:
        text = handoff_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return [f"cannot read handoff artifact: {exc}"]

    result = readiness.parse_frontmatter(text)
    errors: list[str] = []
    for field_name in HANDOFF_REQUIRED_CLOSURE_FIELDS:
        if field_name not in result.data:
            errors.append(f"handoff frontmatter missing field: {field_name}")

    if errors:
        return errors

    memory_update = result.data.get("memory_update")
    memory_files = result.data.get("memory_files")
    if not isinstance(memory_files, list):
        errors.append("handoff memory_files must be a list")
        memory_files = []

    if memory_update == "updated" and not memory_files:
        errors.append("handoff memory_update is updated but memory_files is empty")

    for raw_file in memory_files:
        if not isinstance(raw_file, str) or not raw_file.strip():
            errors.append("handoff memory_files contains an empty entry")
            continue
        candidate = first_existing_evidence_path(raw_file, root=root, run_dir=run_dir)
        if candidate is None:
            errors.append(f"handoff memory file does not exist: {raw_file}")

    return errors


def first_indexed_evidence_path(
    state: dict[str, Any],
    evidence_type: str,
    *,
    root: Path,
    run_dir: Path,
) -> Path | None:
    for _index, evidence in evidence_items(state):
        if evidence.get("type") != evidence_type:
            continue
        raw_path = evidence.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        candidate = first_existing_evidence_path(raw_path, root=root, run_dir=run_dir)
        if candidate is not None:
            return candidate
    return None


def validate_transition_policy(
    state: dict[str, Any],
    next_status: str,
) -> list[str]:
    if (
        state.get("status") == "external_review_unavailable"
        and state.get("track") == "Strict"
        and next_status == "risk_accepted"
    ):
        return [
            "strict unavailable review requires needs_user_decision before risk acceptance",
        ]
    return []


def validate_review_decision_transition(
    state: dict[str, Any],
    next_status: str,
    *,
    root: Path,
    run_dir: Path,
) -> list[str]:
    if next_status not in REVIEW_DECISION_TARGETS:
        return []

    decision, _index, load_errors = load_indexed_review_decision(
        state,
        root=root,
        run_dir=run_dir,
    )
    if load_errors:
        return load_errors
    if decision is None:
        # No indexed decision. It is only required for the triage-disposition
        # targets (reviewed, review_blocked), where Codex's review decision
        # must be recorded. The other review-related targets are adapter
        # outcomes (process-failure states, external_review_unavailable) or
        # the user-driven risk-acceptance path, which reuse their own Phase 1
        # evidence contracts and do not need a decision record. This keeps
        # historical runs valid without migration.
        if next_status not in REVIEW_DECISION_REQUIRED_TARGETS:
            return []
        evidence_types = {
            evidence.get("type")
            for _index, evidence in evidence_items(state)
            if isinstance(evidence.get("type"), str)
        }
        if evidence_types & REVIEW_SIGNAL_EVIDENCE_TYPES:
            return [
                "review-decision is required to advance to a review outcome state "
                "when review evidence is indexed",
            ]
        return []

    recommended_status = decision.get("recommended_status")
    if recommended_status != next_status:
        return [
            f"advance target {next_status} does not match review-decision "
            f"recommended_status {recommended_status}",
        ]
    return []


def advance_run(
    run_dir: Path | str,
    next_status: str,
    *,
    actor: str = CODEX_ACTOR,
    root: Path | str | None = None,
) -> dict[str, Any]:
    if actor != CODEX_ACTOR:
        raise HarnessCliError("only codex may advance harness run state")

    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    path = state_path(resolved_run_dir)
    try:
        state = load_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HarnessCliError(f"cannot read state file: {exc}") from exc

    current_status = state["status"]
    if not can_transition(current_status, next_status):
        raise HarnessCliError(
            f"invalid transition: {current_status} -> {next_status}",
        )

    policy_errors = validate_transition_policy(state, next_status)
    if policy_errors:
        raise HarnessCliError(format_errors(policy_errors))

    review_decision_errors = validate_review_decision_transition(
        state,
        next_status,
        root=repo_root,
        run_dir=resolved_run_dir,
    )
    if review_decision_errors:
        raise HarnessCliError(format_errors(review_decision_errors))

    completion_errors = validate_completion_evidence(state, next_status)
    if completion_errors:
        raise HarnessCliError(format_errors(completion_errors))

    handoff_errors = validate_handoff_closure(
        state,
        next_status,
        root=repo_root,
        run_dir=resolved_run_dir,
    )
    if handoff_errors:
        raise HarnessCliError(format_errors(handoff_errors))

    candidate = dict(state)
    candidate["status"] = next_status
    candidate["updated_at"] = utc_now()
    candidate_errors = validate_state(candidate, root=repo_root, run_dir=resolved_run_dir)
    if candidate_errors:
        raise HarnessCliError(format_errors(candidate_errors))

    write_json_atomic(path, candidate)

    return candidate


def check_ready(
    run_dir: Path | str,
    *,
    root: Path | str | None = None,
) -> readiness.ReadinessReport:
    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    validation = validate_run(resolved_run_dir, root=repo_root)
    if not validation.ok:
        raise HarnessCliError(format_errors(validation.errors))

    try:
        state = load_json(state_path(resolved_run_dir))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HarnessCliError(f"cannot read state file: {exc}") from exc

    return readiness.check_run_readiness(resolved_run_dir, state)


def index_evidence(
    run_dir: Path | str,
    evidence_type: str,
    evidence_path: str,
    *,
    description: str | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    validation = validate_run(resolved_run_dir, root=repo_root)
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

    candidate_errors = validate_state(candidate, root=repo_root, run_dir=resolved_run_dir)
    if candidate_errors:
        raise HarnessCliError(format_errors(candidate_errors))

    write_json_atomic(path, candidate)
    return candidate


TEMPLATE_DIR = PACKAGE_DIR / "templates"


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


def init_run(
    run_dir: Path | str,
    *,
    run_id: str,
    track: str,
    workflow: str,
    base_commit: str,
    root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    if resolved_run_dir.exists():
        raise HarnessCliError(f"run directory already exists: {resolved_run_dir}")

    created_at = utc_now()
    state = {
        "run_id": run_id,
        "harness_version": HARNESS_VERSION,
        "state_schema_version": HARNESS_VERSION,
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

    precheck_errors = validate_state(
        state,
        root=repo_root,
        run_dir=resolved_run_dir,
        validate_paths=False,
    )
    if precheck_errors:
        raise HarnessCliError(format_errors(precheck_errors))

    created_run_dir = False
    try:
        resolved_run_dir.mkdir(parents=True)
        created_run_dir = True

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
        validation = validate_run(resolved_run_dir, root=repo_root)
        if not validation.ok:
            raise HarnessCliError(format_errors(validation.errors))
    except Exception:
        if created_run_dir:
            remove_created_run_dir(resolved_run_dir)
        raise
    return state


def remove_created_run_dir(run_dir: Path) -> None:
    target = run_dir.resolve(strict=False)
    parent = run_dir.parent.resolve(strict=False)
    if target == parent or not is_within_path(target, parent):
        return
    shutil.rmtree(target)


def validate_non_empty_string(value: Any, field: str) -> None:
    if not isinstance(value, str):
        raise HarnessCliError(f"{field} must be a string")
    if not value.strip():
        raise HarnessCliError(f"{field} must be non-empty")


def validate_generic_agent_job_id(job_id: str) -> None:
    if (
        Path(job_id).is_absolute()
        or "/" in job_id
        or "\\" in job_id
        or job_id in {".", ".."}
    ):
        raise HarnessCliError("job_id must be a single safe path segment")


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
    validate_non_empty_string(job_id, "job_id")
    validate_generic_agent_job_id(job_id)
    validate_non_empty_string(agent, "agent")
    validate_non_empty_string(adapter, "adapter")
    if not command:
        raise HarnessCliError("generic agent command must be non-empty")
    if not isinstance(command, list) or any(not isinstance(item, str) for item in command):
        raise HarnessCliError("command must be a non-empty list of strings")
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
        raise HarnessCliError(f"job directory already exists: {job_dir}")
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
        "updated_at": created_at,
        "worker_id": None,
        "timeout_seconds": timeout_seconds,
        "error_reason": None,
        "provenance": {
            "agent": agent,
            "adapter_version": GENERIC_ADAPTER_VERSION,
            "runtime": "local-cli",
        },
    }
    input_payload = {
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
    }
    try:
        write_json_file(input_path, input_payload)
        write_json_file(job_path, job)
    except Exception:
        remove_created_run_dir(job_dir)
        raise
    return job


def validate_generic_agent_input(
    input_payload: Any,
    job: dict[str, Any],
    state: dict[str, Any],
    job_dir: Path,
    input_path: Path,
    output_path: Path,
    raw_log_path: Path,
) -> list[str]:
    if not isinstance(input_payload, dict):
        return ["job input must be an object"]

    errors: list[str] = []
    command = input_payload.get("command")
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(item, str) for item in command)
    ):
        errors.append("command must be a non-empty list of strings")

    expected_fields = {
        "run_id": state["run_id"],
        "job_id": job["job_id"],
        "agent": job["agent"],
        "adapter": job["adapter"],
        "timeout_seconds": job["timeout_seconds"],
    }
    for field, expected in expected_fields.items():
        if input_payload.get(field) != expected:
            errors.append(
                f"input {field} mismatch: expected {expected}, got {input_payload.get(field)}",
            )

    expected_paths = {
        "input_file": input_path,
        "output_file": output_path,
        "raw_log_file": raw_log_path,
    }
    for field, expected_path in expected_paths.items():
        raw_path = input_payload.get(field)
        if not isinstance(raw_path, str) or not raw_path.strip():
            errors.append(f"input {field} must be a non-empty string")
            continue

        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = job_dir / candidate
        resolved_candidate = candidate.resolve(strict=False)
        if not is_within_path(resolved_candidate, job_dir):
            errors.append(f"input {field} escapes job directory: {raw_path}")
        elif not same_path(resolved_candidate, expected_path):
            errors.append(
                f"input {field} mismatch: expected {expected_path}, got {raw_path}",
            )

    return errors


def execute_generic_agent_job(
    run_dir: Path | str,
    job_id: str,
    *,
    worker_id: str | None = None,
    root: Path | str | None = None,
    claim: JobClaim | None = None,
) -> dict[str, Any]:
    validate_non_empty_string(job_id, "job_id")
    validate_generic_agent_job_id(job_id)

    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    jobs_dir = (resolved_run_dir / "jobs").resolve(strict=False)
    job_dir = (jobs_dir / job_id).resolve(strict=False)
    if not is_within_path(job_dir, jobs_dir):
        raise HarnessCliError(f"job_id escapes jobs directory: {job_id}")

    job_path = job_dir / "job.json"
    job, job_errors = validate_json_artifact(job_path, JOB_SCHEMA, "job")
    if job_errors:
        raise HarnessCliError(format_errors(job_errors))
    if job is None:
        raise HarnessCliError(f"job cannot be loaded: {job_path}")
    if job["status"] != "queued":
        raise HarnessCliError(f"cannot execute job {job_id} with status {job['status']}")
    state = load_json(state_path(resolved_run_dir))
    run_id = state["run_id"]
    if job["job_id"] != job_id:
        raise HarnessCliError(f"job_id mismatch: expected {job_id}, got {job['job_id']}")
    if job["run_id"] != run_id:
        raise HarnessCliError(f"run_id mismatch: expected {run_id}, got {job['run_id']}")

    def resolve_job_artifact_path(field: str) -> Path:
        artifact_path = (job_dir / job[field]).resolve(strict=False)
        if not is_within_path(artifact_path, job_dir):
            raise HarnessCliError(f"{field} escapes job directory: {job[field]}")
        return artifact_path

    input_path = resolve_job_artifact_path("input_file")
    output_path = resolve_job_artifact_path("output_file")
    raw_log_path = resolve_job_artifact_path("raw_log_file")
    try:
        input_payload = load_json(input_path)
    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
        raise HarnessCliError(f"job input cannot be loaded: {exc}") from exc

    input_errors = validate_generic_agent_input(
        input_payload,
        job,
        state,
        job_dir,
        input_path,
        output_path,
        raw_log_path,
    )
    if input_errors:
        raise HarnessCliError(format_errors(input_errors))
    if output_path.exists():
        raise HarnessCliError(f"output_file already exists: {output_path}")
    if raw_log_path.exists():
        raise HarnessCliError(f"raw_log_file already exists: {raw_log_path}")

    command = input_payload["command"]
    agent = job["agent"]
    adapter = job["adapter"]
    timeout_seconds = job["timeout_seconds"]
    started_at = utc_now()
    if claim is None:
        job["status"] = "running"
        job["started_at"] = started_at
        job["updated_at"] = started_at
        job["worker_id"] = worker_id
        write_json_file(job_path, job)
    else:
        if claim.job_id != job_id:
            raise HarnessCliError(
                f"claim job_id mismatch: expected {job_id}, got {claim.job_id}",
            )
        job = mark_claimed_job_running(claim, started_at=started_at)

    agent_output_path = output_path
    if claim is not None:
        agent_output_path = claimed_output_temp_path(job_dir, claim.claim_token)
        if agent_output_path.exists():
            raise HarnessCliError(f"claimed output temp file already exists: {agent_output_path}")

    env = os.environ.copy()
    env.update(
        {
            "HARNESS_RUN_ID": run_id,
            "HARNESS_JOB_ID": job_id,
            "HARNESS_AGENT": agent,
            "HARNESS_AGENT_ADAPTER": adapter,
            "HARNESS_AGENT_INPUT_FILE": str(input_path),
            "HARNESS_AGENT_OUTPUT_FILE": str(agent_output_path),
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

    def write_claimed_terminal_job_unlocked(
        terminal_status: str,
        terminal_error_reason: str | None,
        terminal_completed_at: str,
    ) -> dict[str, Any]:
        if claim is None:
            raise AssertionError("claim is required for claimed terminal job write")

        def complete_claimed_job(current: dict[str, Any]) -> dict[str, Any]:
            current["status"] = terminal_status
            current["completed_at"] = terminal_completed_at
            current["updated_at"] = terminal_completed_at
            current["error_reason"] = terminal_error_reason
            current["claim_updated_at"] = terminal_completed_at
            return current

        return write_job_if_claim_matches_unlocked(
            claim,
            expected_status="running",
            mutate=complete_claimed_job,
        )

    if claim is None:
        try:
            write_raw_log(raw_log_path, command, returncode, raw_stdout, raw_stderr)
        except HarnessCliError as exc:
            status = "failed"
            error_reason = str(exc)
    else:
        with claim_lifecycle_lock(claim.job_dir):
            assert_current_job_claim_matches_unlocked(claim, expected_status="running")
            try:
                write_raw_log(raw_log_path, command, returncode, raw_stdout, raw_stderr)
            except HarnessCliError as exc:
                status = "failed"
                error_reason = str(exc)
                cleanup_claimed_output_temp(agent_output_path)
                return write_claimed_terminal_job_unlocked(
                    status,
                    error_reason,
                    utc_now(),
                )

    if claim is None and status == "succeeded":
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

    if claim is not None:
        with claim_lifecycle_lock(claim.job_dir):
            assert_current_job_claim_matches_unlocked(claim, expected_status="running")
            if status == "succeeded":
                if not agent_output_path.exists():
                    status = "failed"
                    error_reason = "agent did not write output_file"
                else:
                    try:
                        publish_claimed_output(agent_output_path, output_path)
                    except HarnessCliError as exc:
                        status = "failed"
                        error_reason = str(exc)
                        cleanup_claimed_output_temp(agent_output_path)
                if status == "succeeded" and not output_path.exists():
                    status = "failed"
                    error_reason = "agent did not write output_file"
                elif status == "succeeded":
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
            else:
                cleanup_claimed_output_temp(agent_output_path)

            return write_claimed_terminal_job_unlocked(
                status,
                error_reason,
                utc_now(),
            )

    completed_at = utc_now()
    if claim is None:
        job["status"] = status
        job["completed_at"] = completed_at
        job["updated_at"] = completed_at
        job["error_reason"] = error_reason
        write_json_file(job_path, job)
        return job
    raise AssertionError("unreachable claimed job completion")


def load_scheduler_jobs(run_dir: Path, *, root: Path) -> list[dict[str, Any]]:
    state = load_json(state_path(run_dir))
    run_id = state["run_id"]
    jobs_dir = run_dir / "jobs"
    if not jobs_dir.exists():
        return []

    jobs: list[dict[str, Any]] = []
    errors: list[str] = []
    for job_path in sorted(jobs_dir.glob("*/job.json")):
        job, job_errors = validate_json_artifact(job_path, JOB_SCHEMA, "job")
        errors.extend(f"{job_path}: {error}" for error in job_errors)
        if job is None:
            continue

        job_id = job.get("job_id")
        if isinstance(job_id, str):
            try:
                validate_generic_agent_job_id(job_id)
            except HarnessCliError as exc:
                errors.append(f"{job_path}: {exc}")
            if job_path.parent.name != job_id:
                errors.append(
                    f"{job_path}: job_id mismatch: expected {job_path.parent.name}, "
                    f"got {job_id}",
                )
        if job.get("run_id") != run_id:
            errors.append(
                f"{job_path}: run_id mismatch: expected {run_id}, got {job.get('run_id')}",
            )

        timestamp_errors = validate_job_timestamp_semantics(job)
        errors.extend(f"{job_path}: {error}" for error in timestamp_errors)
        jobs.append(job)

    if errors:
        raise HarnessCliError(format_errors(errors))
    return jobs


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


def job_claim_lock_dir(run_dir: Path | str, job_id: str) -> Path:
    return Path(run_dir) / "jobs" / job_id / CLAIM_LOCK_DIR_NAME


def job_claim_owner_path(run_dir: Path | str, job_id: str) -> Path:
    return job_claim_lock_dir(run_dir, job_id) / "owner.json"


def claim_lock_relative_path(job_id: str) -> str:
    return f"jobs/{job_id}/{CLAIM_LOCK_DIR_NAME}"


def cross_run_queue_entries_dir(queue_dir: Path | str) -> Path:
    return Path(queue_dir) / "entries"


def cross_run_queue_entry_dir(queue_dir: Path | str, entry_id: str) -> Path:
    validate_generic_agent_job_id(entry_id)
    return cross_run_queue_entries_dir(queue_dir) / entry_id


def cross_run_queue_entry_path(queue_dir: Path | str, entry_id: str) -> Path:
    return cross_run_queue_entry_dir(queue_dir, entry_id) / "entry.json"


def cross_run_queue_claim_lock_dir(queue_dir: Path | str, entry_id: str) -> Path:
    return cross_run_queue_entry_dir(queue_dir, entry_id) / CLAIM_LOCK_DIR_NAME


def cross_run_queue_claim_owner_path(queue_dir: Path | str, entry_id: str) -> Path:
    return cross_run_queue_claim_lock_dir(queue_dir, entry_id) / "owner.json"


def cross_run_queue_claim_lock_relative_path(entry_id: str) -> str:
    return f"entries/{entry_id}/{CLAIM_LOCK_DIR_NAME}"


def cross_run_queue_events_path(queue_dir: Path | str) -> Path:
    return Path(queue_dir) / "events.log"


def cross_run_queue_manifest_path(queue_dir: Path | str) -> Path:
    return Path(queue_dir) / "queue.json"


def queue_id_for_dir(queue_dir: Path | str) -> str:
    return Path(queue_dir).name or "local-cross-run-queue"


def ensure_cross_run_queue(queue_dir: Path | str) -> str:
    queue_path = Path(queue_dir)
    queue_id = queue_id_for_dir(queue_path)
    manifest_path = cross_run_queue_manifest_path(queue_path)
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        existing_queue_id = manifest.get("queue_id")
        if existing_queue_id != queue_id:
            raise HarnessCliError(
                f"cross-run queue id mismatch: expected {queue_id}, got {existing_queue_id}",
            )
        return queue_id

    created_at = utc_now()
    manifest = {
        "schema_version": CROSS_RUN_QUEUE_ENTRY_VERSION,
        "queue_id": queue_id,
        "created_at": created_at,
        "updated_at": created_at,
    }
    validate_non_empty_string(queue_id, "queue_id")
    write_json_atomic(manifest_path, manifest)
    append_cross_run_queue_event(
        queue_path,
        queue_id=queue_id,
        entry_id=None,
        event="queue_initialized",
        actor=CODEX_ACTOR,
        details={},
    )
    return queue_id


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
    with events_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
    return payload


def load_cross_run_queue_entry(queue_dir: Path | str, entry_id: str) -> dict[str, Any]:
    entry_path = cross_run_queue_entry_path(queue_dir, entry_id)
    entry, errors = validate_json_artifact(
        entry_path,
        CROSS_RUN_QUEUE_ENTRY_SCHEMA,
        "cross-run-queue-entry",
    )
    if errors:
        raise HarnessCliError(format_errors(errors))
    if entry is None:
        raise HarnessCliError(f"cross-run queue entry cannot be loaded: {entry_path}")
    return entry


def write_cross_run_queue_entry(
    queue_dir: Path | str,
    entry_id: str,
    entry: dict[str, Any],
) -> None:
    validate_json_payload(entry, CROSS_RUN_QUEUE_ENTRY_SCHEMA, "cross-run-queue-entry")
    write_json_atomic(cross_run_queue_entry_path(queue_dir, entry_id), entry)


def repository_relative_path(path: Path, *, root: Path) -> str:
    resolved_path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    if not is_within_path(resolved_path, resolved_root):
        raise HarnessCliError(f"path is outside repository root: {path}")
    return str(resolved_path.relative_to(resolved_root)).replace("\\", "/")


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
    if allowed_worker_id is not None:
        validate_non_empty_string(allowed_worker_id, "allowed_worker_id")
    for group in allowed_worker_groups:
        validate_non_empty_string(group, "allowed_worker_group")
    if allowed_worker_id is None and not allowed_worker_groups:
        raise HarnessCliError("cross-run queue entry requires allowed_worker_id or allowed_worker_groups")

    resolved_run_dir = Path(run_dir).resolve(strict=False)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    state = load_json(state_path(resolved_run_dir))
    job_path = resolved_run_dir / "jobs" / job_id / "job.json"
    if not job_path.exists():
        raise HarnessCliError(f"referenced job does not exist: {job_id}")
    job = load_job_payload(job_path)
    if job.get("status") != "queued":
        raise HarnessCliError(f"referenced job must be queued, got {job.get('status')}")

    queue_path = Path(queue_dir)
    queue_id = ensure_cross_run_queue(queue_path)
    entry_dir = cross_run_queue_entry_dir(queue_path, entry_id)
    entry_path = entry_dir / "entry.json"
    try:
        entry_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise HarnessCliError(f"cross-run queue entry already exists: {entry_id}") from exc
    except OSError as exc:
        raise HarnessCliError(f"failed to create cross-run queue entry directory: {exc}") from exc

    created_at = utc_now()
    entry = {
        "schema_version": CROSS_RUN_QUEUE_ENTRY_VERSION,
        "queue_id": queue_id,
        "entry_id": entry_id,
        "run_id": state["run_id"],
        "run_dir": repository_relative_path(resolved_run_dir, root=repo_root),
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
    try:
        validate_json_payload(entry, CROSS_RUN_QUEUE_ENTRY_SCHEMA, "cross-run-queue-entry")
        write_json_atomic(entry_path, entry)
        append_cross_run_queue_event(
            queue_path,
            queue_id=queue_id,
            entry_id=entry_id,
            event="entry_created",
            actor=creator,
            details={"run_id": state["run_id"], "job_id": job_id},
        )
    except Exception:
        shutil.rmtree(entry_dir, ignore_errors=True)
        raise
    return entry


def cross_run_queue_worker_authorized(
    entry: dict[str, Any],
    *,
    worker_id: str,
    worker_groups: list[str],
) -> bool:
    allowed_worker_id = entry.get("allowed_worker_id")
    if allowed_worker_id is not None and allowed_worker_id == worker_id:
        return True
    allowed_worker_groups = set(entry.get("allowed_worker_groups", []))
    return bool(allowed_worker_groups.intersection(worker_groups))


def build_cross_run_queue_claim_owner(
    *,
    queue_id: str,
    entry_id: str,
    worker_id: str,
    worker_groups: list[str],
    claim_token: str,
    claimed_at: datetime,
    lease_seconds: float = DEFAULT_CLAIM_LEASE_SECONDS,
) -> dict[str, Any]:
    formatted_claimed_at = format_datetime(claimed_at)
    return {
        "schema_version": 1,
        "queue_id": queue_id,
        "entry_id": entry_id,
        "worker_id": worker_id,
        "worker_groups": worker_groups,
        "claim_token": claim_token,
        "claimed_at": formatted_claimed_at,
        "lease_started_at": formatted_claimed_at,
        "lease_heartbeat_at": formatted_claimed_at,
        "lease_expires_at": format_datetime(add_seconds(claimed_at, lease_seconds)),
        "lock_path": cross_run_queue_claim_lock_relative_path(entry_id),
    }


def release_cross_run_queue_claim(queue_dir: Path | str, entry_id: str) -> None:
    entry_dir = cross_run_queue_entry_dir(queue_dir, entry_id)
    remove_claim_lock_dir(cross_run_queue_claim_lock_dir(queue_dir, entry_id), entry_dir)


def try_claim_cross_run_queue_entry(
    queue_dir: Path | str,
    entry_id: str,
    *,
    worker_id: str,
    worker_groups: list[str],
    root: Path | str | None = None,
) -> dict[str, Any] | None:
    validate_generic_agent_job_id(entry_id)
    validate_non_empty_string(worker_id, "worker_id")
    for group in worker_groups:
        validate_non_empty_string(group, "worker_group")

    queue_path = Path(queue_dir)
    entry = load_cross_run_queue_entry(queue_path, entry_id)
    if entry["status"] != "queued":
        return None
    if not cross_run_queue_worker_authorized(
        entry,
        worker_id=worker_id,
        worker_groups=worker_groups,
    ):
        return None

    entry_dir = cross_run_queue_entry_dir(queue_path, entry_id)
    lock_dir = cross_run_queue_claim_lock_dir(queue_path, entry_id)
    claim_token = new_claim_token()
    claimed_at = datetime.now(timezone.utc)
    owner = build_cross_run_queue_claim_owner(
        queue_id=entry["queue_id"],
        entry_id=entry_id,
        worker_id=worker_id,
        worker_groups=worker_groups,
        claim_token=claim_token,
        claimed_at=claimed_at,
    )
    if not acquire_claim_lock_dir(entry_dir, lock_dir, owner):
        return None

    try:
        entry = load_cross_run_queue_entry(queue_path, entry_id)
        if entry["status"] != "queued" or not cross_run_queue_worker_authorized(
            entry,
            worker_id=worker_id,
            worker_groups=worker_groups,
        ):
            release_cross_run_queue_claim(queue_path, entry_id)
            return None

        claimed_at_text = owner["claimed_at"]
        entry["status"] = "claimed"
        entry["claim_owner"] = worker_id
        entry["claim_token"] = claim_token
        entry["claim_started_at"] = claimed_at_text
        entry["claim_updated_at"] = claimed_at_text
        entry["lease_expires_at"] = owner["lease_expires_at"]
        entry["updated_at"] = claimed_at_text
        write_cross_run_queue_entry(queue_path, entry_id, entry)
        append_cross_run_queue_event(
            queue_path,
            queue_id=entry["queue_id"],
            entry_id=entry_id,
            event="entry_claimed",
            actor=worker_id,
            details={"worker_groups": worker_groups},
        )
        return entry
    except Exception:
        if lock_dir.exists():
            try:
                release_cross_run_queue_claim(queue_path, entry_id)
            except HarnessCliError:
                pass
        raise


def mark_cross_run_queue_entry_running(
    queue_dir: Path | str,
    entry: dict[str, Any],
    *,
    worker_id: str,
) -> dict[str, Any]:
    updated_at = utc_now()
    entry["status"] = "running"
    entry["claim_updated_at"] = updated_at
    entry["updated_at"] = updated_at
    write_cross_run_queue_entry(queue_dir, entry["entry_id"], entry)
    append_cross_run_queue_event(
        queue_dir,
        queue_id=entry["queue_id"],
        entry_id=entry["entry_id"],
        event="entry_executing_job",
        actor=worker_id,
        details={"run_id": entry["run_id"], "job_id": entry["job_id"]},
    )
    return entry


def mark_cross_run_queue_entry_terminal(
    queue_dir: Path | str,
    entry: dict[str, Any],
    *,
    status: str,
    terminal_job_status: str | None,
    worker_id: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updated_at = utc_now()
    entry["status"] = status
    entry["terminal_job_status"] = terminal_job_status
    entry["claim_updated_at"] = updated_at
    entry["updated_at"] = updated_at
    write_cross_run_queue_entry(queue_dir, entry["entry_id"], entry)
    event = "entry_completed" if status == "succeeded" else "entry_failed"
    append_cross_run_queue_event(
        queue_dir,
        queue_id=entry["queue_id"],
        entry_id=entry["entry_id"],
        event=event,
        actor=worker_id,
        details=details or {"terminal_job_status": terminal_job_status},
    )
    return entry


def cross_run_queue_status_for_terminal_job(terminal_job_status: str) -> str:
    if terminal_job_status not in TERMINAL_JOB_STATUSES:
        raise HarnessCliError(f"job status is not terminal: {terminal_job_status}")
    return terminal_job_status


def cross_run_queue_run_once(
    queue_dir: Path | str,
    *,
    worker_id: str,
    worker_groups: list[str],
    root: Path | str | None = None,
) -> dict[str, Any]:
    validate_non_empty_string(worker_id, "worker_id")
    for group in worker_groups:
        validate_non_empty_string(group, "worker_group")

    queue_path = Path(queue_dir)
    repo_root = resolve_repository_root(queue_path, root=root)
    executed_entries: list[str] = []
    skipped_entries: list[str] = []
    entries_dir = cross_run_queue_entries_dir(queue_path)
    if not entries_dir.exists():
        return {"executed_entries": executed_entries, "skipped_entries": skipped_entries}

    for entry_path in sorted(entries_dir.glob("*/entry.json")):
        entry_id = entry_path.parent.name
        claimed_entry = try_claim_cross_run_queue_entry(
            queue_path,
            entry_id,
            worker_id=worker_id,
            worker_groups=worker_groups,
            root=repo_root,
        )
        if claimed_entry is None:
            skipped_entries.append(entry_id)
            continue

        release_queue_claim = False
        try:
            run_dir = repo_root / claimed_entry["run_dir"]
            before = validate_run(run_dir, root=repo_root)
            if not before.ok:
                raise HarnessCliError(format_errors(before.errors))

            claimed_entry = mark_cross_run_queue_entry_running(
                queue_path,
                claimed_entry,
                worker_id=worker_id,
            )
            try:
                job_claim = try_claim_job(
                    run_dir,
                    claimed_entry["job_id"],
                    worker_id=worker_id,
                    root=repo_root,
                )
            except Exception as exc:
                mark_cross_run_queue_entry_terminal(
                    queue_path,
                    claimed_entry,
                    status="failed",
                    terminal_job_status=None,
                    worker_id=worker_id,
                    details={"reason": f"referenced job could not be claimed: {exc}"},
                )
                skipped_entries.append(entry_id)
                release_queue_claim = True
                continue
            if job_claim is None:
                try:
                    current_job = load_job_payload(
                        run_dir / "jobs" / claimed_entry["job_id"] / "job.json",
                    )
                except Exception as exc:
                    mark_cross_run_queue_entry_terminal(
                        queue_path,
                        claimed_entry,
                        status="failed",
                        terminal_job_status=None,
                        worker_id=worker_id,
                        details={"reason": f"referenced job could not be loaded: {exc}"},
                    )
                    skipped_entries.append(entry_id)
                    release_queue_claim = True
                    continue
                if current_job["status"] in TERMINAL_JOB_STATUSES:
                    terminal_job_status = current_job["status"]
                    terminal_entry_status = cross_run_queue_status_for_terminal_job(
                        terminal_job_status,
                    )
                    mark_cross_run_queue_entry_terminal(
                        queue_path,
                        claimed_entry,
                        status=terminal_entry_status,
                        terminal_job_status=terminal_job_status,
                        worker_id=worker_id,
                        details={
                            "terminal_job_status": terminal_job_status,
                            "reason": "referenced job was already terminal",
                        },
                    )
                    skipped_entries.append(entry_id)
                    release_queue_claim = True
                    continue
                mark_cross_run_queue_entry_terminal(
                    queue_path,
                    claimed_entry,
                    status="failed",
                    terminal_job_status=None,
                    worker_id=worker_id,
                    details={"reason": "referenced job could not be claimed"},
                )
                skipped_entries.append(entry_id)
                release_queue_claim = True
                continue

            write_scheduler_worker(
                run_dir,
                worker_id=worker_id,
                poll_interval_seconds=0.1,
                max_iterations=1,
                max_seconds=None,
                root=repo_root,
            )
            write_scheduler_heartbeat(
                run_dir,
                worker_id=worker_id,
                iteration=1,
                status="running-job",
                current_job_id=claimed_entry["job_id"],
            )
            executed_job = execute_claimed_generic_agent_job(
                run_dir,
                job_claim,
                iteration=1,
                poll_interval_seconds=0.1,
                root=repo_root,
            )
            terminal_job_status = executed_job["status"]
            terminal_entry_status = cross_run_queue_status_for_terminal_job(
                terminal_job_status,
            )
            mark_cross_run_queue_entry_terminal(
                queue_path,
                claimed_entry,
                status=terminal_entry_status,
                terminal_job_status=terminal_job_status,
                worker_id=worker_id,
            )
            executed_entries.append(entry_id)
            release_queue_claim = True
        except Exception as exc:
            mark_cross_run_queue_entry_terminal(
                queue_path,
                claimed_entry,
                status="failed",
                terminal_job_status=None,
                worker_id=worker_id,
                details={"reason": f"cross-run queue execution failed: {exc}"},
            )
            skipped_entries.append(entry_id)
            release_queue_claim = True
        finally:
            if release_queue_claim:
                release_cross_run_queue_claim(queue_path, entry_id)

    return {"executed_entries": executed_entries, "skipped_entries": skipped_entries}


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
    validate_generic_agent_job_id(entry_id)
    validate_non_empty_string(reason, "reason")
    validate_non_empty_string(actor, "actor")
    if action not in {"requeue", "abandon"}:
        raise HarnessCliError("action must be one of: requeue, abandon")
    if not confirm:
        raise HarnessCliError("cross-run queue recovery requires --confirm")

    queue_path = Path(queue_dir)
    entry = load_cross_run_queue_entry(queue_path, entry_id)
    if entry["status"] not in {"claimed", "running", "failed"}:
        raise HarnessCliError(f"entry {entry_id} is {entry['status']}, not recoverable")

    repo_root = resolve_repository_root(queue_path, root=root)
    run_dir = repo_root / entry["run_dir"]
    before = validate_run(run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))
    if action == "requeue":
        referenced_job = load_job_payload(run_dir / "jobs" / entry["job_id"] / "job.json")
        if referenced_job["status"] != "queued":
            raise HarnessCliError(
                "cross-run queue requeue requires the referenced run-local job "
                "to be queued; recover the run-local job first",
            )

    created_at = utc_now()
    timestamp = recovery_timestamp_fragment(created_at)
    recovery_path = (
        cross_run_queue_entry_dir(queue_path, entry_id)
        / "recovery"
        / f"{timestamp}-{action}.json"
    )
    recovery = {
        "entry_id": entry_id,
        "run_id": entry["run_id"],
        "job_id": entry["job_id"],
        "action": action,
        "reason": reason,
        "actor": actor,
        "created_at": created_at,
        "previous_status": entry["status"],
    }
    write_json_atomic(recovery_path, recovery)

    entry["status"] = "queued" if action == "requeue" else "abandoned"
    entry["claim_owner"] = None
    entry["claim_token"] = None
    entry["claim_started_at"] = None
    entry["claim_updated_at"] = None
    entry["lease_expires_at"] = None
    if action == "requeue":
        entry["terminal_job_status"] = None
    entry["updated_at"] = created_at
    entry["recovery"].append(str(recovery_path.relative_to(queue_path)).replace("\\", "/"))
    write_cross_run_queue_entry(queue_path, entry_id, entry)
    release_cross_run_queue_claim(queue_path, entry_id)
    append_cross_run_queue_event(
        queue_path,
        queue_id=entry["queue_id"],
        entry_id=entry_id,
        event="entry_requeued" if action == "requeue" else "entry_abandoned",
        actor=actor,
        details={"reason": reason},
    )
    return {"entry": entry, "recovery_path": recovery_path}


def cleanup_cross_run_queue_entry(
    queue_dir: Path | str,
    entry_id: str,
    *,
    confirm: bool,
    actor: str,
    root: Path | str | None = None,
) -> dict[str, Any]:
    validate_generic_agent_job_id(entry_id)
    validate_non_empty_string(actor, "actor")
    if not confirm:
        raise HarnessCliError("cross-run queue cleanup requires --confirm")

    queue_path = Path(queue_dir)
    entry = load_cross_run_queue_entry(queue_path, entry_id)
    if entry["status"] not in TERMINAL_JOB_STATUSES.union({"abandoned"}):
        raise HarnessCliError(f"entry {entry_id} is {entry['status']}, not terminal")

    repo_root = resolve_repository_root(queue_path, root=root)
    run_dir = repo_root / entry["run_dir"]
    before = validate_run(run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    created_at = utc_now()
    timestamp = recovery_timestamp_fragment(created_at)
    cleanup_path = (
        cross_run_queue_entry_dir(queue_path, entry_id)
        / "cleanup"
        / f"{timestamp}-cleanup.json"
    )
    cleanup = {
        "entry_id": entry_id,
        "run_id": entry["run_id"],
        "job_id": entry["job_id"],
        "actor": actor,
        "created_at": created_at,
        "retained_run_dir": entry["run_dir"],
        "retained_job_id": entry["job_id"],
    }
    write_json_atomic(cleanup_path, cleanup)

    cleanup_record = str(cleanup_path.relative_to(queue_path)).replace("\\", "/")
    entry["cleanup"].append(cleanup_record)
    entry["updated_at"] = created_at
    write_cross_run_queue_entry(queue_path, entry_id, entry)
    append_cross_run_queue_event(
        queue_path,
        queue_id=entry["queue_id"],
        entry_id=entry_id,
        event="entry_cleanup_recorded",
        actor=actor,
        details={"cleanup": cleanup_record},
    )
    return {"entry": entry, "cleanup_record": cleanup_record}


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
        "started_at": utc_now(),
        "run_dir": str(resolved_run_dir.resolve(strict=False)),
        "poll_interval": poll_interval_seconds,
        "max_iterations": max_iterations,
        "max_seconds": max_seconds,
        "cli_version": HARNESS_VERSION,
    }
    write_json_atomic(scheduler_worker_path(resolved_run_dir), worker)
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
    write_json_atomic(scheduler_heartbeat_path(run_dir), heartbeat)
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
    write_json_atomic(scheduler_stop_path(resolved_run_dir), payload)
    return payload


def clear_scheduler_stop_request(run_dir: Path | str) -> None:
    path = scheduler_stop_path(run_dir)
    try:
        path.unlink()
    except FileNotFoundError:
        return


def validate_scheduler_watch_options(
    *,
    poll_interval_seconds: float,
    max_iterations: int | None,
    max_seconds: float | None,
) -> None:
    if not math.isfinite(poll_interval_seconds):
        raise HarnessCliError("poll_interval_seconds must be finite")
    if poll_interval_seconds < 0:
        raise HarnessCliError("poll_interval_seconds must be non-negative")
    if poll_interval_seconds == 0 and max_iterations is None and max_seconds is None:
        raise HarnessCliError(
            "poll_interval_seconds can be zero only with max_iterations or max_seconds",
        )
    if max_iterations is not None and max_iterations < 1:
        raise HarnessCliError("max_iterations must be at least 1")
    if max_seconds is not None:
        if not math.isfinite(max_seconds):
            raise HarnessCliError("max_seconds must be finite")
        if max_seconds <= 0:
            raise HarnessCliError("max_seconds must be greater than 0")


def load_scheduler_jobs_for_watch(
    run_dir: Path | str,
    *,
    root: Path | str,
) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        return load_scheduler_jobs(Path(run_dir), root=root), []
    except HarnessCliError as exc:
        return [], str(exc).splitlines()


def resolve_generic_job_dir(run_dir: Path, job_id: str) -> Path:
    jobs_dir = (run_dir / "jobs").resolve(strict=False)
    job_dir = (jobs_dir / job_id).resolve(strict=False)
    if not is_within_path(job_dir, jobs_dir):
        raise HarnessCliError(f"job_id escapes jobs directory: {job_id}")
    return job_dir


def claim_lifecycle_mutex_path(job_dir: Path) -> Path:
    return job_dir / CLAIM_LIFECYCLE_MUTEX_FILE


def claim_lifecycle_local_lock(mutex_path: Path) -> threading.RLock:
    resolved_mutex_path = mutex_path.resolve(strict=False)
    with _CLAIM_LIFECYCLE_LOCKS_GUARD:
        lock = _CLAIM_LIFECYCLE_LOCKS.get(resolved_mutex_path)
        if lock is None:
            lock = threading.RLock()
            _CLAIM_LIFECYCLE_LOCKS[resolved_mutex_path] = lock
        return lock


def lock_claim_lifecycle_file(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def unlock_claim_lifecycle_file(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def claim_lifecycle_lock(job_dir: Path):
    resolved_job_dir = job_dir.resolve(strict=False)
    mutex_path = claim_lifecycle_mutex_path(resolved_job_dir)
    local_lock = claim_lifecycle_local_lock(mutex_path)
    with local_lock:
        try:
            mutex_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(mutex_path, os.O_RDWR | os.O_CREAT)
        except OSError as exc:
            raise HarnessCliError(
                f"failed to open claim lifecycle mutex {mutex_path}: {exc}",
            ) from exc
        with os.fdopen(fd, "r+b") as handle:
            try:
                lock_claim_lifecycle_file(handle)
            except OSError as exc:
                raise HarnessCliError(
                    f"failed to lock claim lifecycle mutex {mutex_path}: {exc}",
                ) from exc
            try:
                yield
            finally:
                try:
                    unlock_claim_lifecycle_file(handle)
                except OSError as exc:
                    raise HarnessCliError(
                        f"failed to unlock claim lifecycle mutex {mutex_path}: {exc}",
                    ) from exc


def remove_claim_lock_dir(lock_dir: Path, job_dir: Path) -> None:
    resolved_job_dir = job_dir.resolve(strict=False)
    resolved_lock_dir = lock_dir.resolve(strict=False)
    if (
        resolved_lock_dir.name != CLAIM_LOCK_DIR_NAME
        or resolved_lock_dir.parent != resolved_job_dir
        or not is_within_path(resolved_lock_dir, resolved_job_dir)
    ):
        raise HarnessCliError(f"refusing to remove unexpected claim lock path: {lock_dir}")
    retry_seconds = CLAIM_LOCK_REMOVE_RETRY_SECONDS
    for attempt in range(CLAIM_LOCK_REMOVE_ATTEMPTS):
        try:
            shutil.rmtree(resolved_lock_dir)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            transient = (
                os.name == "nt"
                and getattr(exc, "winerror", None) in TRANSIENT_CLAIM_LOCK_REMOVE_WINERRORS
            )
            if transient and attempt + 1 < CLAIM_LOCK_REMOVE_ATTEMPTS:
                time.sleep(retry_seconds)
                retry_seconds *= 2
                continue
            raise HarnessCliError(f"failed to remove claim lock {lock_dir}: {exc}") from exc


def release_job_claim_unlocked(claim: JobClaim | None) -> None:
    if claim is None:
        return
    remove_claim_lock_dir(claim.lock_dir, claim.job_dir)


def claim_owner_matches_claim(owner: dict[str, Any], claim: JobClaim) -> bool:
    return (
        owner.get("run_id") == claim.owner.get("run_id")
        and owner.get("job_id") == claim.job_id
        and owner.get("worker_id") == claim.worker_id
        and owner.get("claim_token") == claim.claim_token
    )


def release_job_claim(claim: JobClaim | None) -> None:
    if claim is None:
        return
    with claim_lifecycle_lock(claim.job_dir):
        try:
            owner = load_claim_owner_for_claim_unlocked(claim)
        except HarnessCliError:
            return
        if claim_owner_matches_claim(owner, claim):
            release_job_claim_unlocked(claim)


def acquire_claim_lock_dir(job_dir: Path, lock_dir: Path, owner: dict[str, Any]) -> bool:
    temp_dir = job_dir / f".{CLAIM_LOCK_DIR_NAME}.{uuid.uuid4().hex}.tmp"
    try:
        temp_dir.mkdir()
        write_json_atomic(temp_dir / "owner.json", owner)
        retry_seconds = CLAIM_LOCK_RENAME_RETRY_SECONDS
        for attempt in range(CLAIM_LOCK_RENAME_ATTEMPTS):
            try:
                temp_dir.rename(lock_dir)
                break
            except FileExistsError:
                shutil.rmtree(temp_dir, ignore_errors=True)
                return False
            except OSError as exc:
                if lock_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return False
                transient = getattr(exc, "winerror", None) in TRANSIENT_CLAIM_LOCK_WINERRORS
                if transient and attempt + 1 < CLAIM_LOCK_RENAME_ATTEMPTS:
                    time.sleep(retry_seconds)
                    retry_seconds *= 2
                    continue
                raise HarnessCliError(
                    f"failed to acquire claim lock {lock_dir}: {exc}",
                ) from exc
        return True
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def try_claim_job(
    run_dir: Path | str,
    job_id: str,
    *,
    worker_id: str,
    root: Path | str | None = None,
) -> JobClaim | None:
    validate_non_empty_string(job_id, "job_id")
    validate_generic_agent_job_id(job_id)
    validate_non_empty_string(worker_id, "worker_id")

    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    state = load_json(state_path(resolved_run_dir))
    job_dir = resolve_generic_job_dir(resolved_run_dir, job_id)
    job_path = job_dir / "job.json"
    if not job_path.exists():
        raise HarnessCliError(f"job does not exist: {job_id}")

    lock_dir = job_claim_lock_dir(resolved_run_dir, job_id)
    owner_path = lock_dir / "owner.json"
    claim_token = new_claim_token()
    owner = build_claim_owner(
        run_id=state["run_id"],
        job_id=job_id,
        worker_id=worker_id,
        claim_token=claim_token,
        claimed_at=datetime.now(timezone.utc),
    )
    claim = JobClaim(
        run_dir=resolved_run_dir,
        job_id=job_id,
        worker_id=worker_id,
        claim_token=claim_token,
        job_dir=job_dir,
        lock_dir=lock_dir,
        owner_path=owner_path,
        owner=owner,
    )
    with claim_lifecycle_lock(job_dir):
        if not acquire_claim_lock_dir(job_dir, lock_dir, owner):
            return None

        try:
            job, job_errors = validate_json_artifact(job_path, JOB_SCHEMA, "job")
            if job_errors:
                release_job_claim_unlocked(claim)
                raise HarnessCliError(format_errors(job_errors))
            if job is None:
                release_job_claim_unlocked(claim)
                raise HarnessCliError(f"job cannot be loaded: {job_path}")
            if job.get("job_id") != job_id:
                release_job_claim_unlocked(claim)
                raise HarnessCliError(
                    f"job_id mismatch: expected {job_id}, got {job.get('job_id')}",
                )
            if job.get("run_id") != state["run_id"]:
                release_job_claim_unlocked(claim)
                raise HarnessCliError(
                    f"run_id mismatch: expected {state['run_id']}, got {job.get('run_id')}",
                )
            if job["status"] != "queued":
                release_job_claim_unlocked(claim)
                return None
            return claim
        except Exception:
            if lock_dir.exists():
                try:
                    remove_claim_lock_dir(lock_dir, job_dir)
                except HarnessCliError:
                    pass
            raise


def refresh_claim_lease(
    claim: JobClaim,
    *,
    lease_seconds: float = DEFAULT_CLAIM_LEASE_SECONDS,
    now: str | datetime | None = None,
    root: Path | str | None = None,
) -> JobClaim:
    validate_non_empty_string(claim.job_id, "job_id")
    validate_generic_agent_job_id(claim.job_id)
    validate_non_empty_string(claim.worker_id, "worker_id")
    validate_non_empty_string(claim.claim_token, "claim_token")

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

        errors: list[str] = []
        if owner.get("run_id") != state["run_id"]:
            errors.append(
                f"run_id mismatch: expected {state['run_id']}, got {owner.get('run_id')}",
            )
        if owner.get("job_id") != claim.job_id:
            errors.append(
                f"job_id mismatch: expected {claim.job_id}, got {owner.get('job_id')}",
            )
        if owner.get("worker_id") != claim.worker_id:
            errors.append(
                f"worker_id mismatch: expected {claim.worker_id}, got {owner.get('worker_id')}",
            )
        if owner.get("claim_token") != claim.claim_token:
            errors.append("claim_token mismatch")
        if errors:
            raise HarnessCliError(format_errors(errors))

        now_dt = resolve_datetime(now, "now")
        refreshed_owner = dict(owner)
        refreshed_owner["lease_heartbeat_at"] = format_datetime(now_dt)
        refreshed_owner["lease_expires_at"] = format_datetime(
            add_seconds(now_dt, lease_seconds),
        )
        write_json_atomic(claim.owner_path, refreshed_owner)
        return replace(claim, owner=refreshed_owner)


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
        errors.append(
            f"run_id mismatch: owner {owner.get('run_id')}, job {job.get('run_id')}",
        )
    if owner.get("job_id") != job.get("job_id"):
        errors.append(
            f"job_id mismatch: owner {owner.get('job_id')}, job {job.get('job_id')}",
        )
    if owner.get("worker_id") != worker_id:
        errors.append(
            f"worker_id mismatch: expected {worker_id}, got {owner.get('worker_id')}",
        )
    if owner.get("claim_token") != expected_claim_token:
        errors.append("owner claim_token mismatch")
    if job.get("status") != expected_status:
        errors.append(
            f"status mismatch: expected {expected_status}, got {job.get('status')}",
        )

    job_claim_token = job.get("claim_token")
    if expected_status == "queued" and job_claim_token is not None:
        errors.append(f"claim_token mismatch: expected null, got {job_claim_token}")
    if expected_status == "running" and job_claim_token != expected_claim_token:
        errors.append("claim_token mismatch")
    if errors:
        raise HarnessCliError(format_errors(errors))


def load_claim_owner_for_claim_unlocked(claim: JobClaim) -> dict[str, Any]:
    owner, owner_errors = validate_json_artifact(
        claim.owner_path,
        CLAIM_OWNER_SCHEMA,
        "claim-owner",
    )
    if owner_errors:
        raise HarnessCliError(format_errors(owner_errors))
    if owner is None:
        raise HarnessCliError(f"claim owner cannot be loaded: {claim.owner_path}")
    return owner


def load_claim_owner_for_claim(claim: JobClaim) -> dict[str, Any]:
    return load_claim_owner_for_claim_unlocked(claim)


def load_job_payload(job_path: Path) -> dict[str, Any]:
    job, job_errors = validate_json_artifact(job_path, JOB_SCHEMA, "job")
    if job_errors:
        raise HarnessCliError(format_errors(job_errors))
    if job is None:
        raise HarnessCliError(f"job cannot be loaded: {job_path}")
    return job


def load_job_for_claim_unlocked(claim: JobClaim) -> dict[str, Any]:
    return load_job_payload(claim.job_dir / "job.json")


def validate_job_payload(job: Any) -> list[str]:
    schema = load_json(JOB_SCHEMA)
    errors = format_schema_errors(
        "job",
        Draft202012Validator(schema).iter_errors(job),
    )
    if isinstance(job, dict):
        errors.extend(validate_job_timestamp_semantics(job))
    return errors


def write_job_if_claim_matches_unlocked(
    claim: JobClaim,
    *,
    expected_status: str,
    mutate: Any,
) -> dict[str, Any]:
    job_path = claim.job_dir / "job.json"
    owner = load_claim_owner_for_claim_unlocked(claim)
    job = load_job_for_claim_unlocked(claim)
    assert_claim_matches_job(
        job,
        owner,
        worker_id=claim.worker_id,
        expected_status=expected_status,
        expected_claim_token=claim.claim_token,
    )
    new_job = mutate(json.loads(json.dumps(job)))
    new_job_errors = validate_job_payload(new_job)
    if new_job_errors:
        raise HarnessCliError(format_errors(new_job_errors))
    write_json_atomic(job_path, new_job)
    return new_job


def write_job_if_claim_matches(
    claim: JobClaim,
    *,
    expected_status: str,
    mutate: Any,
) -> dict[str, Any]:
    with claim_lifecycle_lock(claim.job_dir):
        return write_job_if_claim_matches_unlocked(
            claim,
            expected_status=expected_status,
            mutate=mutate,
        )


def assert_current_job_claim_matches_unlocked(
    claim: JobClaim,
    *,
    expected_status: str,
) -> dict[str, Any]:
    owner = load_claim_owner_for_claim_unlocked(claim)
    job = load_job_for_claim_unlocked(claim)
    assert_claim_matches_job(
        job,
        owner,
        worker_id=claim.worker_id,
        expected_status=expected_status,
        expected_claim_token=claim.claim_token,
    )
    return job


def assert_current_job_claim_matches(
    claim: JobClaim,
    *,
    expected_status: str,
) -> dict[str, Any]:
    with claim_lifecycle_lock(claim.job_dir):
        return assert_current_job_claim_matches_unlocked(
            claim,
            expected_status=expected_status,
        )


def mark_claimed_job_running(
    claim: JobClaim,
    *,
    started_at: str,
) -> dict[str, Any]:
    def mutate(job: dict[str, Any]) -> dict[str, Any]:
        job["status"] = "running"
        job["started_at"] = started_at
        job["updated_at"] = started_at
        job["worker_id"] = claim.worker_id
        job["claim_token"] = claim.claim_token
        job["claim_started_at"] = started_at
        job["claim_updated_at"] = started_at
        return job

    return write_job_if_claim_matches(
        claim,
        expected_status="queued",
        mutate=mutate,
    )


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


def cleanup_claimed_output_temp(temp_path: Path) -> None:
    try:
        temp_path.unlink(missing_ok=True)
    except OSError as exc:
        raise HarnessCliError(f"failed to remove claimed output temp file {temp_path}: {exc}") from exc


def claim_lock_snapshot_matches_current_unlocked(
    run_dir: Path,
    job_id: str,
    *,
    run_id: str,
    now: datetime,
    expected_status: str,
    expected_owner: dict[str, Any] | None,
    expected_errors: list[str],
) -> bool:
    current = read_claim_lock_status(
        run_dir,
        job_id,
        run_id=run_id,
        now=now,
    )
    if current.get("status") != expected_status:
        return False
    if current.get("owner") != expected_owner:
        return False
    if expected_status in {"invalid-lock", "missing-owner", "invalid-owner"}:
        return current.get("errors") == expected_errors
    return True


def claim_lock_has_fresh_matching_lease(
    job: dict[str, Any],
    claim_lock_status: dict[str, Any],
) -> bool:
    owner = claim_lock_status.get("owner")
    return (
        claim_lock_status.get("status") == "present"
        and isinstance(owner, dict)
        and claim_lock_status.get("lease_expired") is False
        and owner.get("run_id") == job.get("run_id")
        and owner.get("job_id") == job.get("job_id")
        and owner.get("worker_id") == job.get("worker_id")
        and owner.get("claim_token") == job.get("claim_token")
    )


def remove_recovered_claim_lock_if_unchanged(
    *,
    job_dir: Path,
    lock_dir: Path,
    expected_status: str,
    expected_owner: dict[str, Any] | None,
) -> bool:
    if not lock_dir.exists():
        return False
    with claim_lifecycle_lock(job_dir):
        if not lock_dir.exists():
            return False
        owner_path = lock_dir / "owner.json"
        if expected_status == "missing-owner":
            if owner_path.exists():
                return False
            remove_claim_lock_dir(lock_dir, job_dir)
            return True
        if expected_status != "present" or expected_owner is None:
            return False
        current_owner, owner_errors = validate_json_artifact(
            owner_path,
            CLAIM_OWNER_SCHEMA,
            "claim-owner",
        )
        if owner_errors or current_owner is None:
            return False
        if current_owner != expected_owner:
            return False
        remove_claim_lock_dir(lock_dir, job_dir)
        return True


def read_claim_lock_status(
    run_dir: Path | str,
    job_id: str,
    *,
    run_id: str,
    now: str | datetime | None = None,
) -> dict[str, Any]:
    now_dt = resolve_datetime(now, "now")
    lock_dir = job_claim_lock_dir(run_dir, job_id)
    owner_path = lock_dir / "owner.json"
    status = {
        "status": "absent",
        "path": claim_lock_relative_path(job_id),
        "owner": None,
        "errors": [],
    }
    if not lock_dir.exists():
        return status
    if not lock_dir.is_dir():
        status["status"] = "invalid-lock"
        status["errors"] = [f"{lock_dir}: claim lock must be a directory"]
        return status
    if not owner_path.exists():
        status["status"] = "missing-owner"
        status["errors"] = [f"{owner_path}: owner.json missing"]
        return status

    owner, owner_errors = validate_json_artifact(
        owner_path,
        CLAIM_OWNER_SCHEMA,
        "claim-owner",
    )
    errors = list(owner_errors)
    if owner is not None:
        if owner.get("job_id") != job_id:
            errors.append(
                f"{owner_path}: job_id mismatch: expected {job_id}, got {owner.get('job_id')}",
            )
        if owner.get("run_id") != run_id:
            errors.append(
                f"{owner_path}: run_id mismatch: expected {run_id}, got {owner.get('run_id')}",
            )
    if errors:
        status["status"] = "invalid-owner"
        status["owner"] = owner
        status["errors"] = errors
        return status

    status["status"] = "present"
    status["owner"] = owner
    lease_heartbeat_at = parse_datetime(owner.get("lease_heartbeat_at"))
    lease_expires_at = parse_datetime(owner.get("lease_expires_at"))
    status["claim_token"] = owner.get("claim_token")
    status["lease_heartbeat_at"] = owner.get("lease_heartbeat_at")
    status["lease_expires_at"] = owner.get("lease_expires_at")
    status["lease_age_seconds"] = seconds_since(lease_heartbeat_at, now_dt)
    status["lease_expired"] = (
        lease_expires_at is not None and seconds_since(lease_expires_at, now_dt) > 0
    )
    return status


def execute_claimed_generic_agent_job(
    run_dir: Path,
    claim: JobClaim,
    *,
    iteration: int,
    poll_interval_seconds: float,
    root: Path,
) -> dict[str, Any]:
    executed_job: dict[str, Any] | None = None
    try:
        executed_job = execute_scheduler_job_with_heartbeat(
            run_dir,
            claim.job_id,
            worker_id=claim.worker_id,
            iteration=iteration,
            poll_interval_seconds=poll_interval_seconds,
            root=root,
            claim=claim,
        )
        return executed_job
    finally:
        # Retain the lock for uncertain running states; explicit stale recovery owns cleanup.
        should_release = False
        if executed_job is not None:
            should_release = executed_job.get("status") in TERMINAL_JOB_STATUSES
        else:
            try:
                current_job = load_json(claim.job_dir / "job.json")
                should_release = current_job.get("status") != "running"
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                should_release = False
        if should_release:
            release_job_claim(claim)


def scheduler_stop_requested(
    run_dir: Path | str,
) -> tuple[bool, dict[str, Any] | None, list[str]]:
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


def validate_heartbeat_timeout(heartbeat_timeout_seconds: float) -> None:
    if not math.isfinite(heartbeat_timeout_seconds):
        raise HarnessCliError("heartbeat_timeout_seconds must be finite")
    if heartbeat_timeout_seconds <= 0:
        raise HarnessCliError("heartbeat_timeout_seconds must be greater than 0")


def load_scheduler_heartbeat(
    run_dir: Path | str,
) -> tuple[dict[str, Any] | None, list[str]]:
    path = scheduler_heartbeat_path(run_dir)
    if not path.exists():
        return None, ["scheduler heartbeat missing"]
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, [f"{path}: scheduler heartbeat cannot be read: {exc}"]
    if not isinstance(payload, dict):
        return None, [f"{path}: scheduler heartbeat must be an object"]
    return payload, []


def seconds_since(timestamp: datetime | None, now: datetime) -> float | None:
    if timestamp is None:
        return None
    return max(0.0, (now - timestamp).total_seconds())


def assess_running_job_staleness(
    job: dict[str, Any],
    *,
    heartbeat: dict[str, Any] | None,
    heartbeat_errors: list[str],
    heartbeat_timeout_seconds: float,
    now_dt: datetime,
) -> dict[str, Any]:
    job_id = job["job_id"]
    worker_id = job.get("worker_id")
    started_at = parse_datetime(job.get("started_at"))
    updated_at = parse_datetime(job.get("updated_at")) if job.get("updated_at") else None
    freshness_timestamp = updated_at or started_at
    freshness_label = "updated_at" if updated_at is not None else "started_at"
    freshness_age = seconds_since(freshness_timestamp, now_dt)
    reasons: list[str] = []
    heartbeat_age: float | None = None
    classification = "stale"

    if heartbeat_errors:
        reasons.extend(heartbeat_errors)
    if not worker_id:
        reasons.append("job worker_id missing")

    if heartbeat is not None:
        heartbeat_worker_id = heartbeat.get("worker_id")
        heartbeat_last_seen_at = parse_datetime(heartbeat.get("last_seen_at"))
        heartbeat_age = seconds_since(heartbeat_last_seen_at, now_dt)
        if heartbeat_worker_id != worker_id:
            reasons.append("scheduler heartbeat worker_id mismatch")
        if heartbeat_last_seen_at is None:
            reasons.append("scheduler heartbeat last_seen_at invalid")
        elif heartbeat_age is not None and heartbeat_age > heartbeat_timeout_seconds:
            reasons.append("scheduler heartbeat timed out")
        if heartbeat.get("status") != "running-job":
            reasons.append(f"scheduler heartbeat status is {heartbeat.get('status')}")
        if heartbeat.get("current_job_id") != job_id:
            reasons.append("scheduler heartbeat current_job_id mismatch")

        if (
            worker_id
            and heartbeat_worker_id == worker_id
            and heartbeat_last_seen_at is not None
            and heartbeat_age is not None
            and heartbeat_age <= heartbeat_timeout_seconds
            and heartbeat.get("status") == "running-job"
            and heartbeat.get("current_job_id") == job_id
        ):
            classification = "active"
            reasons = ["fresh matching scheduler heartbeat"]
    if classification != "active":
        if freshness_timestamp is None:
            classification = "invalid"
            reasons.append(f"job {freshness_label} invalid")
        elif freshness_age is not None and freshness_age <= heartbeat_timeout_seconds:
            classification = "recent"
            reasons.append(f"job {freshness_label} within timeout")
        else:
            classification = "stale"
            reasons.append(f"job {freshness_label} timed out")

    return {
        "job_id": job_id,
        "classification": classification,
        "reasons": reasons,
        "worker_id": worker_id,
        "started_at": job.get("started_at"),
        "updated_at": job.get("updated_at"),
        "heartbeat_worker_id": heartbeat.get("worker_id") if heartbeat else None,
        "heartbeat_status": heartbeat.get("status") if heartbeat else None,
        "heartbeat_current_job_id": heartbeat.get("current_job_id") if heartbeat else None,
        "heartbeat_last_seen_at": heartbeat.get("last_seen_at") if heartbeat else None,
        "heartbeat_age_seconds": heartbeat_age,
        "job_age_seconds": freshness_age,
    }


def invalid_running_job_assessment(
    *,
    job_id: str,
    reasons: list[str],
    job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "classification": "invalid",
        "reasons": reasons,
        "worker_id": job.get("worker_id") if job else None,
        "started_at": job.get("started_at") if job else None,
        "updated_at": job.get("updated_at") if job else None,
        "heartbeat_worker_id": None,
        "heartbeat_status": None,
        "heartbeat_current_job_id": None,
        "heartbeat_last_seen_at": None,
        "heartbeat_age_seconds": None,
        "job_age_seconds": None,
    }


def load_running_jobs_for_stale_detection(
    run_dir: Path,
    *,
    root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    state = load_json(state_path(run_dir))
    run_id = state["run_id"]
    jobs_dir = run_dir / "jobs"
    if not jobs_dir.exists():
        return [], []

    running_jobs: list[dict[str, Any]] = []
    invalid_jobs: list[dict[str, Any]] = []
    for job_path in sorted(jobs_dir.glob("*/job.json")):
        job_id = job_path.parent.name
        try:
            raw_job = load_json(job_path)
        except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
            invalid_jobs.append(
                invalid_running_job_assessment(
                    job_id=job_id,
                    reasons=[f"{job_path}: job cannot be loaded: {exc}"],
                )
            )
            continue
        if not isinstance(raw_job, dict):
            invalid_jobs.append(
                invalid_running_job_assessment(
                    job_id=job_id,
                    reasons=[f"{job_path}: job must be an object"],
                )
            )
            continue
        if raw_job.get("status") != "running":
            continue

        job, schema_errors = validate_json_artifact(job_path, JOB_SCHEMA, "job")
        errors = [f"{job_path}: {error}" for error in schema_errors]
        candidate = raw_job if job is None else job
        raw_job_id = candidate.get("job_id")
        if isinstance(raw_job_id, str):
            try:
                validate_generic_agent_job_id(raw_job_id)
            except HarnessCliError as exc:
                errors.append(f"{job_path}: {exc}")
            if raw_job_id != job_id:
                errors.append(
                    f"{job_path}: job_id mismatch: expected {job_id}, got {raw_job_id}",
                )
        else:
            errors.append(f"{job_path}: job_id must be a string")
        if candidate.get("run_id") != run_id:
            errors.append(
                f"{job_path}: run_id mismatch: expected {run_id}, got {candidate.get('run_id')}",
            )
        errors.extend(
            f"{job_path}: {error}" for error in validate_job_timestamp_semantics(candidate)
        )

        if errors:
            invalid_jobs.append(
                invalid_running_job_assessment(
                    job_id=job_id,
                    reasons=errors,
                    job=candidate,
                )
            )
            continue
        running_jobs.append(candidate)

    return running_jobs, invalid_jobs


def detect_stale_running_jobs(
    run_dir: Path | str,
    *,
    heartbeat_timeout_seconds: float,
    now: str | datetime | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    validate_heartbeat_timeout(heartbeat_timeout_seconds)
    now_dt = resolve_datetime(now, "now")
    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    state = load_json(state_path(resolved_run_dir))
    heartbeat, heartbeat_errors = load_scheduler_heartbeat(resolved_run_dir)
    jobs, invalid_assessments = load_running_jobs_for_stale_detection(
        resolved_run_dir,
        root=repo_root,
    )
    jobs = sorted(jobs, key=lambda item: (item["created_at"], item["job_id"]))
    assessments = [
        assess_running_job_staleness(
            job,
            heartbeat=heartbeat,
            heartbeat_errors=heartbeat_errors,
            heartbeat_timeout_seconds=heartbeat_timeout_seconds,
            now_dt=now_dt,
        )
        for job in jobs
    ]
    assessments.extend(invalid_assessments)
    for assessment in assessments:
        assessment["claim_lock"] = read_claim_lock_status(
            resolved_run_dir,
            assessment["job_id"],
            run_id=state["run_id"],
            now=now_dt,
        )

    return {
        "run_id": state["run_id"],
        "generated_at": format_datetime(now_dt),
        "heartbeat_timeout_seconds": heartbeat_timeout_seconds,
        "active_jobs": [
            item["job_id"] for item in assessments if item["classification"] == "active"
        ],
        "recent_jobs": [
            item["job_id"] for item in assessments if item["classification"] == "recent"
        ],
        "stale_jobs": [
            item["job_id"] for item in assessments if item["classification"] == "stale"
        ],
        "invalid_jobs": [
            item["job_id"] for item in assessments if item["classification"] == "invalid"
        ],
        "jobs": assessments,
    }


def job_artifact_path(job_dir: Path, job: dict[str, Any], field: str) -> Path:
    raw_path = job[field]
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = job_dir / candidate
    resolved = candidate.resolve(strict=False)
    if not is_within_path(resolved, job_dir):
        raise HarnessCliError(f"{field} escapes job directory: {raw_path}")
    return resolved


def recovery_timestamp_fragment(timestamp: str) -> str:
    return (
        timestamp.replace("-", "")
        .replace(":", "")
        .replace("+", "")
        .replace(".", "")
    )


def write_job_recovery_artifact(
    run_dir: Path,
    *,
    job_id: str,
    artifact: dict[str, Any],
) -> Path:
    recovery_dir = run_dir / "jobs" / job_id / "recovery"
    recovery_dir.mkdir(parents=True, exist_ok=True)
    requested_at = recovery_timestamp_fragment(artifact["requested_at"])
    path = recovery_dir / f"{requested_at}-{artifact['action']}.json"
    if path.exists():
        path = recovery_dir / f"{requested_at}-{artifact['action']}-{uuid.uuid4().hex[:8]}.json"
    write_json_atomic(path, artifact)
    return path


def recover_stale_running_job(
    run_dir: Path | str,
    job_id: str,
    *,
    action: str,
    reason: str,
    heartbeat_timeout_seconds: float,
    now: str | datetime | None = None,
    confirm: bool = False,
    artifact_correction_confirmed: bool = False,
    actor: str = CODEX_ACTOR,
    root: Path | str | None = None,
) -> dict[str, Any]:
    validate_non_empty_string(job_id, "job_id")
    validate_generic_agent_job_id(job_id)
    validate_non_empty_string(reason, "reason")
    if action not in {"requeue", "fail"}:
        raise HarnessCliError("action must be one of: requeue, fail")
    if not confirm:
        raise HarnessCliError("--confirm is required to recover a stale running job")

    validate_heartbeat_timeout(heartbeat_timeout_seconds)
    now_dt = resolve_datetime(now, "now")
    requested_at = format_datetime(now_dt)
    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    report = detect_stale_running_jobs(
        resolved_run_dir,
        heartbeat_timeout_seconds=heartbeat_timeout_seconds,
        now=now_dt,
        root=repo_root,
    )
    assessment = next(
        (item for item in report["jobs"] if item["job_id"] == job_id),
        None,
    )
    if assessment is None:
        raise HarnessCliError(f"job is not running or does not exist: {job_id}")
    if assessment["classification"] != "stale":
        raise HarnessCliError(
            f"job {job_id} is {assessment['classification']}, not stale; "
            "recovery would risk rewriting an active job",
        )
    claim_lock_assessment = assessment.get("claim_lock", {})
    claim_lock_status = claim_lock_assessment.get("status")
    claim_lock_owner = claim_lock_assessment.get("owner")
    claim_lock_errors = list(claim_lock_assessment.get("errors", []))
    expected_claim_lock_owner = (
        json.loads(json.dumps(claim_lock_owner))
        if isinstance(claim_lock_owner, dict)
        else None
    )

    job_dir = (resolved_run_dir / "jobs" / job_id).resolve(strict=False)
    jobs_dir = (resolved_run_dir / "jobs").resolve(strict=False)
    if not is_within_path(job_dir, jobs_dir):
        raise HarnessCliError(f"job_id escapes jobs directory: {job_id}")
    job_path = job_dir / "job.json"
    job, job_errors = validate_json_artifact(job_path, JOB_SCHEMA, "job")
    if job_errors:
        raise HarnessCliError(format_errors(job_errors))
    if job is None:
        raise HarnessCliError(f"job cannot be loaded: {job_path}")
    if job["status"] != "running":
        raise HarnessCliError(f"job {job_id} is not running")
    if claim_lock_has_fresh_matching_lease(job, claim_lock_assessment):
        raise HarnessCliError(
            f"job {job_id} has a fresh matching claim lease; "
            "recovery would risk rewriting an active job",
        )

    artifact_warnings: list[str] = []
    conflicting_artifacts: list[str] = []
    for field in ("output_file", "raw_log_file"):
        artifact_path = job_artifact_path(job_dir, job, field)
        if artifact_path.exists():
            conflicting_artifacts.append(job[field])
    if action == "requeue" and conflicting_artifacts:
        raise HarnessCliError(
            "artifact correction required before requeue: "
            + ", ".join(conflicting_artifacts),
        )
    if artifact_correction_confirmed:
        artifact_warnings.append("operator confirmed artifact correction before recovery")

    previous_job = json.loads(json.dumps(job))
    new_job = json.loads(json.dumps(job))
    if action == "requeue":
        new_job["status"] = "queued"
        new_job["started_at"] = None
        new_job["completed_at"] = None
        new_job["updated_at"] = requested_at
        new_job["worker_id"] = None
        new_job["error_reason"] = None
        new_job["claim_token"] = None
        new_job["claim_started_at"] = None
        new_job["claim_updated_at"] = None
    else:
        new_job["status"] = "failed"
        new_job["completed_at"] = requested_at
        new_job["updated_at"] = requested_at
        new_job["error_reason"] = f"stale running recovery: {reason}"

    artifact = {
        "schema_version": HARNESS_VERSION,
        "run_id": job["run_id"],
        "job_id": job_id,
        "action": action,
        "requested_by": actor,
        "requested_at": requested_at,
        "reason": reason,
        "heartbeat_timeout_seconds": heartbeat_timeout_seconds,
        "artifact_correction_confirmed": artifact_correction_confirmed,
        "artifact_warnings": artifact_warnings,
        "stale_assessment": assessment,
        "previous_job": previous_job,
        "new_job": new_job,
    }
    recovery_path = write_job_recovery_artifact(
        resolved_run_dir,
        job_id=job_id,
        artifact=artifact,
    )
    claim_lock_removed = False
    lock_dir = job_claim_lock_dir(resolved_run_dir, job_id)
    if not isinstance(claim_lock_status, str):
        raise HarnessCliError("stale assessment missing claim lock status")
    with claim_lifecycle_lock(job_dir):
        current_job = load_job_payload(job_path)
        if current_job != previous_job:
            raise HarnessCliError(
                f"job {job_id} changed during recovery; "
                "refusing to rewrite current job state",
            )
        if not claim_lock_snapshot_matches_current_unlocked(
            resolved_run_dir,
            job_id,
            run_id=job["run_id"],
            now=now_dt,
            expected_status=claim_lock_status,
            expected_owner=expected_claim_lock_owner,
            expected_errors=claim_lock_errors,
        ):
            raise HarnessCliError(
                f"claim lock for job {job_id} changed during recovery; "
                "refusing to rewrite current job state",
            )
        append_scheduler_event(
            resolved_run_dir,
            "stale_running_job_recovered",
            {
                "job_id": job_id,
                "action": action,
                "worker_id": previous_job.get("worker_id"),
                "recovery_artifact": str(recovery_path.relative_to(resolved_run_dir)),
            },
        )
        current_job = load_job_payload(job_path)
        if current_job != previous_job:
            raise HarnessCliError(
                f"job {job_id} changed during recovery; "
                "refusing to rewrite current job state",
            )
        if not claim_lock_snapshot_matches_current_unlocked(
            resolved_run_dir,
            job_id,
            run_id=job["run_id"],
            now=now_dt,
            expected_status=claim_lock_status,
            expected_owner=expected_claim_lock_owner,
            expected_errors=claim_lock_errors,
        ):
            raise HarnessCliError(
                f"claim lock for job {job_id} changed during recovery; "
                "refusing to rewrite current job state",
            )
        write_json_atomic(job_path, new_job)
        if (
            claim_lock_status in {"present", "missing-owner"}
            and claim_lock_snapshot_matches_current_unlocked(
                resolved_run_dir,
                job_id,
                run_id=job["run_id"],
                now=now_dt,
                expected_status=claim_lock_status,
                expected_owner=expected_claim_lock_owner,
                expected_errors=claim_lock_errors,
            )
        ):
            remove_claim_lock_dir(lock_dir, job_dir)
            claim_lock_removed = True
    return {
        "path": recovery_path,
        "artifact": artifact,
        "job": new_job,
        "claim_lock_removed": claim_lock_removed,
    }


def scheduler_run_once(
    run_dir: Path | str,
    *,
    worker_id: str | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    resolved_run_dir = Path(run_dir)
    repo_root = resolve_repository_root(resolved_run_dir, root=root)
    before = validate_run(resolved_run_dir, root=repo_root)
    if not before.ok:
        raise HarnessCliError(format_errors(before.errors))

    state = load_json(state_path(resolved_run_dir))
    jobs = load_scheduler_jobs(resolved_run_dir, root=repo_root)
    ordered_jobs = sorted(jobs, key=lambda job: (job["created_at"], job["job_id"]))
    executed_jobs: list[str] = []
    skipped_jobs: list[str] = []
    terminal_statuses: dict[str, str] = {}
    active_worker_id = worker_id or default_worker_id()
    write_scheduler_worker(
        resolved_run_dir,
        worker_id=active_worker_id,
        poll_interval_seconds=0.1,
        max_iterations=1,
        max_seconds=None,
        root=repo_root,
    )
    write_scheduler_heartbeat(
        resolved_run_dir,
        worker_id=active_worker_id,
        iteration=1,
        status="idle",
        current_job_id=None,
    )
    append_scheduler_event(
        resolved_run_dir,
        "worker_started",
        {"worker_id": active_worker_id, "mode": "once"},
    )

    for job in ordered_jobs:
        job_id = job["job_id"]
        status = job["status"]
        if status == "queued":
            claim = try_claim_job(
                resolved_run_dir,
                job_id,
                worker_id=active_worker_id,
                root=repo_root,
            )
            if claim is None:
                skipped_jobs.append(job_id)
                append_scheduler_event(
                    resolved_run_dir,
                    "job_claim_skipped",
                    {"worker_id": active_worker_id, "job_id": job_id},
                )
                continue
            write_scheduler_heartbeat(
                resolved_run_dir,
                worker_id=active_worker_id,
                iteration=1,
                status="running-job",
                current_job_id=job_id,
            )
            append_scheduler_event(
                resolved_run_dir,
                "job_started",
                {"worker_id": active_worker_id, "job_id": job_id},
            )
            executed_job = execute_claimed_generic_agent_job(
                resolved_run_dir,
                claim,
                iteration=1,
                poll_interval_seconds=0.1,
                root=repo_root,
            )
            executed_jobs.append(job_id)
            if executed_job["status"] in TERMINAL_JOB_STATUSES:
                terminal_statuses[job_id] = executed_job["status"]
            append_scheduler_event(
                resolved_run_dir,
                "job_completed",
                {
                    "worker_id": active_worker_id,
                    "job_id": job_id,
                    "status": executed_job["status"],
                },
            )
        elif status == "running" or status in TERMINAL_JOB_STATUSES:
            skipped_jobs.append(job_id)
            if status in TERMINAL_JOB_STATUSES:
                terminal_statuses[job_id] = status

    write_scheduler_heartbeat(
        resolved_run_dir,
        worker_id=active_worker_id,
        iteration=1,
        status="stopped",
        current_job_id=None,
    )
    append_scheduler_event(
        resolved_run_dir,
        "worker_stopped",
        {
            "worker_id": active_worker_id,
            "iteration": 1,
            "stop_reason": "once_completed",
        },
    )
    return {
        "run_id": state["run_id"],
        "worker_id": active_worker_id,
        "executed_jobs": executed_jobs,
        "skipped_jobs": skipped_jobs,
        "terminal_statuses": terminal_statuses,
    }


def scheduler_job_heartbeat_interval(poll_interval_seconds: float) -> float:
    if poll_interval_seconds <= 0:
        return 0.1
    return min(max(poll_interval_seconds, 0.1), 5.0)


def execute_scheduler_job_with_heartbeat(
    run_dir: Path,
    job_id: str,
    *,
    worker_id: str,
    iteration: int,
    poll_interval_seconds: float,
    root: Path,
    claim: JobClaim | None = None,
) -> dict[str, Any]:
    stop_event = threading.Event()
    heartbeat_errors: list[str] = []

    def refresh_heartbeat() -> None:
        interval = scheduler_job_heartbeat_interval(poll_interval_seconds)
        while not stop_event.wait(interval):
            try:
                write_scheduler_heartbeat(
                    run_dir,
                    worker_id=worker_id,
                    iteration=iteration,
                    status="running-job",
                    current_job_id=job_id,
                )
                if claim is not None:
                    refresh_claim_lease(claim, root=root)
            except Exception as exc:  # pragma: no cover - defensive diagnostic path.
                heartbeat_errors.append(str(exc))
                return

    heartbeat_thread = threading.Thread(
        target=refresh_heartbeat,
        name=f"harness-heartbeat-{job_id}",
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        return execute_generic_agent_job(
            run_dir,
            job_id,
            worker_id=worker_id,
            root=root,
            claim=claim,
        )
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=1)
        if heartbeat_errors:
            append_scheduler_event(
                run_dir,
                "heartbeat_write_failed",
                {
                    "worker_id": worker_id,
                    "job_id": job_id,
                    "errors": heartbeat_errors,
                },
            )


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
    append_scheduler_event(
        resolved_run_dir,
        "worker_started",
        {"worker_id": active_worker_id},
    )

    started_monotonic = monotonic_fn()
    iteration = 0
    executed_jobs: list[str] = []
    skipped_jobs: list[str] = []
    seen_skipped_jobs: set[str] = set()
    stop_reason = "unknown"

    try:
        stop_loop = False
        while not stop_loop:
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

            stop_requested, stop_payload, stop_errors = scheduler_stop_requested(
                resolved_run_dir,
            )
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
            jobs, job_errors = load_scheduler_jobs_for_watch(
                resolved_run_dir,
                root=repo_root,
            )
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
                    {
                        "worker_id": active_worker_id,
                        "iteration": iteration,
                        "errors": job_errors,
                    },
                )
                sleep_fn(poll_interval_seconds)
                continue

            ordered_jobs = sorted(jobs, key=lambda job: (job["created_at"], job["job_id"]))
            queued_jobs = [job for job in ordered_jobs if job["status"] == "queued"]
            for job in ordered_jobs:
                job_id = job["job_id"]
                status = job["status"]
                if (
                    status == "running" or status in TERMINAL_JOB_STATUSES
                ) and job_id not in seen_skipped_jobs and job_id not in executed_jobs:
                    skipped_jobs.append(job_id)
                    seen_skipped_jobs.add(job_id)
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
                    {
                        "worker_id": active_worker_id,
                        "iteration": iteration,
                        "executed_jobs": [],
                    },
                )
                sleep_fn(poll_interval_seconds)
                continue

            executed_this_iteration: list[str] = []
            for job in queued_jobs:
                job_id = job["job_id"]
                claim = try_claim_job(
                    resolved_run_dir,
                    job_id,
                    worker_id=active_worker_id,
                    root=repo_root,
                )
                if claim is None:
                    if job_id not in seen_skipped_jobs and job_id not in executed_jobs:
                        skipped_jobs.append(job_id)
                        seen_skipped_jobs.add(job_id)
                    append_scheduler_event(
                        resolved_run_dir,
                        "job_claim_skipped",
                        {
                            "worker_id": active_worker_id,
                            "iteration": iteration,
                            "job_id": job_id,
                        },
                    )
                    continue
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
                executed_job = execute_claimed_generic_agent_job(
                    resolved_run_dir,
                    claim,
                    iteration=iteration,
                    poll_interval_seconds=poll_interval_seconds,
                    root=repo_root,
                )
                executed_jobs.append(job_id)
                executed_this_iteration.append(job_id)
                append_scheduler_event(
                    resolved_run_dir,
                    "job_completed",
                    {
                        "worker_id": active_worker_id,
                        "job_id": job_id,
                        "status": executed_job["status"],
                    },
                )
                stop_requested, stop_payload, stop_errors = scheduler_stop_requested(
                    resolved_run_dir,
                )
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
                    stop_loop = True
                    break

            if stop_loop:
                continue

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
                {
                    "worker_id": active_worker_id,
                    "iteration": iteration,
                    "executed_jobs": executed_this_iteration,
                },
            )
            sleep_fn(poll_interval_seconds)
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
        {
            "worker_id": active_worker_id,
            "iteration": iteration,
            "stop_reason": stop_reason,
        },
    )
    return {
        "run_id": state["run_id"],
        "worker_id": active_worker_id,
        "iterations": iteration,
        "executed_jobs": executed_jobs,
        "skipped_jobs": skipped_jobs,
        "stop_reason": stop_reason,
    }


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
        key=lambda job: job["job_id"],
    )
    aggregation: dict[str, Any] = {
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
    status_buckets = {
        "succeeded": "succeeded_jobs",
        "failed": "failed_jobs",
        "timeout": "timeout_jobs",
        "cancelled": "cancelled_jobs",
    }

    for job in jobs:
        job_id = job["job_id"]
        status = job["status"]
        if status not in TERMINAL_JOB_STATUSES:
            aggregation["incomplete_jobs"].append(job_id)
            continue

        aggregation["consumed_jobs"].append(job_id)
        aggregation[status_buckets[status]].append(job_id)

        output_file = job.get("output_file")
        if not isinstance(output_file, str) or not output_file.strip():
            aggregation["residual_risks"].append(
                f"job {job_id} terminal output is missing or invalid: output_file",
            )
            continue

        job_dir = resolved_run_dir / "jobs" / job_id
        raw_output_path = Path(output_file)
        output_path = raw_output_path if raw_output_path.is_absolute() else job_dir / raw_output_path
        output_path = output_path.resolve(strict=False)
        if not is_within_path(output_path, job_dir.resolve(strict=False)):
            aggregation["residual_risks"].append(
                f"job {job_id} terminal output is invalid: {output_file}",
            )
            continue
        if not output_path.exists():
            aggregation["residual_risks"].append(
                f"job {job_id} terminal output is missing: {output_file}",
            )
            continue

        agent_result, result_errors = validate_json_artifact(
            output_path,
            AGENT_RESULT_SCHEMA,
            "agent-result",
        )
        if result_errors:
            aggregation["residual_risks"].append(
                f"job {job_id} terminal output is invalid: {output_file}: "
                f"{'; '.join(result_errors)}",
            )
            continue
        if agent_result is None:
            aggregation["residual_risks"].append(
                f"job {job_id} terminal output could not be loaded: {output_file}",
            )
            continue

        result_contract_errors = validate_agent_result_matches_job(agent_result, job)
        if result_contract_errors:
            aggregation["residual_risks"].append(
                f"job {job_id} terminal output is invalid: {output_file}: "
                f"{'; '.join(result_contract_errors)}",
            )
            continue

        for finding in agent_result["findings"]:
            aggregation["findings"].append(
                {
                    "job_id": job_id,
                    "severity": finding["severity"],
                    "title": finding["title"],
                    "evidence": finding["evidence"],
                    "recommendation": finding["recommendation"],
                }
            )
        aggregation["residual_risks"].extend(agent_result["residual_risks"])

    aggregation_path = resolved_run_dir / "jobs" / "aggregation.json"
    write_json_file(aggregation_path, aggregation)
    return aggregation


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
        command=command,
        adapter=adapter,
        timeout_seconds=timeout_seconds,
        root=root,
    )
    return execute_generic_agent_job(run_dir, job_id, root=root)


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
        str(resolved_run_dir.resolve(strict=False)),
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


def run_agent_subprocess(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
) -> tuple[int, str | None, str | None]:
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        terminate_process_tree(process)
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            exc.cmd,
            exc.timeout,
            output=stdout,
            stderr=stderr,
        ) from exc
    return process.returncode, stdout, stderr


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def validate_agent_result_matches_job(
    agent_result: dict[str, Any],
    job: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    for field in ("run_id", "job_id", "agent", "adapter"):
        if agent_result.get(field) != job.get(field):
            errors.append(
                f"agent-result {field} {agent_result.get(field)} "
                f"does not match job {field} {job.get(field)}",
            )
    return errors


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, payload)


def output_to_text(value: str | bytes | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


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
        ],
    )
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise HarnessCliError(f"raw_log_file already exists: {path}") from exc


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temp_path: Path | None = None
    replaced = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            dir=path.parent,
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(json.dumps(payload, indent=2) + "\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())

        retry_seconds = ATOMIC_REPLACE_RETRY_SECONDS
        for attempt in range(ATOMIC_REPLACE_ATTEMPTS):
            try:
                temp_path.replace(path)
                break
            except PermissionError:
                if attempt + 1 == ATOMIC_REPLACE_ATTEMPTS:
                    raise
                time.sleep(retry_seconds)
                retry_seconds *= 2
        replaced = True
    except OSError as exc:
        raise HarnessCliError(f"failed to write {path} atomically: {exc}") from exc
    finally:
        if temp_path is not None:
            try:
                if not replaced:
                    temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def utc_now() -> str:
    return format_datetime(datetime.now(timezone.utc))


def format_errors(errors: Iterable[str]) -> str:
    return "\n".join(errors)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and advance Harness runs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate a Harness run directory.")
    validate.add_argument("run_dir")

    check_ready_parser = subparsers.add_parser(
        "check-ready",
        help="Report non-mutating Phase 2 readiness warnings for a Harness run.",
    )
    check_ready_parser.add_argument("run_dir")

    index_evidence_parser = subparsers.add_parser(
        "index-evidence",
        help="Append an evidence entry after existing validation accepts it.",
    )
    index_evidence_parser.add_argument("run_dir")
    index_evidence_parser.add_argument("evidence_type")
    index_evidence_parser.add_argument("path")
    index_evidence_parser.add_argument("--description")

    init_run_parser = subparsers.add_parser(
        "init-run",
        help="Create a draft Harness run with Phase 2 run documents.",
    )
    init_run_parser.add_argument("run_dir")
    init_run_parser.add_argument("--run-id", required=True)
    init_run_parser.add_argument("--track", required=True, choices=["Fast", "Standard", "Strict"])
    init_run_parser.add_argument("--workflow", required=True)
    init_run_parser.add_argument("--base-commit", default="HEAD")

    advance = subparsers.add_parser("advance", help="Advance a Harness run status.")
    advance.add_argument("run_dir")
    advance.add_argument("status")
    advance.add_argument("--actor", default=CODEX_ACTOR)

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

    scheduler = subparsers.add_parser(
        "run-scheduler",
        help="Run the local async scheduler for queued jobs.",
    )
    scheduler.add_argument("run_dir")
    scheduler_mode = scheduler.add_mutually_exclusive_group(required=True)
    scheduler_mode.add_argument("--once", action="store_true")
    scheduler_mode.add_argument("--watch", action="store_true")
    scheduler.add_argument("--poll-interval-seconds", type=float, default=5.0)
    scheduler.add_argument("--max-iterations", type=int)
    scheduler.add_argument("--max-seconds", type=float)
    scheduler.add_argument("--worker-id")

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

    detect_stale_parser = subparsers.add_parser(
        "detect-stale-jobs",
        help="Classify running jobs as active, recent, stale, or invalid.",
    )
    detect_stale_parser.add_argument("run_dir")
    detect_stale_parser.add_argument("--heartbeat-timeout-seconds", type=float, required=True)

    recover_stale_parser = subparsers.add_parser(
        "recover-stale-job",
        help="Explicitly requeue or fail one stale running job with an audit artifact.",
    )
    recover_stale_parser.add_argument("run_dir")
    recover_stale_parser.add_argument("job_id")
    recover_stale_parser.add_argument("--action", choices=["requeue", "fail"], required=True)
    recover_stale_parser.add_argument("--reason", required=True)
    recover_stale_parser.add_argument("--heartbeat-timeout-seconds", type=float, required=True)
    recover_stale_parser.add_argument("--confirm", action="store_true")
    recover_stale_parser.add_argument("--confirm-artifact-correction", action="store_true")

    aggregate = subparsers.add_parser(
        "aggregate-jobs",
        help="Write jobs/aggregation.json for a Harness run.",
    )
    aggregate.add_argument("run_dir")

    generic = subparsers.add_parser(
        "run-generic-agent",
        help="Run a generic CLI agent as a run-local async job.",
    )
    generic.add_argument("run_dir")
    generic.add_argument("job_id")
    generic.add_argument("--agent", required=True)
    generic.add_argument("--adapter", default="generic-cli-agent")
    generic.add_argument("--timeout-seconds", type=int, default=1800)
    generic.add_argument("agent_command", nargs=argparse.REMAINDER)

    return parser


def _normalize_queue_generic_agent_argv(
    argv: list[str],
    parser: argparse.ArgumentParser,
) -> list[str]:
    if not argv or argv[0] != "queue-generic-agent" or "--" not in argv:
        return argv

    separator = argv.index("--")
    before_separator = argv[1:separator]
    if len(before_separator) < 2:
        return argv

    run_dir = before_separator[0]
    job_id = before_separator[1]
    tail = before_separator[2:]
    options: list[str] = []
    remainder: list[str] = []
    option_names = {"--agent", "--adapter", "--timeout-seconds"}
    index = 0
    while index < len(tail):
        token = tail[index]
        if token in option_names:
            if index + 1 >= len(tail) or tail[index + 1].startswith("--"):
                parser.error(f"argument {token}: expected one argument")
            options.extend([token, tail[index + 1]])
            index += 2
            continue
        if any(token.startswith(f"{option_name}=") for option_name in option_names):
            options.append(token)
            index += 1
            continue
        remainder.append(token)
        index += 1

    return [argv[0], *options, run_dir, job_id, *remainder, *argv[separator:]]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = _normalize_queue_generic_agent_argv(
        list(sys.argv[1:] if argv is None else argv),
        parser,
    )
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            result = validate_run(args.run_dir)
            if not result.ok:
                print(format_errors(result.errors))
                return 1
            print(f"valid: {result.run_dir}")
            return 0

        if args.command == "check-ready":
            report = check_ready(args.run_dir)
            if report.warnings:
                print(format_errors(report.warnings))
                return 1
            print("ready: no readiness warnings")
            return 0

        if args.command == "index-evidence":
            state = index_evidence(
                args.run_dir,
                args.evidence_type,
                args.path,
                description=args.description,
            )
            print(f"indexed evidence: {state['run_id']} {args.evidence_type} {args.path}")
            return 0

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

        if args.command == "advance":
            state = advance_run(args.run_dir, args.status, actor=args.actor)
            print(f"advanced: {state['run_id']} -> {state['status']}")
            return 0

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
            print(
                f"queued cross-run job: "
                f"{entry['queue_id']}/{entry['entry_id']} -> "
                f"{entry['run_id']}/{entry['job_id']}",
            )
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

        if args.command == "run-scheduler":
            if args.once:
                summary = scheduler_run_once(args.run_dir, worker_id=args.worker_id)
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
            print(
                f"stop requested: "
                f"{load_json(state_path(Path(args.run_dir)))['run_id']} "
                f"{stop['reason']}",
            )
            return 0

        if args.command == "detect-stale-jobs":
            report = detect_stale_running_jobs(
                args.run_dir,
                heartbeat_timeout_seconds=args.heartbeat_timeout_seconds,
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0

        if args.command == "recover-stale-job":
            recovery = recover_stale_running_job(
                args.run_dir,
                args.job_id,
                action=args.action,
                reason=args.reason,
                heartbeat_timeout_seconds=args.heartbeat_timeout_seconds,
                confirm=args.confirm,
                artifact_correction_confirmed=args.confirm_artifact_correction,
            )
            print(
                f"recovered stale job: "
                f"{recovery['artifact']['run_id']}/{args.job_id} "
                f"action={args.action} artifact={recovery['path']}",
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

        if args.command == "run-generic-agent":
            command = args.agent_command
            if command and command[0] == "--":
                command = command[1:]
            job = run_generic_agent(
                args.run_dir,
                args.job_id,
                agent=args.agent,
                adapter=args.adapter,
                command=command,
                timeout_seconds=args.timeout_seconds,
            )
            print(f"generic-agent: {job['run_id']}/{job['job_id']} -> {job['status']}")
            return 0
    except HarnessCliError as exc:
        print(str(exc))
        return 1

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
