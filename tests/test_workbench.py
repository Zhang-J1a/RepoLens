"""Offline V5 HTTP contracts, provenance boundaries and task lifecycle."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    from repolens.workbench.api import create_app
except ImportError:
    TestClient = None


@unittest.skipIf(TestClient is None, "Install the web and web-test extras to run V5 API tests")
class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.repository = root / "repository"
        self.repository.mkdir()
        self.directory = root / "index"
        self.env = os.environ | {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        self.git("init", "--quiet")
        (self.repository / "service.py").write_text("def dispatch(value):\n    return value + 1\n", encoding="utf-8")
        (self.repository / "old.md").write_text("# dispatch\nThe dispatch entry.\n", encoding="utf-8")
        self.base = self.commit("base")
        (self.repository / "service.py").write_text("def dispatch(value):\n    return value + 2\n\ndef future():\n    return dispatch(1)\n", encoding="utf-8")
        (self.repository / "old.md").unlink()
        self.head = self.commit("head")
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            self.app = create_app(self.directory)
        self.client = TestClient(self.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(lambda: self.client.__exit__(None, None, None))

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=Workbench Test", "-c", "user.email=web@example.invalid",
                               "-C", str(self.repository), *args], env=self.env, capture_output=True,
                              check=True, timeout=30).stdout.decode().strip()

    def commit(self, message):
        self.git("add", "--all")
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", message)
        return self.git("rev-parse", "HEAD")

    def wait_task(self, response):
        self.assertEqual(response.status_code, 202, response.text)
        identity = response.json()["id"]
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            task = self.client.get(f"/api/tasks/{identity}").json()
            if task["status"] in ("completed", "failed"):
                return task
            time.sleep(0.03)
        self.fail("Task did not finish")

    def imported(self, ref="HEAD"):
        task = self.wait_task(self.client.post("/api/tasks", json={"action": "import", "repository": str(self.repository), "ref": ref}))
        self.assertEqual(task["status"], "completed", task["error"])
        return task["result"]

    def task(self, action, workspace_id, **kwargs):
        return self.wait_task(self.client.post("/api/tasks", json={"action": action, "workspace_id": workspace_id, **kwargs}))

    def test_import_metadata_restart_and_target_unchanged(self):
        before = self.git("status", "--porcelain")
        imported = self.imported()
        identity = imported["workspace"]["workspace_id"]
        listing = self.client.get("/api/workspaces").json()
        self.assertEqual(listing[0]["workspace_id"], identity)
        detail = self.client.get(f"/api/workspaces/{identity}").json()
        self.assertTrue(detail["history"])
        self.assertTrue(detail["files"])
        self.assertEqual(detail["snapshots"][0]["commit_sha"], self.head)
        from repolens.workbench.service import WorkbenchService
        self.assertEqual(WorkbenchService(self.directory).workspaces()[0]["workspace_id"], identity)
        self.assertEqual(before, self.git("status", "--porcelain"))

    def test_source_diff_deleted_file_and_snapshot_boundaries(self):
        first = self.imported(self.base)
        head = self.imported(self.head)
        identity = first["workspace"]["workspace_id"]
        base_id, head_id = first["snapshot"]["snapshot_id"], head["snapshot"]["snapshot_id"]
        source = self.client.post("/api/source", json={"workspace_id": identity, "snapshot_id": base_id, "path": "service.py"})
        self.assertEqual(source.status_code, 200)
        self.assertNotIn("future", source.json()["text"])
        diff = self.client.post("/api/diff", json={"workspace_id": identity, "base_snapshot_id": base_id, "head_snapshot_id": head_id, "path": "old.md"})
        self.assertEqual(diff.json()["head"]["text"], "")
        for payload in ({"workspace_id": "wrong", "snapshot_id": head_id, "path": "service.py"},
                        {"workspace_id": identity, "snapshot_id": head_id, "path": "../secret"},
                        {"workspace_id": identity, "snapshot_id": head_id, "path": "old.md"}):
            self.assertEqual(self.client.post("/api/source", json=payload).status_code, 400)
        self.assertEqual(self.client.post("/api/diff", json={"workspace_id": identity, "base_snapshot_id": base_id,
                         "head_snapshot_id": head_id, "path": "absent.py"}).status_code, 400)

    def test_search_ask_graph_and_evidence_binding(self):
        imported = self.imported()
        identity = imported["workspace"]["workspace_id"]
        search = self.task("search", identity, query="dispatch", retrieval="hybrid")
        evidence = search["result"]["results"][0]
        source = self.client.post("/api/source", json={"workspace_id": identity, "snapshot_id": evidence["snapshot_id"],
                                                      "path": evidence["path"], "evidence_id": evidence["evidence_id"]})
        self.assertEqual(source.status_code, 200)
        self.assertEqual(source.json()["evidence"]["evidence_id"], evidence["evidence_id"])
        self.assertEqual(self.task("ask", identity, question="dispatch", provider="mock")["result"]["answer"]["status"], "answered")
        graph = self.task("graph", identity, seed_kind="symbol", seed="dispatch")["result"]
        self.assertTrue(graph["nodes"])
        self.assertEqual(graph["commit_sha"], self.head)
        history_graph = self.task("graph", identity, ref=self.base, seed_kind="symbol", seed="future")["result"]
        self.assertEqual(history_graph["nodes"], [])

    def test_langchain_requires_key_and_optional_dependency_before_queueing(self):
        imported = self.imported()
        payload = {"action": "ask", "workspace_id": imported["workspace"]["workspace_id"],
                   "question": "dispatch", "provider": "langchain"}
        self.app.state.service.runtime_api_key = None
        response = self.client.post("/api/tasks", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("API Key", response.json()["error"])
        self.app.state.service.runtime_api_key = "unit-private-marker"
        with patch.dict(sys.modules, {"repolens.langchain_integration": None}):
            response = self.client.post("/api/tasks", json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn("install the 'langchain' extra", response.json()["error"])
        self.assertNotIn("unit-private-marker", response.text)

    def test_impact_pr_diff_validation_and_exports(self):
        imported = self.imported()
        identity = imported["workspace"]["workspace_id"]
        diff = self.git("diff", "--no-ext-diff", "--no-textconv", "--no-color", "--no-renames", "--unified=3", self.base, self.head, "--")
        task = self.task("impact", identity, base=self.base, diff=diff)
        self.assertEqual(task["status"], "completed", task["error"])
        self.assertEqual(task["result"]["head"]["commit_sha"], self.head)
        for format in ("markdown", "json"):
            response = self.client.get(f'/api/tasks/{task["id"]}/export?format={format}')
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment", response.headers["content-disposition"])
        invalid = self.task("impact", identity, base=self.base, diff=diff.replace("value + 2", "value + 999"))
        self.assertEqual(invalid["status"], "failed")
        self.assertIn("不匹配", invalid["error"])

    def test_sse_replay_and_agent_events(self):
        imported = self.imported()
        identity = imported["workspace"]["workspace_id"]
        task = self.task("agent", identity, question="dispatch", base=self.base, max_steps=3, timeout_seconds=20)
        self.assertEqual(task["status"], "completed", task["error"])
        self.assertTrue(task["result"]["trace"]["events"])
        self.assertTrue(any(event["data"].get("state") == "tool" for event in task["events"]))
        response = self.client.get(f'/api/tasks/{task["id"]}/events', headers={"Last-Event-ID": "2"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("event: finished", response.text)
        self.assertNotIn("id: 1\n", response.text)
        self.assertIn("id: 3\n", response.text)
        self.assertEqual(self.client.get(f'/api/tasks/{task["id"]}/events?after=-1').status_code, 400)

    def test_closed_contract_no_secret_echo_and_local_origin(self):
        marker = "unit-test-private-marker"
        self.assertEqual(self.client.post("/api/settings", json={"api_key": marker}).status_code, 200)
        self.assertTrue(self.client.get("/api/health").json()["key_configured"])
        self.assertNotIn(marker, self.client.get("/api/health").text)
        response = self.client.post("/api/settings", json={"api_key": marker, "extra": marker})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(marker, response.text)
        self.assertEqual(self.client.post("/api/settings", json={"api_key": ""}, headers={"Origin": "https://example.invalid"}).status_code, 403)
        self.assertEqual(self.client.get("/api/health", headers={"Host": "example.invalid"}).status_code, 403)
        self.assertEqual(self.client.post("/api/settings", content="key", headers={"Content-Type": "text/plain"}).status_code, 415)
        self.assertEqual(self.client.post("/api/settings", json={"api_key": "x" * 140000}).status_code, 413)
        invalid = self.client.post("/api/tasks", json={"action": "graph", "workspace_id": "x", "hops": True})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.client.get("/api/not-present").status_code, 404)

    def test_demo_evaluation_and_typed_openapi(self):
        response = self.client.post("/api/demo", json={})
        self.assertEqual(response.status_code, 200, response.text)
        task = response.json()["task"]
        deadline = time.monotonic() + 20
        while task["status"] in ("queued", "running") and time.monotonic() < deadline:
            time.sleep(0.03)
            task = self.client.get(f'/api/tasks/{task["id"]}').json()
        self.assertEqual(task["status"], "completed", task["error"])
        self.assertEqual(response.json()["demo"]["workspace_id"], task["result"]["workspace"]["workspace_id"])
        self.assertNotEqual(response.json()["demo"]["base"], response.json()["demo"]["head"])
        records = self.client.get("/api/evaluations").json()
        self.assertEqual(len(records), 6)
        self.assertTrue(all(item["citation_precision"] is None for item in records))
        schema = self.client.get("/openapi.json").json()
        self.assertIn("TaskView", schema["components"]["schemas"])
        self.assertIn("discriminator", schema["paths"]["/api/tasks"]["post"]["requestBody"]["content"]["application/json"]["schema"])


if __name__ == "__main__":
    unittest.main()
