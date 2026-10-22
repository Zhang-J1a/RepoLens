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


def _saved_answer(case, model):
    pack = EvidenceContextPacker(16000).pack(case["evidence"])
    try:
        return validate_provider_output(case["output"], pack, case["question"],
                                        provider="saved-response", model=model)
    except RepoLensError:
        return None


def create_review_template(responses, *, reviewer):
    cases = responses.get("cases") if isinstance(responses, dict) else None
    if not isinstance(cases, list) or not cases or not isinstance(reviewer, str) or not reviewer.strip():
        raise RepoLensError("Review template requires response cases and a reviewer identifier.")
    labels = []
    seen = set()
    for case in cases:
        if (not isinstance(case, dict) or not isinstance(case.get("id"), str)
                or not case["id"].strip() or case["id"] in seen):
            raise RepoLensError("Response cases require unique string IDs.")
        seen.add(case["id"])
        output = case.get("output")
        if not isinstance(output, dict):
            raise RepoLensError("Every response case must contain a structured output object.")
        answer = _saved_answer(case, responses.get("model"))
        support = []
        for index, claim in enumerate(answer.claims if answer is not None else ()):
            support.extend({"claim_index": index, "citation_id": citation_id, "supported": None}
                           for citation_id in claim.citation_ids)
        labels.append({"id": case["id"], "output_sha256": output_hash(output),
                       "answer_correct": None, "citation_support": support,
                       "failure_type": None})
    return {"schema_version": "repolens.generation-judgments.v1", "reviewer": reviewer.strip(),
            "cases": labels,
            "instructions": "Fill answer_correct and every citation_support.supported with true/false. "
                            "Do not alter output_sha256. Record a failure_type for incorrect answers."}


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
    true_abstentions = unanswerable = false_abstentions = missed_abstentions = 0
    unsupported_answer_count = answered_count = 0
    latencies, tokens = [], []
    grouped = {"strategy": {}, "category": {}}
    for case in cases:
        label = by_id[case["id"]]
        for dimension in ("strategy", "category"):
            if not isinstance(case.get(dimension, "unspecified"), str) or not case.get(dimension, "unspecified").strip():
                raise RepoLensError("Strategy and category must be nonempty strings when supplied.")
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
        answer = _saved_answer(case, responses["model"])
        valid = answer is not None
        valid_count += valid
        correct += valid and label["answer_correct"]
        unanswerable += not case["answerable"]
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
        actual_abstain = bool(valid and answer.status == "abstained")
        expected_abstain = not case["answerable"]
        if actual_abstain and expected_abstain:
            true_abstentions += 1
        elif actual_abstain:
            false_abstentions += 1
        elif expected_abstain:
            missed_abstentions += 1
        if valid and answer.status == "answered":
            answered_count += 1
            unsupported_answer_count += any(not row["supported"] for row in reviews)
        result = {"id": case["id"], "strategy": case.get("strategy", "unspecified"),
                  "category": case.get("category", "unspecified"),
                  "schema_and_citation_valid": valid,
                  "answer_correct": valid and label["answer_correct"],
                  "actual_abstain": actual_abstain,
                  "unsupported_answer": bool(valid and answer.status == "answered"
                                              and any(not row["supported"] for row in reviews)),
                  "status": answer.status if valid else "rejected"}
        results.append(result)
        for dimension, value in (("strategy", result["strategy"]), ("category", result["category"])):
            bucket = grouped[dimension].setdefault(value, {"count": 0, "correct": 0, "valid": 0,
                                                            "abstain_tp": 0, "abstain_fp": 0,
                                                            "abstain_fn": 0, "unsupported": 0,
                                                            "answered": 0})
            bucket["count"] += 1
            bucket["correct"] += bool(result["answer_correct"])
            bucket["valid"] += valid
            bucket["abstain_tp"] += actual_abstain and expected_abstain
            bucket["abstain_fp"] += actual_abstain and not expected_abstain
            bucket["abstain_fn"] += not actual_abstain and expected_abstain
            if valid and answer.status == "answered":
                bucket["answered"] += 1
                bucket["unsupported"] += result["unsupported_answer"]

    def ratio(numerator, denominator):
        return numerator / denominator if denominator else None

    def percentile(values, fraction):
        ordered = sorted(values)
        position = (len(ordered) - 1) * fraction
        low, high = math.floor(position), math.ceil(position)
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    def summarize_buckets(values):
        output = {}
        for key, bucket in sorted(values.items()):
            tp, fp, fn = bucket["abstain_tp"], bucket["abstain_fp"], bucket["abstain_fn"]
            precision = ratio(tp, tp + fp)
            recall = ratio(tp, tp + fn)
            output[key] = {"case_count": bucket["count"],
                           "structured_output_pass_rate": bucket["valid"] / bucket["count"],
                           "answer_accuracy": bucket["correct"] / bucket["count"],
                           "abstention_precision": precision, "abstention_recall": recall,
                           "abstention_f1": ratio(2 * tp, 2 * tp + fp + fn),
                           "unsupported_answer_rate": ratio(bucket["unsupported"], bucket["answered"])}
        return output

    abstention_precision = ratio(true_abstentions, true_abstentions + false_abstentions)
    abstention_recall = ratio(true_abstentions, true_abstentions + missed_abstentions)
    return {"schema_version": "repolens.generation-evaluation.v2", "scope": responses["scope"],
            "model": responses["model"], "reviewer": judgments["reviewer"], "case_count": len(cases),
            "metrics": {"structured_output_pass_rate": valid_count / len(cases),
                        "answer_accuracy": correct / len(cases),
                        "citation_precision_valid_outputs": ratio(supported, cited),
                        "claim_support_coverage_valid_outputs": ratio(covered, claims),
                        "abstention_precision": abstention_precision,
                        "abstention_recall": abstention_recall,
                        "abstention_f1": ratio(2 * true_abstentions,
                                               2 * true_abstentions + false_abstentions + missed_abstentions),
                        "unsupported_answer_rate": ratio(unsupported_answer_count, answered_count),
                        "answerable_case_count": len(cases) - unanswerable,
                        "unanswerable_case_count": unanswerable,
                        "latency_ms": {"measured_count": len(latencies),
                                       "p50": percentile(latencies, .5) if latencies else None,
                                       "p95": percentile(latencies, .95) if latencies else None},
                        "total_tokens": sum(tokens) if len(tokens) == len(cases) else None},
            "by_strategy": summarize_buckets(grouped["strategy"]),
            "by_category": summarize_buckets(grouped["category"]), "cases": results,
            "metric_definitions": {
                "abstention": "Expected abstention is not answerable; invalid outputs count as non-abstentions.",
                "unsupported_answer": "Answered outputs with at least one explicitly unsupported citation divided by valid answered outputs."},
            "limitations": "Support/correctness depend on supplied review labels; invalid outputs counted as failures. "
                            "Citation precision denominator includes valid outputs only. No automatic semantic judging."}
