import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from unittest.mock import Mock, patch

from repolens.ingestion import ingest_or_reuse
from repolens.webapp import RepoLensRequestHandler, create_server


class HTTPDisconnectTests(unittest.TestCase):
    def test_disconnected_client_closes_without_a_second_response(self):
        for failure in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            for stage in ("headers", "body"):
                for endpoint in ("json", "html"):
                    with self.subTest(failure=failure, stage=stage, endpoint=endpoint):
                        handler = object.__new__(RepoLensRequestHandler)
                        handler.send_response = Mock()
                        handler.send_header = Mock()
                        handler.end_headers = Mock()
                        handler.wfile = Mock()
                        handler.close_connection = False
                        failing = handler.end_headers if stage == "headers" else handler.wfile.write
                        failing.side_effect = failure("disconnected fixture")
                        if endpoint == "json":
                            handler.path = "/api/graph"
                            handler._local_request = Mock(return_value=True)
                            handler._read_json = Mock(return_value={})
                            handler._graph = Mock(return_value={"ok": True})
                            handler.do_POST()
                        else:
                            handler._send_html()
                        self.assertTrue(handler.close_connection)
                        handler.send_response.assert_called_once_with(200)


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.repo = root / "repository"
        self.repo.mkdir()
        self.data = root / "index"
        self.env = os.environ | {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        self.git("init", "--quiet")
        self.write("src/service.py", "def dispatch(value):\n    return value + 1\n")
        self.write("tests/test_service.py", "def test_dispatch():\n    assert dispatch(1) == 2\n")
        self.base = self.commit("base")
        self.write("src/service.py", "def dispatch(value):\n    return value + 2\n\ndef helper():\n    return True\n")
        self.write("tests/test_service.py", "def test_dispatch():\n    assert dispatch(1) == 3\n")
        self.head = self.commit("head")
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            self.server = create_server(default_data_dir=self.data)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def stop_server(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def git(self, *args):
        return subprocess.run(
            ["git", "-c", "user.name=RepoLens Web Test", "-c", "user.email=web@example.invalid",
             "-C", str(self.repo), *args],
            env=self.env, capture_output=True, check=True, timeout=30,
        ).stdout.decode("utf-8").strip()

    def write(self, path, text):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="")

    def commit(self, message):
        self.git("add", "--all")
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", message)
        return self.git("rev-parse", "HEAD")

    def call(self, path, payload=None):
        request = Request(
            self.url + path,
            data=None if payload is None else json.dumps(payload).encode("utf-8"),
            headers={} if payload is None else {"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            if hasattr(exc, "code"):
                return exc.code, json.loads(exc.read().decode("utf-8"))
            raise

    def common(self):
        return {
            "repository": str(self.repo),
            "data_dir": str(self.data),
            "provider": "mock",
        }

    def test_health_and_mock_ask(self):
        status, health = self.call("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["version"], "4.1.0")
        self.assertFalse(health["key_configured"])

        payload = self.common() | {"question": "What does dispatch do?", "ref": self.head}
        status, result = self.call("/api/ask", payload)
        self.assertEqual(status, 200)
        self.assertEqual(result["answer"]["status"], "answered")
        self.assertEqual(result["workflow"]["commit_sha"], self.head)
        self.assertTrue(result["answer"]["citations"])

    def test_impact_and_in_memory_settings(self):
        status, report = self.call("/api/impact", self.common() | {"base": self.base, "head": self.head})
        self.assertEqual(status, 200)
        self.assertEqual(report["schema_version"], "repolens.impact.v2")
        self.assertGreaterEqual(len(report["changed_files"]), 2)

        status, settings = self.call("/api/settings", {"api_key": "test-only-secret"})
        self.assertEqual(status, 200)
        self.assertTrue(settings["key_configured"])
        status, health = self.call("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["key_configured"])
        self.assertNotIn("test-only-secret", json.dumps(health))

    def test_invalid_request_is_json_error(self):
        status, body = self.call("/api/ask", {"provider": "mock"})
        self.assertEqual(status, 400)
        self.assertIn("repository", body["error"])

    def test_legacy_settings_reject_cross_site_and_non_json_requests(self):
        from urllib.error import HTTPError
        body = json.dumps({"api_key": "unit-key-never-applied"}).encode()
        for headers, expected in (
            ({"Content-Type": "application/json", "Origin": "https://example.invalid"}, 403),
            ({"Content-Type": "text/plain"}, 415),
            ({"Content-Type": "application/json", "Host": "attacker.invalid"}, 403),
            ({"Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"}, 403),
        ):
            with self.subTest(headers=headers):
                request = Request(self.url + "/api/settings", data=body, headers=headers)
                with self.assertRaises(HTTPError) as raised:
                    urlopen(request, timeout=5)
                self.assertEqual(raised.exception.code, expected)
                self.assertNotIn("unit-key-never-applied", raised.exception.read().decode())
        self.assertIsNone(self.server.runtime_api_key)

    def test_agent_api_returns_trace_and_rejects_invalid_budget(self):
        status, result = self.call("/api/agent", self.common() | {
            "question": "dispatch service", "ref": self.head, "base": self.base,
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["schema_version"], "repolens.agent.v1")
        self.assertEqual(result["workflow"]["commit_sha"], self.head)
        self.assertTrue(result["trace"]["events"])
        self.assertTrue(result["rule_report"])
        for budget in ({"max_steps": True}, {"unknown_permission": "shell"}, {"timeout_seconds": "NaN"}):
            with self.subTest(budget=budget):
                status, body = self.call("/api/agent", self.common() | {"question": "dispatch", "budget": budget})
                self.assertEqual(status, 400)
                self.assertIn("error", body)

    def test_graph_and_version_search_api_pin_selected_version(self):
        # Version binding is independent of cold indexing on a shared runner.
        base = ingest_or_reuse(self.repo, self.data, self.base)
        head = ingest_or_reuse(self.repo, self.data, self.head)
        status, graph = self.call("/api/graph", self.common() | {
            "ref": self.base, "symbol": "dispatch", "hops": 2,
        })
        self.assertEqual(status, 200)
        self.assertEqual(graph["schema_version"], "repolens.graph.v1")
        self.assertEqual(graph["commit_sha"], self.base)
        self.assertEqual(graph["workflow"]["snapshot_id"], base["snapshot_id"])
        self.assertEqual(graph["workflow"]["index_action"], "reused")
        self.assertTrue(graph["nodes"])
        status, results = self.call("/api/search", self.common() | {
            "ref": self.head, "query": "dispatch", "retrieval": "graph",
        })
        self.assertEqual(status, 200)
        self.assertEqual(results["commit_sha"], self.head)
        self.assertEqual(results["snapshot_id"], head["snapshot_id"])
        self.assertTrue(all(item["commit_sha"] == self.head for item in results["results"]))
        for selection in ({"hops": 3}, {"commit": "yes"}, {"path": "../secret"}):
            status, body = self.call("/api/graph", self.common() | {"symbol": "dispatch", **selection})
            self.assertEqual(status, 400)

    def test_ask_api_can_use_graph_retrieval(self):
        status, result = self.call("/api/ask", self.common() | {
            "ref": self.head, "question": "dispatch", "retrieval": "graph",
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["answer"]["status"], "answered")
        self.assertEqual(result["workflow"]["index_action"], "created")


if __name__ == "__main__":
    unittest.main()
