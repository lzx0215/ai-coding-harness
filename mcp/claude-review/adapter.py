from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ADAPTER_VERSION = "0.1.0"
DEFAULT_VERSION = "0.1.0"
REVIEWER = "claude-code"
UNKNOWN = "unknown"

SUCCESS_STATUSES = {"passed", "findings"}
TERMINAL_STATUSES = {
    "passed",
    "findings",
    "failed",
    "timeout",
    "schema_invalid",
    "not_available",
}
ALLOWED_REASONS = {
    "tool_missing",
    "auth_missing",
    "input_over_budget",
    "no_review_target",
    "unsupported_environment",
    "wrapper_failed_to_start",
}
ALLOWED_SEVERITIES = {"info", "low", "medium", "high", "critical"}
REVIEW_SYSTEM_PROMPT = (
    "You are a JSON-only read-only code review function. "
    "Use only the review target embedded in the user prompt. "
    "Do not inspect the repository, do not ask follow-up questions, and do not "
    "modify files. Return a JSON object matching the provided schema."
)
WRITE_PATH_KEYS = ("output_file", "review_file", "raw_log_file")
PROMPT_INPUT_FILE_KEYS = (
    "task_file",
    "plan_file",
    "diff_file",
    "diff_meta_file",
    "changed_files_file",
    "verification_file",
)


class ReviewSchemaError(ValueError):
    """Raised when Claude output cannot be normalized into the review contract."""


@dataclass(frozen=True)
class ArtifactPaths:
    artifact_dir: Path
    output_file: Path
    review_file: Path
    raw_log_file: Path


@dataclass(frozen=True)
class PathSafety:
    artifact_dir: Path
    resolved_paths: dict[str, Path]
    unsafe_keys: tuple[str, ...]

    @property
    def all_safe(self) -> bool:
        return not self.unsafe_keys

    def safe_path(self, key: str) -> Path | None:
        if key in self.unsafe_keys:
            return None
        return self.resolved_paths.get(key)

    def artifact_paths(self) -> ArtifactPaths:
        if self.unsafe_keys:
            raise ValueError("artifact paths are not all safe")
        return ArtifactPaths(
            artifact_dir=self.artifact_dir,
            output_file=self.resolved_paths["output_file"],
            review_file=self.resolved_paths["review_file"],
            raw_log_file=self.resolved_paths["raw_log_file"],
        )


def count_lines(path: Path | str) -> int:
    resolved = Path(path)
    if not resolved.exists():
        return 0
    return len(resolved.read_text(encoding="utf-8", errors="replace").splitlines())


def check_budget(payload: dict[str, Any]) -> str | None:
    diff_file = Path(str(payload.get("diff_file", "")))
    changed_files_file = Path(str(payload.get("changed_files_file", "")))
    max_diff_lines = int(payload.get("max_diff_lines", 2000))
    max_files = int(payload.get("max_files", 30))
    max_input_chars = int(payload.get("max_input_chars", 120000))

    changed_file_count = count_lines(changed_files_file)
    diff_text = read_text(diff_file)
    input_chars = sum(len(read_text(str(payload.get(key, "")))) for key in PROMPT_INPUT_FILE_KEYS)

    if changed_file_count > max_files:
        return "input_over_budget"
    if len(diff_text.splitlines()) > max_diff_lines:
        return "input_over_budget"
    if input_chars > max_input_chars:
        return "input_over_budget"
    return None


def read_text(path: Path | str) -> str:
    resolved = Path(path)
    if not resolved.exists():
        return ""
    return resolved.read_text(encoding="utf-8", errors="replace")


def resolve_path(path: Path | str) -> Path:
    return Path(path).resolve(strict=False)


def is_path_under(path: Path | str, directory: Path | str) -> bool:
    resolved_path = resolve_path(path)
    resolved_directory = resolve_path(directory)
    return resolved_path == resolved_directory or resolved_directory in resolved_path.parents


def inspect_artifact_paths(payload: dict[str, Any]) -> PathSafety:
    artifact_dir_value = payload.get("artifact_dir")
    artifact_dir_missing = (
        not isinstance(artifact_dir_value, str) or not artifact_dir_value.strip()
    )
    artifact_dir = Path() if artifact_dir_missing else resolve_path(artifact_dir_value)
    resolved_paths: dict[str, Path] = {}
    unsafe_keys: list[str] = []

    if artifact_dir_missing:
        unsafe_keys.extend(("artifact_dir", *WRITE_PATH_KEYS))

    for key in WRITE_PATH_KEYS:
        value = payload.get(key)
        if not value:
            unsafe_keys.append(key)
            continue
        resolved = resolve_path(str(value))
        resolved_paths[key] = resolved
        if not artifact_dir_missing and not is_path_under(resolved, artifact_dir):
            unsafe_keys.append(key)

    return PathSafety(
        artifact_dir=artifact_dir,
        resolved_paths=resolved_paths,
        unsafe_keys=tuple(unsafe_keys),
    )


