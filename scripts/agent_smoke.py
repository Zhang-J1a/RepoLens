"""Reproducible offline agent smoke and failure fallback on a chosen fixed commit."""

import argparse
import hashlib
import json
from pathlib import Path

from repolens.agent import ControlledAgent
from repolens.git import GitRepository
from repolens.provider import MockProvider


class UnavailableProvider:
    name = "simulated-unavailable"

    def generate(self, request):
        raise RuntimeError("Simulated provider failure")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    git = GitRepository(args.repository)
    commit = git.commit(args.ref)
    if not commit.parents:
        raise RuntimeError("This smoke requires a commit with a first parent.")
    scenarios = []
    for name, provider in (("offline_mock", MockProvider()), ("provider_failure", UnavailableProvider())):
        result = ControlledAgent(provider).run(
            args.repository, Path(args.data_dir), "Flask.test_client related tests and callers",
            ref=commit.sha, base_ref=commit.parents[0],
        )
        if not result["rule_report"] or not result["evidence"]:
            raise RuntimeError("Smoke failed to retain rules or evidence.")
        if name == "provider_failure" and result["stop_reason"] != "provider_failed":
            raise RuntimeError("Provider failure did not use the expected fallback.")
        if name == "offline_mock" and result["answer"]["status"] != "answered":
            raise RuntimeError("Offline mock did not produce a validated answer.")
        scenarios.append({"name": name, "status": result["status"], "stop_reason": result["stop_reason"],
                          "answer_status": result["answer"]["status"], "workflow": result["workflow"],
                          "evidence_count": len(result["evidence"]),
                          "rule_report_status": result["rule_report"]["status"], "trace": result["trace"]})
    report = {"schema_version": "repolens.agent-smoke.v1", "repository": "pallets/flask",
              "commit_sha": commit.sha, "base_sha": commit.parents[0],
              "note": "Offline contract smoke only; no real model or agent quality benchmark.",
              "scenarios": scenarios}
    output = Path(args.output)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                      "scenarios": [{key: item[key] for key in ("name", "status", "stop_reason", "answer_status", "evidence_count")}
                                    for item in scenarios]}, indent=2))


if __name__ == "__main__":
    main()
