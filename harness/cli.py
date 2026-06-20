from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
STATE_SCHEMA = ROOT / "harness" / "schemas" / "state.schema.json"
CODEX_ACTOR = "codex"
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
JOB_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "timeout", "cancelled"})
TERMINAL_JOB_STATUSES = frozenset({"succeeded", "failed", "timeout", "cancelled"})

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
    errors.extend(validate_evidence_paths(state, root=root, run_dir=run_dir))
    errors.extend(validate_job_evidence(state, root=root, run_dir=run_dir))
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
    errors: list[str] = []
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

        status = job.get("status")
        if status not in TERMINAL_JOB_STATUSES:
            errors.append(
                f"non-terminal job cannot be consumed at evidence[{index}]: {status}",
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


def is_within_path(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


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

    advance = subparsers.add_parser("advance", help="Advance a Harness run status.")
    advance.add_argument("run_dir")
    advance.add_argument("status")
    advance.add_argument("--actor", default=CODEX_ACTOR)

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

        if args.command == "advance":
            state = advance_run(args.run_dir, args.status, actor=args.actor)
            print(f"advanced: {state['run_id']} -> {state['status']}")
            return 0
    except HarnessCliError as exc:
        print(str(exc))
        return 1

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
