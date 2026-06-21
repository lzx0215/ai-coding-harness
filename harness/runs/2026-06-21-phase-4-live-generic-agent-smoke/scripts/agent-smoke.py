from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> int:
    input_path = Path(os.environ["HARNESS_AGENT_INPUT_FILE"])
    output_path = Path(os.environ["HARNESS_AGENT_OUTPUT_FILE"])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    result = {
        "run_id": payload["run_id"],
        "job_id": payload["job_id"],
        "agent": payload["agent"],
        "adapter": payload["adapter"],
        "status": "passed",
        "summary": "Phase 4 live generic agent smoke completed.",
        "findings": [],
        "evidence": [
            {
                "path": "raw.log",
                "description": "raw.log captures deterministic smoke-agent stdout.",
            }
        ],
        "not_tested": [
            "Scheduler or background worker execution.",
            "External reviewer independence.",
        ],
        "residual_risks": [
            "This proves the local generic-agent CLI path only.",
        ],
        "generated_at": payload["created_at"],
    }
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("phase4 live generic agent wrote output")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