def build_envelope(
    payload: dict[str, Any],
    status: str,
    *,
    started: float | None = None,
    duration_seconds: float | None = None,
    reason: str | None = None,
    exit_code: int | None = None,
    paths: ArtifactPaths | None = None,
    resolved_paths: dict[str, Path] | None = None,
    review_data: dict[str, Any] | None = None,
    reviewer_model: str = UNKNOWN,
    reviewer_model_version: str = UNKNOWN,
    reviewer_cli_version: str = UNKNOWN,
) -> dict[str, Any]:
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"unsupported status: {status}")
    if reason is not None and reason not in ALLOWED_REASONS:
        raise ValueError(f"unsupported reason: {reason}")

    if duration_seconds is None:
        duration_seconds = 0.0
        if started is not None:
            duration_seconds = time.monotonic() - started

    output_path = _envelope_path(payload, "output_file", paths, resolved_paths)
    raw_log_path = _envelope_path(payload, "raw_log_file", paths, resolved_paths)

    envelope: dict[str, Any] = {
        "status": status,
        "run_id": str(payload.get("run_id", "")),
        "completed": status in SUCCESS_STATUSES,
        "harness_version": _nonempty_string(payload.get("harness_version"), DEFAULT_VERSION),
        "adapter_version": ADAPTER_VERSION,
        "prompt_version": _nonempty_string(payload.get("prompt_version"), DEFAULT_VERSION),
        "reviewer": REVIEWER,
        "reviewer_model": _nonempty_string(reviewer_model, UNKNOWN),
        "reviewer_model_version": _nonempty_string(reviewer_model_version, UNKNOWN),
        "reviewer_cli_version": _nonempty_string(reviewer_cli_version, UNKNOWN),
        "output_file": output_path,
        "raw_log_file": raw_log_path,
        "exit_code": exit_code,
        "duration_seconds": round(max(duration_seconds, 0.0), 3),
    }

    if reason is not None:
        envelope["reason"] = reason

    if review_data is not None:
        review_file = _envelope_path(payload, "review_file", paths, resolved_paths)
        envelope["review_file"] = review_file
        envelope.update(review_data)

    return envelope


def normalize_claude_json(
    parsed: dict[str, Any],
    payload: dict[str, Any],
    *,
    output_file: Path | str | None = None,
    review_file: Path | str | None = None,
    raw_log_file: Path | str | None = None,
    duration_seconds: float = 0.0,
    exit_code: int | None = 0,
) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise ReviewSchemaError("Claude stdout JSON must be an object")

    content = _extract_review_content(parsed)
    review_data = _normalize_review_data(content)
    status = "findings" if review_data["findings"] else "passed"
    path_overrides = _path_overrides(
        output_file=output_file,
        review_file=review_file,
        raw_log_file=raw_log_file,
    )
    envelope = build_envelope(
        payload,
        status,
        duration_seconds=duration_seconds,
        exit_code=exit_code,
        resolved_paths=path_overrides,
        review_data=review_data,
        reviewer_model=_metadata_value(parsed, content, "reviewer_model", "model"),
        reviewer_model_version=_metadata_value(
            parsed,
            content,
            "reviewer_model_version",
            "model_version",
        ),
        reviewer_cli_version=_metadata_value(
            parsed,
            content,
            "reviewer_cli_version",
            "cli_version",
        ),
    )
    _validate_success_envelope(envelope)
    return envelope


