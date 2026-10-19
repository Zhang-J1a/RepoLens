"""Explicit counterexamples separate citation validity from semantic support."""

import copy
import unittest

from repolens.domain import RepoLensError
from repolens.generation_evaluation import evaluate_responses, output_hash


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
                      "evidence": [evidence], "output": output})
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
