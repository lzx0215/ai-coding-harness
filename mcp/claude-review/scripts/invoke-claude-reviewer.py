from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapter import build_envelope, run_claude_review  # noqa: E402


def load_payload(input_file: str | Path) -> dict:
    return json.loads(Path(input_file).read_text(encoding="utf-8-sig"))


def run_from_paths(input_file: str | Path, output_file: str | Path, raw_log_file: str | Path) -> dict:
    payload = load_payload(input_file)
    if payload.get("output_file") != str(output_file) or payload.get("raw_log_file") != str(raw_log_file):
        return build_envelope(
            payload,
            "not_available",
            duration_seconds=0.0,
            reason="unsupported_environment",
        )
    return run_claude_review(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--raw-log", required=True)
    args = parser.parse_args()

    envelope = run_from_paths(args.input, args.output, args.raw_log)
    print(json.dumps(envelope, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