def run_claude_review(payload: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    path_safety = inspect_artifact_paths(payload)
    if not path_safety.all_safe:
        envelope = build_envelope(
            payload,
            "not_available",
            started=started,
            reason="unsupported_environment",
            resolved_paths=path_safety.resolved_paths,
        )
        _write_failure_artifacts(
            path_safety,
            envelope,
            "Rejected unsafe artifact path outside artifact_dir.\n",
        )
        return envelope

    paths = path_safety.artifact_paths()
    budget_reason = check_budget(payload)
    if budget_reason is not None:
        envelope = build_envelope(
            payload,
            "not_available",
            started=started,
            reason=budget_reason,
            paths=paths,
        )
        _write_failure_artifacts(
            path_safety,
            envelope,
            "Review input exceeded configured budget.\n",
        )
        return envelope

    claude_executable = shutil.which("claude")
    if claude_executable is None:
        envelope = build_envelope(
            payload,
            "not_available",
            started=started,
            reason="tool_missing",
            paths=paths,
        )
        _write_failure_artifacts(
            path_safety,
            envelope,
            "Claude CLI was not found on PATH.\n",
        )
        return envelope

    prompt = build_review_prompt(payload)
    command = [
        claude_executable,
        "-p",
        "--output-format",
        "json",
        "--system-prompt",
        REVIEW_SYSTEM_PROMPT,
        "--json-schema",
        review_content_json_schema(),
        "--permission-mode",
        "plan",
        "--tools",
        "",
        "--no-session-persistence",
        "--max-budget-usd",
        "1",
    ]

    try:
        completed = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=int(payload.get("timeout_seconds", 900)),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raw_log = _combined_raw_log(exc.stdout, exc.stderr)
        envelope = build_envelope(
            payload,
            "timeout",
            started=started,
            paths=paths,
            exit_code=None,
        )
        _write_failure_artifacts(path_safety, envelope, raw_log)
        return envelope
    except OSError as exc:
        envelope = build_envelope(
            payload,
            "not_available",
            started=started,
            reason="wrapper_failed_to_start",
            paths=paths,
            exit_code=None,
        )
        _write_failure_artifacts(path_safety, envelope, f"{type(exc).__name__}: {exc}\n")
        return envelope

    raw_log = _combined_raw_log(completed.stdout, completed.stderr)
    paths.raw_log_file.parent.mkdir(parents=True, exist_ok=True)
    paths.raw_log_file.write_text(raw_log, encoding="utf-8")

    if completed.returncode != 0:
        if output_indicates_auth_missing(raw_log):
            envelope = build_envelope(
                payload,
                "not_available",
                started=started,
                reason="auth_missing",
                paths=paths,
                exit_code=completed.returncode,
            )
        else:
            envelope = build_envelope(
                payload,
                "failed",
                started=started,
                paths=paths,
                exit_code=completed.returncode,
            )
        _write_json(paths.output_file, envelope)
        return envelope

    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError:
        envelope = build_envelope(
            payload,
            "schema_invalid",
            started=started,
            paths=paths,
            exit_code=completed.returncode,
        )
        _write_json(paths.output_file, envelope)
        return envelope

    duration_seconds = time.monotonic() - started
    try:
        envelope = normalize_claude_json(
            parsed,
            payload,
            output_file=paths.output_file,
            review_file=paths.review_file,
            raw_log_file=paths.raw_log_file,
            duration_seconds=duration_seconds,
            exit_code=completed.returncode,
        )
    except ReviewSchemaError:
        envelope = build_envelope(
            payload,
            "schema_invalid",
            duration_seconds=duration_seconds,
            paths=paths,
            exit_code=completed.returncode,
        )
        _write_json(paths.output_file, envelope)
        return envelope

    _write_json(paths.review_file, build_review_evidence(envelope))
    _write_json(paths.output_file, envelope)
    return envelope


def build_review_prompt(payload: dict[str, Any]) -> str:
    task_text = read_text(payload.get("task_file", ""))
    plan_text = read_text(payload.get("plan_file", ""))
    diff_text = read_text(payload.get("diff_file", ""))
    diff_meta_text = read_text(payload.get("diff_meta_file", ""))
    changed_files_text = read_text(payload.get("changed_files_file", ""))
    verification_text = read_text(payload.get("verification_file", ""))
    review_scope = payload.get("review_scope", [])

    return "\n".join(
        [
            "The review target is fully embedded below. Do not use repository state.",
            "Do not ask follow-up questions. If evidence is insufficient, record it in not_tested or residual_risks.",
            "Return only JSON with keys: summary, findings, tested, not_tested, residual_risks.",
            "Each finding must include severity, title, evidence, and recommendation.",
            "Allowed severities: info, low, medium, high, critical.",
            f"Run ID: {payload.get('run_id', '')}",
            f"Review scope: {json.dumps(review_scope)}",
            "",
            "TASK_FILE:",
            str(payload.get("task_file", "")),
            "TASK_CONTENT:",
            task_text,
            "",
            "PLAN_FILE:",
            str(payload.get("plan_file", "")),
            "PLAN_CONTENT:",
            plan_text,
            "",
            "DIFF_META_FILE:",
            str(payload.get("diff_meta_file", "")),
            "DIFF_META_CONTENT:",
            diff_meta_text,
            "",
            "CHANGED_FILES_FILE:",
            str(payload.get("changed_files_file", "")),
            "CHANGED_FILES_CONTENT:",
            changed_files_text,
            "",
            "VERIFICATION_FILE:",
            str(payload.get("verification_file", "")),
            "VERIFICATION_CONTENT:",
            verification_text,
            "",
            "DIFF_FILE:",
            str(payload.get("diff_file", "")),
            "DIFF_CONTENT:",
            diff_text,
        ]
    )


def review_content_json_schema() -> str:
    return json.dumps(
        {
            "type": "object",
            "required": [
                "summary",
                "findings",
                "tested",
                "not_tested",
                "residual_risks",
            ],
            "properties": {
                "summary": {"type": "string", "minLength": 1},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "severity",
                            "title",
                            "evidence",
                            "recommendation",
                        ],
                        "properties": {
                            "severity": {
                                "type": "string",
                                "enum": sorted(ALLOWED_SEVERITIES),
                            },
                            "title": {"type": "string", "minLength": 1},
                            "evidence": {"type": "string", "minLength": 1},
                            "recommendation": {"type": "string", "minLength": 1},
                            "file": {"type": "string", "minLength": 1},
                            "line": {"type": "integer", "minimum": 1},
                        },
                        "additionalProperties": False,
                    },
                },
                "tested": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "not_tested": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "residual_risks": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
            },
            "additionalProperties": False,
        },
        separators=(",", ":"),
    )


