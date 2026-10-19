"""Score saved model outputs against independently supplied review labels.

Source/citation validation and semantic support are separate measurements.
This module never asks a model to judge its own output or infers semantics
from a citation merely being valid.
"""

import hashlib
import json
import math

from repolens.answer import validate_provider_output
from repolens.context import EvidenceContextPacker
from repolens.domain import RepoLensError


def output_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def evaluate_responses(responses, judgments):
    cases, labels = responses.get("cases"), judgments.get("cases")
    if not isinstance(cases, list) or not cases or not isinstance(labels, list):
        raise RepoLensError("Evaluation requires nonempty responses and review labels.")
    if not judgments.get("reviewer") or not responses.get("model") or not responses.get("scope"):
        raise RepoLensError("Record the model, evaluation scope and reviewer.")
    ids = [case["id"] for case in cases]
    label_ids = [label["id"] for label in labels]
    if len(set(ids)) != len(ids) or len(set(label_ids)) != len(label_ids) or set(ids) != set(label_ids):
        raise RepoLensError("Response and judgment IDs must match without duplicates.")
    by_id = {item["id"]: item for item in labels}
    results = []
    supported = cited = correct = valid_count = covered = claims = 0
    true_abstentions = abstentions = unanswerable = 0
    latencies, tokens = [], []
    for case in cases:
        label = by_id[case["id"]]
        if type(case["answerable"]) is not bool or type(label["answer_correct"]) is not bool:
            raise RepoLensError("Answerability and correctness require boolean review labels.")
        if label.get("output_sha256") != output_hash(case["output"]):
            raise RepoLensError("Review labels do not match the exact model output.")
        latency = case.get("latency_ms")
        if latency is not None:
            if type(latency) not in (float, int) or not math.isfinite(latency) or latency < 0:
                raise RepoLensError("Latency must be finite nonnegative milliseconds.")
            latencies.append(latency)
        total_tokens = case.get("total_tokens")
        if total_tokens is not None:
            if type(total_tokens) is not int or total_tokens < 0:
                raise RepoLensError("Token usage must be a nonnegative integer.")
            tokens.append(total_tokens)
        pack = EvidenceContextPacker(16000).pack(case["evidence"])
        valid = True
        try:
            answer = validate_provider_output(case["output"], pack, case["question"],
                                              provider="saved-response", model=responses["model"])
        except RepoLensError:
            answer, valid = None, False
        valid_count += valid
        correct += valid and label["answer_correct"]
        unanswerable += not case["answerable"]
        if valid and answer.status == "abstained":
            abstentions += 1
            true_abstentions += not case["answerable"]
        # Require a label for every cited (claim, citation) pair: missing
        # reviews cannot silently improve precision by shrinking a denominator.
        expected = {(i, identity) for i, claim in enumerate(answer.claims) for identity in claim.citation_ids} if valid else set()
        reviews = label.get("citation_support", [])
        observed = {(row["claim_index"], row["citation_id"]) for row in reviews}
        if observed != expected or len(observed) != len(reviews) or any(type(row["supported"]) is not bool for row in reviews):
            raise RepoLensError("Each valid claim/citation pair requires one explicit support judgment.")
        claims += len(answer.claims) if valid else 0
        covered += sum(any(row["claim_index"] == i and row["supported"] for row in reviews)
                       for i in range(len(answer.claims))) if valid else 0
        cited += len(reviews)
        supported += sum(row["supported"] for row in reviews)
        results.append({"id": case["id"], "schema_and_citation_valid": valid,
                        "answer_correct": valid and label["answer_correct"],
                        "status": answer.status if valid else "rejected"})

    def ratio(numerator, denominator):
        return numerator / denominator if denominator else None

    def percentile(values, fraction):
        ordered = sorted(values)
        position = (len(ordered) - 1) * fraction
        low, high = math.floor(position), math.ceil(position)
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    return {"schema_version": "repolens.generation-evaluation.v1", "scope": responses["scope"],
            "model": responses["model"], "reviewer": judgments["reviewer"], "case_count": len(cases),
            "metrics": {"structured_output_pass_rate": valid_count / len(cases),
                        "answer_accuracy": correct / len(cases),
                        "citation_precision_valid_outputs": ratio(supported, cited),
                        "claim_support_coverage_valid_outputs": ratio(covered, claims),
                        "abstention_precision": ratio(true_abstentions, abstentions),
                        "abstention_recall": ratio(true_abstentions, unanswerable),
                        "latency_ms": {"measured_count": len(latencies),
                                       "p50": percentile(latencies, .5) if latencies else None,
                                       "p95": percentile(latencies, .95) if latencies else None},
                        "total_tokens": sum(tokens) if len(tokens) == len(cases) else None},
            "cases": results,
            "limitations": "Support/correctness depend on supplied review labels; invalid outputs counted as failures. "
                            "Citation precision denominator includes valid outputs only. No automatic semantic judging."}
