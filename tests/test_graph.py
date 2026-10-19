import contextlib
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from repolens.cli import main
from repolens.domain import RepoLensError
from repolens.graph.query import GraphStore
from repolens.graph.schema import GRAPH_POLICY
from repolens.graph.workflow import inspect_graph, search_version
from repolens.impact import analyze_impact
from repolens.index import DATABASE_NAME, IndexStore
from repolens.ingestion import ingest, ingest_or_reuse
from repolens.agent.tools import ToolContext, dispatch_tool, observation, validate_action


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.data = self.root / "index"
        self.env = os.environ | {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        self.git("init", "--quiet")
        self.write("pkg/__init__.py", "from .engine import dispatch\n")
        self.write("pkg/engine.py", "def helper(value):\n    return value + 1\n\ndef dispatch(value):\n    return helper(value)\n\nclass Base:\n    def run(self):\n        return dispatch(1)\n")
        self.write("pkg/service.py", "from .engine import dispatch as route, Base\n\nclass Service(Base):\n    def flow(self):\n        return self.run()\n\ndef entry():\n    return route(1)\n")
        self.write("tests/test_service.py", "from pkg.service import entry\n\ndef test_entry():\n    assert entry() == 2\n")
        self.write("docs/guide.md", "# Service\n`Service.flow` delegates to `Base.run`.\n")
        self.write("settings.toml", "enabled = true\n")
        self.write("pkg/configuration.py", 'def option(app):\n    return app.config["DEBUG"]\n')
        self.write("pkg/left.py", "def shared():\n    return 1\n")
        self.write("pkg/right.py", "def shared():\n    return 2\n")
        self.write("pkg/ambiguous.py", "from .left import shared as chosen\n\ndef exact():\n    return chosen()\n\ndef unknown(receiver):\n    return receiver.shared()\n\ndef shadow(chosen):\n    return chosen()\n")
        self.base = self.commit("base")
        self.base_snapshot = ingest(self.repo, self.data, self.base)["snapshot_id"]
        self.write("pkg/engine.py", "def helper(value):\n    return value + 2\n\ndef dispatch(value):\n    return helper(value)\n\nclass Base:\n    def run(self):\n        return dispatch(2)\n\ndef future_only():\n    return 99\n")
        self.head = self.commit("update engine")
        self.head_snapshot = ingest(self.repo, self.data, self.head)["snapshot_id"]

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=RepoLens Test", "-c", "user.email=test@example.invalid",
                               "-C", str(self.repo), *args], env=self.env, capture_output=True,
                              check=True, timeout=30).stdout.decode().strip()

    def write(self, path, text):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="")

    def commit(self, message):
        self.git("add", "--all")
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", message)
        return self.git("rev-parse", "HEAD")

    def graph(self, **selection):
        with IndexStore(self.data) as store:
            return GraphStore(store).subgraph(self.head_snapshot, **selection)

    def relation_names(self, graph, kind):
        nodes = {item["id"]: item for item in graph["nodes"]}
        return [(nodes[e["source_id"]]["symbol"], nodes[e["target_id"]]["symbol"])
                for e in graph["edges"] if e["kind"] == kind]

    def test_import_alias_and_inheritance_resolve_across_files(self):
        graph = self.graph(symbol="entry", hops=2)
        calls = self.relation_names(graph, "calls")
        self.assertIn(("entry", "dispatch"), calls)
        self.assertIn(("dispatch", "helper"), calls)
        inherited = self.graph(symbol="Service.flow", hops=2)
        self.assertIn(("Service.flow", "Base.run"), self.relation_names(inherited, "calls"))

    def test_graph_exposes_tests_documents_configuration_and_provenance(self):
        graph = self.graph(symbol="entry", hops=1)
        self.assertTrue(any(item["kind"] == "test" for item in graph["nodes"]))
        docs = self.graph(symbol="Service.flow", hops=1)
        self.assertTrue(any(edge["kind"] == "documents" and edge["inference"] for edge in docs["edges"]))
        configuration = self.graph(symbol="option", hops=1)
        self.assertTrue(any(item["kind"] == "configuration" and item["name"] == "DEBUG" for item in configuration["nodes"]))
        for item in (*graph["nodes"], *graph["edges"]):
            self.assertEqual(item["provenance"]["commit_sha"], self.head)
            self.assertEqual(item["snapshot_id"], self.head_snapshot)

    def test_same_name_methods_and_shadowing_do_not_create_false_calls(self):
        graph = self.graph(symbol="exact", hops=1)
        targets = [node for node in graph["nodes"] if node["symbol"] == "shared"]
        self.assertEqual([item["path"] for item in targets], ["pkg/left.py"])
        for symbol in ("unknown", "shadow"):
            graph = self.graph(symbol=symbol, hops=1, edge_kinds=("calls",))
            self.assertEqual(graph["edges"], [])

    def test_two_hops_are_bounded_and_no_dangling_edges(self):
        graph = self.graph(symbol="entry", hops=2, max_nodes=3, max_edges=2)
        self.assertLessEqual(len(graph["nodes"]), 3)
        self.assertLessEqual(len(graph["edges"]), 2)
        self.assertTrue(graph["truncated"])
        identities = {node["id"] for node in graph["nodes"]}
        self.assertTrue(all(edge["source_id"] in identities and edge["target_id"] in identities for edge in graph["edges"]))
        with self.assertRaises(RepoLensError):
            self.graph(symbol="entry", hops=3)

    def test_history_queries_never_return_future_symbols_or_evidence(self):
        with IndexStore(self.data) as store:
            graph = GraphStore(store).subgraph(self.base_snapshot, path="pkg/engine.py", hops=2)
            self.assertFalse(any(node["symbol"] == "future_only" for node in graph["nodes"]))
            self.assertTrue(all(item["commit_sha"] == self.base for item in graph["evidence"]))
            for item in store.search_graph("dispatch", self.base_snapshot, limit=10):
                self.assertEqual(item["commit_sha"], self.base)
            future_id = store.connection.execute("SELECT id FROM graph_nodes WHERE snapshot_id=? AND symbol='future_only'", (self.head_snapshot,)).fetchone()[0]
            with self.assertRaises(RepoLensError):
                GraphStore(store).subgraph(self.base_snapshot, node_ids=[future_id])

    def test_incremental_cache_relinks_after_dependency_change(self):
        with IndexStore(self.data) as store:
            info = GraphStore(store).info(self.head_snapshot)
            self.assertEqual(info["stats"]["parsed_fact_files"], 1)
            self.assertEqual(info["stats"]["reused_fact_files"], 9)
            self.assertEqual(info["stats"]["base_snapshot_id"], self.base_snapshot)
            graph = GraphStore(store).subgraph(self.head_snapshot, symbol="entry", hops=2)
            self.assertTrue(all(node["provenance"]["commit_sha"] == self.head for node in graph["nodes"]))

    def test_persistence_rebuild_is_idempotent(self):
        before = self.graph(symbol="entry", hops=2)
        ingest(self.repo, self.data, self.head)
        after = self.graph(symbol="entry", hops=2)
        self.assertEqual(before["nodes"], after["nodes"])
        self.assertEqual(before["edges"], after["edges"])

    def test_commit_seed_and_graph_impact_keep_rule_severities(self):
        graph = self.graph(commit=True, hops=2)
        self.assertTrue(any(edge["kind"] == "modifies" for edge in graph["edges"]))
        self.assertTrue(any(item["symbol"] == "entry" for item in graph["nodes"]))
        plain = analyze_impact(self.repo, self.data, self.base, self.head)
        enhanced = analyze_impact(self.repo, self.data, self.base, self.head, with_graph=True)
        self.assertEqual(sorted(r["severity"] for r in plain["risks"]), sorted(r["severity"] for r in enhanced["risks"]))
        self.assertEqual(enhanced["graph"]["commit_sha"], self.head)

    def test_graph_search_prefix_and_limit_are_stable(self):
        with IndexStore(self.data) as store:
            short = store.search_graph("entry", self.head_snapshot, limit=3)
            longer = store.search_graph("entry", self.head_snapshot, limit=10)
            self.assertEqual(short, longer[:3])
            tests = store.search_graph("entry", self.head_snapshot, limit=10, path_prefix="tests/")
            self.assertTrue(tests)
            self.assertTrue(all(item["path"].startswith("tests/") for item in tests))

    def test_branch_moves_resolve_to_new_snapshot_without_changing_old(self):
        self.git("branch", "analysis", self.base)
        first = search_version(self.repo, self.data, "dispatch", "analysis")
        self.git("branch", "-f", "analysis", self.head)
        second = search_version(self.repo, self.data, "dispatch", "analysis")
        self.assertEqual(first["commit_sha"], self.base)
        self.assertEqual(second["commit_sha"], self.head)
        old = inspect_graph(self.repo, self.data, self.base, symbol="dispatch", hops=2)
        self.assertEqual(old["commit_sha"], self.base)

    def test_schema_three_migration_and_legacy_graph_backfill(self):
        with contextlib.closing(sqlite3.connect(self.data / DATABASE_NAME)) as connection:
            for table in ("graph_edges", "graph_nodes", "graph_file_facts", "graph_builds"):
                connection.execute("DROP TABLE " + table)
            connection.execute("PRAGMA user_version=3")
            connection.commit()
        result = ingest_or_reuse(self.repo, self.data, self.base)
        self.assertEqual(result["snapshot_id"], self.base_snapshot)
        with IndexStore(self.data) as store:
            self.assertEqual(store.connection.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(GraphStore(store).info(self.base_snapshot)["graph_policy"], GRAPH_POLICY)

    def test_graph_failure_rolls_back_snapshot_replacement(self):
        with IndexStore(self.data) as store:
            old = GraphStore(store).info(self.head_snapshot)
        with patch("repolens.graph.builder.build_graph", side_effect=RepoLensError("injected graph failure")):
            with self.assertRaises(RepoLensError):
                ingest(self.repo, self.data, self.head)
        with IndexStore(self.data) as store:
            self.assertEqual(old, GraphStore(store).info(self.head_snapshot))

    def test_corrupt_graph_provenance_fails_closed(self):
        with contextlib.closing(sqlite3.connect(self.data / DATABASE_NAME)) as connection:
            connection.execute("UPDATE graph_nodes SET provenance_json=? WHERE snapshot_id=? AND symbol='entry'",
                               (json.dumps({"commit_sha": self.base, "snapshot_id": self.base_snapshot}), self.head_snapshot))
            connection.commit()
        with self.assertRaisesRegex(RepoLensError, "provenance|snapshot binding"):
            self.graph(symbol="entry", hops=1)

    def test_unindexed_target_code_is_not_executed(self):
        self.write("pkg/danger.py", "raise RuntimeError('must never execute')\n")
        commit = self.commit("untrusted source")
        before = self.git("status", "--porcelain")
        result = inspect_graph(self.repo, self.data, commit, path="pkg/danger.py", hops=1)
        self.assertTrue(result["nodes"])
        self.assertEqual(before, self.git("status", "--porcelain"))

    def test_reexported_import_is_resolved(self):
        self.write("pkg/export_user.py", "from pkg import dispatch as exported\n\ndef use():\n    return exported(1)\n")
        commit = self.commit("reexport user")
        graph = inspect_graph(self.repo, self.data, commit, symbol="use", hops=1)
        self.assertIn(("use", "dispatch"), self.relation_names(graph, "calls"))

    def test_deleted_file_analysis_keeps_base_graph_separate(self):
        (self.repo / "pkg/engine.py").unlink()
        commit = self.commit("remove engine")
        graph = inspect_graph(self.repo, self.data, commit, commit=True, hops=2)
        self.assertFalse(any(item["path"] == "pkg/engine.py" for item in graph["nodes"]))
        self.assertEqual(graph["base_graph"]["commit_sha"], self.head)
        self.assertTrue(any(item["symbol"] == "dispatch" for item in graph["base_graph"]["nodes"]))
        report = analyze_impact(self.repo, self.data, self.base, commit, with_graph=True)
        self.assertEqual(report["graph_base"]["commit_sha"], self.base)

    def test_dependency_retargeting_relinks_reused_caller_facts(self):
        self.write("pkg/engine.py", "from .right import shared as helper\n\ndef dispatch(value):\n    return helper()\n")
        commit = self.commit("retarget dependency")
        graph = inspect_graph(self.repo, self.data, commit, symbol="entry", hops=2)
        self.assertIn(("dispatch", "shared"), self.relation_names(graph, "calls"))
        self.assertFalse(any(item["symbol"] == "future_only" for item in graph["nodes"]))

    def test_cli_graph_uses_requested_commit(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["graph", "--repository", str(self.repo), "--ref", self.base,
                                   "--symbol", "entry", "--hops", "2", "--data-dir", str(self.data)]), 0)
        self.assertEqual(json.loads(output.getvalue())["commit_sha"], self.base)

    def test_agent_subgraph_exposes_bounded_nodes_and_edges(self):
        repository_alias = self.repo / ".." / self.repo.name
        context = ToolContext(str(repository_alias), str(self.data), self.head_snapshot, self.head)
        result = dispatch_tool(context, "build_dependency_subgraph", {"symbol": "entry", "hops": 2, "limit": 8})
        view = observation(result)
        self.assertTrue(view["graph"]["nodes"])
        self.assertTrue(view["graph"]["edges"])
        self.assertLessEqual(view["result_count"], 8)
        self.assertNotIn("return route(1)", json.dumps(view))
        found = dispatch_tool(context, "search_code", validate_action("search_code", {"query": "entry", "retrieval": "graph"}, 8))
        self.assertTrue(found["evidence"])
        wrong_repository = replace(context, repository=str(self.repo.parent))
        with self.assertRaisesRegex(RepoLensError, "snapshot_binding_failed"):
            dispatch_tool(wrong_repository, "find_symbol", {"symbol": "entry", "limit": 8})

    def test_method_bare_names_and_nested_receivers_obey_python_scope(self):
        self.write("pkg/scopes.py", "def helper():\n    return 1\n\nclass Example:\n    def helper(self):\n        return 2\n\n    def method(self):\n        def nested(self):\n            return self.helper()\n        return helper()\n")
        commit = self.commit("scope boundary")
        graph = inspect_graph(self.repo, self.data, commit, symbol="Example.method", hops=1, edge_kinds=("calls",))
        self.assertIn(("Example.method", "helper"), self.relation_names(graph, "calls"))
        self.assertNotIn(("Example.method", "Example.helper"), self.relation_names(graph, "calls"))
        nested = inspect_graph(self.repo, self.data, commit, symbol="Example.method.nested", hops=1, edge_kinds=("calls",))
        self.assertEqual(nested["edges"], [])


if __name__ == "__main__":
    unittest.main()