def build_review_evidence(envelope: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": envelope["run_id"],
        "status": envelope["status"],
        "reviewer": envelope["reviewer"],
        "reviewer_model": envelope["reviewer_model"],
        "reviewer_model_version": envelope["reviewer_model_version"],
        "reviewer_cli_version": envelope["reviewer_cli_version"],
        "summary": envelope["summary"],
        "findings": envelope["findings"],
        "tested": envelope["tested"],
        "not_tested": envelope["not_tested"],
        "residual_risks": envelope["residual_risks"],
    }


def output_indicates_auth_missing(output: str) -> bool:
    normalized = output.lower()
    markers = (
        "not logged in",
        "login required",
        "please login",
        "please log in",
        "log in first",
        "not authenticated",
        "authentication required",
        "authentication failed",
        "unauthorized",
        "missing auth",
        "invalid api key",
        "missing api key",
        "no api key",
        "api key required",
        "missing auth token",
        "auth token required",
    )
    return any(marker in normalized for marker in markers)


def _extract_review_content(parsed: dict[str, Any]) -> dict[str, Any]:
    content: Any
    if parsed.get("structured_output"):
        content = parsed["structured_output"]
    elif "result" in parsed:
        content = parsed["result"]
    elif "content" in parsed:
        content = parsed["content"]
    elif "review" in parsed:
        content = parsed["review"]
    else:
        content = parsed

    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ReviewSchemaError("Claude result is not JSON") from exc

    if isinstance(content, list):
        content = _parse_content_list(content)

    if not isinstance(content, dict):
        raise ReviewSchemaError("Claude review content must be an object")

    return content


def _parse_content_list(content: list[Any]) -> dict[str, Any]:
    text_parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            text_parts.append(item["text"])
        elif isinstance(item, str):
            text_parts.append(item)

    text = "\n".join(text_parts).strip()
    if not text:
        raise ReviewSchemaError("Claude content list has no JSON text")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReviewSchemaError("Claude content list text is not JSON") from exc

    if not isinstance(parsed, dict):
        raise ReviewSchemaError("Claude content list JSON must be an object")
    return parsed


def _normalize_review_data(content: dict[str, Any]) -> dict[str, Any]:
    summary = _required_string(content.get("summary"), "summary")
    findings = _normalize_findings(content.get("findings"))
    return {
        "summary": summary,
        "findings": findings,
        "tested": _normalize_string_list(content.get("tested"), "tested"),
        "not_tested": _normalize_string_list(content.get("not_tested"), "not_tested"),
        "residual_risks": _normalize_string_list(
            content.get("residual_risks"),
            "residual_risks",
        ),
    }


