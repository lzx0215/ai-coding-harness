import json
import os
from datetime import datetime, timezone


def main() -> None:
    input_file = os.environ["HARNESS_AGENT_INPUT_FILE"]
    output_file = os.environ["HARNESS_AGENT_OUTPUT_FILE"]

    with open(input_file, "r", encoding="utf-8") as handle:
        job_input = json.load(handle)

    output = {
        "run_id": job_input["run_id"],
        "job_id": job_input["job_id"],
        "agent": job_input["agent"],
        "adapter": job_input["adapter"],
        "status": "passed",
        "summary": "Phase 6 scheduler watch smoke completed.",
        "findings": [],
        "evidence": [
            {
                "path": "jobs/phase6-watch-agent/raw.log",
                "description": "Raw stdout and stderr captured from the watch-executed smoke agent.",
            }
        ],
        "not_tested": [
            "Multi-worker claim locking",
            "Automatic stale-running recovery",
            "Cloud queue execution",
            "Cross-run queue execution",
        ],
        "residual_risks": [
            "Heartbeat observational only",
            "Stop cooperative and does not interrupt running jobs",
            "Double-claim risk remains",
        ],
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }

    with open(output_file, "w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2)
        handle.write("\n")

    print("phase6 scheduler watch agent wrote output")


if __name__ == "__main__":
    main()
