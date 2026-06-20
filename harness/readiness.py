from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


RUN_DOCUMENTS = ("task.md", "triage.md", "plan.md", "handoff.md")
REQUIRED_FRONTMATTER_FIELDS = {
    "task.md": (
        "run_id",
        "schema_version",
        "track",
        "workflow",
        "owner",
        "requested_outcome",
        "scope",
        "non_goals",
        "constraints",
    ),
    "triage.md": (
        "run_id",
        "schema_version",
        "track",
        "workflow",
        "review_required",
        "strict_triggers",
        "risk_reasons",
        "verification_required",
    ),
    "plan.md": (
        "run_id",
        "schema_version",
        "workflow",
        "acceptance",
        "verification",
        "review_plan",
        "constraints",
    ),
    "handoff.md": (
        "run_id",
        "schema_version",
        "changed",
        "verified",
        "not_verified",
        "residual_risks",
        "next_step",
        "memory_update",
        "memory_files",
    ),
}
RECOMMENDED_FRONTMATTER_FIELDS: dict[str, tuple[str, ...]] = {}
STRICT_PLAN_FRONTMATTER_FIELDS = ("recovery_strategy", "residual_risk_owner")


@dataclass(frozen=True)
class FrontmatterResult:
    data: dict[str, Any]
    warnings: list[str]


@dataclass(frozen=True)
class ReadinessReport:
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.warnings


def parse_frontmatter(text: str) -> FrontmatterResult:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return FrontmatterResult({}, ["missing frontmatter block"])

    try:
        end_index = lines[1:].index("---") + 1
    except ValueError:
        return FrontmatterResult({}, ["unterminated frontmatter block"])

    raw_lines = lines[1:end_index]
    data: dict[str, Any] = {}
    warnings: list[str] = []
    index = 0
    while index < len(raw_lines):
        line = raw_lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith(" "):
            warnings.append(f"unsupported frontmatter line: {line}")
            index += 1
            continue
        if ":" not in line:
            warnings.append(f"unsupported frontmatter line: {line}")
            index += 1
            continue

        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            warnings.append(f"unsupported frontmatter line: {line}")
            index += 1
            continue

        if raw_value:
            data[key] = parse_scalar(raw_value)
            index += 1
            continue

        nested, consumed, nested_warnings = parse_nested_block(raw_lines[index + 1 :])
        warnings.extend(nested_warnings)
        data[key] = nested
        index += consumed + 1

    return FrontmatterResult(data, warnings)


def parse_nested_block(lines: list[str]) -> tuple[Any, int, list[str]]:
    warnings: list[str] = []
    items: list[str] = []
    mapping: dict[str, Any] = {}
    consumed = 0
    mode: str | None = None
    unsupported_nested = False

    for line in lines:
        if not line.strip():
            consumed += 1
            continue
        if not line.startswith("  "):
            break
        if line.startswith("    "):
            warnings.append("unsupported frontmatter nesting")
            unsupported_nested = True
            consumed += 1
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            if mode == "map":
                warnings.append("mixed frontmatter sequence and map values are unsupported")
            mode = "list"
            raw_item = stripped[2:]
            if is_unquoted_mapping_like_value(raw_item):
                warnings.append(f"unsupported frontmatter sequence item: {raw_item}")
            items.append(parse_scalar(raw_item))
            consumed += 1
            continue
        if ":" in stripped:
            if mode == "list":
                warnings.append("mixed frontmatter sequence and map values are unsupported")
            mode = "map"
            child_key, child_value = stripped.split(":", 1)
            child_key = child_key.strip()
            child_value = child_value.strip()
            if not child_value:
                warnings.append("unsupported frontmatter nesting")
                unsupported_nested = True
                consumed += 1
                continue
            mapping[child_key] = parse_scalar(child_value)
            consumed += 1
            continue
        warnings.append(f"unsupported frontmatter line: {line}")
        consumed += 1

    if unsupported_nested:
        return [], consumed, warnings
    if mode == "map":
        return mapping, consumed, warnings
    return items, consumed, warnings


def is_unquoted_mapping_like_value(value: str) -> bool:
    if (
        (value.startswith('"') and value.endswith('"'))
        or (value.startswith("'") and value.endswith("'"))
    ):
        return False
    return ":" in value


def parse_scalar(value: str) -> Any:
    if value == "[]":
        return []
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if (
        (value.startswith('"') and value.endswith('"'))
        or (value.startswith("'") and value.endswith("'"))
    ):
        return value[1:-1]
    return value


def check_run_readiness(run_dir: Path, state: dict[str, Any]) -> ReadinessReport:
    warnings: list[str] = []
    for document_name in RUN_DOCUMENTS:
        path = run_dir / document_name
        if not path.exists():
            warnings.append(f"missing run document: {document_name}")
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            warnings.append(f"cannot read run document {document_name}: {exc}")
            continue

        result = parse_frontmatter(text)
        warnings.extend(f"{document_name}: {warning}" for warning in result.warnings)
        warnings.extend(validate_document_frontmatter(document_name, result.data, state))

    return ReadinessReport(warnings)


def validate_document_frontmatter(
    document_name: str,
    data: dict[str, Any],
    state: dict[str, Any],
) -> list[str]:
    if not data:
        return []

    warnings: list[str] = []
    for field_name in REQUIRED_FRONTMATTER_FIELDS.get(document_name, ()):
        if field_name not in data:
            warnings.append(f"{document_name} frontmatter missing field: {field_name}")

    for field_name in RECOMMENDED_FRONTMATTER_FIELDS.get(document_name, ()):
        if field_name not in data:
            warnings.append(f"{document_name} frontmatter missing field: {field_name}")

    if document_name == "plan.md" and state.get("track") == "Strict":
        for field_name in STRICT_PLAN_FRONTMATTER_FIELDS:
            if field_name not in data:
                warnings.append(f"{document_name} frontmatter missing field: {field_name}")

    state_run_id = state.get("run_id")
    if data.get("run_id") != state_run_id:
        warnings.append(
            f"{document_name} frontmatter run_id {data.get('run_id')} "
            f"does not match state run_id {state_run_id}"
        )

    if "track" in data and data.get("track") != state.get("track"):
        warnings.append(
            f"{document_name} frontmatter track {data.get('track')} "
            f"does not match state track {state.get('track')}"
        )

    if "workflow" in data and data.get("workflow") != state.get("current_workflow"):
        warnings.append(
            f"{document_name} frontmatter workflow {data.get('workflow')} "
            f"does not match state workflow {state.get('current_workflow')}"
        )

    return warnings
