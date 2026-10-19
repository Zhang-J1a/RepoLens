"""Installed-package V6 walkthrough; synthetic inputs and Mock only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from fastapi.testclient import TestClient
import repolens
from repolens.workbench.api import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="repolens-v6-demo-") as temporary:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            app = create_app(Path(temporary) / "index")
        with TestClient(app, base_url="http://127.0.0.1") as client:
            def complete(task):
                deadline = time.monotonic() + 60
                while task["status"] in ("queued", "running"):
                    if time.monotonic() > deadline:
                        raise RuntimeError("Demo task timed out")
                    time.sleep(0.03)
                    task = client.get(f'/api/tasks/{task["id"]}').json()
                if task["status"] != "completed":
                    raise RuntimeError(task["error"])
                return task

            def submit(**payload):
                response = client.post("/api/tasks", json=payload)
                response.raise_for_status()
                return complete(response.json())

            started = time.monotonic()
            demo = client.post("/api/demo", json={}).json()
            imported = complete(demo["task"])
            workspace = imported["result"]["workspace"]["workspace_id"]
            common = {"workspace_id": workspace, "ref": demo["demo"]["head"]}
            search = submit(action="search", query="TaskService.create_task", **common)
            evidence = search["result"]["results"][0]
            source = client.post("/api/source", json={"workspace_id": workspace,
                                 "snapshot_id": evidence["snapshot_id"], "path": evidence["path"],
                                 "evidence_id": evidence["evidence_id"]})
            source.raise_for_status()
            ask = submit(action="ask", question="TaskService.create_task 如何处理任务标题？", **common)
            graph = submit(action="graph", seed_kind="symbol", seed="TaskService.create_task", **common)
            impact = submit(action="impact", base=demo["demo"]["base"], **common)
            diff = client.post("/api/diff", json={"workspace_id": workspace,
                               "base_snapshot_id": impact["result"]["base"]["snapshot_id"],
                               "head_snapshot_id": impact["result"]["head"]["snapshot_id"], "path": "service.py"})
            diff.raise_for_status()
            agent = submit(action="agent", question="TaskService.create_task callers and tests", max_steps=3, **common)
            normal_agent = submit(action="agent", question="TaskService.create_task callers and tests", max_steps=8, **common)
            markdown = client.get(f'/api/tasks/{impact["id"]}/export?format=markdown')
            markdown.raise_for_status()
            sse = client.get(f'/api/tasks/{agent["id"]}/events', headers={"Last-Event-ID": "2"})
            if "event: finished" not in sse.text or "id: 1\n" in sse.text:
                raise RuntimeError("SSE resume failed")
            if diff.json()["base"]["text"] == diff.json()["head"]["text"]:
                raise RuntimeError("Demo diff was empty")
            if (ask["result"]["answer"]["status"] != "answered"
                    or agent["result"]["stop_reason"] != "step_budget_exhausted"
                    or normal_agent["result"]["status"] != "completed"):
                raise RuntimeError("Answer or Agent contract did not match the scenario")
            agent_cases = []
            for name, task in (("normal_mock", normal_agent), ("step_budget_degradation", agent)):
                result = task["result"]
                trace = result["trace"]
                events = trace["events"]
                calls = [event for event in events if event["state"] == "tool" and event["status"] == "started"]
                finished = [event for event in events if event["state"] == "tool" and event["status"] != "started"]
                unique = {(event["name"], json.dumps(event["input"], sort_keys=True)) for event in calls}
                if any(event["trace_id"] != trace["trace_id"] or event["task_id"] != trace["task_id"] for event in events):
                    raise RuntimeError("Incomplete Agent trace correlation")
                agent_cases.append({"name": name, "status": result["status"], "stop_reason": result["stop_reason"],
                                    "tool_calls": len(calls), "successful_tool_calls": sum(event["status"] == "ok" for event in finished),
                                    "tool_success_rate": sum(event["status"] == "ok" for event in finished) / len(calls) if calls else None,
                                    "repeated_tool_calls": len(calls) - len(unique),
                                    "trace_complete": True, "trace": trace})
            tasks = [imported, search, ask, graph, impact, agent, normal_agent]
            durations = sorted(task["duration_ms"] for task in tasks)

            def percentile(fraction):
                position = (len(durations) - 1) * fraction
                low = int(position)
                high = min(low + 1, len(durations) - 1)
                return durations[low] + (durations[high] - durations[low]) * (position - low)

            report = {"schema_version": "repolens.workbench-smoke.v1", "ok": True,
                      "stage": "V6", "scope": "synthetic-mock-contract-walkthrough-not-model-quality",
                      "package_path": repolens.__file__, "homepage_status": client.get("/").status_code,
                      "fixture": "synthetic-taskboard-two-commits", "provider": "mock",
                      "source_span_verified": True, "answer_status": ask["result"]["answer"]["status"],
                      "graph_nodes": len(graph["result"]["nodes"]), "graph_edges": len(graph["result"]["edges"]),
                      "changed_files": len(impact["result"]["changed_files"]), "diff_sides_differ": True,
                      "markdown_export_status": markdown.status_code, "agent_status": agent["result"]["status"],
                      "agent_stop_reason": agent["result"]["stop_reason"],
                      "agent_trace_events": len(agent["result"]["trace"]["events"]), "sse_resume_verified": True,
                      "frozen_evaluation_views": len(client.get("/api/evaluations").json()),
                      "request_id": imported["request_id"],
                      "metrics_status": client.get("/api/metrics").status_code,
                      "system_metrics": {"task_count": len(tasks), "task_completion_rate": 1.0,
                                         "task_duration_ms": {"p50": percentile(.5), "p95": percentile(.95)},
                                         "walkthrough_duration_ms": round((time.monotonic() - started) * 1000),
                                         "total_tokens": None, "cost": None},
                      "agent_cases": agent_cases,
                      "fixture_hashes": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                         for path in (Path(repolens.__file__).parent / "workbench/fixtures/taskboard").rglob("*") if path.is_file()},
                      "note": "Offline installed-package contract smoke, not model or retrieval quality evaluation."}
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