def _normalize_findings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ReviewSchemaError("findings must be an array")

    normalized: list[dict[str, Any]] = []
    for index, finding in enumerate(value):
        if not isinstance(finding, dict):
            raise ReviewSchemaError(f"finding {index} must be an object")

        severity = _required_string(finding.get("severity"), f"finding {index} severity")
        if severity not in ALLOWED_SEVERITIES:
            raise ReviewSchemaError(f"finding {index} severity is not allowed")

        normalized_finding: dict[str, Any] = {
            "severity": severity,
            "title": _required_string(finding.get("title"), f"finding {index} title"),
            "evidence": _required_string(
                finding.get("evidence"),
                f"finding {index} evidence",
            ),
            "recommendation": _required_string(
                finding.get("recommendation"),
                f"finding {index} recommendation",
            ),
        }

        file_value = finding.get("file")
        if file_value is not None:
            if not isinstance(file_value, str):
                raise ReviewSchemaError(f"finding {index} file must be a string")
            file_text = file_value.strip()
            if not file_text:
                raise ReviewSchemaError(f"finding {index} file must be non-empty")
            normalized_finding["file"] = file_text

        if "line" in finding:
            line_value = finding["line"]
            if line_value is None:
                normalized_finding["line"] = None
            else:
                if not isinstance(line_value, int) or isinstance(line_value, bool):
                    raise ReviewSchemaError(f"finding {index} line is invalid")
                if line_value < 1:
                    raise ReviewSchemaError(f"finding {index} line must be positive")
                normalized_finding["line"] = line_value

        normalized.append(normalized_finding)

    return normalized


def _normalize_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ReviewSchemaError(f"{field} must be an array")

    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ReviewSchemaError(f"{field}[{index}] must be a string")
        text = item.strip()
        if not text:
            raise ReviewSchemaError(f"{field}[{index}] must be non-empty")
        normalized.append(text)
    return normalized


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ReviewSchemaError(f"{field} must be a string")
    text = value.strip()
    if not text:
        raise ReviewSchemaError(f"{field} must be non-empty")
    return text


def _validate_success_envelope(envelope: dict[str, Any]) -> None:
    status = envelope.get("status")
    findings = envelope.get("findings")

    if status == "passed" and findings != []:
        raise ReviewSchemaError("passed requires empty findings")
    if status == "findings" and not findings:
        raise ReviewSchemaError("findings requires at least one finding")

    for field in (
        "review_file",
        "summary",
        "findings",
        "tested",
        "not_tested",
        "residual_risks",
    ):
        if field not in envelope:
            raise ReviewSchemaError(f"missing required success field: {field}")


def _combined_raw_log(stdout: Any, stderr: Any) -> str:
    stdout_text = _to_text(stdout)
    stderr_text = _to_text(stderr)
    parts: list[str] = []
    if stdout_text:
        parts.append("STDOUT:\n" + stdout_text)
    if stderr_text:
        parts.append("STDERR:\n" + stderr_text)
    return "\n".join(parts) + ("\n" if parts else "")


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _write_failure_artifacts(
    path_safety: PathSafety,
    envelope: dict[str, Any],
    raw_log: str,
) -> None:
    raw_log_file = path_safety.safe_path("raw_log_file")
    if raw_log_file is not None:
        raw_log_file.parent.mkdir(parents=True, exist_ok=True)
        raw_log_file.write_text(raw_log, encoding="utf-8")

    output_file = path_safety.safe_path("output_file")
    if output_file is not None:
        _write_json(output_file, envelope)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _envelope_path(
    payload: dict[str, Any],
    key: str,
    paths: ArtifactPaths | None,
    resolved_paths: dict[str, Path] | None,
) -> str:
    if paths is not None:
        if key == "output_file":
            return str(paths.output_file)
        if key == "review_file":
            return str(paths.review_file)
        if key == "raw_log_file":
            return str(paths.raw_log_file)

    if resolved_paths is not None and key in resolved_paths:
        return str(resolved_paths[key])

    return str(payload.get(key, ""))


def _path_overrides(
    *,
    output_file: Path | str | None,
    review_file: Path | str | None,
    raw_log_file: Path | str | None,
) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    if output_file is not None:
        overrides["output_file"] = resolve_path(output_file)
    if review_file is not None:
        overrides["review_file"] = resolve_path(review_file)
    if raw_log_file is not None:
        overrides["raw_log_file"] = resolve_path(raw_log_file)
    return overrides


def _metadata_value(
    parsed: dict[str, Any],
    content: dict[str, Any],
    *keys: str,
) -> str:
    for source in (content, parsed):
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return UNKNOWN


def _nonempty_string(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default
