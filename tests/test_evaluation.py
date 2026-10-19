import contextlib
import copy
import io
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from repolens.domain import RepoLensError
from repolens.evaluation import _score_case, evaluate_dataset
from repolens.git import _environment
from repolens.index import IndexStore
from repolens.ingestion import ingest
from repolens.cli import main


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "source"
        self.repo.mkdir()
        self.data = self.base / "index"
        self.dataset = self.base / "questions.jsonl"
        self.environment = _environment() | {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        self.git("-c", "init.templateDir=", "init", "--quiet")
        source = (
            'def alpha_handler():\n'
            '    return "alpha_marker"\n'
            '\n'
            'def beta_handler():\n'
            '    return "beta_marker"\n'
        )
        source_path = self.repo / "src" / "service.py"
        source_path.parent.mkdir(parents=True)
        source_path.write_text(source, encoding="utf-8", newline="")
        self.git("add", "--all")
        self.git("-c", "user.name=RepoLens Test", "-c", "user.email=test@example.invalid",
                 "commit", "--quiet", "--no-gpg-sign", "-m", "Evaluation fixture")
        self.commit_sha = self.git("rev-parse", "HEAD")
        self.snapshot = ingest(self.repo, self.data, self.commit_sha)["snapshot_id"]
        self.cases = [
            self.case("alpha", "alpha_handler", "routing", 1, 2, "alpha_handler"),
            self.case("beta", "beta_handler", "routing", 4, 5, "beta_handler"),
        ]
        self.write_dataset()

    def git(self, *args):
        result = subprocess.run(
            ["git", "-c", "core.autocrlf=false", "-C", str(self.repo), *args],
            env=self.environment, capture_output=True, check=True, timeout=30,
        )
        return result.stdout.decode("utf-8").strip()

    def case(self, case_id, query, category, start, end, symbol):
        return {
            "id": case_id,
            "repo": "fixture/service",
            "commit_sha": self.commit_sha,
            "category": category,
            "query": query,
            "expected_behavior": "Return evidence for the named function.",
            "expected_evidence": [{
                "path": "src/service.py",
                "line_start": start,
                "line_end": end,
                "symbol": symbol,
            }],
        }

    def write_dataset(self):
        self.dataset.write_text(
            "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in self.cases),
            encoding="utf-8",
            newline="",
        )

    def test_evaluation_validates_evidence_and_reports_reproducibility_metadata(self):
        with IndexStore(self.data) as store:
            result = evaluate_dataset(self.dataset, store, self.snapshot)
        self.assertEqual(result["run"]["commit_sha"], self.commit_sha)
        self.assertEqual(result["run"]["snapshot_id"], self.snapshot)
        self.assertEqual(result["run"]["validated_evidence_count"], 2)
        self.assertEqual(len(result["run"]["dataset_sha256"]), 64)
        self.assertEqual(result["metrics"]["case_count"], 2)
        self.assertEqual(result["metrics"]["recall@5"], 1.0)
        self.assertEqual(result["metrics"]["recall@10"], 1.0)
        self.assertEqual(result["metrics"]["mrr"], 1.0)
        self.assertEqual(result["metrics"]["ndcg@10"], 1.0)
        self.assertIn("p95", result["metrics"]["latency_ms"])
        self.assertEqual(result["by_category"]["routing"]["case_count"], 2)

    def test_evaluation_rejects_a_dataset_for_another_commit(self):
        for case in self.cases:
            case["commit_sha"] = "b" * 40
        self.write_dataset()
        with IndexStore(self.data) as store, self.assertRaisesRegex(RepoLensError, "does not match"):
            evaluate_dataset(self.dataset, store, self.snapshot)

    def test_evaluation_rejects_a_locator_outside_its_symbol(self):
        self.cases[0]["expected_evidence"][0]["line_end"] = 5
        self.write_dataset()
        with IndexStore(self.data) as store, self.assertRaisesRegex(RepoLensError, "outside symbol"):
            evaluate_dataset(self.dataset, store, self.snapshot)

    def test_same_named_getter_and_setter_resolve_by_containing_range(self):
        (self.repo / "src" / "service.py").write_text(
            "class Limits:\n    @property\n    def size(self):\n        return 1\n"
            "    @size.setter\n    def size(self, value):\n        self._size = value\n",
            encoding="utf-8",
        )
        self.git("add", "--all")
        self.git("-c", "user.name=RepoLens Test", "-c", "user.email=test@example.invalid",
                 "commit", "--quiet", "--no-gpg-sign", "-m", "Property fixture")
        self.commit_sha = self.git("rev-parse", "HEAD")
        snapshot = ingest(self.repo, self.data, self.commit_sha)["snapshot_id"]
        self.cases = [self.case("setter", "Limits.size", "properties", 5, 7, "Limits.size")]
        self.write_dataset()
        with IndexStore(self.data) as store:
            result = evaluate_dataset(self.dataset, store, snapshot)
            self.assertEqual(result["run"]["validated_evidence_count"], 1)
            self.cases[0]["expected_evidence"][0]["line_start"] = 2
            self.write_dataset()
            with self.assertRaisesRegex(RepoLensError, "outside symbol"):
                evaluate_dataset(self.dataset, store, snapshot)

    def test_invalid_dataset_shapes_and_locators_fail_before_scoring(self):
        original = copy.deepcopy(self.cases)
        mutations = (
            (lambda rows: rows.append(copy.deepcopy(rows[0])), "duplicate case ID"),
            (lambda rows: rows[0].pop("expected_behavior"), "missing a required field"),
            (lambda rows: rows[0]["expected_evidence"][0].update(path="../service.py"), "invalid evidence path"),
            (lambda rows: rows[0]["expected_evidence"][0].update(line_start=True), "invalid 1-based"),
            (lambda rows: rows[0]["expected_evidence"][0].update(line_end=999), "range exceeds"),
            (lambda rows: rows[0]["expected_evidence"][0].update(symbol="missing"), "does not exist"),
        )
        with IndexStore(self.data) as store:
            for mutate, message in mutations:
                with self.subTest(message=message):
                    self.cases = copy.deepcopy(original)
                    mutate(self.cases)
                    self.write_dataset()
                    with self.assertRaisesRegex(RepoLensError, message):
                        evaluate_dataset(self.dataset, store, self.snapshot)

    def test_non_json_and_empty_datasets_are_rejected(self):
        with IndexStore(self.data) as store:
            for text, message in (("not json\n", "not valid JSON"), ("\n", "no cases")):
                with self.subTest(text=text):
                    self.dataset.write_text(text, encoding="utf-8")
                    with self.assertRaisesRegex(RepoLensError, message):
                        evaluate_dataset(self.dataset, store, self.snapshot)

    def test_query_errors_are_counted_and_scored_as_zero(self):
        with IndexStore(self.data) as store:
            with patch.object(store, "search", side_effect=RepoLensError("test failure")):
                result = evaluate_dataset(self.dataset, store, self.snapshot)
        self.assertEqual(result["metrics"]["query_error_count"], 2)
        self.assertEqual(result["metrics"]["query_error_rate"], 1.0)
        self.assertEqual(result["metrics"]["recall@10"], 0.0)
        self.assertEqual(result["metrics"]["mrr"], 0.0)
        self.assertEqual(result["metrics"]["ndcg@10"], 0.0)

    def test_duplicate_retrieval_ids_do_not_receive_duplicate_relevance_credit(self):
        case = {
            "expected_evidence": [
                {"path": "src/service.py", "line_start": 1, "line_end": 2, "symbol": "alpha_handler"},
                {"path": "src/service.py", "line_start": 4, "line_end": 5, "symbol": "beta_handler"},
            ]
        }
        first = {
            "evidence_id": "same-evidence",
            "path": "src/service.py",
            "line_start": 1,
            "line_end": 2,
            "symbol": "alpha_handler",
            "text": "alpha",
        }
        duplicate = first | {"path": "src/service.py", "line_start": 4, "line_end": 5, "symbol": "beta_handler"}
        scored = _score_case(case, [first, duplicate])
        self.assertEqual(scored["recall@10"], 0.5)
        self.assertEqual(scored["evidence_covered@10"], 1)
        self.assertEqual(scored["mrr"], 1.0)

    def test_repeated_chunks_for_the_same_gold_unit_do_not_inflate_ndcg(self):
        case = {"expected_evidence": [
            {"path": "src/service.py", "line_start": 1, "line_end": 2, "symbol": "alpha_handler"},
            {"path": "src/service.py", "line_start": 4, "line_end": 5, "symbol": "beta_handler"},
        ]}
        case_result = {
            "evidence_id": "alpha", "path": "src/service.py", "line_start": 1,
            "line_end": 2, "symbol": "alpha_handler", "text": "alpha",
        }
        unrelated = case_result | {"evidence_id": "other", "path": "unrelated.py"}
        overlap = case_result | {"evidence_id": "alpha-overlap"}
        second = case_result | {
            "evidence_id": "beta", "line_start": 4, "line_end": 5,
            "symbol": "beta_handler", "text": "beta",
        }
        scored = _score_case(case, [unrelated, case_result, overlap, second])
        self.assertEqual(scored["recall@5"], 1.0)
        self.assertEqual(scored["mrr"], 0.5)
        expected = (1 / math.log2(3) + 1 / math.log2(5)) / (1 + 1 / math.log2(3))
        self.assertAlmostEqual(scored["ndcg@10"], expected)

    def test_cli_evaluate_emits_json(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main([
                "evaluate", str(self.dataset), "--snapshot", self.snapshot,
                "--data-dir", str(self.data),
            ])
        self.assertEqual(status, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["run"]["repository"], "fixture/service")
        self.assertEqual(result["metrics"]["case_count"], 2)


if __name__ == "__main__":
    unittest.main()
