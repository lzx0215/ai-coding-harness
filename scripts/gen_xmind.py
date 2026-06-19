"""Generate docs/xmind/ai-coding-harness.xmind from the overview index."""
from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime, timezone


TREE = (
    "ai-coding-harness v0.2.1",
    [
        (
            "入口",
            [
                "AGENTS.md",
                "README.md",
                "docs/INDEX.md",
                "docs/project-overview.md",
            ],
        ),
        (
            "harness/core",
            [
                "state-authority.md",
                "task-triage.md",
                "lifecycle.md",
                "delegation.md",
                "verification.md",
                "memory.md",
                "safety.md",
            ],
        ),
        (
            "harness/adapters",
            [
                "codex.md",
                "claude-code.md",
                "generic-cli-agent.md",
            ],
        ),
        (
            "运行证据",
            [
                "harness/runs/<run-id>/state.json",
                "task / triage / plan / verification / review / handoff",
                "reviews/*.json + raw logs",
                "artifacts/diff.patch + changed-files.txt",
            ],
        ),
        (
            "Claude review MCP",
            [
                "mcp/claude-review/server.py",
                "mcp/claude-review/adapter.py",
                "schema input/output contracts",
                "reviewer provenance",
            ],
        ),
        (
            "v0.2.1 closure",
            [
                "merged to master",
                "pushed to origin/master",
                "hardening plan completed",
                "project overview formalized",
            ],
        ),
    ],
)


def make_id(counter: list[int]) -> str:
    counter[0] += 1
    return f"topic-{counter[0]}"


def build_topic(node: str | tuple, counter: list[int]) -> dict:
    if isinstance(node, str):
        return {"id": make_id(counter), "class": "topic", "title": node}

    title, children = node
    topic = {"id": make_id(counter), "class": "topic", "title": title}
    if children:
        topic["children"] = {
            "attached": [build_topic(child, counter) for child in children],
        }
    return topic


def main() -> int:
    counter = [0]
    now = datetime.now(timezone.utc).isoformat()
    content = [
        {
            "id": "sheet-1",
            "class": "sheet",
            "title": "ai-coding-harness",
            "rootTopic": build_topic(TREE, counter),
        }
    ]
    metadata = {
        "creator": {"name": "ai-coding-harness", "version": "0.2.1"},
        "modifier": {"name": "ai-coding-harness", "version": "0.2.1"},
        "created_at": now,
        "updated_at": now,
    }
    manifest = {"file-entries": {"content.json": {}, "metadata.json": {}}}

    out_dir = os.path.join("docs", "xmind")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "ai-coding-harness.xmind")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("content.json", json.dumps(content, ensure_ascii=False))
        zf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False))
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))

    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
