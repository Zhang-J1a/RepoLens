"""Explicit counterexamples separate citation validity from semantic support."""

import copy
import hashlib
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

from repolens.domain import RepoLensError
from repolens.generation_evaluation import create_review_template, evaluate_responses, output_hash


def evaluation_fixture():
    evidence = {"evidence_id": "unit-evidence", "snapshot_id": "unit-snapshot", "commit_sha": "a" * 40,
                "path": "settings.py", "symbol": "timeout", "line_start": 1, "line_end": 2,
                "text": "def timeout():\n    return 30\n"}
    cases, judgments = [], []
    scenarios = (
        ("supported", True, {"status": "answered", "summary": "Timeout is 30.",
                            "claims": [{"text": "Timeout is 30.", "citation_ids": ["E1"]}], "unknowns": []}, True, True),
        ("wrong_with_valid_citation", True, {"status": "answered", "summary": "Timeout is 60.",
                                             "claims": [{"text": "Timeout is 60.", "citation_ids": ["E1"]}], "unknowns": []}, False, False),
        ("forged_citation", True, {"status": "answered", "summary": "Timeout is 30.",
                                  "claims": [{"text": "Timeout is 30.", "citation_ids": ["E999"]}], "unknowns": []}, False, None),
        ("correct_abstention", False, {"status": "abstained", "summary": "No deployment evidence.",
                                      "claims": [], "unknowns": ["Deployment is not documented."]}, True, None),
        ("false_abstention", True, {"status": "abstained", "summary": "No timeout evidence.",
                                   "claims": [], "unknowns": ["Unknown."]}, False, None),
    )
    for identity, answerable, output, correct, support in scenarios:
        cases.append({"id": identity, "question": "What is the timeout?", "answerable": answerable,
                      "evidence": [evidence], "output": output,
                      "strategy": "hybrid", "category": "answerability"})
        judgments.append({"id": identity, "output_sha256": output_hash(output), "answer_correct": correct,
                          "citation_support": [] if support is None else [
                              {"claim_index": 0, "citation_id": "E1", "supported": support}]})
    return ({"scope": "curated-validator-replay-not-model-quality", "model": "scripted-fixtures", "cases": cases},
            {"reviewer": "fixture-author-exact-literal-labels", "cases": judgments})


