"""V6 observability and security boundary contracts."""

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from repolens.observability import JsonLogFormatter, MetricsRegistry
from repolens.domain import RepoLensError

try:
    from fastapi.testclient import TestClient
    from repolens.workbench.api import create_app
except ImportError:
    TestClient = None


class ObservabilityTests(unittest.TestCase):
    def test_structured_formatter_redacts_secret_and_keeps_request_metadata(self):
        import logging

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonLogFormatter())
        record = logging.LogRecord("repolens.test", logging.INFO, __file__, 1, "request complete", (), None)
        record.request_id = "req-v6"
        record.operation = "/api/tasks/{id}"
        record.status_code = 200
        record.api_key = "never-log-this"
        stream.write(handler.format(record))
        payload = json.loads(stream.getvalue())
        self.assertEqual(payload["request_id"], "req-v6")
        self.assertEqual(payload["operation"], "/api/tasks/{id}")
        self.assertNotIn("never-log-this", stream.getvalue())

    def test_metrics_are_bounded_and_prometheus_is_metadata_only(self):
        metrics = MetricsRegistry(max_samples=2)
        metrics.increment("tasks_submitted")
        for value in (1, 2, 3):
            metrics.observe_request("GET", "/api/tasks/0123456789abcdef0123456789abcdef", 200, value)
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["counters"]["tasks_submitted"], 1)
        duration = next(iter(snapshot["durations"].values()))
        self.assertEqual(duration["count"], 2)
        self.assertIn("repolens_http_requests_total", metrics.prometheus())
        self.assertNotIn("0123456789abcdef0123456789abcdef", metrics.prometheus())

    def test_arbitrary_paths_and_methods_cannot_create_metric_series(self):
        metrics = MetricsRegistry(max_samples=2)
        for number in range(2000):
            metrics.observe_request(f"UNTRUSTED-{number}", f'/secret-{number}"\nvalue', 404, 1)
        self.assertEqual(len(metrics.snapshot()["counters"]), 1)
        self.assertNotIn("secret-", metrics.prometheus())
        self.assertNotIn("UNTRUSTED-", metrics.prometheus())

    def test_configured_repository_roots_reject_before_git_reads(self):
        from repolens.workbench.service import WorkbenchService
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = WorkbenchService(root / "index")
            with patch.dict("os.environ", {"REPOLENS_REPOSITORY_ROOTS": str(root / "authorized")}):
                with patch("repolens.workbench.service.GitRepository", side_effect=AssertionError("must not open Git")):
                    with self.assertRaisesRegex(RepoLensError, "已授权"):
                        service.validate_repository(root / "outside")

    def test_saved_snapshot_cannot_bypass_new_directory_restrictions(self):
        from repolens.workbench.service import WorkbenchService
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = WorkbenchService(root / "index")
            snapshot = {"repository_id": "repo-old", "root": str(root / "old-private")}
            store = Mock()
            store.snapshot.return_value = snapshot
            store.snapshots.return_value = [snapshot]
            (service.default_data_dir).mkdir()
            from repolens.index import DATABASE_NAME
            (service.default_data_dir / DATABASE_NAME).touch()
            with patch.dict("os.environ", {"REPOLENS_REPOSITORY_ROOTS": str(root / "authorized")}):
                with patch("repolens.workbench.service.IndexStore") as index:
                    index.return_value.__enter__.return_value = store
                    self.assertEqual(service.workspaces(), [])
                with patch.object(service, "workspace", return_value={}):
                    with self.assertRaisesRegex(RepoLensError, "已授权"):
                        service.checked_snapshot(store, "repo-old", "snapshot-old")

    def test_interrupted_stream_finishes_and_logs_only_metadata(self):
        import asyncio
        try:
            from repolens.workbench.middleware import LocalBoundaryMiddleware
        except ImportError:
            self.skipTest("Install web extras for ASGI boundary tests")
        messages = []

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"event: update\n\n", "more_body": True})
            raise RuntimeError("private-stream-marker")

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(message):
            messages.append(message)

        middleware = LocalBoundaryMiddleware(app, MetricsRegistry())
        scope = {"type": "http", "scheme": "http", "method": "GET", "path": "/api/tasks/test/events",
                 "headers": [(b"host", b"127.0.0.1")]}
        with self.assertLogs("repolens.web", level="INFO") as captured:
            asyncio.run(middleware(scope, receive, send))
        self.assertFalse(messages[-1]["more_body"])
        self.assertEqual(captured.records[0].error_code, "internal_error")
        self.assertNotIn("private-stream-marker", str(captured.output))

    def test_task_log_correlates_nested_answer_trace(self):
        from repolens.observability import bind_request_id, reset_request_id
        from repolens.workbench.jobs import JobStore
        service = Mock()
        service.execute.return_value = {"telemetry": {"trace_id": "answer-trace"}}
        token = bind_request_id("request-unit")
        try:
            with self.assertLogs("repolens.tasks", level="INFO") as captured:
                store = JobStore(service)
                task = store.submit({"action": "ask"})
                store.close()
            self.assertEqual(captured.records[0].trace_id, "answer-trace")
            self.assertEqual(store.get(task["id"])["request_id"], "request-unit")
        finally:
            reset_request_id(token)


