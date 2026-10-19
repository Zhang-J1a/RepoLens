"""Evaluate previously saved responses with output-bound reviewer labels."""

import argparse
import hashlib
import json
from pathlib import Path

from repolens.generation_evaluation import evaluate_responses


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--judgments", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate_responses(json.loads(args.responses.read_text(encoding="utf-8")),
                                json.loads(args.judgments.read_text(encoding="utf-8")))
    report["provenance"] = {"responses_sha256": hashlib.sha256(args.responses.read_bytes()).hexdigest(),
                            "judgments_sha256": hashlib.sha256(args.judgments.read_bytes()).hexdigest()}
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"output": str(args.output), "scope": report["scope"], "case_count": report["case_count"]}))


if __name__ == "__main__":
    main()
