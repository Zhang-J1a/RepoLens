"""Evaluate previously saved responses with output-bound reviewer labels."""

import argparse
import hashlib
import json
from pathlib import Path

from repolens.generation_evaluation import create_review_template, evaluate_responses


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--judgments", type=Path)
    mode.add_argument("--create-review-template", action="store_true")
    parser.add_argument("--reviewer", default="reviewer-1")
    args = parser.parse_args()
    response_bytes = args.responses.read_bytes()
    responses = json.loads(response_bytes.decode("utf-8"))
    if args.create_review_template:
        report = create_review_template(responses, reviewer=args.reviewer)
    else:
        if args.judgments is None or not args.judgments.is_file():
            parser.error("--judgments must point to a completed review file unless --create-review-template is set")
        judgment_bytes = args.judgments.read_bytes()
        report = evaluate_responses(responses, json.loads(judgment_bytes.decode("utf-8")))
    report["provenance"] = {"responses_sha256": hashlib.sha256(response_bytes).hexdigest()}
    if args.judgments is not None:
        report["provenance"]["judgments_sha256"] = hashlib.sha256(judgment_bytes).hexdigest()
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"output": str(args.output), "scope": report.get("scope", "review-template"),
                      "case_count": len(report["cases"])}))


if __name__ == "__main__":
    main()
