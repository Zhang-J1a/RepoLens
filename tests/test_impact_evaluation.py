import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from repolens.impact_evaluation import evaluate_impact_dataset


class ImpactEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repository"
        self.repo.mkdir()
        self.data = self.base / "index"
        self.env = os.environ | {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        self.git("init", "--quiet")
        self.write("src/service.py", "def dispatch(value):\n    return value + 1\n")
        self.write("tests/test_service.py", "def test_dispatch():\n    assert dispatch(1) == 2\n")
        self.write("docs/service.md", "# Service\nDispatch is the service entry point.\n")
        self.base_sha = self.commit("base")
        self.write("src/service.py", "def dispatch(value):\n    return value + 2\n")
        self.write("tests/test_service.py", "def test_dispatch():\n    assert dispatch(1) == 3\n")
        self.head_sha = self.commit("change dispatch")
        self.dataset = self.base / "impact-eval.json"
        self.dataset.write_text(json.dumps({
            "schema_version": "repolens.impact-eval.v1",
            "cases": [{
                "id": "dispatch-change",
                "base_sha": self.base_sha,
                "head_sha": self.head_sha,
                "expected_changed_files": ["src/service.py", "tests/test_service.py"],
                "expected_changed_symbols": [
                    {"path": "src/service.py", "name": "dispatch", "change": "modified"},
                    {"path": "tests/test_service.py", "name": "test_dispatch", "change": "modified"},
                ],
                "expected_related_tests": ["tests/test_service.py"],
                "expected_related_docs": [],
                "expected_risk_severities": [],
            }],
        }, ensure_ascii=False), encoding="utf-8")

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

    def test_evaluate_impact_report_scores_structure_and_binding(self):
        result = evaluate_impact_dataset(self.dataset, self.repo, self.data)
        self.assertEqual(result["run"]["successful_cases"], 1)
        self.assertEqual(result["run"]["error_cases"], 0)
        self.assertEqual(result["quality"]["schema_valid_rate"], 1.0)
        self.assertEqual(result["quality"]["snapshot_binding_rate"], 1.0)
        self.assertEqual(result["quality"]["evidence_valid_rate"], 1.0)
        self.assertEqual(result["metrics"]["changed_files"]["f1"], 1.0)
        self.assertEqual(result["metrics"]["changed_symbols"]["f1"], 1.0)


if __name__ == "__main__":
    unittest.main()
