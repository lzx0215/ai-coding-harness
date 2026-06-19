from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
STATE_SCHEMA = ROOT / "harness" / "schemas" / "state.schema.json"
CODEX_ACTOR = "codex"

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
    except json.JSONDecodeError as exc:
        return ValidationResult(resolved_run_dir, [f"invalid state JSON: {exc}"])

    errors.extend(validate_state(state, root=root, run_dir=resolved_run_dir))

    return ValidationResult(resolved_run_dir, errors)


def validate_state(
    state: dict[str, Any],
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

    errors.extend(validate_evidence_paths(state, root=root, run_dir=run_dir))
    return errors


def validate_evidence_paths(
    state: dict[str, Any],
    *,
    root: Path,
    run_dir: Path,
) -> list[str]:
    errors: list[str] = []
    for index, evidence in enumerate(state.get("evidence", [])):
        raw_path = evidence.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue

        evidence_path = Path(raw_path)
        candidates = [evidence_path]
        if not evidence_path.is_absolute():
            candidates = [root / evidence_path, run_dir / evidence_path]

        if not any(candidate.exists() for candidate in candidates):
            errors.append(f"evidence path does not exist at evidence[{index}]: {raw_path}")

    return errors


def can_transition(current_status: str, next_status: str) -> bool:
    return next_status in ALLOWED_TRANSITIONS.get(current_status, set())


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
    state = load_json(path)
    current_status = state["status"]
    if not can_transition(current_status, next_status):
        raise HarnessCliError(
            f"invalid transition: {current_status} -> {next_status}",
        )

    candidate = dict(state)
    candidate["status"] = next_status
    candidate["updated_at"] = utc_now()
    candidate_errors = validate_state(candidate, root=root, run_dir=resolved_run_dir)
    if candidate_errors:
        raise HarnessCliError(format_errors(candidate_errors))

    path.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")

    return candidate


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
