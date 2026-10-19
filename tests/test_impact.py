import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from repolens.cli import build_parser, main
from repolens.impact import analyze_impact, render_impact_markdown
from repolens.provider import MockProvider


class ImpactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repository"
        self.repo.mkdir()
        self.data = self.base / "index"
        self.env = os.environ | {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        self.git("init", "--quiet")
        self.write("src/service.py", "def dispatch(value):\n    return value + 1\n")
        self.write("src/legacy.py", "def legacy():\n    return False\n")
        self.write("tests/test_service.py", "def test_dispatch():\n    assert dispatch(1) == 2\n")
        self.write("docs/architecture.md", "# Service\nThe dispatch function is the service entry point.\n")
        self.base_commit = self.commit("base")
        self.write("src/service.py", "def dispatch(value):\n    return value + 2\n\ndef helper():\n    return True\n")
        (self.repo / "src/legacy.py").unlink()
        self.write("tests/test_service.py", "def test_dispatch():\n    assert dispatch(1) == 3\n")
        self.write("docs/architecture.md", "# Service\nThe dispatch function now delegates to the updated path.\n")
        self.head_commit = self.commit("head")

    def git(self, *args):
        return subprocess.run(
            ["git", "-c", "user.name=RepoLens Test", "-c", "user.email=test@example.invalid",
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

    def test_impact_report_is_snapshot_pinned_and_evidence_backed(self):
        report = analyze_impact(
            str(self.repo), self.data, self.base_commit, self.head_commit,
            provider=MockProvider(),
        )
        self.assertEqual(report["schema_version"], "repolens.impact.v2")
        self.assertEqual(report["base"]["commit_sha"], self.base_commit)
        self.assertEqual(report["head"]["commit_sha"], self.head_commit)
        paths = {item["path"] for item in report["changed_files"]}
        self.assertEqual(paths, {"docs/architecture.md", "src/legacy.py", "src/service.py", "tests/test_service.py"})
        service = next(item for item in report["changed_files"] if item["path"] == "src/service.py")
        self.assertEqual({item["name"] for item in service["symbols"]}, {"dispatch", "helper"})
        self.assertEqual(next(item for item in service["symbols"] if item["name"] == "dispatch")["change"], "modified")
        self.assertTrue(report["related_tests"])
        self.assertTrue(report["related_docs"])
        self.assertTrue(report["risks"])
        self.assertTrue({risk["severity"] for risk in report["risks"]} >= {"low", "high"})
        self.assertTrue(report["suggested_tests"])
        evidence_ids = {item["evidence_id"] for item in report["evidence"]}
        self.assertTrue(all(
            symbol["evidence_id"] in evidence_ids
            for change in report["changed_files"]
            for symbol in change["symbols"]
            if symbol["evidence_id"]
        ))
        self.assertTrue(all(
            evidence_id in evidence_ids
            for suggestion in report["suggested_tests"]
            for evidence_id in suggestion["evidence_ids"]
        ))
        self.assertTrue(report["related_history"])
        self.assertEqual(report["telemetry"]["provider_calls"], 1)
        self.assertEqual(report["model_answer"]["status"], "answered")
        self.assertTrue(report["evidence"])
        self.assertTrue(all(item["snapshot_id"] in {report["base"]["snapshot_id"], report["head"]["snapshot_id"]}
                            for item in report["evidence"]))

    def test_impact_cli_uses_mock_without_api_key(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main([
                "impact", "--repository", str(self.repo), "--base", self.base_commit,
                "--head", self.head_commit, "--provider", "mock", "--data-dir", str(self.data),
            ]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["workflow"]["base_ref"], self.base_commit)
        self.assertEqual(report["workflow"]["head_ref"], self.head_commit)

    def test_impact_parser_requires_base_and_bounds_provider_options(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["impact"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["impact", "--base", self.base_commit, "--context-tokens", "0"])

    def test_analyze_commit_uses_first_parent(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main([
                "analyze", "commit", self.head_commit,
                "--repository", str(self.repo), "--provider", "mock", "--data-dir", str(self.data),
            ]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["workflow"]["head_ref"], self.head_commit)
        self.assertEqual(report["workflow"]["base_ref"], self.base_commit)

    def test_impact_markdown_render_and_cli_format(self):
        report = analyze_impact(str(self.repo), self.data, self.base_commit, self.head_commit)
        markdown = render_impact_markdown(report)
        self.assertIn("# RepoLens Impact Report", markdown)
        self.assertIn("src/service.py", markdown)
        self.assertIn("## Related History", markdown)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main([
                "impact", "--repository", str(self.repo), "--base", self.base_commit,
                "--head", self.head_commit, "--provider", "mock", "--format", "markdown",
                "--data-dir", str(self.data),
            ]), 0)
        self.assertTrue(output.getvalue().startswith("# RepoLens Impact Report\n"))

    def test_static_python_relations_are_snapshot_bound(self):
        self.write("src/consumer.py", "def run():\n    return dispatch(1)\n")
        consumer_commit = self.commit("add caller")
        self.write(
            "src/service.py",
            "def dispatch(value):\n    return helper(value)\n\ndef helper(value):\n    return value + 3\n",
        )
        changed_commit = self.commit("add callee")
        report = analyze_impact(str(self.repo), self.data, consumer_commit, changed_commit)
        self.assertTrue(any(item["symbol"] == "run" and item["target_symbol"] == "dispatch"
                            for item in report["related_callers"]))
        self.assertTrue(any(item["target_symbol"] == "helper" for item in report["related_callees"]))
        self.assertTrue(all(item["snapshot_id"] == report["head"]["snapshot_id"]
                            for item in (*report["related_callers"], *report["related_callees"])))


if __name__ == "__main__":
    unittest.main()