class GenerationEvaluationTests(unittest.TestCase):
    def test_semantic_support_is_not_inferred_from_valid_citation(self):
        responses, judgments = evaluation_fixture()
        result = evaluate_responses(responses, judgments)
        self.assertEqual(result["metrics"]["structured_output_pass_rate"], .8)
        self.assertEqual(result["metrics"]["answer_accuracy"], .4)
        self.assertEqual(result["metrics"]["citation_precision_valid_outputs"], .5)
        self.assertEqual(result["metrics"]["abstention_precision"], .5)
        self.assertEqual(result["metrics"]["abstention_recall"], 1)
        self.assertEqual(result["metrics"]["abstention_f1"], 2 / 3)
        self.assertEqual(result["metrics"]["unsupported_answer_rate"], .5)
        self.assertEqual(result["by_strategy"]["hybrid"]["abstention_f1"], 2 / 3)
        self.assertEqual(result["by_category"]["answerability"]["case_count"], 5)
        self.assertIsNone(result["metrics"]["latency_ms"]["p95"])
        self.assertIsNone(result["metrics"]["total_tokens"])

    def test_stale_review_and_missing_support_labels_fail(self):
        responses, judgments = evaluation_fixture()
        for mutate in (lambda labels: labels["cases"][0].update(output_sha256="0" * 64),
                       lambda labels: labels["cases"][0].update(citation_support=[]),
                       lambda labels: labels["cases"].append(labels["cases"][0])):
            changed = copy.deepcopy(judgments)
            mutate(changed)
            with self.assertRaises(RepoLensError):
                evaluate_responses(responses, changed)

    def test_nan_latency_is_rejected(self):
        responses, judgments = evaluation_fixture()
        responses["cases"][0]["latency_ms"] = float("nan")
        with self.assertRaises(RepoLensError):
            evaluate_responses(responses, judgments)

    def test_review_template_binds_hash_and_expands_citation_pairs(self):
        responses, _ = evaluation_fixture()
        template = create_review_template(responses, reviewer="independent reviewer")
        self.assertEqual(template["reviewer"], "independent reviewer")
        self.assertEqual(len(template["cases"]), len(responses["cases"]))
        first = template["cases"][0]
        self.assertEqual(first["output_sha256"], output_hash(responses["cases"][0]["output"]))
        self.assertEqual(first["citation_support"], [
            {"claim_index": 0, "citation_id": "E1", "supported": None}])
        self.assertIsNone(first["answer_correct"])

    def test_completed_template_scores_invalid_outputs_without_editing_pairs(self):
        responses, judgments = evaluation_fixture()
        template = create_review_template(responses, reviewer="reviewer")
        self.assertEqual(template["cases"][2]["citation_support"], [])
        for label, completed in zip(template["cases"], judgments["cases"]):
            label["answer_correct"] = completed["answer_correct"]
            for pair, reviewed in zip(label["citation_support"], completed["citation_support"]):
                pair["supported"] = reviewed["supported"]
        result = evaluate_responses(responses, template)
        self.assertEqual(result["metrics"]["answer_accuracy"], .4)

    def test_zero_true_positive_f1_and_invalid_abstention(self):
        responses, judgments = evaluation_fixture()
        responses["cases"] = [responses["cases"][2], responses["cases"][4]]
        judgments["cases"] = [judgments["cases"][2], judgments["cases"][4]]
        responses["cases"][0]["answerable"] = False
        result = evaluate_responses(responses, judgments)
        self.assertEqual(result["metrics"]["abstention_f1"], 0)
        self.assertEqual(result["metrics"]["abstention_recall"], 0)
        self.assertEqual(result["by_strategy"]["hybrid"]["abstention_f1"], 0)
        self.assertIsNone(result["metrics"]["unsupported_answer_rate"])

    def test_groups_keep_separate_denominators_and_missing_labels_fail(self):
        responses, judgments = evaluation_fixture()
        responses["cases"][0].update(strategy="keyword", category="symbol")
        report = evaluate_responses(responses, judgments)
        self.assertEqual(report["by_strategy"]["keyword"]["case_count"], 1)
        self.assertEqual(report["by_strategy"]["keyword"]["unsupported_answer_rate"], 0)
        self.assertIsNone(report["by_category"]["symbol"]["abstention_f1"])
        template = create_review_template(responses, reviewer="reviewer")
        with self.assertRaises(RepoLensError):
            evaluate_responses(responses, template)

    def test_cli_template_and_scoring_provenance_and_no_overwrite(self):
        main = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/evaluate_generation.py"))["main"]

        responses, judgments = evaluation_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            response_path, judgment_path = root / "responses.json", root / "judgments.json"
            template_path, report_path = root / "template.json", root / "report.json"
            response_path.write_text(json.dumps(responses), encoding="utf-8")
            judgment_path.write_text(json.dumps(judgments), encoding="utf-8")
            arguments = ["evaluate_generation", "--responses", str(response_path)]
            template_arguments = arguments + ["--create-review-template", "--output", str(template_path)]
            with patch("sys.argv", template_arguments), redirect_stdout(io.StringIO()):
                main()
            template_bytes = template_path.read_bytes()
            template = json.loads(template_bytes)
            self.assertEqual(template["provenance"], {
                "responses_sha256": hashlib.sha256(response_path.read_bytes()).hexdigest()})
            with patch("sys.argv", template_arguments), self.assertRaises(FileExistsError):
                main()
            self.assertEqual(template_path.read_bytes(), template_bytes)
            with patch("sys.argv", arguments + ["--judgments", str(judgment_path),
                                                "--output", str(report_path)]), redirect_stdout(io.StringIO()):
                main()
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["provenance"]["judgments_sha256"],
                             hashlib.sha256(judgment_path.read_bytes()).hexdigest())
            self.assertEqual(report["case_count"], 5)
            for modes in ([], ["--judgments", str(judgment_path), "--create-review-template"]):
                rejected_path = root / "rejected.json"
                with patch("sys.argv", arguments + modes + ["--output", str(rejected_path)]), \
                        redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    main()
                self.assertEqual(caught.exception.code, 2)
                self.assertFalse(rejected_path.exists())
