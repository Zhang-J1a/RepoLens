import json
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "eval" / "fixtures" / "taskboard"
DATASET = ROOT / "eval" / "questions.jsonl"


class EvaluationDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_dataset_has_at_least_30_unique_cases(self):
        ids = [row["id"] for row in self.rows]
        self.assertGreaterEqual(len(ids), 30)
        self.assertEqual(len(ids), len(set(ids)))

    def test_cases_have_required_fields_and_categories(self):
        required = {"id", "repo", "category", "query", "expected_answer", "answerable", "expected_behavior", "expected_evidence"}
        categories = set()
        for row in self.rows:
            with self.subTest(case=row.get("id")):
                self.assertTrue(required.issubset(row))
                self.assertEqual(row["repo"], "taskboard-v0")
                self.assertTrue(row["expected_evidence"])
                categories.add(row["category"])
        self.assertGreaterEqual(len(categories), 6)

    def test_evidence_paths_and_line_ranges_resolve(self):
        for row in self.rows:
            for evidence in row["expected_evidence"]:
                with self.subTest(case=row["id"], path=evidence["path"]):
                    source = FIXTURE / evidence["path"]
                    self.assertTrue(source.is_file())
                    line_count = len(source.read_text(encoding="utf-8").splitlines())
                    self.assertGreaterEqual(evidence["line_start"], 1)
                    self.assertLessEqual(evidence["line_start"], evidence["line_end"])
                    self.assertLessEqual(evidence["line_end"], line_count)

    def test_symbol_anchors_appear_in_the_cited_span(self):
        for row in self.rows:
            for evidence in row["expected_evidence"]:
                symbol = evidence.get("symbol")
                if not symbol:
                    continue
                with self.subTest(case=row["id"], symbol=symbol):
                    source = FIXTURE / evidence["path"]
                    lines = source.read_text(encoding="utf-8").splitlines()
                    excerpt = "\n".join(lines[evidence["line_start"] - 1:evidence["line_end"]])
                    self.assertIn(symbol.rsplit(".", 1)[-1], excerpt)

    def test_unanswerable_cases_explicitly_require_abstention(self):
        unanswerable = [row for row in self.rows if not row["answerable"]]
        self.assertTrue(unanswerable)
        for row in unanswerable:
            with self.subTest(case=row["id"]):
                self.assertIn("abstain", row["expected_behavior"].lower())


class FrozenValidationTests(unittest.TestCase):
    def test_manifest_matches_new_questions_without_development_gold_reuse(self):
        raw = (ROOT / "eval" / "flask-validation.jsonl").read_bytes()
        manifest = json.loads((ROOT / "eval" / "flask-validation-manifest.json").read_text(encoding="utf-8"))
        cases = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
        development = [json.loads(line) for line in (ROOT / "eval" / "flask-questions.jsonl").read_text(
            encoding="utf-8").splitlines()]
        self.assertEqual(hashlib.sha256(raw).hexdigest(), manifest["dataset_sha256"])
        self.assertEqual(len(cases), manifest["case_count"])
        self.assertEqual(len({row["id"] for row in cases}), len(cases))
        self.assertEqual(sum(len(row["expected_evidence"]) for row in cases), manifest["locator_count"])
        old_symbols = {(e["path"], e.get("symbol")) for row in development for e in row["expected_evidence"]}
        new_symbols = {(e["path"], e.get("symbol")) for row in cases for e in row["expected_evidence"]}
        self.assertFalse(old_symbols & new_symbols)
        for category, count in manifest["categories"].items():
            self.assertEqual(sum(row["category"] == category for row in cases), count)


if __name__ == "__main__":
    unittest.main()
