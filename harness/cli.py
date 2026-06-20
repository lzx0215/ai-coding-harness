from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator

from harness import readiness


ROOT = Path(__file__).resolve().parents[1]
STATE_SCHEMA = ROOT / "harness" / "schemas" / "state.schema.json"
CODEX_ACTOR = "codex"
GENERIC_ADAPTER_VERSION = "0.1.0"
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
    }
)
REVIEW_COMPLETION_EVIDENCE_TYPES = frozenset(
    {"review", "review-evidence", "review-waiver"},
)
COMPLETION_REQUIRED_EVIDENCE_TYPES = frozenset({"verification", "handoff"})
JOB_SCHEMA = ROOT / "harness" / "schemas" / "job.schema.json"
AGGREGATION_SCHEMA = ROOT / "harness" / "schemas" / "aggregation.schema.json"
AGENT_RESULT_SCHEMA = ROOT / "harness" / "schemas" / "agent-result.schema.json"
TERMINAL_JOB_STATUSES = frozenset({"succeeded", "failed", "timeout", "cancelled"})
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


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def state_path(run_dir: Path) -> Path:
    return run_dir / "state.json"


def validate_run(run_dir: Path | str, *, root: Path = ROOT) -> ValidationResult:
    resolved_run_dir = Path(run_dir)
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

    errors.extend(validate_state(state, root=root, run_dir=resolved_run_dir))

    return ValidationResult(resolved_run_dir, errors)


def validate_state(
    state: Any,
    *,
    root: Path = ROOT,
    run_dir: Path,
    validate_paths: bool = True,
) -> list[str]:
    errors: list[str] = []
    schema = load_json(root / "harness" / "schemas" / "state.schema.json")
    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(state), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.path) or "<root>"
        errors.append(f"schema error at {location}: {error.message}")

    if not isinstance(state, dict):
        return errors

    errors.extend(validate_evidence_types(state))
    if validate_paths:
        errors.extend(validate_evidence_paths(state, root=root, run_dir=run_dir))
    indexed_jobs, job_errors = load_indexed_job_evidence(
        state,
        root=root,
        run_dir=run_dir,
    )
    errors.extend(job_errors)
    errors.extend(validate_indexed_job_evidence(state, indexed_jobs))
    errors.extend(
        validate_agent_result_evidence(
            state,
            root=root,
            run_dir=run_dir,
            indexed_jobs=indexed_jobs,
        )
    )
    errors.extend(
        validate_aggregation_evidence(
            state,
            root=root,
            run_dir=run_dir,
            indexed_jobs=indexed_jobs,
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

    if created_at is None:
        errors.append("job requires created_at")
    elif parse_datetime(created_at) is None:
        errors.append("created_at must be a valid ISO 8601 timestamp")
    if started_at is not None and parse_datetime(started_at) is None:
        errors.append("started_at must be a valid ISO 8601 timestamp")
    if completed_at is not None and parse_datetime(completed_at) is None:
        errors.append("completed_at must be a valid ISO 8601 timestamp")

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
    if created_dt is not None and started_dt is not None and started_dt < created_dt:
        errors.append("started_at must be on or after created_at")
    if started_dt is not None and completed_dt is not None and completed_dt < started_dt:
        errors.append("completed_at must be on or after started_at")
    if created_dt is not None and completed_dt is not None and completed_dt < created_dt:
        errors.append("completed_at must be on or after created_at")

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
            f"job id {job_id} has no terminal or incomplete classification",
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


def advance_run(
    run_dir: Path | str,
    next_status: str,
    *,
    actor: str = CODEX_ACTOR,
    root: Path = ROOT,
) -> dict[str, Any]:
    if actor != CODEX_ACTOR:
        raise HarnessCliError("only codex may advance harness run state")

    resolved_run_dir = Path(run_dir)
    before = validate_run(resolved_run_dir, root=root)
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

    completion_errors = validate_completion_evidence(state, next_status)
    if completion_errors:
        raise HarnessCliError(format_errors(completion_errors))

    candidate = dict(state)
    candidate["status"] = next_status
    candidate["updated_at"] = utc_now()
    candidate_errors = validate_state(candidate, root=root, run_dir=resolved_run_dir)
    if candidate_errors:
        raise HarnessCliError(format_errors(candidate_errors))

    write_json_atomic(path, candidate)

    return candidate


def check_ready(run_dir: Path | str, *, root: Path = ROOT) -> readiness.ReadinessReport:
    resolved_run_dir = Path(run_dir)
    validation = validate_run(resolved_run_dir, root=root)
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
    root: Path = ROOT,
) -> dict[str, Any]:
    resolved_run_dir = Path(run_dir)
    validation = validate_run(resolved_run_dir, root=root)
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

    candidate_errors = validate_state(candidate, root=root, run_dir=resolved_run_dir)
    if candidate_errors:
        raise HarnessCliError(format_errors(candidate_errors))

    write_json_atomic(path, candidate)
    return candidate


TEMPLATE_DIR = ROOT / "harness" / "templates"


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
    root: Path = ROOT,
) -> dict[str, Any]:
    resolved_run_dir = Path(run_dir)
    if resolved_run_dir.exists():
        raise HarnessCliError(f"run directory already exists: {resolved_run_dir}")

    created_at = utc_now()
    state = {
        "run_id": run_id,
        "harness_version": "0.2.0",
        "state_schema_version": "0.2.0",
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
        root=root,
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
        validation = validate_run(resolved_run_dir, root=root)
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


def run_generic_agent(
    run_dir: Path | str,
    job_id: str,
    *,
    agent: str,
    command: list[str],
    adapter: str = "generic-cli-agent",
    timeout_seconds: int = 1800,
    root: Path = ROOT,
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
    before = validate_run(resolved_run_dir, root=root)
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

    job["status"] = "running"
    job["started_at"] = utc_now()
    write_json_file(job_path, job)

    env = os.environ.copy()
    env.update(
        {
            "HARNESS_RUN_ID": run_id,
            "HARNESS_JOB_ID": job_id,
            "HARNESS_AGENT": agent,
            "HARNESS_AGENT_ADAPTER": adapter,
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
    path.write_text(
        "\n".join(
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
        ),
        encoding="utf-8",
    )


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temp_path: Path | None = None
    replaced = False
    try:
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

        temp_path.replace(path)
        replaced = True
    except OSError as exc:
        raise HarnessCliError(f"failed to write state atomically: {exc}") from exc
    finally:
        if temp_path is not None:
            try:
                if not replaced:
                    temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
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
