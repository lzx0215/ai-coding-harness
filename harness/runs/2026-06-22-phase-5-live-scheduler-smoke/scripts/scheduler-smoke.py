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
        "summary": "Local scheduler smoke job executed through run-scheduler --once.",
        "findings": [],
        "evidence": [
            {
                "path": "jobs/phase5-live-scheduler-agent/raw.log",
                "description": "Captured stdout from the scheduler-executed smoke agent.",
            }
        ],
        "not_tested": [
            "watch mode",
            "multi-worker concurrency",
            "cloud queue",
            "stale-running recovery",
            "orphaned running jobs",
        ],
        "residual_risks": [
            "Watch mode was not exercised.",
            "Multi-worker concurrency was not exercised.",
            "Cloud queue behavior was not exercised.",
            "Automatic stale-running recovery was not exercised.",
            "Orphaned running jobs are skipped, not recovered.",
        ],
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }

    with open(output_file, "w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2)
        handle.write("\n")

    print("phase5 live scheduler agent wrote output")


if __name__ == "__main__":
    main()