@unittest.skipIf(TestClient is None, "Install the web and web-test extras to run V6 API tests")
class V6ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app(Path(self.temp.name) / "index")
        self.client = TestClient(self.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        self.client.__enter__()
        self.addCleanup(lambda: self.client.__exit__(None, None, None))

    def test_request_id_metrics_and_security_headers(self):
        response = self.client.get("/api/health", headers={"X-Request-ID": "test-v6_01"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-request-id"], "test-v6_01")
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertIn("Cross-Origin-Resource-Policy", response.headers)
        metrics = self.client.get("/api/metrics")
        self.assertEqual(metrics.status_code, 200)
        self.assertTrue(any("/api/health" in key for key in metrics.json()["counters"]))
        prometheus = self.client.get("/metrics")
        self.assertEqual(prometheus.status_code, 200)
        self.assertIn("repolens_http_requests_total", prometheus.text)

    def test_rejected_requests_keep_request_id_and_do_not_echo_body(self):
        response = self.client.post("/api/settings", content="secret-body", headers={
            "Content-Type": "text/plain", "X-Request-ID": "reject-v6",
        })
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.headers["x-request-id"], "reject-v6")
        self.assertNotIn("secret-body", response.text)
        response = self.client.get("/api/health", headers={"X-Request-ID": "bad id"})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.headers["x-request-id"], "bad id")

    def test_cross_origin_and_oversized_body_are_rejected(self):
        cross_origin = self.client.post("/api/settings", json={"api_key": "x"}, headers={
            "Origin": "https://example.invalid",
        })
        self.assertEqual(cross_origin.status_code, 403)
        self.assertEqual(self.client.post("/api/settings", json={"api_key": "x" * 140000}).status_code, 413)

    def test_internal_errors_keep_request_id_without_leaking_exception(self):
        with patch.object(self.app.state.service, "workspaces", side_effect=RuntimeError("private-source-marker")):
            with self.assertLogs("repolens.web", level="INFO") as captured:
                response = self.client.get("/api/workspaces", headers={"X-Request-ID": "error-test"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["x-request-id"], "error-test")
        self.assertEqual(response.json()["error_code"], "internal_error")
        self.assertNotIn("private-source-marker", response.text + str(captured.output))
        self.assertEqual(captured.records[0].error_type, "RuntimeError")

    def test_queue_links_request_and_agent_trace_without_persisting_input(self):
        import time
        fake = {"trace_id": "trace-unit", "status": "degraded", "answer": {}}
        with patch.object(self.app.state.service, "execute", return_value=fake):
            response = self.client.post("/api/tasks", json={"action": "import", "repository": "unit-only"},
                                        headers={"X-Request-ID": "queue-test"})
            self.assertEqual(response.status_code, 202)
            identity = response.json()["id"]
            for _ in range(100):
                task = self.client.get(f"/api/tasks/{identity}").json()
                if task["status"] == "completed":
                    break
                time.sleep(0.01)
            self.assertEqual(task["request_id"], "queue-test")
            self.assertEqual(task["result"]["trace_id"], "trace-unit")
            self.assertNotIn("unit-only", json.dumps(task))
            self.assertEqual(self.app.state.metrics.snapshot()["counters"]["tasks_degraded"], 1)

    def test_api_docs_have_no_external_script_or_style_dependency(self):
        response = self.client.get("/docs")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/openapi.json", response.text)
        self.assertNotIn("<script", response.text)
        self.assertNotIn("cdn.jsdelivr", response.text)

    def test_pythonw_launcher_accepts_missing_standard_streams(self):
        from repolens.workbench.launcher import main
        with patch("sys.argv", ["repolens-workbench", "--no-browser"]):
            with patch("sys.stdout", None), patch("sys.stderr", None):
                with patch("repolens.workbench.api.create_app", return_value=self.app):
                    with patch("uvicorn.Server.run") as run:
                        main()
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
